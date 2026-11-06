from __future__ import annotations

import hashlib
import json
import urllib.parse
from pathlib import Path

import pytest

from explainer_reel_kit.llm.client import LLMClient
from explainer_reel_kit.llm.config import Endpoint
from explainer_reel_kit.llm.readings import (
    ReadingCheck,
    ask_readings,
    compare,
    is_katakana_reading,
    normalize_kana,
    render_section,
    suggest,
)
from explainer_reel_kit.narration.cli import main as narration_main
from explainer_reel_kit.narration.tts.aivisspeech import HttpResponse

# エンジンの読み（長音の書き方の違い）と LLM の候補の例
@pytest.mark.parametrize(
    "engine, candidate",
    [
        ("ヒツヨオフウ/リョオ", "ヒツヨウフウリョウ"),
        ("トオピッチ", "トウピッチ"),
        ("ゼセエソチ", "ゼセイソチ"),
        ("アンダアカット", "アンダーカット"),
        ("マイビョオニイテン/ゼロメエトル", "マイビョウニーテンゼロメートル"),
        ("パスコンポオネント,/アレイ", "パスコンポーネント・アレイ"),
        ("たてぐ", "タテグ"),
    ],
)
def test_normalize_treats_spelling_differences_as_equal(engine, candidate):
    assert normalize_kana(engine) == normalize_kana(candidate)


@pytest.mark.parametrize("engine, candidate", [("ハシブ", "タンブ"), ("カクアタリ", "カクヘン"), ("リイドゥミイ", "リードミー"),
                                               ("ヒツヨオカゼリョウ", "ヒツヨウフウリョウ")])
def test_normalize_keeps_real_differences(engine, candidate):
    assert normalize_kana(engine) != normalize_kana(candidate)


def test_is_katakana_reading():
    assert is_katakana_reading("タテグ") and is_katakana_reading("パス・アレイ")
    assert not is_katakana_reading("建具") and not is_katakana_reading("tategu") and not is_katakana_reading("")


CHECKS = [
    ReadingCheck("建具", "タテグ", None, "タテグ", "建具の枠から内側に"),            # check term, engine right
    ReadingCheck("必要風量", "ヒツヨオカゼリョウ", None, "ヒツヨオカゼリョウ", ""),  # check term, engine wrong
    ReadingCheck("端部", "タンブ", "タンブ", "ハシブ", ""),                          # entry fixes it
    ReadingCheck("README", "リイドミイ", "リードミー", "リイドゥミイ", ""),          # entry ok, engine still differs? (no: matches)
    ReadingCheck("辺", "アタリ", "アタリ", "アタリ", "辺ごとに"),                    # entry with a wrong reading
    ReadingCheck("累積長", "ルイセキチョオ", "ルイセキチョウ", "ルイセキチョオ", ""),  # entry not needed
    ReadingCheck("鉛直軸", "エンチョクジク", None, "エンチョクジク", ""),            # no candidate
]
CANDIDATES = {"建具": "タテグ", "必要風量": "ヒツヨウフウリョウ", "端部": "タンブ", "README": "リードミー", "辺": "ヘン",
              "累積長": "ルイセキチョウ"}


def test_compare():
    by_term = {s.term: s for s in compare(CHECKS, CANDIDATES)}
    assert by_term["建具"].status == "match" and by_term["建具"].yaml_line is None
    assert by_term["必要風量"].status == "mismatch"
    assert by_term["必要風量"].yaml_line == "  必要風量: ヒツヨウフウリョウ"
    assert by_term["端部"].status == "match" and by_term["端部"].note == ""
    assert by_term["README"].status == "match"
    assert by_term["辺"].status == "mismatch" and by_term["辺"].yaml_line == "  辺: ヘン   # 現在: アタリ"
    assert by_term["累積長"].status == "match" and "辞書から外せる" in by_term["累積長"].note
    assert by_term["鉛直軸"].status == "no_candidate"


def test_compare_entry_right_but_engine_differs():
    check = ReadingCheck("必要風量", "ヒツヨオカゼリョウ", "ヒツヨウフウリョウ", "ヒツヨオカゼリョウ")
    [s] = compare([check], {"必要風量": "ヒツヨウフウリョウ"})
    assert s.status == "mismatch" and s.yaml_line is None and "ユーザー辞書" in s.note


def _client(fake):
    return LLMClient(Endpoint("fake", fake.url, "m", 5))


def _json_reply(readings: dict[str, str]):
    return lambda body: json.dumps({"readings": [{"term": t, "reading": r} for t, r in readings.items()]},
                                   ensure_ascii=False)


def test_ask_readings_batches_and_filters(fake_llm):
    fake_llm.reply = _json_reply({"建具": "タテグ", "必要風量": "ひつようふうりょう", "部外": "ブガイ", "端部": "タンブ"})
    records = []
    readings, warnings = ask_readings(_client(fake_llm), CHECKS, model="m", batch_size=3, records=records)
    assert readings == {"建具": "タテグ", "端部": "タンブ"}  # readable entries of failed batches are still kept
    assert any("カタカナではない" in w for w in warnings)
    assert any("2 回書き直しても" in w and "読みがありません" in w for w in warnings)
    posts = [r for r in fake_llm.requests if r["method"] == "POST"]
    assert len(posts) == 9  # 7 terms in batches of 3, each asked once + 2 rewrites (the fake never improves)
    assert [len(r["attempts"]) for r in records] == [3, 3, 3] and not any(r["ok"] for r in records)
    prompt = posts[0]["body"]["messages"][-1]["content"]
    assert "- 建具（建具の枠から内側に）" in prompt and posts[0]["body"]["temperature"] == 0


def test_ask_readings_reports_bad_answers(fake_llm):
    fake_llm.reply = lambda body: "読みは次のとおりです"
    readings, warnings = ask_readings(_client(fake_llm), CHECKS[:2], model="m")
    assert readings == {} and len(warnings) == 1 and "JSON として読めません" in warnings[0]
    fake_llm.requests.clear()
    fake_llm.status = 500
    readings, warnings = ask_readings(_client(fake_llm), CHECKS[:2], model="m")
    assert readings == {} and "応答を得られませんでした" in warnings[0]
    assert len(fake_llm.requests) == 1  # transport errors are not retried as rewrites


def test_ask_readings_rewrite_fixes_the_answer(fake_llm):
    def reply(body):
        last = body["messages"][-1]["content"]
        if "前の出力には次の問題がありました" in last:  # the rewrite request names the missing term
            assert "必要風量" in last
            return json.dumps({"readings": [{"term": "建具", "reading": "タテグ"},
                                            {"term": "必要風量", "reading": "ヒツヨウフウリョウ"}]}, ensure_ascii=False)
        return "```json\n" + json.dumps({"readings": [{"term": "建具", "reading": "タテグ"}]}, ensure_ascii=False) + "\n```"

    fake_llm.reply = reply
    records = []
    readings, warnings = ask_readings(_client(fake_llm), CHECKS[:2], model="m", records=records)
    assert readings == {"建具": "タテグ", "必要風量": "ヒツヨウフウリョウ"} and warnings == []
    assert records[0]["ok"] and records[0]["rewrites"] == 1
    second = [r for r in fake_llm.requests if r["method"] == "POST"][1]["body"]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[0]["content"] and second[1]["content"].startswith("解説動画のナレーション")


def test_ask_readings_sends_thinking_off(fake_llm):
    fake_llm.reply = _json_reply({"建具": "タテグ"})
    ask_readings(_client(fake_llm), CHECKS[:1], model="m")
    body = fake_llm.requests[-1]["body"]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


def test_render_section_shows_only_a_proposal(fake_llm):
    fake_llm.reply = _json_reply(CANDIDATES)
    report = suggest(_client(fake_llm), CHECKS, model="test-model-7b")
    text = render_section(report)
    assert "test-model-7b" in text and "思考 off" in text
    assert "自動では書きません" in text and "dictionaries/" in text
    assert "```yaml\n  必要風量: ヒツヨウフウリョウ\n  辺: ヘン   # 現在: アタリ\n```" in text
    assert "| 必要風量 | ヒツヨオカゼリョウ | ヒツヨウフウリョウ | **不一致** |" in text


# -- erkit voice suggest（表示だけ。辞書は書かない） ----------------------------------------------

ENGINE_READINGS = {"必要風量": "ヒツヨオカゼリョウ", "建具": "タテグ", "端部": "ハシブ", "タンブ": "タンブ"}


def fake_engine(method, url, headers, body, timeout):
    """AivisSpeech の代わり: /audio_query は決まった読み（無ければ文のまま）を返す。"""
    parsed = urllib.parse.urlsplit(url)
    if parsed.path == "/version":
        return HttpResponse(200, b'"1.1.0"', "application/json")
    if parsed.path == "/speakers":
        speakers = [{"name": "S", "speaker_uuid": "u", "styles": [{"name": "N", "id": 808373280}]}]
        return HttpResponse(200, json.dumps(speakers).encode(), "application/json")
    if parsed.path == "/audio_query":
        text = dict(urllib.parse.parse_qsl(parsed.query))["text"]
        kana = ENGINE_READINGS.get(text, text)
        return HttpResponse(200, json.dumps({"kana": kana}, ensure_ascii=False).encode(), "application/json")
    return HttpResponse(404, b"{}", "application/json")


def _storyboard(tmp_path, confidentiality: str | None = "general") -> Path:
    level = f"confidentiality: {confidentiality}\n" if confidentiality else ""
    text = (
        "---\nid: t\ntitle: 読みの確かめ\nschema_version: kit-1.0.0\naudience: A\nkind: tool_intro\n"
        f"{level}aspect: \"16:9\"\noutput_name: t\n---\n\n"
        "## intro\n```yaml\nsummary: 読み\n```\n建具の枠を確認します。\n\n"
        "## s01: 風量を入力する\n```yaml\nwhere: 説明図\nimage:\n  source: generated\n  ref: assets/s01.png\n"
        "  label: 説明用再構成図\nrecipe: highlight_box\ncapture:\n  prompt: 入力欄\n```\n"
        "必要風量を入力します。\n\n端部合わせには対応しません。\n\n"
        "## outro\n```yaml\nsummary: 以上\n```\n以上です。\n"
    )
    path = tmp_path / "t.storyboard.md"
    path.write_text(text, encoding="utf-8")
    return path


def _dictionary(tmp_path) -> Path:
    path = tmp_path / "pron.yaml"
    path.write_text("version: 1\nentries:\n  端部: タンブ\ncheck_terms:\n  - 建具\n  - 必要風量\n", encoding="utf-8")
    return path


def _kit_dictionaries() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2] / "dictionaries"
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob("*.yaml"))}


def test_voice_suggest_end_to_end_never_writes_the_dictionary(fake_llm, llm_config, tmp_path, capsys):
    fake_llm.reply = _json_reply({"建具": "タテグ", "必要風量": "ヒツヨウフウリョウ", "端部": "タンブ"})
    dictionary = _dictionary(tmp_path)
    before = dictionary.read_bytes()
    before_mtime = dictionary.stat().st_mtime_ns
    kit_dicts = _kit_dictionaries()
    listing = sorted(p.name for p in tmp_path.iterdir())
    code = narration_main(["suggest", str(_storyboard(tmp_path)), "--dictionary", str(dictionary),
                           "--llm-config", str(llm_config)], transport=fake_engine)
    assert code == 0
    printed = capsys.readouterr().out
    assert printed.index("## 用語ごとの読み") < printed.index("## LLM による読みの候補")
    assert "```yaml\n  必要風量: ヒツヨウフウリョウ\n```" in printed
    assert "| 端部 | タンブ | タンブ | 一致 |" in printed
    # 表示だけ: 辞書は書かない・新しいファイルも作らない
    assert dictionary.read_bytes() == before and dictionary.stat().st_mtime_ns == before_mtime
    assert _kit_dictionaries() == kit_dicts
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(listing + ["t.storyboard.md"])
    prompt = [r for r in fake_llm.requests if r["method"] == "POST"][0]["body"]["messages"][-1]["content"]
    assert "- 必要風量（必要風量を入力します。）" in prompt


def test_voice_suggest_has_no_out_option(llm_config, tmp_path, capsys):
    code = narration_main(["suggest", str(_storyboard(tmp_path)), "--out", str(tmp_path / "x.yaml"),
                           "--llm-config", str(llm_config)], transport=fake_engine)
    assert code == 2 and not (tmp_path / "x.yaml").exists()


@pytest.mark.parametrize("level", [None, "confidential"])
def test_voice_suggest_unwritten_confidentiality_is_confidential(level, draft_config, tmp_path, capsys, no_socket):
    """区分が未記入・書き間違いの台本は社外秘: LAN の LLM には送らない（エンジンにも聞く前に止まる）。"""
    calls = []

    def engine(*args):
        calls.append(args)
        return fake_engine(*args)

    code = narration_main(["suggest", str(_storyboard(tmp_path, level)), "--dictionary", str(_dictionary(tmp_path)),
                           "--llm-config", str(draft_config), "--profile", "lan"], transport=engine)
    assert code == 1 and no_socket == [] and calls == []
    assert "社外秘" in capsys.readouterr().err


def test_voice_suggest_general_may_use_the_lan_profile(draft_config, tmp_path, monkeypatch):
    """general なら LAN の profile も作れる（ここでは送る直前で止めて、作れたことだけを見る）。"""
    from explainer_reel_kit.llm import readings

    from explainer_reel_kit.llm.errors import ConfigError

    seen = []

    def stop(client, checks, **kw):
        seen.append((client.endpoint.base_url, client.confidentiality))
        raise ConfigError("ここで止める")

    monkeypatch.setattr(readings, "suggest", stop)
    code = narration_main(["suggest", str(_storyboard(tmp_path)), "--dictionary", str(_dictionary(tmp_path)),
                           "--llm-config", str(draft_config), "--profile", "lan"], transport=fake_engine)
    assert code == 2 and seen == [("http://192.168.1.20:1234/v1", "general")]


def test_voice_suggest_needs_a_storyboard(llm_config, tmp_path, capsys):
    path = tmp_path / "narration-input.json"
    path.write_text(json.dumps({"items": []}), encoding="utf-8")
    assert narration_main(["suggest", str(path), "--llm-config", str(llm_config)], transport=fake_engine) == 2
    assert "台本" in capsys.readouterr().err


def test_voice_suggest_with_missing_light_model_exits(fake_llm, tmp_path, capsys):
    config = tmp_path / "llm_tasks.yaml"
    config.write_text(
        "version: 1\ndefault_profile: fake\ntasks:\n  light:\n    model: small-9b\n    thinking: \"off\"\n"
        f"profiles:\n  fake:\n    route: local\n    base_url: {fake_llm.url}\n    model: ''\n    timeout_sec: 5\n",
        encoding="utf-8",
    )
    code = narration_main(["suggest", str(_storyboard(tmp_path)), "--dictionary", str(_dictionary(tmp_path)),
                           "--llm-config", str(config)], transport=fake_engine)
    assert code == 1 and "small-9b" in capsys.readouterr().err
    assert [r for r in fake_llm.requests if r["method"] == "POST"] == []


def test_voice_suggest_is_registered_in_erkit(capsys):
    from explainer_reel_kit.cli import main as erkit

    assert erkit(["voice", "suggest", "--help"]) == 0
    assert "辞書のファイルは書かない" in "".join(capsys.readouterr().out.split())
