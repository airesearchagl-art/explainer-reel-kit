"""Minimal OpenAI-compatible chat client (standard library HTTP only).

- ``GET {base_url}/models`` and ``POST {base_url}/chat/completions`` (plain and streamed SSE).
- The destination is checked on every request (this PC / the LAN only; confidential → this PC only),
  system proxies are bypassed and redirects are refused, so a local server cannot bounce the request elsewhere.
- No API key is ever read or sent: the kit talks to a server on this PC or the LAN, never to a cloud AI.
- ``timeout_sec`` bounds each socket wait *and* the whole request (a server that trickles
  tokens forever is stopped too).
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any, Iterator

from .confidentiality import CONFIDENTIAL, GENERAL, normalize
from .config import Endpoint, check_route, host_kind
from .errors import ConfigError, LLMError, LLMErrorKind, ModelNotFoundError, RouteBlockedError

_DETAIL_MAX = 600


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise urllib.error.HTTPError(req.full_url, code, f"redirect to {newurl} refused", headers, fp)


_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


#: Fields in which OpenAI-compatible servers return the model's thinking separately from the answer.
#: LM Studio / DeepSeek / vLLM use ``reasoning_content``; Ollama and OpenRouter use ``reasoning``.
REASONING_FIELDS = ("reasoning_content", "reasoning", "thinking")

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def split_think(text: str) -> tuple[str, str]:
    """(reasoning, body) for answers that inline the thinking in the content.

    Handles ``<think>…</think>`` anywhere, an unterminated ``<think>`` (cut off by max_tokens:
    everything after it is reasoning) and a bare leading ``…</think>`` (chat templates that
    open the think block in the prompt, so the answer starts inside it).
    """
    splitter = ThinkSplitter()
    splitter.feed(text)
    splitter.close()
    return splitter.reasoning.strip(), splitter.content.strip()


class ThinkSplitter:
    """Incremental split of streamed content into thinking and answer (tags may span chunks)."""

    def __init__(self) -> None:
        self.inside = False
        self.buffer = ""
        self._reasoning: list[str] = []
        self._content: list[str] = []
        self.saw_tag = False

    @property
    def reasoning(self) -> str:
        return "".join(self._reasoning)

    @property
    def content(self) -> str:
        return "".join(self._content)

    def _emit(self, text: str) -> None:
        if text:
            (self._reasoning if self.inside else self._content).append(text)

    def feed(self, text: str) -> tuple[bool, bool, bool]:
        """Returns (reasoning grew, content grew, earlier content was moved to reasoning)."""
        r0, c0 = len(self.reasoning), len(self.content.strip())
        moved = False
        self.buffer += text
        while self.buffer:
            if self.inside:
                index = self.buffer.find(_THINK_CLOSE)
                if index != -1:
                    self._emit(self.buffer[:index])
                    self.buffer = self.buffer[index + len(_THINK_CLOSE):]
                    self.inside = False
                    continue
            else:
                open_at = self.buffer.find(_THINK_OPEN)
                close_at = self.buffer.find(_THINK_CLOSE)
                if close_at != -1 and (open_at == -1 or close_at < open_at) and not self.saw_tag:
                    # bare leading </think>: everything so far was thinking
                    self._reasoning = self._content + [self.buffer[:close_at]] + self._reasoning
                    self._content = []
                    self.buffer = self.buffer[close_at + len(_THINK_CLOSE):]
                    self.saw_tag = True
                    moved = True
                    continue
                if open_at != -1:
                    self._emit(self.buffer[:open_at])
                    self.buffer = self.buffer[open_at + len(_THINK_OPEN):]
                    self.inside = True
                    self.saw_tag = True
                    continue
            # no complete tag: emit all but a possible partial tag at the end
            keep = 0
            for tag in (_THINK_CLOSE, _THINK_OPEN):
                for k in range(min(len(tag) - 1, len(self.buffer)), 0, -1):
                    if tag.startswith(self.buffer[-k:]):
                        keep = max(keep, k)
                        break
            self._emit(self.buffer[: len(self.buffer) - keep])
            self.buffer = self.buffer[len(self.buffer) - keep:]
            break
        return len(self.reasoning) > r0 or (moved and bool(self.reasoning)), len(self.content.strip()) > c0, moved

    def close(self) -> None:
        self._emit(self.buffer)
        self.buffer = ""


def _reasoning_of(obj: dict[str, Any]) -> tuple[str, str | None]:
    for name in REASONING_FIELDS:
        value = obj.get(name)
        if isinstance(value, str) and value:
            return value, name
    return "", None


@dataclass
class ChatResult:
    content: str  # the answer only (thinking removed)
    elapsed_sec: float
    model: str | None = None
    usage: dict[str, Any] | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None
    reasoning: str = ""
    reasoning_source: str | None = None  # "reasoning_content" / "reasoning" / "<think>" / None


@dataclass
class StreamResult:
    content: str  # the answer only (thinking removed)
    first_content_sec: float | None  # first visible answer text
    total_sec: float
    content_chunks: int
    usage: dict[str, Any] | None = None
    model: str | None = None
    finish_reason: str | None = None
    chunk_times: list[float] = field(default_factory=list)
    reasoning: str = ""
    first_reasoning_sec: float | None = None
    reasoning_chunks: int = 0
    reasoning_source: str | None = None

    @property
    def ttft_sec(self) -> float | None:
        """Time to the first *answer* text."""
        return self.first_content_sec

    @property
    def first_token_sec(self) -> float | None:
        times = [t for t in (self.first_reasoning_sec, self.first_content_sec) if t is not None]
        return min(times) if times else None


def _truncate(text: str) -> str:
    return text if len(text) <= _DETAIL_MAX else text[:_DETAIL_MAX] + "…"


def _is_timeout(error: BaseException) -> bool:
    if isinstance(error, (socket.timeout, TimeoutError)):
        return True
    reason = getattr(error, "reason", None)
    return isinstance(reason, (socket.timeout, TimeoutError))


class LLMClient:
    """``confidentiality``: what the material sent through this client is. Anything but ``general``
    (the default included) is confidential and goes to this PC only — checked when the client is made
    and again right before every request. The endpoint and the confidentiality are fixed at creation
    (read-only properties); a different destination needs a new client, which is checked again."""

    def __init__(self, endpoint: Endpoint, *, confidentiality: str = CONFIDENTIAL) -> None:
        self.__confidentiality = normalize(confidentiality)
        check_route(endpoint)
        self.__endpoint = endpoint
        self._check_confidential()

    @property
    def confidentiality(self) -> str:
        return self.__confidentiality

    @property
    def endpoint(self) -> Endpoint:
        return self.__endpoint

    def _check_confidential(self) -> None:
        """confidential → loopback only (not the LAN). There is no setting, argument or environment variable to turn it off."""
        if self.__confidentiality == GENERAL:
            return
        host = urllib.parse.urlsplit(self.endpoint.base_url).hostname or ""
        if host_kind(host) != "loopback":
            raise RouteBlockedError(
                f"{self.endpoint.name}: 社外秘の区分（confidential。区分が分からないときも同じ）のため、"
                f"この PC（127.0.0.1 / ::1 / localhost）以外の {host or self.endpoint.base_url} には送りません。"
                "LAN の PC は使えません。設定・引数・環境変数では変えられません"
            )

    # -- low level -------------------------------------------------------------------

    def _open(self, method: str, path: str, body: dict[str, Any] | None):
        check_route(self.endpoint)  # again on every request: the guard is in code, not in config
        self._check_confidential()  # and the confidentiality gate, right before any socket is opened
        url = f"{self.endpoint.base_url}{path}"
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            return _LOCAL_OPENER.open(request, timeout=self.endpoint.timeout_sec)
        except urllib.error.HTTPError as error:
            try:
                detail = error.read().decode("utf-8", errors="replace")
            except Exception:  # pragma: no cover - evidence only
                detail = ""
            raise LLMError(
                LLMErrorKind.HTTP_ERROR,
                f"{self.endpoint.name} が {path} で HTTP {error.code} を返しました。",
                endpoint=path,
                http_status=error.code,
                detail=_truncate(detail or str(error.reason)),
            ) from error
        except (urllib.error.URLError, OSError) as error:
            if _is_timeout(error):
                raise self._timeout(path) from error
            reason = getattr(error, "reason", error)
            raise LLMError(
                LLMErrorKind.CONNECTION_FAILED,
                f"{self.endpoint.name}（{self.endpoint.base_url}）に接続できませんでした: {reason}",
                endpoint=path,
            ) from error

    def _timeout(self, path: str) -> LLMError:
        return LLMError(
            LLMErrorKind.TIMEOUT,
            f"{self.endpoint.name} が {self.endpoint.timeout_sec:g} 秒以内に応答しませんでした"
            "（モデルの読み込み中なら、しばらく待つか --llm-timeout を延ばす）。",
            endpoint=path,
        )

    def _read_json(self, response, path: str, deadline: float) -> dict[str, Any]:
        try:
            raw = response.read()
        except (OSError, socket.timeout) as error:
            if _is_timeout(error):
                raise self._timeout(path) from error
            raise LLMError(LLMErrorKind.CONNECTION_FAILED, f"{path} の応答の途中で切断されました: {error}", endpoint=path) from error
        if time.monotonic() > deadline:
            raise self._timeout(path)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LLMError(LLMErrorKind.MALFORMED_RESPONSE, f"{path} の応答が JSON ではありません。", endpoint=path,
                           detail=_truncate(raw.decode("utf-8", errors="replace"))) from error
        if not isinstance(data, dict):
            raise LLMError(LLMErrorKind.MALFORMED_RESPONSE, f"{path} の応答がオブジェクトではありません。", endpoint=path,
                           detail=_truncate(json.dumps(data, ensure_ascii=False)))
        return data

    # -- endpoints --------------------------------------------------------------------

    def list_models(self) -> list[str]:
        path = "/models"
        deadline = time.monotonic() + self.endpoint.timeout_sec
        with self._open("GET", path, None) as response:
            data = self._read_json(response, path, deadline)
        items = data.get("data")
        if not isinstance(items, list) or not all(isinstance(m, dict) and isinstance(m.get("id"), str) for m in items):
            raise LLMError(LLMErrorKind.MALFORMED_RESPONSE, "/models に data[].id がありません。", endpoint=path,
                           detail=_truncate(json.dumps(data, ensure_ascii=False)))
        return [m["id"] for m in items]

    def resolve_model(self, models: list[str] | None = None) -> str:
        """The configured model, or the only model the server lists. Never picks one of several."""
        if self.endpoint.model:
            return self.endpoint.model
        models = self.list_models() if models is None else models
        if len(models) == 1:
            return models[0]
        if not models:
            raise LLMError(LLMErrorKind.MALFORMED_RESPONSE, "サーバーにモデルが読み込まれていません（/models が空）。",
                           endpoint="/models")
        raise ConfigError("サーバーに複数のモデルがあります。--model で指定してください: " + ", ".join(models))

    def require_model(self, model: str, models: list[str] | None = None, *, task: str | None = None) -> str:
        """``model`` if the server lists it; otherwise ModelNotFoundError (never falls back to another model)."""
        models = self.list_models() if models is None else models
        if model not in models:
            raise ModelNotFoundError(model, models, task=task)
        return model

    def chat(self, messages: list[dict[str, str]], *, model: str, max_tokens: int = 256, temperature: float = 0.3,
             response_format: dict[str, Any] | None = None, extra_body: dict[str, Any] | None = None) -> ChatResult:
        path = "/chat/completions"
        body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens,
                                "temperature": temperature, "stream": False}
        if response_format is not None:
            body["response_format"] = response_format
        body.update(extra_body or {})
        started = time.monotonic()
        deadline = started + self.endpoint.timeout_sec
        with self._open("POST", path, body) as response:
            data = self._read_json(response, path, deadline)
        elapsed = time.monotonic() - started
        choices = data.get("choices")
        try:
            message = choices[0]["message"]
            content = message.get("content")
        except (TypeError, IndexError, KeyError) as error:
            raise LLMError(LLMErrorKind.MALFORMED_RESPONSE, "choices[0].message がありません。", endpoint=path,
                           detail=_truncate(json.dumps(data, ensure_ascii=False))) from error
        if content is None:
            content = ""  # some servers send null when the whole budget went to thinking
        if not isinstance(content, str) or not isinstance(message, dict):
            raise LLMError(LLMErrorKind.MALFORMED_RESPONSE, "choices[0].message.content が文字列ではありません。",
                           endpoint=path, detail=_truncate(json.dumps(data, ensure_ascii=False)))
        reasoning, source = _reasoning_of(message)
        inline_reasoning, content = split_think(content)
        if inline_reasoning:
            reasoning = (reasoning + "\n" + inline_reasoning).strip() if reasoning else inline_reasoning
            source = source or "<think>"
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        return ChatResult(content, elapsed, data.get("model"), usage, choices[0].get("finish_reason"), data,
                          reasoning, source)

    def chat_stream(self, messages: list[dict[str, str]], *, model: str, max_tokens: int = 4096,
                    temperature: float = 0.3, extra_body: dict[str, Any] | None = None) -> StreamResult:
        path = "/chat/completions"
        body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens,
                                "temperature": temperature, "stream": True, "stream_options": {"include_usage": True}}
        body.update(extra_body or {})
        started = time.monotonic()
        deadline = started + self.endpoint.timeout_sec
        splitter = ThinkSplitter()  # delta.content may inline <think>…</think>
        reasoning_parts: list[str] = []
        chunk_times: list[float] = []
        reasoning_chunks = 0
        first_reasoning: float | None = None
        first_content: float | None = None
        source: str | None = None
        usage = None
        served_model = None
        finish = None
        done = False
        with self._open("POST", path, body) as response:
            for event in self._sse_events(response, path, deadline):
                if event == "[DONE]":
                    done = True
                    break
                try:
                    data = json.loads(event)
                except json.JSONDecodeError as error:
                    raise LLMError(LLMErrorKind.MALFORMED_RESPONSE, "ストリームのイベントが JSON ではありません。",
                                   endpoint=path, detail=_truncate(event)) from error
                if not isinstance(data, dict):
                    continue
                served_model = served_model or data.get("model")
                if isinstance(data.get("usage"), dict):
                    usage = data["usage"]
                for choice in data.get("choices") or []:
                    if not isinstance(choice, dict):
                        continue
                    finish = choice.get("finish_reason") or finish
                    delta = choice.get("delta")
                    if not isinstance(delta, dict):
                        continue
                    now = time.monotonic() - started
                    thought, name = _reasoning_of(delta)
                    if thought:
                        reasoning_parts.append(thought)
                        reasoning_chunks += 1
                        source = source or name
                        first_reasoning = now if first_reasoning is None else first_reasoning
                    text = delta.get("content")
                    if isinstance(text, str) and text:
                        grew_reasoning, grew_content, moved = splitter.feed(text)
                        if moved:  # "…</think>": what looked like the answer was thinking
                            source = source or "<think>"
                            reasoning_chunks += len(chunk_times)
                            first_reasoning = min(t for t in (first_reasoning, first_content, now) if t is not None)
                            chunk_times, first_content = [], None
                        if grew_reasoning or (splitter.inside and not grew_content):
                            reasoning_chunks += 1
                            source = source or "<think>"
                            first_reasoning = now if first_reasoning is None else first_reasoning
                        if grew_content:
                            chunk_times.append(now)
                            first_content = now if first_content is None else first_content
        total = time.monotonic() - started
        splitter.close()
        content = splitter.content.strip()
        reasoning = "".join(reasoning_parts)
        inline = splitter.reasoning.strip()
        if inline:
            reasoning = (reasoning + "\n" + inline).strip() if reasoning else inline
        if not done and not content and not reasoning:
            raise LLMError(LLMErrorKind.MALFORMED_RESPONSE, "ストリームが内容なしで終わりました（data: [DONE] もありません）。",
                           endpoint=path)
        return StreamResult(content, first_content, total, len(chunk_times), usage, served_model, finish, chunk_times,
                            reasoning, first_reasoning, reasoning_chunks, source)

    def root_json(self, path: str) -> dict[str, Any]:
        """GET a server-specific endpoint next to the OpenAI one (``…/v1`` stripped), e.g. LM Studio /api/v0/models.

        Same host, so the same route guard applies.
        """
        base = self.endpoint.base_url
        root = base[: -len("/v1")] if base.endswith("/v1") else base
        sibling = LLMClient(replace(self.endpoint, base_url=root), confidentiality=self.confidentiality)
        deadline = time.monotonic() + self.endpoint.timeout_sec
        with sibling._open("GET", path, None) as response:
            return sibling._read_json(response, path, deadline)

    def _sse_events(self, response, path: str, deadline: float) -> Iterator[str]:
        buffer: list[str] = []
        while True:
            if time.monotonic() > deadline:
                raise self._timeout(path)
            try:
                line = response.readline()
            except (OSError, socket.timeout) as error:
                if _is_timeout(error):
                    raise self._timeout(path) from error
                raise LLMError(LLMErrorKind.CONNECTION_FAILED, f"{path} のストリームが途中で切断されました: {error}",
                               endpoint=path) from error
            if not line:
                if buffer:
                    yield "\n".join(buffer)
                return
            text = line.decode("utf-8", errors="replace").rstrip("\r\n")
            if text == "":
                if buffer:
                    yield "\n".join(buffer)
                    buffer = []
                continue
            if text.startswith(":"):
                continue  # SSE comment / keep-alive
            if text.startswith("data:"):
                buffer.append(text[5:].lstrip())
