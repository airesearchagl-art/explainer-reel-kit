import json
import shutil

import pytest
from pptx import Presentation

from deck_helpers import FIXTURES, NS, SAMPLES, all_xml_text, slide_roots, slide_transition, variant

from explainer_reel_kit.deck import BuildError, build_deck
from explainer_reel_kit.deck import cli as deck_cli
from explainer_reel_kit.deck.builder import load_storyboard
from explainer_reel_kit.deck.timing import Effect, Step, fit_to_budget, total_ms

P = "{%s}" % NS["p"]


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    """テスト用の台本から .pptx を生成（生成物は tmp に置き、commit しない）。"""
    out_dir = tmp_path_factory.mktemp("decks")
    return {key: build_deck(path, out_dir / f"{key}.pptx") for key, path in SAMPLES.items()}


def _doc(key):
    return load_storyboard(SAMPLES[key], None)


def _timing(sld):
    return sld.find("p:timing", NS)


def _effects(sld, preset_class):
    return sld.findall(f".//p:cTn[@presetClass='{preset_class}']", NS)


# ------------------------------------------------------------------ 基本構成

@pytest.mark.parametrize("key", ["web", "mixed"])
def test_opens_with_python_pptx_and_has_expected_slides(built, key):
    res = built[key]
    prs = Presentation(str(res.output))
    doc = _doc(key)
    assert len(prs.slides) == res.slide_count == 1 + len(doc["scenes"]) + 1
    assert prs.slide_width == 12192000 and prs.slide_height == 6858000  # 13.333in × 7.5in（16:9）


@pytest.mark.parametrize("key", ["web", "mixed"])
def test_notes_hold_narration(built, key):
    prs = Presentation(str(built[key].output))
    doc = _doc(key)
    expected = [doc["intro"]["narration"]] + [s["narration"] for s in doc["scenes"]] + [doc["outro"]["narration"]]
    got = [s.notes_slide.notes_text_frame.text for s in prs.slides]
    assert got == expected


@pytest.mark.parametrize("key", ["web", "mixed"])
def test_scene_slide_shows_heading_text_and_label(built, key):
    prs = Presentation(str(built[key].output))
    doc = _doc(key)
    for slide, scene in zip(list(prs.slides)[1:-1], doc["scenes"]):
        texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame]
        assert scene["heading"] in texts
        # 撮影前（プレースホルダー）は来歴ラベルの代わりに「撮影前（仮）」
        is_placeholder = any(t.startswith("撮影予定:") for t in texts)
        assert ("撮影前（仮）" if is_placeholder else scene["image"]["label"]) in texts
        if scene.get("on_screen_text") and scene["recipe"] != "text_build":
            assert scene["on_screen_text"] in texts


def test_intro_and_outro_content(built):
    prs = Presentation(str(built["mixed"].output))
    doc = _doc("mixed")
    intro_text = "\n".join(sh.text_frame.text for sh in prs.slides[0].shapes if sh.has_text_frame)
    assert doc["reel"]["title"] in intro_text and doc["intro"]["summary"] in intro_text
    assert all(p in intro_text for p in doc["intro"]["prerequisites"])
    assert "所要時間" not in intro_text  # deck 単体（秒数が分からない）では出さない
    outro_text = "\n".join(sh.text_frame.text for sh in prs.slides[-1].shapes if sh.has_text_frame)
    assert doc["outro"]["summary"] in outro_text and doc["outro"]["next"] in outro_text
    assert all(c in outro_text for c in doc["outro"]["checks"])


# ------------------------------------------------------------------ 画像

def test_missing_web_and_generated_images_become_placeholders(built):
    doc = _doc("mixed")
    expected = [s["image"]["ref"] for s in doc["scenes"] if s["image"]["source"] != "manual"]
    assert built["mixed"].placeholders == expected
    prs = Presentation(str(built["mixed"].output))
    texts = [sh.text_frame.text for sh in prs.slides[1].shapes if sh.has_text_frame]
    assert f"撮影予定: {expected[0]}" in texts


def test_existing_manual_image_is_embedded_as_picture(built):
    prs = Presentation(str(built["mixed"].output))
    doc = _doc("mixed")
    idx = next(i for i, s in enumerate(doc["scenes"]) if s["image"]["source"] == "manual")
    pics = [sh for sh in prs.slides[idx + 1].shapes if sh.shape_type == 13]  # PICTURE
    assert len(pics) == 1


def test_missing_manual_image_is_an_error(tmp_path):
    shutil.copy(SAMPLES["mixed"], tmp_path / "m.storyboard.json")  # 画像を持たない場所へコピー
    with pytest.raises(BuildError, match="manual"):
        build_deck(tmp_path / "m.storyboard.json", tmp_path / "out.pptx")


def test_assets_root_is_used_for_images(tmp_path):
    shutil.copy(SAMPLES["mixed"], tmp_path / "m.storyboard.json")
    res = build_deck(tmp_path / "m.storyboard.json", tmp_path / "out.pptx", assets_root=FIXTURES)
    assert res.slide_count == 8


# ------------------------------------------------------------------ 自動切替（advTm）

@pytest.mark.parametrize("key", ["web", "mixed"])
def test_every_slide_auto_advances_from_duration_sec(built, key):
    doc = _doc(key)
    expected = [6000] + [int(s.get("duration_sec", 6) * 1000) for s in doc["scenes"]] + [6000]
    roots = slide_roots(built[key].output)
    adv = []
    for sld in roots:
        trs = sld.findall("p:transition", NS) + sld.findall("mc:AlternateContent", NS)
        assert len(trs) == 1  # 切替はちょうど 1 つ（Morph は AlternateContent で 1 つ）
        tr, _ = slide_transition(sld)
        assert tr.get("advClick") == "0"  # クリック進行なし
        adv.append(int(tr.get("advTm")))
    assert adv == expected == built[key].adv_ms


def _durations(path, items, complete=True):
    path.write_text(json.dumps({
        "format": "explainer-reel/narration-durations", "version": 1, "complete": complete,
        "pre_pause_sec": 0.3, "post_pause_sec": 0.5,
        "items": [{"id": i, "wav": f"{i}.wav", "audio_sec": s - 0.8, "slide_sec": s} for i, s in items],
    }), encoding="utf-8")
    return path


def test_durations_json_overrides_seconds(tmp_path):
    doc = _doc("web")
    ids = ["intro"] + [s["id"] for s in doc["scenes"]] + ["outro"]
    secs = [round(3.15 + i * 1.01, 2) for i in range(len(ids))]
    dj = _durations(tmp_path / "durations.json", zip(ids, secs))
    res = build_deck(SAMPLES["web"], tmp_path / "d.pptx", durations=dj)
    got = [int(slide_transition(r)[0].get("advTm")) for r in slide_roots(res.output)]
    assert got == [int(round(s * 1000)) for s in secs]
    assert not any("durations.json" in w and "段落" not in w for w in res.warnings)


def test_durations_json_missing_id_falls_back_with_warning(tmp_path):
    dj = _durations(tmp_path / "durations.json", [("intro", 4.2), ("s01", 7.77)], complete=False)
    res = build_deck(SAMPLES["web"], tmp_path / "d.pptx", durations=dj)
    assert res.adv_ms[0] == 4200 and res.adv_ms[1] == 7770
    assert res.adv_ms[2] == int(_doc("web")["scenes"][1]["duration_sec"] * 1000)  # s02 は duration_sec
    assert res.adv_ms[-1] == 6000  # outro は既定
    assert any("complete=false" in w for w in res.warnings)


def test_durations_json_wrong_format_is_an_error(tmp_path):
    bad = tmp_path / "durations.json"
    bad.write_text(json.dumps({"items": []}), encoding="utf-8")
    with pytest.raises(BuildError, match="format"):
        build_deck(SAMPLES["web"], tmp_path / "d.pptx", durations=bad)


# ------------------------------------------------------------------ レシピの p:timing

def _slide_for(key, built, recipe):
    doc = _doc(key)
    roots = slide_roots(built[key].output)
    for i, s in enumerate(doc["scenes"]):
        if s["recipe"] == recipe:
            return roots[i + 1], s
    raise AssertionError(recipe)


def _chain_ok(sld):
    t = _timing(sld)
    assert t is not None
    # スライド開始で自動開始（クリック待ちなし）
    grp = t.find(".//p:seq/p:cTn/p:childTnLst/p:par/p:cTn", NS)
    conds = grp.findall("p:stCondLst/p:cond", NS)
    assert conds[0].get("delay") == "indefinite" and conds[1].get("evt") == "onBegin"
    effects = t.findall(".//p:cTn[@presetClass]", NS)
    assert effects and all(e.get("nodeType") in ("afterEffect", "withEffect") for e in effects)
    assert all(e.find("p:stCondLst/p:cond", NS).get("delay").isdigit() for e in effects)
    # 継続時間がすべて明示されている
    durs = [c.get("dur") for c in t.findall(".//p:cBhvr/p:cTn", NS)]
    assert durs and all(d and d.isdigit() for d in durs)
    # 段の開始時刻は単調増加
    steps = grp.findall("p:childTnLst/p:par/p:cTn", NS)
    starts = [int(s.find("p:stCondLst/p:cond", NS).get("delay")) for s in steps]
    assert starts == sorted(starts)
    return effects


def test_fade_sequence_heading_image_text(built):
    sld, scene = _slide_for("mixed", built, "fade_sequence")
    effects = _chain_ok(sld)
    assert len(effects) == 3 and {e.get("presetID") for e in effects} == {"10"}
    assert len(sld.findall(".//p:animEffect[@filter='fade']", NS)) == 3


def test_highlight_box_fade_and_blink(built):
    sld, _ = _slide_for("recipes", built, "highlight_box")
    _chain_ok(sld)
    assert len(_effects(sld, "emph")) == 1
    anim = sld.find(".//p:anim[@calcmode='discrete']", NS)
    assert [v.get("val") for v in anim.findall(".//p:strVal", NS)] == ["hidden", "visible"]
    box = [b for b in sld.findall(".//p:bldP", NS) if b.get("animBg") == "1"]
    assert {b.get("grpId") for b in box} == {"0", "1"}


def test_highlight_box_uses_recipe_params(tmp_path):
    def edit(doc):
        doc["scenes"][0]["recipe_params"] = {"box": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0}}
    res = build_deck(variant("recipes", tmp_path, edit), tmp_path / "df.pptx")
    slide = Presentation(str(res.output)).slides[1]
    img = next(s for s in slide.shapes if s.name == "Image Placeholder")
    box = next(s for s in slide.shapes if s.name == "Highlight Box")
    assert box.left == img.left and box.top == img.top
    assert abs(box.width - img.width // 2) <= 1 and abs(box.height - img.height) <= 1


def test_arrow_move_motion_path(built):
    sld, _ = _slide_for("recipes", built, "arrow_move")
    _chain_ok(sld)
    mo = sld.find(".//p:animMotion", NS)
    assert mo is not None and mo.get("path").startswith("M 0 0 L ") and mo.get("path").endswith(" E")
    assert len(_effects(sld, "path")) == 1


def test_text_build_by_paragraph(tmp_path):
    def edit(doc):
        doc["scenes"][1]["recipe_params"] = {"lines": ["項目A", "項目B", "項目C"]}
    res = build_deck(variant("recipes", tmp_path, edit), tmp_path / "df.pptx")
    sld = slide_roots(res.output)[2]
    _chain_ok(sld)
    rngs = [(r.get("st"), r.get("end")) for r in sld.findall(".//p:pRg", NS)]
    # set と animEffect の2要素 × 3段落
    assert sorted(set(rngs)) == [("0", "0"), ("1", "1"), ("2", "2")]
    assert any(b.get("build") == "p" for b in sld.findall(".//p:bldP", NS))


def test_morph_transition_uses_real_morph(built):
    """morph_transition は実際の Morph（Fallback はフェード）を書く。"""
    sld, scene = _slide_for("recipes", built, "morph_transition")
    assert sld.find("p:transition", NS) is None  # 素の p:transition は残さない
    tr, kind = slide_transition(sld)
    assert kind == "morph" and tr.get("advClick") == "0" and tr.get(f"{{{NS['p14']}}}dur") == "1000"
    assert tr.find("p159:morph", NS).get("option") == "byObject"
    assert _timing(sld) is None
    assert not any("morph_transition" in w for w in built["recipes"].warnings)  # 代替の警告は出さない


@pytest.mark.parametrize("key", ["web", "mixed", "example", "recipes"])
def test_alternate_content_only_for_morph(built, key):
    """mc:AlternateContent は Morph の切替にだけ使い、Requires="p159" と、フェードの Fallback を持つ。"""
    for sld in slide_roots(built[key].output):
        for ac in sld.findall("mc:AlternateContent", NS):
            choice = ac.find("mc:Choice", NS)
            assert choice.get("Requires") == "p159" and choice.nsmap.get("p159") == NS["p159"]
            assert [c.tag.split("}")[1] for c in ac] == ["Choice", "Fallback"]
            fb = ac.find("mc:Fallback/p:transition", NS)
            assert [c.tag.split("}")[1] for c in fb] == ["fade"]
            assert fb.get("advTm") == choice.find("p:transition", NS).get("advTm")
    xml = all_xml_text(built[key].output)
    assert xml.count("<mc:AlternateContent") == xml.count("<p159:morph")


# ------------------------------------------------------------------ 合計時間の整合

def test_fit_to_budget_shrinks_proportionally():
    steps = [Step([Effect("fade_in", 2, dur=1000, delay=500)]), Step([Effect("fade_in", 3, dur=2000, delay=500)])]
    assert total_ms(steps) == 4000
    steps, shrunk = fit_to_budget(steps, 2000)
    assert shrunk and total_ms(steps) <= 2000


def test_short_slide_shrinks_animation_and_warns(tmp_path):
    def edit(doc):
        assert doc["scenes"][3]["recipe"] == "arrow_move"
        doc["scenes"][3]["duration_sec"] = 1.5
    res = build_deck(variant("recipes", tmp_path, edit), tmp_path / "df.pptx")
    sld = slide_roots(res.output)[4]  # s04 arrow_move
    assert slide_transition(sld)[0].get("advTm") == "1500"
    steps = sld.findall(".//p:seq/p:cTn/p:childTnLst/p:par/p:cTn/p:childTnLst/p:par/p:cTn", NS)
    last_start = int(steps[-1].find("p:stCondLst/p:cond", NS).get("delay"))
    assert last_start < 1500
    assert any(w.startswith("s04:") and "縮めました" in w for w in res.warnings)


# ------------------------------------------------------------------ CLI

def test_cli_build(tmp_path, capsys):
    out = tmp_path / "x.pptx"
    assert deck_cli.main([str(SAMPLES["mixed"]), "--out", str(out)]) == 0
    assert out.is_file()
    assert "slides=8" in capsys.readouterr().out


def test_cli_errors(tmp_path, capsys):
    assert deck_cli.main([str(tmp_path / "none.md"), "--out", str(tmp_path / "x.pptx")]) == 2
    assert deck_cli.main([str(SAMPLES["mixed"]), "--out", str(tmp_path / "x.ppt")]) == 2
    shutil.copy(SAMPLES["mixed"], tmp_path / "m.storyboard.json")
    assert deck_cli.main([str(tmp_path / "m.storyboard.json"), "--out", str(tmp_path / "x.pptx")]) == 1
