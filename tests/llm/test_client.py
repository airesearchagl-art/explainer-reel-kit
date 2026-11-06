from __future__ import annotations

import socket
import time

import pytest

from explainer_reel_kit.llm.client import LLMClient
from explainer_reel_kit.llm.config import Endpoint
from explainer_reel_kit.llm.errors import ConfigError, LLMError, LLMErrorKind


def client_for(fake, *, timeout=5.0, model=""):
    return LLMClient(Endpoint("fake", fake.url, model, timeout))


def test_models_and_chat(fake_llm):
    c = client_for(fake_llm)
    assert c.list_models() == ["test-model-7b"]
    assert c.resolve_model() == "test-model-7b"
    answer = c.chat([{"role": "user", "content": "hi"}], model="test-model-7b", max_tokens=8)
    assert answer.content == "準備できました" and answer.usage["completion_tokens"] == 7
    body = fake_llm.requests[-1]["body"]
    assert body["model"] == "test-model-7b" and body["stream"] is False and body["max_tokens"] == 8


def test_resolve_model_never_picks_one_of_several(fake_llm):
    fake_llm.models = ["a", "b"]
    with pytest.raises(ConfigError, match="--model"):
        client_for(fake_llm).resolve_model()
    assert client_for(fake_llm, model="b").resolve_model() == "b"
    fake_llm.models = []
    with pytest.raises(LLMError):
        client_for(fake_llm).resolve_model()


def test_stream_collects_text_ttft_and_usage(fake_llm):
    fake_llm.reply = lambda body: "あいうえおかきくけこ"
    fake_llm.chunk_delay = 0.02
    result = client_for(fake_llm).chat_stream([{"role": "user", "content": "x"}], model="m")
    assert result.content == "あいうえおかきくけこ"
    assert result.content_chunks == 3  # 4 + 4 + 2 chars
    assert result.usage == {"prompt_tokens": 1, "completion_tokens": 6}
    assert result.finish_reason == "stop"
    assert 0 < result.ttft_sec <= result.total_sec
    assert fake_llm.requests[-1]["body"]["stream_options"] == {"include_usage": True}


def test_timeout_before_first_byte(fake_llm):
    fake_llm.first_delay = 1.5
    started = time.monotonic()
    with pytest.raises(LLMError) as info:
        client_for(fake_llm, timeout=0.5).chat([{"role": "user", "content": "x"}], model="m")
    assert info.value.kind is LLMErrorKind.TIMEOUT
    assert time.monotonic() - started < 1.4


def test_timeout_bounds_the_whole_stream(fake_llm):
    fake_llm.reply = lambda body: "あ" * 40  # 10 chunks
    fake_llm.chunk_delay = 0.25  # each read is quick enough, but the whole stream is not
    with pytest.raises(LLMError) as info:
        client_for(fake_llm, timeout=0.8).chat_stream([{"role": "user", "content": "x"}], model="m")
    assert info.value.kind is LLMErrorKind.TIMEOUT


def test_http_error_and_malformed(fake_llm):
    fake_llm.status = 400
    with pytest.raises(LLMError) as info:
        client_for(fake_llm).chat([{"role": "user", "content": "x"}], model="m")
    assert info.value.kind is LLMErrorKind.HTTP_ERROR and info.value.http_status == 400
    assert "forced" in info.value.detail
    fake_llm.status = None
    for raw in (b"not json", b"[]", b'{"choices": []}', b'{"choices": [{"message": {"content": 1}}]}'):
        fake_llm.raw_body = raw
        with pytest.raises(LLMError) as info:
            client_for(fake_llm).chat([{"role": "user", "content": "x"}], model="m")
        assert info.value.kind is LLMErrorKind.MALFORMED_RESPONSE


def test_connection_refused():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    c = LLMClient(Endpoint("down", f"http://127.0.0.1:{port}/v1", "", 15))  # Windows は断られるまで約 2 秒
    with pytest.raises(LLMError) as info:
        c.list_models()
    assert info.value.kind is LLMErrorKind.CONNECTION_FAILED


def test_local_route_does_not_follow_redirects(fake_llm):
    fake_llm.redirect_to = "https://api.example.com/v1/chat/completions"
    with pytest.raises(LLMError) as info:
        client_for(fake_llm).chat([{"role": "user", "content": "x"}], model="m")
    assert info.value.kind is LLMErrorKind.HTTP_ERROR and info.value.http_status == 307
    assert len([r for r in fake_llm.requests if r["method"] == "POST"]) == 1


def test_local_route_ignores_system_proxy(fake_llm, monkeypatch):
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    assert client_for(fake_llm).list_models() == ["test-model-7b"]


def test_never_sends_an_api_key(fake_llm, monkeypatch):
    """キットは API キーを読まない・送らない（環境変数があっても）。"""
    for name in ("OPENAI_API_KEY", "ERKIT_LLM_API_KEY", "FAKE_LLM_KEY"):
        monkeypatch.setenv(name, "sk-test")
    client_for(fake_llm).list_models()
    client_for(fake_llm).chat([{"role": "user", "content": "hi"}], model="test-model-7b", max_tokens=8)
    assert all("authorization" not in h for h in fake_llm.headers)
