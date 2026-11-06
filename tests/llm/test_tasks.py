"""用途ごとの既定（tasks）と、生成 → 確かめ → 書き直し（structured.generate）。"""
from __future__ import annotations

import json

import pytest

from explainer_reel_kit.llm.client import LLMClient
from explainer_reel_kit.llm.config import BUILTIN, Endpoint, Task, load_llm_config, parse_config, task_settings
from explainer_reel_kit.llm.errors import ConfigError, ModelNotFoundError
from explainer_reel_kit.llm.readings import ReadingCheck, suggest
from explainer_reel_kit.llm.structured import generate, rewrite_request

GOOD = {"title": "サンプルの紹介", "scenes": [{"heading": f"見出し{i}", "narration": "ナレーションです。"} for i in range(3)]}
SCHEMA = {"type": "object", "required": ["title", "scenes"],
          "properties": {"title": {"type": "string"}, "scenes": {"type": "array"}}}


def json_problems(value):
    n = len(value.get("scenes") or [])
    return [] if n == 3 else [f"scenes が {n} 件です（3 件）"]


def client_for(fake, model=""):
    return LLMClient(Endpoint("fake", fake.url, model, 5))


@pytest.fixture
def task_config(tmp_path, fake_llm):
    path = tmp_path / "llm.yaml"
    path.write_text(
        "version: 1\ndefault_profile: fake\n"
        "tasks:\n"
        "  draft:\n    model: big-27b\n    thinking: off\n    max_tokens: 4096\n    expected_context: 8192\n"
        "  light:\n    model: small-9b\n    thinking: \"off\"\n    max_tokens: 2048\n    expected_context: 8192\n"
        f"profiles:\n  fake:\n    route: local\n    base_url: {fake_llm.url}\n    model: ''\n    timeout_sec: 5\n",
        encoding="utf-8",
    )
    return path


# -- tasks -------------------------------------------------------------------------------------


def test_builtin_tasks_leave_the_model_to_the_server():
    """組み込みの既定（= config/llm.example.yaml）: モデルは「サーバーに読み込まれているもの」。"""
    tasks = parse_config(BUILTIN).tasks
    assert tasks["draft"] == Task("draft", "", "off", 4096, 8192)
    assert tasks["light"] == Task("light", "", "off", 2048, 8192)


def test_bare_off_in_yaml_means_off(task_config):
    assert load_llm_config(task_config).tasks["draft"].thinking == "off"  # YAML reads `off` as false


@pytest.mark.parametrize(
    "body",
    [
        "tasks:\n  draft:\n    model: m\n    thinking: maybe\n",
        "tasks:\n  draft:\n    model: m\n    max_tokens: 4\n",
        "tasks:\n  draft:\n    model: m\n    expected_context: big\n",
        "tasks:\n  draft:\n    model: m\n    temperature: 0\n",
        "tasks: [draft]\n",
    ],
)
def test_invalid_tasks(tmp_path, body):
    path = tmp_path / "llm.yaml"
    path.write_text(body + "profiles:\n  pp:\n    route: local\n    base_url: http://127.0.0.1/v1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_llm_config(path)


def test_unknown_task(task_config):
    config = load_llm_config(task_config)
    with pytest.raises(ConfigError, match="nope"):
        config.task("nope")
    assert config.task(None) is None


def test_explicit_arguments_win_over_the_task():
    task = Task("draft", "big-27b", "off", 4096, 8192)
    endpoint = Endpoint("p", "http://127.0.0.1/v1", "profile-model")
    s = task_settings(task, endpoint)
    assert (s.model, s.model_source, s.thinking, s.max_tokens, s.expected_context) == ("big-27b", "task draft", "off",
                                                                                       4096, 8192)
    s = task_settings(task, endpoint, explicit_model="x", explicit_thinking="auto", explicit_max_tokens=100)
    assert (s.model, s.model_source, s.thinking, s.thinking_source, s.max_tokens) == ("x", "引数", "auto", "引数", 100)
    s = task_settings(Task("draft"), endpoint)  # task の model が空 → profile
    assert (s.model, s.model_source) == ("profile-model", "profile")
    s = task_settings(None, Endpoint("p", "http://127.0.0.1/v1"))
    assert s.model is None and s.model_source == ""


def test_require_model_never_falls_back(fake_llm):
    fake_llm.models = ["small-9b"]
    client = client_for(fake_llm)
    assert client.require_model("small-9b") == "small-9b"
    with pytest.raises(ModelNotFoundError) as info:
        client.require_model("big-27b", task="draft")
    message = str(info.value)
    assert "task draft" in message and "big-27b" in message and "small-9b" in message
    assert info.value.exit_code == 1  # 足りないものがある


# -- generate → check → rewrite -------------------------------------------------------------------


def _messages():
    return [{"role": "system", "content": "s"}, {"role": "user", "content": "JSON を出して"}]


def test_generate_accepts_fenced_json_first_time(fake_llm):
    fake_llm.reply = lambda body: "はい。\n```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```\n以上です。"
    result = generate(client_for(fake_llm), _messages(), model="m", schema=SCHEMA, validate=json_problems)
    assert result.ok and result.value == GOOD and result.rewrites == 0 and len(result.attempts) == 1
    assert result.attempts[0].ok and result.attempts[0].elapsed_sec is not None
    body = fake_llm.requests[-1]["body"]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}  # thinking off by default 


def test_generate_rewrites_with_concrete_problems(fake_llm):
    two = {"title": "t", "scenes": GOOD["scenes"][:2]}

    def reply(body):
        last = body["messages"][-1]["content"]
        return json.dumps(GOOD if "前の出力には次の問題がありました" in last else two, ensure_ascii=False)

    fake_llm.reply = reply
    result = generate(client_for(fake_llm), _messages(), model="m", schema=SCHEMA, validate=json_problems)
    assert result.ok and result.rewrites == 1
    assert result.attempts[0].problems == ["scenes が 2 件です（3 件）"]
    second = [r for r in fake_llm.requests if r["method"] == "POST"][1]["body"]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert "- scenes が 2 件です（3 件）" in second[-1]["content"] and "JSON だけで" in second[-1]["content"]
    assert second[2]["content"] == json.dumps(two, ensure_ascii=False)  # the previous answer is shown back


def test_generate_fails_after_two_rewrites(fake_llm):
    fake_llm.reply = lambda body: '{"title": "t"}'
    result = generate(client_for(fake_llm), _messages(), model="m", schema=SCHEMA, validate=json_problems)
    assert not result.ok and len(result.attempts) == 3 and result.rewrites == 2
    assert "2 回書き直しても検査に通りませんでした" in result.error and "scenes" in result.error
    assert result.value == {"title": "t"}  # last readable value is returned, never patched up
    assert [a.ok for a in result.attempts] == [False, False, False]


@pytest.mark.parametrize(
    "answer, finish, problem",
    [("", "stop", "本文が空です"), ("", "length", "上限"), ('{"title": "t", "sc', "length", "途中で切れて"),
     ("JSON はありません", "stop", "JSON として読めません")],
)
def test_generate_problem_kinds(fake_llm, answer, finish, problem):
    fake_llm.reply = lambda body: answer
    fake_llm.finish_reason = finish
    result = generate(client_for(fake_llm), _messages(), model="m", retries=0)
    assert not result.ok and len(result.attempts) == 1 and problem in result.attempts[0].problems[0]


def test_generate_transport_error_is_not_retried(fake_llm):
    fake_llm.status = 500
    result = generate(client_for(fake_llm), _messages(), model="m")
    assert not result.ok and len(result.attempts) == 1 and result.attempts[0].error_kind == "HTTP_ERROR"
    assert "応答を得られませんでした" in result.error
    assert len(fake_llm.requests) == 1


def test_generate_records_are_serialisable(fake_llm):
    fake_llm.reply = lambda body: json.dumps(GOOD, ensure_ascii=False)
    data = generate(client_for(fake_llm), _messages(), model="m").as_dict()
    assert json.loads(json.dumps(data))["attempts"][0]["ok"] is True


def test_rewrite_request_text():
    text = rewrite_request(["a が足りません", "b が長すぎます"])
    assert "- a が足りません\n- b が長すぎます" in text


# -- readings use the light task ------------------------------------------------------------------------


def test_suggest_uses_the_light_task(fake_llm, task_config):
    fake_llm.models = ["big-27b", "small-9b"]
    fake_llm.reply = lambda body: json.dumps({"readings": [{"term": "建具", "reading": "タテグ"}]}, ensure_ascii=False)
    report = suggest(client_for(fake_llm), [ReadingCheck("建具", "タテグ")], config=load_llm_config(task_config))
    assert report.model == "small-9b" and report.task == "light" and report.thinking == "off"
    assert fake_llm.requests[-1]["body"]["model"] == "small-9b"
    assert report.records and report.records[0]["ok"]


def test_suggest_stops_when_light_model_missing(fake_llm, task_config):
    fake_llm.models = ["big-27b"]
    with pytest.raises(ModelNotFoundError, match="task light"):
        suggest(client_for(fake_llm), [ReadingCheck("建具", "タテグ")], config=load_llm_config(task_config))
    assert [r for r in fake_llm.requests if r["method"] == "POST"] == []


def test_suggest_explicit_model_wins(fake_llm, task_config):
    fake_llm.models = ["big-27b", "small-9b"]
    fake_llm.reply = lambda body: json.dumps({"readings": [{"term": "建具", "reading": "タテグ"}]}, ensure_ascii=False)
    report = suggest(client_for(fake_llm), [ReadingCheck("建具", "タテグ")], model="big-27b", config=load_llm_config(task_config))
    assert report.model == "big-27b"
