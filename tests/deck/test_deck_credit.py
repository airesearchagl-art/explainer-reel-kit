from pptx import Presentation

from deck_helpers import SAMPLES

from explainer_reel_kit.deck import build_deck
from explainer_reel_kit.deck import cli as deck_cli


def _outro_texts(path):
    slide = Presentation(str(path)).slides[-1]
    return {sh.name: sh.text_frame.text for sh in slide.shapes if sh.has_text_frame}


def test_outro_shows_credit_when_given(tmp_path):
    res = build_deck(SAMPLES["web"], tmp_path / "c.pptx", credit="テストの声")
    assert _outro_texts(res.output)["Voice Credit"] == "ナレーション音声: テストの声"


def test_credit_is_static_not_animated(tmp_path):
    res = build_deck(SAMPLES["web"], tmp_path / "c.pptx", credit="テストの声")
    slide = Presentation(str(res.output)).slides[-1]
    credit_id = next(sh.shape_id for sh in slide.shapes if sh.name == "Voice Credit")
    xml = slide._element.xml
    assert f'spid="{credit_id}"' not in xml


def test_no_credit_by_default(tmp_path):
    res = build_deck(SAMPLES["web"], tmp_path / "n.pptx")
    assert "Voice Credit" not in _outro_texts(res.output)


def test_cli_credit_option(tmp_path, capsys):
    out = tmp_path / "x.pptx"
    assert deck_cli.main([str(SAMPLES["web"]), "--out", str(out), "--credit", "テストの声"]) == 0
    assert _outro_texts(out)["Voice Credit"].endswith("テストの声")
