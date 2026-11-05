from __future__ import annotations

import json

import pytest

from explainer_reel_kit.narration.cli import main
from explainer_reel_kit.narration.errors import EngineError, EngineErrorKind, InputError
from explainer_reel_kit.narration.kana import (
    SourceText,
    build_report,
    collect_terms,
    load_storyboard_texts,
    reading_of,
)
from explainer_reel_kit.narration.textproc import PronunciationDictionary
from conftest import EXAMPLE, FIXTURES

TERMS = FIXTURES / "narration_terms.storyboard.json"  # 建築用語を含むナレーション（区分 general）


def moras_query(*phrases: str, pause_after: int | None = None) -> dict:
    return {
        "accent_phrases": [
            {
                "moras": [{"text": ch, "vowel": "a"} for ch in phrase],
                "accent": 1,
                "pause_mora": {"text": "、"} if i == pause_after else None,
            }
            for i, phrase in enumerate(phrases)
        ],
        "kana": "ignored when moras exist",
    }


# -- readings ------------------------------------------------------------------------


def test_reading_from_moras_with_pause():
    assert reading_of(moras_query("タテグノ", "ワク", pause_after=0)) == "タテグノ、/ワク"


def test_reading_falls_back_to_kana():
    assert reading_of({"accent_phrases": [{"opaque": True}], "kana": "タ'テグ"}) == "タ'テグ"
    assert reading_of({"kana": "ケ'ング"}) == "ケ'ング"


def test_reading_missing_is_malformed():
    with pytest.raises(EngineError) as info:
        reading_of({"accent_phrases": []})
    assert info.value.kind is EngineErrorKind.MALFORMED_RESPONSE


# -- sources --------------------------------------------------------------------------


def test_load_storyboards():
    texts, speaker = load_storyboard_texts(TERMS)
    assert [t.item_id for t in texts] == ["intro", "s01", "s02", "s03", "s04", "s05", "s06", "outro"]
    assert speaker is None  # the storyboard does not fix a voice
    assert all(t.source == "narration_terms" for t in texts)
    assert "\n" in texts[1].text  # paragraphs survive


def test_storyboard_md_is_read_directly():
    texts, _ = load_storyboard_texts(EXAMPLE)
    assert texts[0].source == "hello-kit" and [t.item_id for t in texts][-1] == "outro"


def test_unreadable_storyboard(tmp_path):
    bad = tmp_path / "bad.storyboard.md"
    bad.write_text("no front matter", encoding="utf-8")
    with pytest.raises(InputError, match="台本を読めません"):
        load_storyboard_texts(bad)


@pytest.mark.parametrize(
    "doc",
    [
        {"intro": {"narration": "a"}},
        {"intro": {"narration": "a"}, "scenes": [{"narration": "b"}], "outro": {"narration": "c"}},
        {"intro": {}, "scenes": [], "outro": {"narration": "c"}},
    ],
)
def test_storyboard_shape_errors(tmp_path, doc):
    path = tmp_path / "x.storyboard.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(InputError):
        load_storyboard_texts(path)


def test_storyboard_integer_speaker(tmp_path):
    doc = {
        "reel": {"voice": {"speaker": 7}},
        "intro": {"narration": "a"},
        "scenes": [{"id": "s01", "narration": "b"}],
        "outro": {"narration": "c"},
    }
    path = tmp_path / "x.storyboard.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert load_storyboard_texts(path)[1] == 7


# -- terms & report --------------------------------------------------------------------


DICT = PronunciationDictionary({"建具": "タテグ", "竪框": "タテガマチ"}, ["意匠境界", "片引き"])
TEXTS = [
    SourceText("a.json", "s01", "建具の枠と意匠境界。\n建具全体。"),
    SourceText("a.json", "s02", "意匠境界です。"),
]


def test_collect_terms_counts_and_locations():
    rows = collect_terms(TEXTS, DICT)
    assert [(r.term, r.occurrences, r.items) for r in rows] == [
        ("建具", 2, ["a.json:s01"]),
        ("意匠境界", 2, ["a.json:s01", "a.json:s02"]),
    ]
    assert [r.term for r in collect_terms(TEXTS, DICT, include_absent=True)] == ["建具", "竪框", "意匠境界", "片引き"]


def test_report_shows_raw_and_dictionary_readings(client, engine):
    report = build_report(TEXTS, DICT, client, speaker=888753760)
    # the fake engine echoes the text back as the reading
    assert "| 建具 | 辞書 | タテグ | 建具 | タテグ | 2 | a.json:s01 |" in report
    assert "| 意匠境界 | 確認のみ | — | 意匠境界 | — | 2 | a.json:s01, a.json:s02 |" in report
    assert "竪框" not in report
    assert "speaker: 888753760 Test Speaker / ノーマル" in report
    sent = engine.synthesized_texts()
    assert sent == ["建具", "タテグ", "意匠境界"]  # nothing synthesized, only /audio_query
    assert "/synthesis" not in engine.paths()


def test_report_sentences_follow_synthesis_units(client, engine):
    report = build_report(TEXTS, DICT, client, speaker=888753760, sentences=True)
    assert "### a.json:s01" in report
    assert "- 段落1: タテグの枠と意匠境界。" in report
    assert "- 段落2: タテグ全体。" in report


def test_report_defaults_to_first_voice(client):
    assert "（指定なしのためエンジンの先頭の話者）" in build_report(TEXTS, DICT, client, speaker=None)


def test_report_unknown_speaker(client):
    with pytest.raises(InputError, match="12345"):
        build_report(TEXTS, DICT, client, speaker=12345)


def test_report_audio_query_failure_is_reported(client, engine, make_response):
    engine.overrides["/audio_query"] = make_response(500, "boom")
    with pytest.raises(EngineError) as info:
        build_report(TEXTS, DICT, client, speaker=888753760)
    assert info.value.kind is EngineErrorKind.AUDIO_QUERY_FAILED


def test_report_uses_moras_from_engine(client, engine):
    from explainer_reel_kit.narration.tts.aivisspeech import HttpResponse

    engine.overrides["/audio_query"] = lambda call: HttpResponse(
        200, json.dumps(moras_query("ケング"), ensure_ascii=False).encode("utf-8")
    )
    report = build_report([SourceText("a.json", "s01", "建具。")], DICT, client, speaker=888753760)
    assert "| 建具 | 辞書 | タテグ | ケング | ケング |" in report


# -- CLI ----------------------------------------------------------------------------------


def test_cli_kana_with_two_storyboards(engine, tmp_path, capsys):
    out = tmp_path / "report" / "kana.md"
    code = main(
        ["kana", str(TERMS), str(EXAMPLE), "--speaker", "7", "--out", str(out), "--dictionary", "architecture",
         "--engine-url", "http://engine.test:10101"],
        transport=engine,
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert out.read_text(encoding="utf-8") == printed
    for term in ["建具", "等ピッチ", "躯体", "意匠境界", "アンダーカット"]:
        assert f"| {term} |" in printed
    assert "speaker: 7 Test Speaker / Alt" in printed
    assert "/synthesis" not in engine.paths()


def test_cli_kana_sentences_and_input(engine, tmp_path, make_input, capsys):
    path = tmp_path / "narration-input.json"
    path.write_text(json.dumps(make_input(), ensure_ascii=False), encoding="utf-8")
    assert main(["kana", str(path), "--sentences", "--dictionary", "architecture"], transport=engine) == 0
    printed = capsys.readouterr().out
    assert "speaker: 888753760" in printed  # taken from the input
    assert "### narration-input:scene-01" in printed
    assert "- 段落1: クタイのテンバを確認します。" in printed


def test_cli_kana_errors(engine, tmp_path, capsys):
    assert main(["kana"], transport=engine) == 2
    assert main(["kana", str(TERMS), "--speaker", "12345"], transport=engine) == 2
    assert main(["kana", str(tmp_path / "none.json")], transport=engine) == 2
    engine.connection_down = True
    assert main(["kana", str(TERMS)], transport=engine) == 1
    assert "ENGINE_CONNECTION_FAILED" in capsys.readouterr().err


def test_cli_kana_confidential_storyboard_stays_on_this_pc(engine, tmp_path, capsys):
    doc = json.loads(TERMS.read_text(encoding="utf-8"))
    del doc["reel"]["confidentiality"]  # 未記入は confidential
    sb = tmp_path / "secret.storyboard.json"
    sb.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert main(["kana", str(sb), "--engine-url", "http://engine.test:10101"], transport=engine) == 2
    assert "社外秘" in capsys.readouterr().err
    assert "/audio_query" not in engine.paths()
    assert main(["kana", str(sb), "--engine-url", "http://127.0.0.1:10101", "--speaker", "7"], transport=engine) == 0


def test_check_term_containing_a_dictionary_word_shows_both(client):
    d = PronunciationDictionary({"PowerPoint": "パワーポイント"}, ["PowerPoint 2024"])
    report = build_report([SourceText("a", "intro", "PowerPoint 2024 の Windows 版")], d, client, speaker=888753760)
    assert "| PowerPoint 2024 | 確認のみ | — | PowerPoint 2024 | パワーポイント 2024 | 1 | a:intro |" in report
