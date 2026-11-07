"""erkit draft: ダミーの資料から、偽の手元の LLM（127.0.0.1）で下書きを作り、erkit check を通す。ネットワークは使わない。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from explainer_reel_kit import storyboard as sb
from explainer_reel_kit.cli import main as erkit
from explainer_reel_kit.llm.budget import SAFETY_MARGIN, Budget, estimate_messages, estimate_tokens
from explainer_reel_kit.llm.client import LLMClient
from explainer_reel_kit.llm.condense import split_pieces
from explainer_reel_kit.llm.config import Endpoint
from explainer_reel_kit.llm.draft import (
    AUDIENCES,
    DraftRequest,
    avoid_word_warnings,
    build_markdown,
    build_prompt,
    default_out_dir,
    draft_max_tokens,
    read_sources,
    soft_warnings,
    unsupported_numbers,
)
from explainer_reel_kit.llm.errors import ConfigError
from explainer_reel_kit.llm.structured import VALUE_MAX_CHARS, schema_problems, short_value


def answer(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def posts(fake, model=None, *, measure=False):
    return [r["body"] for r in fake.requests if r["method"] == "POST"
            and (model is None or r["body"]["model"] == model) and (r["body"]["max_tokens"] == 1) == measure]


def is_rewrite(body) -> bool:
    return "前の出力には次の問題がありました" in body["messages"][-1]["content"]


def draft(config, out, source, *extra):
    return erkit(["draft", "dummy-tool", "--source", str(source), "--llm-config", str(config), "--out", str(out), *extra])


# ------------------------------------------------------------------ 合格する下書き

def test_draft_from_a_dummy_source_passes_check(fake_llm, draft_config, dummy_source, good_answer, tmp_path, capsys):
    fake_llm.reply = lambda body: answer(good_answer)
    out = tmp_path / "reels" / "dummy-tool"
    assert draft(draft_config, out, dummy_source) == 0
    md = out / "dummy-tool.storyboard.md"
    printed = capsys.readouterr().out
    assert f"OK {md}" in printed and "区分: confidential" in printed and "人がすること" in printed
    # erkit check でも合格（--strict でも）
    assert erkit(["check", str(md)]) == 0
    assert erkit(["check", "--strict", str(md)]) == 0
    doc = sb.load_storyboard(md)
    assert doc["reel"]["schema_version"] == sb.SCHEMA_VERSION and doc["reel"]["confidentiality"] == "confidential"
    assert doc["reel"]["audience"] == "A" and doc["reel"]["output_name"] == "dummy_tool"
    scene = doc["scenes"][0]
    assert scene["image"] == {"source": "generated", "ref": "assets/s01_open.png", "label": "説明用再構成図"}
    assert scene["capture"] == {"prompt": "ページの全体を描く"} and "recipe_params" not in scene
    assert [s["id"] for s in doc["scenes"]] == ["s01", "s02", "s03", "s04", "s05"]
    record = json.loads((out / "draft.json").read_text(encoding="utf-8"))
    assert record["status"] == "done" and record["confidentiality"] == "confidential"
    assert record["client_confidentiality"] == "confidential" and record["llm"]["model"] == "big-27b"
    assert record["sources"][0]["path"].endswith("dummy-tool.md")
    body = posts(fake_llm)[-1]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert "dummy-tool.md" in body["messages"][-1]["content"] and "5000 行" in body["messages"][-1]["content"]


def test_default_output_is_reels_id(fake_llm, draft_config, dummy_source, good_answer, tmp_path, monkeypatch):
    fake_llm.reply = lambda body: answer(good_answer)
    monkeypatch.chdir(tmp_path)
    assert erkit(["draft", "dummy-tool", "--source", str(dummy_source), "--llm-config", str(draft_config)]) == 0
    assert (tmp_path / "reels" / "dummy-tool" / "dummy-tool.storyboard.md").is_file()
    assert default_out_dir("x", tmp_path) == tmp_path / "reels" / "x"


def test_general_and_web_capture(fake_llm, draft_config, dummy_source, good_answer, tmp_path):
    fake_llm.reply = lambda body: answer(good_answer)
    out = tmp_path / "out"
    assert draft(draft_config, out, dummy_source, "--confidentiality", "general", "--capture", "web",
                 "--url", "http://127.0.0.1:8000/index.html", "--audience", "C", "--title", "集計ページ") == 0
    doc = sb.load_storyboard(out / "dummy-tool.storyboard.md")
    assert doc["reel"]["confidentiality"] == "general" and doc["reel"]["title"] == "集計ページ"
    assert doc["scenes"][1]["image"]["source"] == "web" and doc["scenes"][1]["image"]["label"] == "実キャプチャ"
    assert doc["scenes"][1]["capture"]["url"] == "http://127.0.0.1:8000/index.html"
    prompt = posts(fake_llm)[-1]["messages"][-1]["content"]
    assert AUDIENCES["C"] in prompt and "Web 画面（http://127.0.0.1:8000/index.html）" in prompt


def test_manual_capture_is_written_but_check_needs_the_images(fake_llm, draft_config, dummy_source, good_answer,
                                                             tmp_path, capsys):
    fake_llm.reply = lambda body: answer(good_answer)
    out = tmp_path / "out"
    assert draft(draft_config, out, dummy_source, "--capture", "manual") == 1  # 下書きはできたが、画像がまだ無い
    md = out / "dummy-tool.storyboard.md"
    assert md.is_file() and "manual 画像が見つかりません" in capsys.readouterr().out
    assert posts(fake_llm) and not any(is_rewrite(b) for b in posts(fake_llm))  # 画像が無いのは書き直しの理由ではない


# ------------------------------------------------------------------ 書き直し・止まるとき

def test_storyboard_problems_are_sent_back(fake_llm, draft_config, dummy_source, good_answer, tmp_path):
    bad = json.loads(answer(good_answer))
    bad["scenes"] = bad["scenes"][:4]  # 4 シーン（5 つ）
    bad["intro_narration"] = "## 見出し\n本文"  # Markdown の記号

    fake_llm.reply = lambda body: answer(good_answer if is_rewrite(body) else bad)
    assert draft(draft_config, tmp_path / "out", dummy_source) == 0
    rewrite = posts(fake_llm)[-1]["messages"][-1]["content"]
    assert "scenes が 4 件です。5 件にしてください" in rewrite
    record = json.loads((tmp_path / "out" / "draft.json").read_text(encoding="utf-8"))
    assert record["rewrites"] == 1


def test_markdown_in_the_text_is_sent_back(fake_llm, draft_config, dummy_source, good_answer, tmp_path):
    bad = json.loads(answer(good_answer))
    bad["scenes"][0]["narration"] = "```\nコード\n```"
    fake_llm.reply = lambda body: answer(good_answer if is_rewrite(body) else bad)
    assert draft(draft_config, tmp_path / "out", dummy_source) == 0
    assert "Markdown の記号" in posts(fake_llm)[-1]["messages"][-1]["content"]


def test_still_bad_after_rewrites_stops_and_records(fake_llm, draft_config, dummy_source, tmp_path, capsys):
    fake_llm.reply = lambda body: '{"title": "t"}'
    out = tmp_path / "out"
    assert draft(draft_config, out, dummy_source, "--retries", "1") == 1
    assert not (out / "dummy-tool.storyboard.md").exists()
    record = json.loads((out / "draft.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed" and len(record["attempts"]) == 2 and record["last_answer"] == '{"title": "t"}'
    assert "作れませんでした" in capsys.readouterr().err


def test_existing_storyboard_is_not_overwritten(fake_llm, draft_config, dummy_source, good_answer, tmp_path, capsys):
    fake_llm.reply = lambda body: answer(good_answer)
    out = tmp_path / "out"
    out.mkdir()
    md = out / "dummy-tool.storyboard.md"
    md.write_text("人が直した台本", encoding="utf-8")
    assert draft(draft_config, out, dummy_source) == 1
    assert md.read_text(encoding="utf-8") == "人が直した台本" and posts(fake_llm) == []
    assert "上書きしません" in capsys.readouterr().err


def test_missing_draft_model_stops_before_sending(fake_llm, draft_config, dummy_source, tmp_path, capsys):
    fake_llm.models = ["other"]
    assert draft(draft_config, tmp_path / "out", dummy_source) == 1
    assert posts(fake_llm) == [] and "big-27b" in capsys.readouterr().err


def test_server_model_is_used_when_nothing_is_set(fake_llm, llm_config, dummy_source, good_answer, tmp_path):
    fake_llm.reply = lambda body: answer(good_answer)
    assert draft(llm_config, tmp_path / "out", dummy_source) == 0
    assert posts(fake_llm)[-1]["model"] == "test-model-7b"


@pytest.mark.parametrize("extra, message", [
    (["--capture", "web"], "--url"),
    (["--url", "http://127.0.0.1/"], "--capture web"),
    (["--scenes", "9"], "1〜8"),
    (["--title", "x" * 81], "--title"),
    (["--retries", "-1"], "--retries"),
])
def test_argument_errors_before_anything(fake_llm, draft_config, dummy_source, tmp_path, capsys, extra, message):
    assert draft(draft_config, tmp_path / "out", dummy_source, *extra) == 2
    assert message in capsys.readouterr().err and fake_llm.requests == []


def test_bad_id_and_missing_source(fake_llm, draft_config, dummy_source, tmp_path, capsys):
    assert erkit(["draft", "Bad_ID!", "--source", str(dummy_source), "--llm-config", str(draft_config)]) == 2
    assert erkit(["draft", "x", "--llm-config", str(draft_config)]) == 2
    assert erkit(["draft", "x", "--source", str(tmp_path / "none.md"), "--llm-config", str(draft_config)]) == 2
    assert fake_llm.requests == []


def test_offline_flag_records_the_checks(fake_llm, draft_config, dummy_source, good_answer, tmp_path):
    fake_llm.reply = lambda body: answer(good_answer)
    assert draft(draft_config, tmp_path / "out", dummy_source, "--offline", "--confidentiality", "general") == 0
    record = json.loads((tmp_path / "out" / "draft.json").read_text(encoding="utf-8"))
    assert record["offline"] and record["offline_checks"][0]["ok"]


def test_offline_flag_stops_a_lan_server_even_for_general(draft_config, dummy_source, tmp_path, capsys, no_socket):
    assert draft(draft_config, tmp_path / "out", dummy_source, "--offline", "--confidentiality", "general",
                 "--profile", "lan") == 1
    assert no_socket == [] and "--offline" in capsys.readouterr().err


# ------------------------------------------------------------------ 動画で触れない語・数値

def test_avoid_words_are_in_the_prompt_and_warned(fake_llm, tmp_path, dummy_source, good_answer, capsys):
    fake_llm.models = ["m"]
    config = tmp_path / "llm.yaml"
    config.write_text("version: 1\nprofiles:\n  fk:\n"
                      f"    base_url: {fake_llm.url}\n    timeout_sec: 5\navoid_words: [社内の呼び名, Zeta]\n",
                      encoding="utf-8")
    value = json.loads(answer(good_answer))
    value["scenes"][2]["narration"] = "ここは社内の呼び名で言うと別の画面です。列を選びます。"
    value["scenes"][3]["capture_steps"] = ["zeta のメニューを開く"]
    fake_llm.reply = lambda body: answer(value)
    assert draft(config, tmp_path / "out", dummy_source) == 0
    assert "次の語には触れない: 社内の呼び名、Zeta" in posts(fake_llm)[-1]["messages"][-1]["content"]
    err = capsys.readouterr().err
    assert "scenes[2].narration に、動画で触れない語「社内の呼び名」" in err
    assert "scenes[3].capture_steps に、動画で触れない語「Zeta」" in err


def test_no_avoid_words_by_default(good_answer):
    req = DraftRequest("x", [Path("a.md")])
    assert req.avoid_words == () and avoid_word_warnings(good_answer, ()) == []
    assert "触れない" not in build_prompt(req, [])


def test_numbers_not_in_the_source_are_warned(dummy_source, good_answer):
    sources, _ = read_sources([dummy_source])
    req = DraftRequest("x", [dummy_source])
    assert unsupported_numbers(good_answer, sources, req) == []
    good_answer["scenes"][1]["narration"] = "読み込めるのは 9000 行までです。所要は 7 分です。"
    warnings = unsupported_numbers(good_answer, sources, req)
    assert any("9000 行" in w for w in warnings) and any("7 分" in w for w in warnings)


def test_soft_warnings(dummy_source, good_answer):
    sources, _ = read_sources([dummy_source])
    good_answer["scenes"][0]["heading"] = "あ" * 21
    good_answer["scenes"][1]["narration"] = "一文だけ。"
    good_answer["scenes"][2]["capture_steps"] = ["#submit を押す"]
    warnings = soft_warnings(good_answer, sources, DraftRequest("x", [dummy_source]))
    assert any("21 字" in w for w in warnings) and any("1 文" in w for w in warnings)
    assert any("セレクタ" in w for w in warnings)


def test_prompt_uses_the_generic_audiences():
    assert AUDIENCES["A"].startswith("初めての人") and AUDIENCES["B"].startswith("よく使う人")
    assert AUDIENCES["C"].startswith("専門家")
    owner_word = "施" + "主"
    req = DraftRequest("x", [Path("a.md")])
    text = build_prompt(req, []) + "".join(AUDIENCES.values())
    assert owner_word not in text and "建築" not in text and "Notion" not in text


def test_markdown_is_built_by_code(dummy_source, good_answer):
    sources, _ = read_sources([dummy_source])
    md = build_markdown(DraftRequest("x", [dummy_source]), good_answer, model="m", sources=sources)
    assert md.startswith("---\nid: x\n") and "aspect: '16:9'" in md and "下書き" in md
    assert sb.validate_storyboard(sb.markdown_to_storyboard(md)).errors == []


def test_long_source_is_cut_with_a_warning(tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("あ" * 30, encoding="utf-8")
    b.write_text("い" * 30, encoding="utf-8")
    sources, warnings = read_sources([a, b], limit=40)
    assert [s.chars for s in sources] == [30, 30] and sources[1].truncated and len(sources[1].text) == 10
    assert "先頭 10 字" in warnings[0]
    with pytest.raises(ConfigError, match="空"):
        (tmp_path / "e.md").write_text("  \n", encoding="utf-8")
        read_sources([tmp_path / "e.md"])


# ------------------------------------------------------------------ 長い資料: 要点に縮めてから（文脈長に収める）

def long_source(tmp_path) -> Path:
    parts = ["# 長いダミーの資料"]
    for i in range(1, 13):
        parts.append(f"## 機能 {i}\n" + f"機能 {i} は表の列を {i} 個まで並べ替えます。画面の左の欄で選びます。" * 20)
    path = tmp_path / "long.md"
    path.write_text("\n\n".join(parts), encoding="utf-8")
    return path


def test_long_source_is_condensed_then_drafted_within_the_budget(fake_llm, draft_config, good_answer, tmp_path):
    summary = "- 表の CSV を読み、合計と平均を出す。1 ファイル 5000 行まで\n- 左の欄で列を選ぶ\n"

    def reply(body):
        if body["max_tokens"] == 1:
            return "x"
        return summary if body["model"] == "small-9b" else answer(good_answer)

    fake_llm.reply = reply
    source = long_source(tmp_path)
    assert estimate_tokens(source.read_text(encoding="utf-8")) > Budget(8192).room(draft_max_tokens(5, 4096))
    out = tmp_path / "out"
    assert draft(draft_config, out, source) == 0
    light, main_calls = posts(fake_llm, "small-9b"), posts(fake_llm, "big-27b")
    assert len(light) >= 2 and len(main_calls) == 1
    for body in posts(fake_llm):
        assert estimate_messages(body["messages"]) + body["max_tokens"] + SAFETY_MARGIN <= 8192
    record = json.loads((out / "draft.json").read_text(encoding="utf-8"))
    assert record["budget"]["input"] == "condensed" and record["condensed"]["model"] == "small-9b"
    assert erkit(["check", str(out / "dummy-tool.storyboard.md")]) == 0


def test_long_source_without_task_light_stops_before_sending(fake_llm, tmp_path, capsys):
    fake_llm.models = ["m"]
    config = tmp_path / "llm.yaml"
    config.write_text(f"version: 1\nprofiles:\n  fk:\n    base_url: {fake_llm.url}\n    timeout_sec: 5\n"
                      "tasks:\n  draft:\n    max_tokens: 4096\n    expected_context: 8192\n", encoding="utf-8")
    fake_llm.reply = lambda body: "x"
    assert draft(config, tmp_path / "out", long_source(tmp_path)) == 2
    assert "task light" in capsys.readouterr().err
    assert posts(fake_llm) == []  # 測る呼び出し（max_tokens=1）だけ


def test_split_pieces_keeps_headings_and_fits(tmp_path):
    text = long_source(tmp_path).read_text(encoding="utf-8")
    pieces = split_pieces(text, 1500)
    assert len(pieces) >= 3 and all(estimate_tokens(p) <= 1500 for p in pieces)
    assert all(p.lstrip().startswith("#") for p in pieces)
    assert "".join(pieces).replace("\n", "") == text.strip().replace("\n", "")


def test_estimate_is_conservative():
    assert estimate_tokens("あいう") == 3
    assert estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2
    assert Budget(8192).room(4096) == 8192 - SAFETY_MARGIN - 4096
    assert draft_max_tokens(5, 4096) == 2800 and draft_max_tokens(8, 4096) == 4000 and draft_max_tokens(9, 4096) == 4096


def test_schema_problems_are_short_and_concrete():
    schema = {"type": "object", "required": ["title", "scenes"],
              "properties": {"title": {"type": "string", "maxLength": 10},
                             "kind": {"enum": ["a", "b"]},
                             "scenes": {"type": "array", "minItems": 3, "maxItems": 3,
                                        "items": {"type": "object", "required": ["heading"]}}}}
    long = "あ" * 500
    problems = schema_problems({"title": long, "kind": long, "scenes": [{"x": long}]}, schema)
    assert "title が 500 字です。10 字以内にしてください" in problems
    assert "scenes が 1 件です。3 件にしてください" in problems and "scenes[0] に heading がありません" in problems
    assert all(len(p) < VALUE_MAX_CHARS + 80 for p in problems)
    assert short_value("x" * 100) == "x" * VALUE_MAX_CHARS + "…"


def test_draft_with_the_library_api(fake_llm, dummy_source, good_answer, tmp_path):
    from explainer_reel_kit.llm.draft import draft_storyboard

    fake_llm.reply = lambda body: answer(good_answer)
    client = LLMClient(Endpoint("fake", fake_llm.url, "test-model-7b", 5))
    result = draft_storyboard(client, DraftRequest("lib-test", [dummy_source]), tmp_path / "o", task=None)
    assert result.ok and result.markdown.name == "lib-test.storyboard.md" and result.rewrites == 0


def test_explainer_kind(fake_llm, draft_config, dummy_source, good_answer, tmp_path):
    fake_llm.reply = lambda body: answer(good_answer)
    out = tmp_path / "out"
    assert draft(draft_config, out, dummy_source, "--kind", "explainer", "--confidentiality", "general") == 0
    doc = sb.load_storyboard(out / "dummy-tool.storyboard.md")
    assert doc["reel"]["kind"] == "explainer" and doc["reel"]["schema_version"] == "kit-1.1.0"
    prompt = posts(fake_llm)[-1]["messages"][-1]["content"]
    assert "一般の解説動画" in prompt and "問い（身近な場面）→ しくみ" in prompt
    assert "構成の決まり" not in build_prompt(DraftRequest("x", [dummy_source]), [])
