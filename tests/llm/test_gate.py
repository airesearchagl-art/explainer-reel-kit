"""社外秘の区分の確かめ: 社外秘（未記入も）はこの PC の LLM にだけ送る。作るときと、送る直前の 2 回。外せない。"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from explainer_reel_kit.cli import main as erkit
from explainer_reel_kit.llm import client as client_module
from explainer_reel_kit.llm.client import LLMClient
from explainer_reel_kit.llm.confidentiality import CONFIDENTIAL, GENERAL, normalize, of_storyboard
from explainer_reel_kit.llm.config import (
    BUILTIN,
    Endpoint,
    check_route,
    host_kind,
    load_llm_config,
    parse_config,
)
from explainer_reel_kit.llm.errors import ConfigError, RouteBlockedError

SRC = Path(__file__).resolve().parents[2] / "src" / "explainer_reel_kit"
LAN = "http://192.168.1.20:1234/v1"


# ------------------------------------------------------------------ 接続先の種類

@pytest.mark.parametrize("host, kind", [
    ("127.0.0.1", "loopback"), ("127.8.9.10", "loopback"), ("::1", "loopback"), ("[::1]", "loopback"),
    ("localhost", "loopback"), ("LOCALHOST", "loopback"),
    ("192.168.1.20", "lan"), ("10.0.0.5", "lan"), ("172.16.3.4", "lan"), ("fe80::1", "lan"),
    ("8.8.8.8", "other"), ("api.example.com", "other"), ("my-pc", "other"), ("", "other"),
])
def test_host_kind(host, kind):
    assert host_kind(host) == kind


@pytest.mark.parametrize("url", ["http://127.0.0.1:1234/v1", "http://localhost:11434/v1", LAN, "http://[::1]:1/v1"])
def test_local_route_allows_this_pc_and_lan(url):
    check_route(Endpoint("p", url))


@pytest.mark.parametrize("url", ["https://api.example.com/v1", "http://8.8.8.8/v1", "http://my-pc:1234/v1",
                                 "ftp://127.0.0.1/v1", "file:///etc/passwd"])
def test_everything_else_is_blocked(url):
    with pytest.raises((RouteBlockedError, ConfigError)):
        check_route(Endpoint("p", url))


# ------------------------------------------------------------------ 設定: cloud と API キーは無い

@pytest.mark.parametrize("profile, message", [
    ("route: cloud\n    base_url: https://api.example.com/v1", "local だけ"),
    ("route: local\n    base_url: http://127.0.0.1:1/v1\n    api" "_key: x", "API キー"),
    ("route: local\n    base_url: http://127.0.0.1:1/v1\n    api_key_env: OPENAI_API_KEY", "API キー"),
    ("route: local\n    base_url: https://api.example.com/v1", "この PC"),
    ("route: local\n    base_url: http://127.0.0.1:1/v1\n    confidentiality: general", "知らない項目"),
])
def test_config_has_no_cloud_and_no_api_key(tmp_path, profile, message):
    path = tmp_path / "llm.yaml"
    path.write_text(f"version: 1\nprofiles:\n  pp:\n    {profile}\n", encoding="utf-8")
    with pytest.raises((ConfigError, RouteBlockedError), match=message):
        load_llm_config(path)


def test_builtin_and_example_are_this_pc_only():
    example = Path(__file__).resolve().parents[2] / "config" / "llm.example.yaml"
    for config in (parse_config(BUILTIN), load_llm_config(example)):
        assert set(config.endpoints) == {"lmstudio", "ollama"}
        assert all(host_kind(e.base_url.split("//")[1].split(":")[0]) == "loopback" for e in config.endpoints.values())
        assert all(e.model == "" and t.model == "" for e in config.endpoints.values() for t in config.tasks.values())
        assert config.avoid_words == ()


def test_config_search_order(tmp_path, monkeypatch):
    env = tmp_path / "env.yaml"
    env.write_text("version: 1\nprofiles:\n  ee:\n    base_url: http://127.0.0.1:2/v1\n", encoding="utf-8")
    cwd = tmp_path / "work"
    (cwd / "config").mkdir(parents=True)
    (cwd / "config" / "llm.yaml").write_text("version: 1\nprofiles:\n  cc:\n    base_url: http://127.0.0.1:3/v1\n",
                                             encoding="utf-8")
    assert load_llm_config(None, {"ERKIT_LLM_CONFIG": str(env)}, cwd).default_profile is None
    assert list(load_llm_config(None, {"ERKIT_LLM_CONFIG": str(env)}, cwd).endpoints) == ["ee"]
    assert list(load_llm_config(None, {}, cwd).endpoints) == ["cc"]
    assert list(load_llm_config(env, {}, cwd).endpoints) == ["ee"]


def test_no_cloud_code_and_no_api_key_reading_anywhere():
    """完了の条件: ``route: cloud`` と API キーの読み込みが、キットのコードのどこにも無い。"""
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "Authorization" not in text, path
        assert "_CLOUD_OPENER" not in text, path
        assert "Bearer" not in text and "OPENAI_API_KEY" not in text, path
        if path.parent.name == "llm":  # 環境変数で読むのは設定ファイルの場所（ERKIT_LLM_CONFIG）だけ
            assert "getenv(" not in text and "os.environ[" not in text, path
    from explainer_reel_kit.llm import config as llm_config

    assert llm_config.ROUTES == ("local",)


# ------------------------------------------------------------------ LLMClient の確かめ

@pytest.mark.parametrize("url", [LAN, "http://10.0.0.5:1234/v1", "http://[fe80::1]:1234/v1"])
def test_confidential_never_leaves_this_pc_at_creation(no_socket, url):
    with pytest.raises(RouteBlockedError, match="社外秘"):
        LLMClient(Endpoint("lan", url))  # 区分を書かなければ社外秘
    with pytest.raises(RouteBlockedError):
        LLMClient(Endpoint("lan", url), confidentiality=CONFIDENTIAL)
    assert no_socket == []


@pytest.mark.parametrize("value", [None, "", "General", "GENERAL", "public", "confidential", 1, True])
def test_anything_but_general_is_confidential(no_socket, value):
    assert normalize(value) == CONFIDENTIAL
    with pytest.raises(RouteBlockedError):
        LLMClient(Endpoint("lan", LAN), confidentiality=value)


def test_general_may_use_the_lan(no_socket):
    client = LLMClient(Endpoint("lan", LAN), confidentiality=GENERAL)
    assert client.confidentiality == GENERAL


def test_loopback_is_fine_for_confidential(fake_llm):
    client = LLMClient(Endpoint("fake", fake_llm.url))
    assert client.confidentiality == CONFIDENTIAL and client.list_models() == ["test-model-7b"]


def test_checked_again_right_before_every_request(fake_llm, monkeypatch, no_socket):
    """作った後に中身をすり替えても、送る直前の確かめで止まる。"""
    client = LLMClient(Endpoint("fake", fake_llm.url))
    endpoint = dataclasses.replace(client.endpoint, base_url=LAN)
    # 読み取り専用の属性は変えられない
    with pytest.raises(AttributeError):
        client.endpoint = endpoint  # type: ignore[misc]
    with pytest.raises(AttributeError):
        client.confidentiality = GENERAL  # type: ignore[misc]
    # 名前を崩した内部の値を無理に書き換えても、送る直前に止まる
    object.__setattr__(client, "_LLMClient__endpoint", endpoint)
    with pytest.raises(RouteBlockedError, match="社外秘"):
        client.list_models()
    with pytest.raises(RouteBlockedError):
        client.chat([{"role": "user", "content": "社外秘の資料"}], model="m")
    object.__setattr__(client, "_LLMClient__endpoint", dataclasses.replace(endpoint, base_url="https://api.example.com/v1"))
    object.__setattr__(client, "_LLMClient__confidentiality", GENERAL)
    with pytest.raises(RouteBlockedError):  # general でも、外を向いた接続先は止める
        client.list_models()
    assert no_socket == []


def test_the_check_runs_inside_open(monkeypatch, fake_llm):
    """_open が送る前に毎回 2 つの確かめを呼ぶ（設定ではなくコード）。"""
    calls = []
    real = LLMClient._check_confidential

    def spy(self):
        calls.append(self.endpoint.base_url)
        return real(self)

    monkeypatch.setattr(client_module.LLMClient, "_check_confidential", spy)
    client = LLMClient(Endpoint("fake", fake_llm.url))
    client.list_models()
    client.chat([{"role": "user", "content": "x"}], model="test-model-7b", max_tokens=4)
    assert len(calls) == 3  # 作るとき + 送る 2 回


@pytest.mark.parametrize("name", ["ERKIT_LLM_ALLOW_LAN", "ERKIT_CONFIDENTIALITY", "ERKIT_LLM_ROUTE",
                                  "ERKIT_ALLOW_CLOUD", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"])
def test_no_environment_variable_turns_it_off(monkeypatch, no_socket, name):
    monkeypatch.setenv(name, "general")
    with pytest.raises(RouteBlockedError):
        LLMClient(Endpoint("lan", LAN))


def test_sibling_client_keeps_the_confidentiality(fake_llm, monkeypatch):
    """/v1 の外（LM Studio の /api/v0）を読むときに作る別のクライアントも、同じ区分で作る。"""
    seen = []
    real = LLMClient.__init__

    def spy(self, endpoint, *, confidentiality=CONFIDENTIAL):
        seen.append(confidentiality)
        real(self, endpoint, confidentiality=confidentiality)

    monkeypatch.setattr(client_module.LLMClient, "__init__", spy)
    fake_llm.lmstudio = []
    LLMClient(Endpoint("fake", fake_llm.url)).root_json("/api/v0/models")
    assert seen == [CONFIDENTIAL, CONFIDENTIAL]


def test_storyboard_confidentiality_is_read_by_the_kit_function():
    assert of_storyboard({"reel": {"confidentiality": "general"}}) == GENERAL
    assert of_storyboard({"reel": {}}) == CONFIDENTIAL
    assert of_storyboard({"reel": {"confidentiality": "General"}}) == CONFIDENTIAL
    assert of_storyboard(None) == CONFIDENTIAL


# ------------------------------------------------------------------ コマンドからも外せない

def test_draft_confidential_to_the_lan_sends_nothing(draft_config, dummy_source, tmp_path, capsys, no_socket):
    code = erkit(["draft", "dummy-tool", "--source", str(dummy_source), "--llm-config", str(draft_config),
                  "--profile", "lan", "--out", str(tmp_path / "out")])
    assert code == 1 and no_socket == []
    err = capsys.readouterr().err
    assert "社外秘" in err and "この PC" in err
    assert not (tmp_path / "out").exists()


def test_draft_base_url_override_cannot_bypass(draft_config, dummy_source, tmp_path, capsys, no_socket):
    code = erkit(["draft", "dummy-tool", "--source", str(dummy_source), "--llm-config", str(draft_config),
                  "--base-url", LAN, "--out", str(tmp_path / "out")])
    assert code == 1 and no_socket == []
    code = erkit(["draft", "dummy-tool", "--source", str(dummy_source), "--llm-config", str(draft_config),
                  "--base-url", "https://api.example.com/v1", "--out", str(tmp_path / "out")])
    assert code == 1 and no_socket == []


def test_draft_confidential_web_capture_url_must_be_this_pc(draft_config, dummy_source, tmp_path, capsys, no_socket):
    code = erkit(["draft", "dummy-tool", "--source", str(dummy_source), "--llm-config", str(draft_config),
                  "--capture", "web", "--url", "https://tool.example.com/", "--out", str(tmp_path / "out")])
    assert code == 1 and no_socket == []
    assert "capture.url" in capsys.readouterr().err


def test_material_from_a_confidential_request_needs_a_confidential_client(fake_llm, dummy_source, tmp_path):
    from explainer_reel_kit.llm.draft import DraftRequest, draft_storyboard

    general = LLMClient(Endpoint("fake", fake_llm.url), confidentiality=GENERAL)
    req = DraftRequest("dummy-tool", [dummy_source])  # 区分は既定で confidential
    with pytest.raises(RouteBlockedError):
        draft_storyboard(general, req, tmp_path / "out", task=None)
    assert [r for r in fake_llm.requests if r["method"] == "POST"] == []
