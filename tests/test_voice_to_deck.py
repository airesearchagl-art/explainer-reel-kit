"""例の台本から、偽の音声エンジン（AivisSpeech ではない TTSEngine）で durations.json と .pptx を作る。"""
from __future__ import annotations

import json

import pytest
from pptx import Presentation

from deck_helpers import pptx_total_sec, slide_roots, slide_transition
from explainer_reel_kit import storyboard as sb
from explainer_reel_kit.cli import main as erkit
from explainer_reel_kit.deck import build_deck
from explainer_reel_kit.narration import tts
from explainer_reel_kit.narration.adapter import slide_ids, storyboard_to_narration_input
from explainer_reel_kit.narration.synth import parse_input, run_synth
from conftest import EXAMPLE
from narration_fakes import FakeTTS


def test_example_storyboard_to_durations_and_pptx(tmp_path):
    doc = sb.load_storyboard(EXAMPLE)
    narration = parse_input(storyboard_to_narration_input(doc))
    engine = FakeTTS()
    assert isinstance(engine, tts.TTSEngine)

    durations = run_synth(narration, tmp_path / "voice", engine, log=lambda m: None)
    dj = tmp_path / "voice" / "durations.json"
    assert dj.is_file() and durations["complete"] is True and durations["engine"] == "fake"
    assert [i["id"] for i in durations["items"]] == slide_ids(doc)
    assert [s[1] for s in engine.spoken] == [808373280] * len(engine.spoken)  # 既定の声（ほのか / ノーマル）
    for item in durations["items"]:
        assert (tmp_path / "voice" / item["wav"]).is_file()
        assert item["slide_sec"] == pytest.approx(item["audio_sec"] + 0.8, abs=0.011)

    res = build_deck(EXAMPLE, tmp_path / "hello_kit.pptx", durations=dj)
    prs = Presentation(str(res.output))
    assert len(prs.slides) == len(slide_ids(doc))
    adv = [int(slide_transition(r)[0].get("advTm")) for r in slide_roots(res.output)]
    assert adv == [round(i["slide_sec"] * 1000) for i in durations["items"]]
    assert res.video_sec == pytest.approx(pptx_total_sec(res.output))
    # ナレーションはノートに入る
    assert prs.slides[1].notes_slide.notes_text_frame.text == doc["scenes"][0]["narration"]


def test_cli_voice_then_deck_with_a_plugged_engine(tmp_path, monkeypatch, capsys):
    """entry point で足したエンジンを --engine で選び、erkit voice synth → erkit deck。"""
    fake = FakeTTS()
    monkeypatch.setattr(tts, "available_engines", lambda: {"aivisspeech": tts._builtin()["aivisspeech"],
                                                           "fake": lambda url, **kw: fake})
    cfg = tmp_path / "kit.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("ERKIT_CONFIG", str(cfg))
    out = tmp_path / "voice"
    assert erkit(["voice", "synth", str(EXAMPLE), "--engine", "fake", "--engine-url", "http://127.0.0.1:9", "--out-dir", str(out)]) == 0
    assert json.loads((out / "durations.json").read_text(encoding="utf-8"))["engine"] == "fake"
    pptx = tmp_path / "deck" / "hello_kit.pptx"
    assert erkit(["deck", str(EXAMPLE), "--out", str(pptx), "--durations", str(out / "durations.json"),
                  "--overlay", str(tmp_path / "deck" / "overlay.png")]) == 0
    assert pptx.is_file() and (tmp_path / "deck" / "overlay.png").is_file()
    assert "slides=7" in capsys.readouterr().out


def test_get_engine_defaults_and_errors():
    eng = tts.get_engine(None)
    assert eng.name == "aivisspeech" and eng.url == "http://127.0.0.1:10101"
    assert tts.get_engine("aivisspeech", "http://127.0.0.1:1/").url == "http://127.0.0.1:1"
    with pytest.raises(Exception, match="使えるもの"):
        tts.get_engine("nothing")
