"""Shared fakes for narration tests. No network, no real engine, no committed WAVs."""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from narration_fakes import FakeTTS  # noqa: F401
from explainer_reel_kit.narration.tts.aivisspeech import AivisSpeechEngine, HttpResponse, TransportConnectionError
from explainer_reel_kit.narration.wavutil import silent_wav

#: Each synthesized character becomes 10 ms of silence, so durations stay in the tens of ms.
SEC_PER_CHAR = 0.01

SPEAKERS = [
    {
        "name": "Test Speaker",
        "speaker_uuid": "test-speaker-uuid",
        "styles": [{"name": "ノーマル", "id": 888753760}, {"name": "Alt", "id": 7}],
        "version": "1.0.0",
    }
]


@dataclass
class Call:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: bytes | None


@dataclass
class FakeEngine:
    """Callable transport emulating the AivisSpeech Engine endpoints used by the CLI."""

    calls: list[Call] = field(default_factory=list)
    overrides: dict[str, Callable[[Call], HttpResponse]] = field(default_factory=dict)
    connection_down: bool = False

    def __call__(self, method, url, headers, body, timeout) -> HttpResponse:
        parsed = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        call = Call(method, parsed.path, query, dict(headers), body)
        self.calls.append(call)
        if self.connection_down:
            raise TransportConnectionError("[Errno 111] Connection refused")
        if parsed.path in self.overrides:
            return self.overrides[parsed.path](call)
        return self._default(call)

    def _default(self, call: Call) -> HttpResponse:
        if call.path == "/version":
            return _json('"1.1.0"')
        if call.path == "/speakers":
            return _json(json.dumps(SPEAKERS))
        if call.path == "/aivm_models":
            return _json(json.dumps({"model-uuid": {"manifest": {"name": "Test Model", "version": "1.0.0"}}}))
        if call.path == "/audio_query":
            text = call.query["text"]
            return _json(
                json.dumps(
                    {
                        "accent_phrases": [{"opaque": True}],
                        "speedScale": 1.0,
                        "volumeScale": 1.0,
                        "intonationScale": 1.0,
                        "tempoDynamicsScale": 1.0,
                        "prePhonemeLength": 0.1,
                        "postPhonemeLength": 0.1,
                        "outputSamplingRate": 24000,
                        "outputStereo": True,
                        "kana": text,
                    },
                    ensure_ascii=False,
                )
            )
        if call.path == "/synthesis":
            query = json.loads(call.body.decode("utf-8"))
            seconds = len(query["kana"]) * SEC_PER_CHAR
            return HttpResponse(200, silent_wav(seconds, sample_rate=query["outputSamplingRate"]), "audio/wav")
        return HttpResponse(404, b'{"detail":"Not Found"}', "application/json")

    # helpers for assertions
    def paths(self) -> list[str]:
        return [c.path for c in self.calls]

    def synthesized_texts(self) -> list[str]:
        return [c.query["text"] for c in self.calls if c.path == "/audio_query"]


def _json(text: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status, text.encode("utf-8"), "application/json")


def respond(status: int, body: bytes | str, content_type: str = "application/json") -> Callable[[Call], HttpResponse]:
    data = body.encode("utf-8") if isinstance(body, str) else body
    return lambda call: HttpResponse(status, data, content_type)


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def client(engine: FakeEngine) -> AivisSpeechEngine:
    """The default TTSEngine (AivisSpeech) talking to the fake HTTP engine."""
    return AivisSpeechEngine("http://engine.test:10101/", transport=engine)


@pytest.fixture
def fake_tts() -> FakeTTS:
    return FakeTTS()


def narration_input(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "speaker": 888753760,
        "items": [
            {"id": "scene-01", "text": "躯体の天端を確認します。"},
            {"id": "scene-02", "text": "笠木の見付けは三十ミリです。"},
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
def make_input() -> Callable[..., dict[str, Any]]:
    return narration_input


@pytest.fixture
def make_response() -> Callable[..., Callable[[Call], HttpResponse]]:
    return respond


@pytest.fixture
def http_client(engine: FakeEngine):
    """The low-level AivisSpeech HTTP client talking to the fake engine."""
    from explainer_reel_kit.narration.tts.aivisspeech import AivisSpeechClient

    return AivisSpeechClient("http://engine.test:10101/", transport=engine)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path_factory, monkeypatch):
    """Never read a config/kit.yaml from the developer's PC; tests use the defaults unless they write one."""
    cfg = tmp_path_factory.mktemp("cfg") / "kit.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("ERKIT_CONFIG", str(cfg))
    monkeypatch.delenv("ERKIT_OUTPUT_ROOT", raising=False)
    return cfg
