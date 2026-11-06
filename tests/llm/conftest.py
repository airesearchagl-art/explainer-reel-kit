"""A fake OpenAI-compatible server on 127.0.0.1 (real sockets, no network, no model)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import pytest


@dataclass
class FakeLLM:
    models: list[str] = field(default_factory=lambda: ["test-model-7b"])
    #: (request body) -> answer text
    reply: Callable[[dict[str, Any]], str] = lambda body: "準備できました"
    include_usage: bool = True
    chunk_chars: int = 4
    first_delay: float = 0.0  # before the response headers
    chunk_delay: float = 0.0  # between streamed chunks
    status: int | None = None  # force an HTTP status for /chat/completions
    redirect_to: str | None = None
    raw_body: bytes | None = None  # force a raw /chat/completions body
    # thinking models 
    think: Callable[[dict[str, Any]], str] = lambda body: ""  # thinking text, streamed before the answer
    reasoning_field: str = "reasoning_content"  # where thinking goes; "inline" puts <think>…</think> in content
    report_reasoning_tokens: bool = False  # usage.completion_tokens_details.reasoning_tokens
    finish_reason: str = "stop"
    lmstudio: list[dict[str, Any]] | None = None  # GET /api/v0/models; None → 404 (not LM Studio)
    reject_if: Callable[[dict[str, Any]], bool] = lambda body: False  # → HTTP 400 (unsupported parameter)
    #: usage.prompt_tokens ; None → the number of characters of the messages
    prompt_tokens: Callable[[dict[str, Any]], int | None] | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)
    headers: list[dict[str, str]] = field(default_factory=list)
    url: str = ""

    def paths(self) -> list[str]:
        return [r["path"] for r in self.requests]


def _handler(fake: FakeLLM):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, status: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _record(self, body: dict | None):
            fake.requests.append({"path": self.path, "method": self.command, "body": body})
            fake.headers.append({k.lower(): v for k, v in self.headers.items()})

        def do_GET(self):  # noqa: N802
            self._record(None)
            if self.path == "/api/v0/models":
                if fake.lmstudio is None:
                    return self._send(404, b'{"error":"not found"}')
                return self._send(200, json.dumps({"object": "list", "data": fake.lmstudio}).encode())
            if self.path.endswith("/models"):
                data = {"object": "list", "data": [{"id": m, "object": "model"} for m in fake.models]}
                return self._send(200, json.dumps(data).encode())
            return self._send(404, b'{"error":"not found"}')

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
            self._record(body)
            if fake.first_delay:
                time.sleep(fake.first_delay)
            if not self.path.endswith("/chat/completions"):
                return self._send(404, b'{"error":"not found"}')
            if fake.redirect_to:
                return self._send(307, b"", extra={"Location": fake.redirect_to})
            if fake.status:
                return self._send(fake.status, b'{"error":{"message":"forced"}}')
            if fake.reject_if(body):
                return self._send(400, b'{"error":{"message":"unsupported parameter"}}')
            if fake.raw_body is not None:
                return self._send(200, fake.raw_body)
            text = fake.reply(body)
            thought = fake.think(body)
            inline = fake.reasoning_field == "inline"
            prompt_tokens = (fake.prompt_tokens(body) if fake.prompt_tokens is not None
                             else sum(len(m.get("content", "")) for m in body.get("messages", [])))
            if not body.get("stream"):
                message: dict[str, Any] = {"role": "assistant", "content": text}
                if thought and inline:
                    message["content"] = f"<think>{thought}</think>{text}"
                elif thought:
                    message[fake.reasoning_field] = thought
                usage: dict[str, Any] = {"prompt_tokens": prompt_tokens, "completion_tokens": len(text) + len(thought)}
                if fake.report_reasoning_tokens:
                    usage["completion_tokens_details"] = {"reasoning_tokens": len(thought)}
                data = {"id": "x", "object": "chat.completion", "model": body.get("model"),
                        "choices": [{"index": 0, "message": message, "finish_reason": fake.finish_reason}],
                        "usage": usage}
                return self._send(200, json.dumps(data, ensure_ascii=False).encode())
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            n = fake.chunk_chars
            pieces: list[tuple[str, str]] = []  # (field, text)
            if thought and inline:
                full = f"<think>{thought}</think>{text}"
                pieces = [("content", full[i : i + n]) for i in range(0, len(full), n)]
            else:
                pieces = [(fake.reasoning_field, thought[i : i + n]) for i in range(0, len(thought), n)]
                pieces += [("content", text[i : i + n]) for i in range(0, len(text), n)]
            self.wfile.write(b": keep-alive\n\n")
            for name, piece in pieces:
                if fake.chunk_delay:
                    time.sleep(fake.chunk_delay)
                event = {"model": body.get("model"), "choices": [{"index": 0, "delta": {name: piece}}]}
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            end = {"choices": [{"index": 0, "delta": {}, "finish_reason": fake.finish_reason}]}
            self.wfile.write(f"data: {json.dumps(end)}\n\n".encode())
            if fake.include_usage:
                thought_chunks = -(-len(thought) // n) if thought else 0
                usage = {"prompt_tokens": prompt_tokens, "completion_tokens": len(pieces) * 2}
                if fake.report_reasoning_tokens:
                    usage["completion_tokens_details"] = {"reasoning_tokens": thought_chunks * 2}
                self.wfile.write(f"data: {json.dumps({'choices': [], 'usage': usage})}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True

    return Handler


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):  # the client hung up (timeout tests): expected
        import sys

        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


@pytest.fixture
def fake_llm():
    fake = FakeLLM()
    server = _QuietServer(("127.0.0.1", 0), _handler(fake))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    yield fake
    server.shutdown()
    server.server_close()


@pytest.fixture
def llm_config(tmp_path, fake_llm) -> Path:
    path = tmp_path / "llm.yaml"
    path.write_text(
        "version: 1\ndefault_profile: fake\nprofiles:\n"
        f"  fake:\n    route: local\n    base_url: {fake_llm.url}\n    model: ''\n    timeout_sec: 5\n",
        encoding="utf-8",
    )
    return path


# -- kit: 下書きのテストで使う共通のもの -----------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures"
DUMMY_SOURCE = FIXTURES / "dummy-tool.md"
LAN_URL = "http://192.168.1.20:1234/v1"

#: dummy-tool.md から書いた、検査に通る中間の JSON（5 シーン）
GOOD_ANSWER: dict[str, Any] = {
    "title": "かんたん集計ページの使い方",
    "summary": "CSV を読み込んで、列ごとの合計と平均を出し、結果を保存するまでを紹介します。",
    "prerequisites": ["ブラウザでページを開けること", "UTF-8 の CSV ファイル"],
    "intro_narration": "かんたん集計ページは、表の CSV から列ごとの合計と平均を出すページです。この動画では、読み込みから保存までの流れをご紹介します。",
    "scenes": [
        {"heading": "ページを開く", "where": "ブラウザ", "narration": "まず、ブラウザでページを開きます。ページはこの PC の中だけで動きます。",
         "check": "ページが表示されているか", "capture_steps": ["ページの全体を描く"], "shot_name": "open"},
        {"heading": "CSV を選ぶ", "where": "ブラウザ（左の欄）", "on_screen_text": "1 ファイル 5000 行まで",
         "narration": "左のファイルを選ぶから、CSV を選びます。読み込めるのは 1 ファイルあたり 5000 行までです。",
         "check": "読み込んだ行数", "capture_steps": ["左の欄とファイルを選ぶボタンを描く"], "shot_name": "pick_file"},
        {"heading": "列を選ぶ", "where": "ブラウザ（左の欄）",
         "narration": "集計したい列にチェックを入れます。数値でない値の入った行は、集計から外れます。",
         "check": "選んだ列", "capture_steps": ["列のチェックボックスを描く"], "shot_name": "columns"},
        {"heading": "集計する", "where": "ブラウザ（右の表）",
         "narration": "集計するボタンを押すと、右側に合計と平均が出ます。外した行の件数も表示されます。",
         "check": "合計と平均が出ているか", "capture_steps": ["右の結果の表を描く"], "shot_name": "result"},
        {"heading": "結果を書き出す", "where": "ブラウザ（右の表）",
         "narration": "書き出すボタンで、結果を CSV に保存できます。保存先は自分で選びます。",
         "check": "保存したファイル", "capture_steps": ["書き出すボタンを描く"], "shot_name": "export"},
    ],
    "outro": {"summary": "CSV から合計と平均を出し、保存できます。", "checks": ["文字コードは UTF-8 だけ"],
              "next": "自分の CSV で試す",
              "narration": "かんたん集計ページの使い方をご紹介しました。文字コードは UTF-8 だけなので、気をつけてください。"},
}


@pytest.fixture
def good_answer():
    import copy

    return copy.deepcopy(GOOD_ANSWER)


@pytest.fixture
def dummy_source() -> Path:
    return DUMMY_SOURCE


@pytest.fixture
def draft_config(tmp_path, fake_llm) -> Path:
    """task draft / light のモデルが決まった設定（fake は 127.0.0.1）と、LAN の profile。"""
    fake_llm.models = ["big-27b", "small-9b"]
    path = tmp_path / "llm.yaml"
    path.write_text(
        "version: 1\ndefault_profile: fake\ntasks:\n"
        "  draft:\n    model: big-27b\n    thinking: \"off\"\n    max_tokens: 4096\n    expected_context: 8192\n"
        "  light:\n    model: small-9b\n    thinking: \"off\"\n    max_tokens: 2048\n    expected_context: 8192\n"
        f"profiles:\n  fake:\n    route: local\n    base_url: {fake_llm.url}\n    model: ''\n    timeout_sec: 5\n"
        f"  lan:\n    route: local\n    base_url: {LAN_URL}\n    model: ''\n    timeout_sec: 5\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def no_socket(monkeypatch):
    """接続を開こうとしたらテストを失敗にする（区分の確かめは、接続の前に止めること）。"""
    from explainer_reel_kit.llm import client as client_module

    opened: list[str] = []

    def refuse(request, timeout=None):  # pragma: no cover - 届いてはいけない
        opened.append(request.full_url)
        raise AssertionError(f"a request was sent: {request.full_url}")

    monkeypatch.setattr(client_module._LOCAL_OPENER, "open", refuse)
    return opened
