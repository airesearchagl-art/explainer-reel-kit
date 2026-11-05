"""AivisSpeech Engine（既定の音声合成エンジン）: HTTP のクライアントと、TTSEngine の実装。

The engine exposes a VOICEVOX-shaped HTTP API, but it is NOT the same
contract. The AudioQuery returned by ``/audio_query`` is therefore treated as
an opaque object: only the fields this tool owns (speed, volume, output
format) are overwritten, and everything else is handed straight back to
``/synthesis``.

HTTP goes through an injectable ``transport`` so tests can mock it without a
network and without extra dependencies.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..errors import EngineError, EngineErrorKind
from . import EngineInfo, Voice

DEFAULT_ENGINE_URL = "http://127.0.0.1:10101"
DEFAULT_TIMEOUT_SEC = 120.0
OUTPUT_SAMPLING_RATE = 44100
OUTPUT_STEREO = False

_DETAIL_MAX = 600

_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    content_type: str | None = None


class TransportConnectionError(Exception):
    """Raised by a transport when the engine could not be reached at all."""


#: (method, url, headers, body, timeout_sec) -> HttpResponse
Transport = Callable[[str, str, Mapping[str, str], "bytes | None", float], HttpResponse]


def urllib_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
) -> HttpResponse:
    """Default transport using only the standard library.

    System proxies are bypassed: the engine is a local / LAN service, and a
    corporate proxy answering 403/502 for 127.0.0.1 would otherwise be
    misreported as an engine failure.
    """
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        with _NO_PROXY_OPENER.open(request, timeout=timeout) as response:
            return HttpResponse(
                status=response.status,
                body=response.read(),
                content_type=response.headers.get("Content-Type"),
            )
    except urllib.error.HTTPError as http_error:
        # The engine answered, but with a non-2xx status: not a connection failure.
        try:
            payload = http_error.read()
        except Exception:  # pragma: no cover - best effort evidence only
            payload = b""
        return HttpResponse(
            status=http_error.code,
            body=payload,
            content_type=http_error.headers.get("Content-Type") if http_error.headers else None,
        )
    except (urllib.error.URLError, OSError, TimeoutError) as reason:
        raise TransportConnectionError(str(getattr(reason, "reason", reason))) from reason


def _truncate(text: str) -> str:
    return text if len(text) <= _DETAIL_MAX else text[:_DETAIL_MAX] + "…"


def _body_text(body: bytes) -> str:
    return _truncate(body.decode("utf-8", errors="replace"))


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def normalize_base_url(url: str) -> str:
    return url.strip().rstrip("/")


class AivisSpeechClient:
    def __init__(
        self,
        base_url: str = DEFAULT_ENGINE_URL,
        *,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.timeout_sec = timeout_sec
        self._transport: Transport = transport or urllib_transport

    # -- low level -------------------------------------------------------

    def _url(self, path: str, query: Mapping[str, str] | None = None) -> str:
        suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
        return f"{self.base_url}{path}{suffix}"

    def _request(
        self,
        method: str,
        path: str,
        failure_kind: EngineErrorKind,
        *,
        query: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> HttpResponse:
        url = self._url(path, query)
        try:
            response = self._transport(method, url, headers or {}, body, self.timeout_sec)
        except TransportConnectionError as cause:
            raise EngineError(
                EngineErrorKind.ENGINE_CONNECTION_FAILED,
                f"AivisSpeech Engine に接続できませんでした ({self.base_url}{path}): {cause}",
                endpoint=path,
            ) from cause
        if not 200 <= response.status < 300:
            raise EngineError(
                failure_kind,
                f"AivisSpeech Engine が {path} で HTTP {response.status} を返しました。",
                endpoint=path,
                http_status=response.status,
                detail=_body_text(response.body),
            )
        return response

    def _read_json(self, response: HttpResponse, path: str) -> Any:
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as cause:
            raise EngineError(
                EngineErrorKind.MALFORMED_RESPONSE,
                f"{path} のレスポンスが JSON として解釈できません。",
                endpoint=path,
                http_status=response.status,
                detail=_body_text(response.body),
            ) from cause

    def _malformed(self, path: str, message: str, payload: Any) -> EngineError:
        return EngineError(
            EngineErrorKind.MALFORMED_RESPONSE,
            message,
            endpoint=path,
            detail=_truncate(json.dumps(payload, ensure_ascii=False, default=str)),
        )

    # -- endpoints -------------------------------------------------------

    def get_version(self) -> str:
        """``GET /version``. A non-2xx here means the endpoint itself misbehaved."""
        path = "/version"
        response = self._request("GET", path, EngineErrorKind.MALFORMED_RESPONSE)
        raw = self._read_json(response, path)
        if _is_nonempty_str(raw):
            return raw.strip()
        if isinstance(raw, dict) and _is_nonempty_str(raw.get("version")):
            return raw["version"].strip()
        raise self._malformed(path, "/version が想定外の形式を返しました。", raw)

    def list_voices(self) -> list[Voice]:
        """``GET /speakers`` flattened to (speaker, style) pairs. Fail-closed."""
        path = "/speakers"
        response = self._request("GET", path, EngineErrorKind.SPEAKERS_FAILED)
        raw = self._read_json(response, path)
        if not isinstance(raw, list):
            raise self._malformed(path, "/speakers が配列を返しませんでした。", raw)

        voices: list[Voice] = []
        for speaker in raw:
            if not isinstance(speaker, dict):
                raise self._malformed(path, "/speakers の要素がオブジェクトではありません。", speaker)
            if not _is_nonempty_str(speaker.get("name")):
                raise self._malformed(path, "/speakers の speaker に有効な name がありません。", speaker)
            if not _is_nonempty_str(speaker.get("speaker_uuid")):
                raise self._malformed(
                    path, "/speakers の speaker に有効な speaker_uuid がありません。", speaker
                )
            styles = speaker.get("styles")
            if not isinstance(styles, list):
                raise self._malformed(path, "/speakers の styles が配列ではありません。", speaker)
            for style in styles:
                if not isinstance(style, dict):
                    raise self._malformed(path, "/speakers の style がオブジェクトではありません。", style)
                style_id = style.get("id")
                if not isinstance(style_id, int) or isinstance(style_id, bool):
                    raise self._malformed(path, "/speakers の style に有効な id がありません。", style)
                if not _is_nonempty_str(style.get("name")):
                    raise self._malformed(path, "/speakers の style に有効な name がありません。", style)
                voices.append(
                    Voice(
                        style_id=style_id,
                        speaker_name=speaker["name"],
                        speaker_uuid=speaker["speaker_uuid"],
                        style_name=style["name"],
                    )
                )
        return voices

    def list_aivm_models(self) -> list[dict[str, Any]]:
        """``GET /aivm_models`` (AivisSpeech-only). Informational, for probe.

        Returns ``[{uuid, name, version}]``. Raises EngineError on failure; the
        caller decides whether that is fatal.
        """
        path = "/aivm_models"
        response = self._request("GET", path, EngineErrorKind.MALFORMED_RESPONSE)
        raw = self._read_json(response, path)
        if not isinstance(raw, dict):
            raise self._malformed(path, "/aivm_models が想定外の形式を返しました。", raw)
        models = []
        for uuid, entry in raw.items():
            manifest = entry.get("manifest") if isinstance(entry, dict) else None
            manifest = manifest if isinstance(manifest, dict) else {}
            models.append(
                {
                    "uuid": uuid,
                    "name": manifest.get("name") if _is_nonempty_str(manifest.get("name")) else None,
                    "version": manifest.get("version")
                    if _is_nonempty_str(manifest.get("version"))
                    else None,
                }
            )
        return models

    def create_audio_query(self, text: str, style_id: int) -> dict[str, Any]:
        """``POST /audio_query?text=&speaker=`` → opaque AudioQuery object."""
        path = "/audio_query"
        response = self._request(
            "POST",
            path,
            EngineErrorKind.AUDIO_QUERY_FAILED,
            query={"text": text, "speaker": str(style_id)},
            headers={"Accept": "application/json"},
        )
        raw = self._read_json(response, path)
        if not isinstance(raw, dict):
            raise self._malformed(path, "/audio_query が AudioQuery オブジェクトを返しませんでした。", raw)
        return raw

    @staticmethod
    def apply_settings(audio_query: Mapping[str, Any], *, speed: float, volume: float) -> dict[str, Any]:
        """Overwrite only the fields this tool owns; keep everything else as-is."""
        return {
            **audio_query,
            "speedScale": speed,
            "volumeScale": volume,
            "outputSamplingRate": OUTPUT_SAMPLING_RATE,
            "outputStereo": OUTPUT_STEREO,
        }

    def synthesize(self, audio_query: Mapping[str, Any], style_id: int) -> bytes:
        """``POST /synthesis?speaker=`` with the AudioQuery as body → WAV bytes."""
        path = "/synthesis"
        response = self._request(
            "POST",
            path,
            EngineErrorKind.SYNTHESIS_FAILED,
            query={"speaker": str(style_id)},
            headers={"Content-Type": "application/json", "Accept": "audio/wav"},
            body=json.dumps(audio_query, ensure_ascii=False).encode("utf-8"),
        )
        audio = response.body
        if len(audio) == 0:
            raise EngineError(
                EngineErrorKind.MALFORMED_RESPONSE,
                "/synthesis が空のレスポンスを返しました。",
                endpoint=path,
                http_status=response.status,
            )
        if len(audio) < 12 or audio[0:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise EngineError(
                EngineErrorKind.MALFORMED_RESPONSE,
                "/synthesis のレスポンスが WAV (RIFF/WAVE) ではありません。",
                endpoint=path,
                http_status=response.status,
                detail=f"byteLength={len(audio)}",
            )
        return audio

    def speak(self, text: str, style_id: int, *, speed: float, volume: float) -> bytes:
        """``/audio_query`` → apply owned settings → ``/synthesis``."""
        query = self.create_audio_query(text, style_id)
        return self.synthesize(self.apply_settings(query, speed=speed, volume=volume), style_id)


# -- reading (kana) ----------------------------------------------------------


def reading_of(audio_query: Mapping[str, Any]) -> str:
    """Katakana reading from an AudioQuery.

    Built from ``accent_phrases[].moras[].text`` (accent phrases separated by ``/``,
    a pause as ``、``). When those are absent, the AudioQuery's ``kana`` string is used.
    This is the engine's text analysis; how it finally sounds still has to be confirmed by listening.
    """
    phrases = audio_query.get("accent_phrases")
    if isinstance(phrases, list) and phrases:
        parts: list[str] = []
        ok = True
        for phrase in phrases:
            moras = phrase.get("moras") if isinstance(phrase, dict) else None
            if not isinstance(moras, list) or not all(
                isinstance(m, dict) and isinstance(m.get("text"), str) for m in moras
            ):
                ok = False
                break
            text = "".join(m["text"] for m in moras)
            if isinstance(phrase.get("pause_mora"), dict):
                text += "、"
            parts.append(text)
        if ok:
            return "/".join(parts)
    kana = audio_query.get("kana")
    if isinstance(kana, str) and kana.strip():
        return kana.strip()
    raise EngineError(
        EngineErrorKind.MALFORMED_RESPONSE,
        "/audio_query の結果に読み（accent_phrases[].moras[].text または kana）がありません。",
        endpoint="/audio_query",
        detail=json.dumps(audio_query, ensure_ascii=False)[:600],
    )


# -- TTSEngine ------------------------------------------------------------------


class AivisSpeechEngine:
    """TTSEngine の実装（``audio_query`` → ``synthesis``）。"""

    name = "aivisspeech"

    def __init__(
        self,
        url: str = DEFAULT_ENGINE_URL,
        *,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        transport: Transport | None = None,
    ) -> None:
        self.client = AivisSpeechClient(url, timeout_sec=timeout_sec, transport=transport)

    @property
    def url(self) -> str:
        return self.client.base_url

    def check(self) -> EngineInfo:
        version = self.client.get_version()
        try:
            models: list[dict[str, Any]] | None = self.client.list_aivm_models()
        except EngineError:
            models = None  # 声のモデルの一覧は参考情報（無くても止めない）
        return EngineInfo(name=self.name, url=self.url, version=version, models=models)

    def voices(self) -> list[Voice]:
        return self.client.list_voices()

    def synthesize(self, text: str, voice: int, *, speed: float, volume: float) -> bytes:
        return self.client.speak(text, voice, speed=speed, volume=volume)

    def reading(self, text: str, voice: int) -> str | None:
        return reading_of(self.client.create_audio_query(text, voice))
