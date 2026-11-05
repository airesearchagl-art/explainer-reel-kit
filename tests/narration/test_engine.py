from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from explainer_reel_kit.narration.tts.aivisspeech import (
    AivisSpeechClient,
    HttpResponse,
    TransportConnectionError,
    urllib_transport,
)
from explainer_reel_kit.narration.errors import EngineError, EngineErrorKind


def kind_of(fn) -> EngineErrorKind:
    with pytest.raises(EngineError) as info:
        fn()
    return info.value.kind


# -- normal ------------------------------------------------------------------


def test_version_and_voices(http_client, engine):
    assert http_client.base_url == "http://engine.test:10101"  # trailing slash removed
    assert http_client.get_version() == "1.1.0"
    voices = http_client.list_voices()
    assert [(v.style_id, v.label) for v in voices] == [
        (888753760, "Test Speaker / ノーマル"),
        (7, "Test Speaker / Alt"),
    ]


def test_version_object_form(http_client, engine, make_response):
    engine.overrides["/version"] = make_response(200, '{"version": "2.0.0"}')
    assert http_client.get_version() == "2.0.0"


def test_audio_query_is_opaque_and_only_owned_fields_change(http_client, engine):
    wav = http_client.speak("こんにちは。", 888753760, speed=1.2, volume=0.8)
    assert wav[:4] == b"RIFF"

    audio_query = next(c for c in engine.calls if c.path == "/audio_query")
    assert audio_query.method == "POST"
    assert audio_query.query == {"text": "こんにちは。", "speaker": "888753760"}

    synthesis = next(c for c in engine.calls if c.path == "/synthesis")
    assert synthesis.query == {"speaker": "888753760"}
    sent = json.loads(synthesis.body)
    # owned fields overwritten
    assert sent["speedScale"] == 1.2
    assert sent["volumeScale"] == 0.8
    assert sent["outputSamplingRate"] == 44100
    assert sent["outputStereo"] is False
    # everything else passed through untouched (AivisSpeech-only fields included)
    assert sent["tempoDynamicsScale"] == 1.0
    assert sent["intonationScale"] == 1.0
    assert sent["accent_phrases"] == [{"opaque": True}]
    assert sent["prePhonemeLength"] == 0.1


# -- error classification ------------------------------------------------------


def test_connection_failed(http_client, engine):
    engine.connection_down = True
    for call in (http_client.get_version, http_client.list_voices, lambda: http_client.speak("あ。", 1, speed=1, volume=1)):
        assert kind_of(call) is EngineErrorKind.ENGINE_CONNECTION_FAILED


def test_speakers_failed(http_client, engine, make_response):
    engine.overrides["/speakers"] = make_response(500, "internal error")
    with pytest.raises(EngineError) as info:
        http_client.list_voices()
    error = info.value
    assert error.kind is EngineErrorKind.SPEAKERS_FAILED
    assert error.http_status == 500
    assert error.endpoint == "/speakers"
    assert "internal error" in error.detail
    assert "SPEAKERS_FAILED" in str(error)


def test_audio_query_failed(http_client, engine, make_response):
    engine.overrides["/audio_query"] = make_response(422, '{"detail":"speaker not found"}')
    assert kind_of(lambda: http_client.speak("あ。", 1, speed=1, volume=1)) is EngineErrorKind.AUDIO_QUERY_FAILED
    assert "/synthesis" not in engine.paths()


def test_synthesis_failed(http_client, engine, make_response):
    engine.overrides["/synthesis"] = make_response(500, "boom")
    assert kind_of(lambda: http_client.speak("あ。", 1, speed=1, volume=1)) is EngineErrorKind.SYNTHESIS_FAILED


@pytest.mark.parametrize(
    "path, body",
    [
        ("/version", "not json"),
        ("/version", "[]"),
        ("/speakers", "not json"),
        ("/speakers", '{"not": "a list"}'),
        ("/speakers", '[{"speaker_uuid": "u", "styles": []}]'),  # missing name
        ("/speakers", '[{"name": "n", "speaker_uuid": "u", "styles": [{"name": "s"}]}]'),  # missing id
        ("/speakers", '[{"name": "n", "speaker_uuid": "u", "styles": [{"name": "s", "id": true}]}]'),
        ("/speakers", '[{"name": "n", "speaker_uuid": "u", "styles": "x"}]'),
    ],
)
def test_malformed_metadata(http_client, engine, make_response, path, body):
    engine.overrides[path] = make_response(200, body)
    call = http_client.get_version if path == "/version" else http_client.list_voices
    assert kind_of(call) is EngineErrorKind.MALFORMED_RESPONSE


@pytest.mark.parametrize(
    "path, body",
    [
        ("/audio_query", "not json"),
        ("/audio_query", '["not an object"]'),
        ("/synthesis", b""),
        ("/synthesis", b"ID3not a wav at all"),
        ("/synthesis", b"RIFF\x00\x00\x00\x00WAVEbroken"),  # RIFF header but not parseable
    ],
)
def test_malformed_synthesis_path(http_client, engine, make_response, path, body):
    engine.overrides[path] = make_response(200, body)

    def run():
        from explainer_reel_kit.narration.wavutil import engine_wav_info

        engine_wav_info(http_client.speak("あ。", 1, speed=1, volume=1))

    assert kind_of(run) is EngineErrorKind.MALFORMED_RESPONSE


def test_errors_are_not_swallowed_as_empty_voice_list(http_client, engine, make_response):
    engine.overrides["/speakers"] = make_response(503, "")
    with pytest.raises(EngineError):
        http_client.list_voices()


# -- default urllib transport against a real local socket ---------------------


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/version":
            body, status = b'"9.9.9"', 200
        else:
            body, status = b'{"detail":"nope"}', 500
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_urllib_transport_ok_and_http_error(local_server):
    ok = urllib_transport("GET", local_server + "/version", {}, None, 5)
    assert ok == HttpResponse(200, b'"9.9.9"', "application/json")
    failed = urllib_transport("GET", local_server + "/speakers", {}, None, 5)
    assert failed.status == 500  # HTTP errors are responses, not connection failures

    http_client = AivisSpeechClient(local_server)
    assert http_client.get_version() == "9.9.9"
    assert kind_of(http_client.list_voices) is EngineErrorKind.SPEAKERS_FAILED


def test_urllib_transport_connection_refused():
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]  # closed again when the block ends → nothing listening
    with pytest.raises(TransportConnectionError):
        urllib_transport("GET", f"http://127.0.0.1:{port}/version", {}, None, 2)
    assert kind_of(AivisSpeechClient(f"http://127.0.0.1:{port}", timeout_sec=2).get_version) is (
        EngineErrorKind.ENGINE_CONNECTION_FAILED
    )


def test_urllib_transport_ignores_system_proxy(local_server, monkeypatch):
    # a proxy that would answer for 127.0.0.1 must not be used for the engine
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    assert AivisSpeechClient(local_server, timeout_sec=5).get_version() == "9.9.9"
