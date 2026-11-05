"""Fixes the splitting rules and dictionary behaviour documented in textproc.py."""

from __future__ import annotations

import pytest

from explainer_reel_kit.narration.errors import InputError
from explainer_reel_kit.config import KIT_ROOT

DEFAULT_PRONUNCIATION_PATH = KIT_ROOT / "dictionaries" / "architecture.yaml"  # 例の辞書（建築用語）
from explainer_reel_kit.narration.textproc import (
    PronunciationDictionary,
    split_paragraph_chunks,
    split_paragraphs,
    split_sentences,
    split_text,
)

# -- sentences (rules 1–2) -------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("一文目です。二文目です。", ["一文目です。", "二文目です。"]),
        ("本当ですか？はい！そうです", ["本当ですか？", "はい！", "そうです"]),
        ("えっ！？そうなの。", ["えっ！？", "そうなの。"]),  # mark runs stay together
        ("「開けます。」と言います。", ["「開けます。」", "と言います。"]),  # closer follows the mark
        ("（注意。）次へ。", ["（注意。）", "次へ。"]),
        ("注意!]次。", ["注意!]", "次。"]),  # ASCII ] is a closer too
        ("Is it OK? Yes!", ["Is it OK?", "Yes!"]),
        ("一行目\n二行目。\n\n  三行目  ", ["一行目", "二行目。", "三行目"]),  # newline ends a sentence
        ("   ", []),
        ("1.5メートルです。", ["1.5メートルです。"]),  # ASCII period is not a split point
    ],
)
def test_split_sentences(text, expected):
    assert split_sentences(text) == expected


# -- chunks (rules 3–5) ------------------------------------------------------------


def test_short_text_is_one_chunk():
    assert split_text("躯体を確認します。次へ進みます。", max_chars=120) == ["躯体を確認します。次へ進みます。"]


def test_greedy_packing_without_separator():
    text = "あいう。かきく。さしす。たち。"
    # sentences: 4 + 4 + 4 + 3 chars
    assert split_text(text, max_chars=8) == ["あいう。かきく。", "さしす。たち。"]
    assert split_text(text, max_chars=11) == ["あいう。かきく。", "さしす。たち。"]
    assert split_text(text, max_chars=12) == ["あいう。かきく。さしす。", "たち。"]
    assert split_text(text, max_chars=4) == ["あいう。", "かきく。", "さしす。", "たち。"]


def test_overlong_sentence_is_not_cut():
    long_sentence = "あ" * 30 + "。"
    assert split_text("前。" + long_sentence + "後。", max_chars=10) == ["前。", long_sentence, "後。"]


def test_chunks_rejoin_to_the_cleaned_text():
    text = "一。二！三？「四。」五\n六。"
    assert "".join(split_text(text, max_chars=3)) == "一。二！三？「四。」五六。"


def test_max_chars_must_be_positive():
    with pytest.raises(ValueError):
        split_text("あ。", max_chars=0)


# -- pronunciation dictionary ---------------------------------------------------------


def test_longest_match_and_single_pass():
    d = PronunciationDictionary({"見付": "ミツケ", "見付け": "ミツケ", "ミツケ": "NG"})
    # 見付け wins over 見付 (no "ミツケけ"), and the produced reading is not re-replaced
    assert d.apply("見付けと見付") == "ミツケとミツケ"


def test_empty_dictionary_is_identity():
    assert PronunciationDictionary.empty().apply("躯体") == "躯体"


def test_default_dictionary_file():
    d = PronunciationDictionary.load(DEFAULT_PRONUNCIATION_PATH)
    for surface in ["庇", "躯体", "竪樋", "笠木", "見付", "見込", "天端", "片開き", "竪框"]:
        assert surface in d.entries
    assert "ガラリ" in d.check_terms  # katakana: listed for checking, not replaced
    assert set(d.check_terms).isdisjoint(d.entries)
    assert d.apply("躯体の天端と竪樋、笠木の見付けと見込み。庇とガラリ。") == (
        "クタイのテンバとタテドイ、カサギのミツケとミコミ。ヒサシとガラリ。"
    )
    assert d.apply("竪框と框") == "タテガマチとカマチ"  # 竪框 wins over 框
    # surfaces that are replaced must never re-trigger inside a reading
    for reading in d.entries.values():
        assert d.apply(reading) == reading or reading in d.entries


# -- decisions from the kana measurement (AivisSpeech 1.1.0-dev) ---------------

REMOVED_AFTER_MEASUREMENT = ["建具", "等ピッチ", "累積長", "端点"]


@pytest.fixture(scope="module")
def default_dict():
    return PronunciationDictionary.load(DEFAULT_PRONUNCIATION_PATH)


@pytest.mark.parametrize("term", REMOVED_AFTER_MEASUREMENT)
def test_removed_terms_are_check_terms_only(default_dict, term):
    assert term not in default_dict.entries
    assert term in default_dict.check_terms


def test_removed_terms_pass_through_unchanged(default_dict):
    text = "建具枠、等ピッチ、全体累積長、端点どうし"
    assert default_dict.apply(text) == text


@pytest.mark.parametrize(
    "term, reading",
    [("端部", "タンブ"), ("README", "リードミー")],
)
def test_kept_terms(default_dict, term, reading):
    assert default_dict.entries[term] == reading


def test_wind_volume(default_dict):
    # no 必要風量 entry; only 風量 is replaced and 必要 stays as written
    assert "必要風量" not in default_dict.entries
    assert default_dict.entries["風量"] == "フウリョウ"
    assert default_dict.apply("必要風量を入力") == "必要フウリョウを入力"
    assert default_dict.apply("換気の風量÷目標風速") == "換気のフウリョウ÷目標風速"
    assert "必要風量" not in default_dict.check_terms


@pytest.mark.parametrize(
    "text, expected",
    [
        # misread in the kana measurement
        ("各辺の中で均等に並びます。", "各ヘンの中で均等に並びます。"),
        ("辺ごとに数え直す", "ヘンごとに数え直す"),
        ("辺の境目で", "ヘンの境目で"),
        # compounds containing 辺 keep their own reading (longest match), never 〜ヘン by accident
        ("この辺りで", "このアタリで"),
        ("周辺の納まり", "シュウヘンの納まり"),
        ("一辺の長さ", "イッペンの長さ"),
        ("近辺", "キンペン"),
        ("底辺と斜辺", "テイヘンとシャヘン"),
        ("水辺の外構", "ミズベの外構"),
        ("海辺・窓辺・浜辺・岸辺", "ウミベ・マドベ・ハマベ・キシベ"),
    ],
)
def test_hen_replacement(default_dict, text, expected):
    assert default_dict.apply(text) == expected


def test_narration_with_hen(default_dict):
    text = "部材は各辺の中で均等に並びます。辺ごとに数え直すので、辺の境目に必ず置かれます。"
    applied = default_dict.apply(text)
    assert "辺" not in applied
    assert "ヘンごとに" in applied and "各ヘンの中" in applied and "ヘンの境目" in applied


def test_dictionary_does_not_add_spaces(default_dict):
    """A space comes only from the storyboard text, never from the dictionary."""
    assert " " not in "".join(default_dict.entries.values())
    assert default_dict.apply("README は") == "リードミー は"
    assert default_dict.apply("READMEは") == "リードミーは"


def test_example_dictionary_is_not_used_by_default(tmp_path):
    """The architecture dictionary is an example: nothing loads it unless it is chosen."""
    from explainer_reel_kit.config import KitConfig, parse_config
    from explainer_reel_kit.narration.dictionaries import available_dictionaries, load_dictionaries, resolve_dictionary

    assert KitConfig().dictionaries == [] and parse_config({}).dictionaries == []
    assert "architecture" in available_dictionaries(tmp_path)
    assert resolve_dictionary("architecture", tmp_path) == DEFAULT_PRONUNCIATION_PATH
    merged, paths = load_dictionaries(["architecture"], tmp_path)
    assert paths == [DEFAULT_PRONUNCIATION_PATH] and merged.entries["躯体"] == "クタイ"


def test_dictionary_by_path_and_merge(tmp_path):
    from explainer_reel_kit.narration.dictionaries import load_dictionaries, resolve_dictionary
    from explainer_reel_kit.narration.errors import InputError

    own = tmp_path / "mine.yaml"
    own.write_text("entries:\n  躯体: ボディ\n  社名: シャメイ\ncheck_terms: [確認語]\n", encoding="utf-8")
    merged, _ = load_dictionaries(["architecture", str(own)], tmp_path)
    assert merged.entries["躯体"] == "ボディ"  # later wins
    assert merged.entries["天端"] == "テンバ" and "確認語" in merged.check_terms
    local = tmp_path / "dictionaries"
    local.mkdir()
    (local / "local.yaml").write_text("entries:\n  框: ワク\n", encoding="utf-8")
    assert resolve_dictionary("local", tmp_path) == local / "local.yaml"
    with pytest.raises(InputError, match="見つかりません"):
        resolve_dictionary("nothing", tmp_path)
    with pytest.raises(InputError, match="見つかりません"):
        resolve_dictionary(str(tmp_path / "none.yaml"), tmp_path)


@pytest.mark.parametrize(
    "content",
    [
        "entries: [a, b]\n",
        "version: 1\n",
        "entries:\n  躯体: ''\n",
        "entries:\n  '': クタイ\n",
        "entries:\n  躯体: [ク, タイ]\n",
        "entries: {躯体: クタイ\n",  # broken YAML
    ],
)
def test_invalid_dictionary(tmp_path, content):
    path = tmp_path / "dict.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(InputError):
        PronunciationDictionary.load(path)


def test_missing_dictionary(tmp_path):
    with pytest.raises(InputError):
        PronunciationDictionary.load(tmp_path / "nope.yaml")


# -- paragraphs (rule 0) ---------------------------------------------------------------


def test_split_paragraphs_ignores_blank_lines():
    assert split_paragraphs("一段落目。\n\n  \n二段落目。\r\n三段落目") == ["一段落目。", "二段落目。", "三段落目"]


def test_packing_never_crosses_a_paragraph():
    text = "あいう。かきく。\nさしす。"
    assert split_paragraph_chunks(text, max_chars=100) == [["あいう。かきく。"], ["さしす。"]]
    assert split_text(text, max_chars=100) == ["あいう。かきく。", "さしす。"]


def test_packing_inside_a_paragraph_is_unchanged():
    text = "あいう。かきく。さしす。\nたち。つて。"
    assert split_paragraph_chunks(text, max_chars=8) == [["あいう。かきく。", "さしす。"], ["たち。つて。"]]


def test_single_paragraph_keeps_old_behaviour():
    text = "あいう。かきく。さしす。たち。"
    assert split_paragraph_chunks(text, max_chars=8) == [["あいう。かきく。", "さしす。たち。"]]


def test_overlong_sentence_stays_in_its_paragraph():
    long_sentence = "あ" * 30 + "。"
    assert split_paragraph_chunks("前。\n" + long_sentence + "後。", max_chars=10) == [["前。"], [long_sentence, "後。"]]


def test_whitespace_only_text_has_no_paragraphs():
    assert split_paragraph_chunks(" \n \n") == []


# -- check_terms --------------------------------------------------------------------------


def test_check_terms_load_dedupe_and_skip_entries(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text("entries:\n  建具: タテグ\ncheck_terms:\n  - 意匠境界\n  - 建具\n  - 意匠境界\n", encoding="utf-8")
    d = PronunciationDictionary.load(path)
    assert d.check_terms == ["意匠境界"]
    assert d.apply("意匠境界と建具") == "意匠境界とタテグ"


def test_check_terms_are_optional(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text("entries:\n  建具: タテグ\ncheck_terms:\n", encoding="utf-8")
    assert PronunciationDictionary.load(path).check_terms == []


@pytest.mark.parametrize("content", ["check_terms: 意匠境界\n", "check_terms: [1]\n", "check_terms: ['  ']\n"])
def test_invalid_check_terms(tmp_path, content):
    path = tmp_path / "d.yaml"
    path.write_text("entries:\n  建具: タテグ\n" + content, encoding="utf-8")
    with pytest.raises(InputError):
        PronunciationDictionary.load(path)


def test_matches_lists_replaced_surfaces_once():
    d = PronunciationDictionary({"見付": "ミツケ", "見付け": "ミツケ", "建具": "タテグ"})
    assert d.matches("見付けと見付と建具と見付け") == ["見付け", "見付", "建具"]
