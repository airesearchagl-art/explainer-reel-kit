"""interactive の既定の場面と image 部品: 来歴ラベル・見出し・台本の注釈を slides と同じく出す。

キットの決まり（AGENTS.md 4 節「画面を捏造しない」）: 実際に撮った画面は 実キャプチャ、説明図は 説明用再構成図 と
画面に出す。interactive でも、既定の場面（場面コードも scenes.yaml も無い場面）と image 部品で必ず出ること、
赤枠・矢印は slides と同じ段落の時刻に出ることを、表示リスト（描画の記録）で確かめる。
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml
from PIL import Image

from explainer_reel_kit.deck import recipes as rc
from explainer_reel_kit.interactive import engine, spec
from explainer_reel_kit.interactive.convert import from_storyboard
from explainer_reel_kit.interactive.engine import ACCENT, SUB_TOP, LayoutError, texts_of
from explainer_reel_kit.interactive.parts.image import IMG_PROPS, LABELS
from explainer_reel_kit.interactive.render import Project, Renderer
from explainer_reel_kit.interactive.scenes import LABEL_RIGHT
from explainer_reel_kit.interactive.timeline import validate_timeline

MARKS_FORMAT = "explainer-reel/marks@1"
SEC = 8.0   # 1 場面の秒


@dataclass
class _T:
    id: str
    start_ms: int
    adv_ms: int
    transition_ms: int


def _png(assets: Path, name: str, size: tuple[int, int], marks: dict) -> None:
    assets.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (235, 238, 242)).save(assets / name)
    w, h = size
    (assets / (Path(name).stem + ".marks.json")).write_text(json.dumps({
        "format": MARKS_FORMAT, "scene": "", "source": "web", "image": name, "image_size": {"w": w, "h": h},
        "marks": {n: {"box": b, "px": {"x": round(b["x"] * w), "y": round(b["y"] * h), "w": round(b["w"] * w),
                                       "h": round(b["h"] * h)}, "how": "test"} for n, b in marks.items()}}),
        encoding="utf-8")


DOC = {
    "reel": {"id": "demo", "title": "デモ"}, "intro": {"summary": "要約です。"},
    "scenes": [
        {"id": "s01", "heading": "画面を開く", "image": {"source": "web", "ref": "s1.png", "label": "実キャプチャ"},
         "recipe": "highlight_box", "recipe_params": {"mark": ["first", "second"]}, "on_screen_text": "条件を入れる"},
        {"id": "s02", "heading": "結果を比べる", "image": {"source": "web", "ref": "s2.png", "label": "実キャプチャ"},
         "recipe": "arrow_move", "recipe_params": {"to": {"mark": "target"}}},
        {"id": "s03", "heading": "図で見る", "image": {"source": "generated", "ref": "s3.png", "label": "説明用再構成図"},
         "recipe": "fade_sequence"},
        {"id": "s04", "heading": "まだ撮っていない", "image": {"source": "web", "ref": "s4.png", "label": "実キャプチャ"},
         "recipe": "fade_sequence"},
        {"id": "s05", "heading": "ツールの紹介", "image": {"source": "generated", "ref": "s5.png", "label": "説明用再構成図"},
         "recipe": "fade_sequence", "recipe_params": {"card": {"title": "カードの題", "text": "説明の文"}}},
    ],
    "outro": {"summary": "まとめです。"}}
IDS = ["intro", "s01", "s02", "s03", "s04", "s05", "outro"]
NARRATION = {"s01": "一つ目の段落です。\n二つ目の段落です。", "s02": "矢印で指します。", "s03": "図を見ます。"}


def build(tmp_path: Path, doc: dict = DOC) -> tuple[dict, Renderer]:
    work = tmp_path / "work"
    assets = work / "assets"
    _png(assets, "s1.png", (1600, 900), {"first": {"x": 0.1, "y": 0.3, "w": 0.15, "h": 0.2},
                                          "second": {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}})
    _png(assets, "s2.png", (1600, 900), {"target": {"x": 0.6, "y": 0.4, "w": 0.15, "h": 0.1}})
    _png(assets, "s3.png", (2420, 1000), {})
    timings = [_T(i, int(k * SEC * 1000), int(SEC * 1000), 0) for k, i in enumerate(IDS)]
    durations = {"pre_pause_sec": 0.3, "items": [
        {"id": "s01", "audio_sec": 6.0, "paragraph_starts_sec": [0.0, 3.0]},
        {"id": "s02", "audio_sec": 2.0, "paragraph_starts_sec": [0.0]},
        {"id": "s03", "audio_sec": 2.0, "paragraph_starts_sec": [0.0]}]}
    images = {"s01": "assets/s1.png", "s02": "assets/s2.png", "s03": "assets/s3.png"}
    tl, _ = from_storyboard(doc, timings, durations, NARRATION, images=images, total_ms=int(len(IDS) * SEC * 1000),
                            image_dir=work)
    assert validate_timeline(tl) == []
    path = work / "render-timeline.json"
    path.write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")
    return tl, Renderer(Project(timeline=path))


def scene_ops(r: Renderer, sec: float) -> tuple:
    return r.layers(int(round(sec * 30)))[0]


def texts_at(r: Renderer, sec: float) -> list[str]:
    return texts_of(scene_ops(r, sec))


def red_boxes(ops) -> list:
    return [(k, x, y) for k, x, y, _ in ops if k[0] == "rr" and k[5] == ACCENT]


def arrows(ops) -> list:
    return [(k, x, y) for k, x, y, _ in ops if k[0] == "arrow"]


def start_of(sid: str) -> float:
    return IDS.index(sid) * SEC


# ---------------------------------------------------------------- 既定の場面: 来歴ラベル・見出し

def test_default_scene_always_shows_the_provenance_label(tmp_path):
    tl, r = build(tmp_path)
    sc = {s["id"]: s for s in tl["scenes"]}
    assert sc["s01"]["label"] == "実キャプチャ" and sc["s03"]["label"] == "説明用再構成図"
    end = SEC - 0.1
    assert "実キャプチャ" in texts_at(r, start_of("s01") + end)
    assert "実キャプチャ" in texts_at(r, start_of("s02") + end)
    assert "説明用再構成図" in texts_at(r, start_of("s03") + end)
    # 画像が出る前（場面の始まり）から出ている（slides の来歴ラベルもアニメーションしない）
    assert "実キャプチャ" in texts_at(r, start_of("s01") + 0.05)


def test_placeholder_says_before_capture_and_card_has_no_label(tmp_path):
    tl, r = build(tmp_path)
    sc = {s["id"]: s for s in tl["scenes"]}
    assert sc["s04"]["label"] == "撮影前（仮）" and sc["s04"]["placeholder"] == {"ref": "s4.png", "reason": "撮影予定"}
    t4 = texts_at(r, start_of("s04") + SEC - 0.1)
    assert "撮影前（仮）" in t4 and "実キャプチャ" not in t4 and "撮影予定: s4.png" in t4
    t5 = texts_at(r, start_of("s05") + SEC - 0.1)
    assert "カードの題" in t5 and "説明の文" in t5
    assert not set(t5) & {*LABELS, "撮影前（仮）"}   # 文字だけのカードは来歴を出さない（slides と同じ）


def test_heading_is_drawn_like_slides(tmp_path):
    _, r = build(tmp_path)
    for sid, heading in (("s01", "画面を開く"), ("s02", "結果を比べる"), ("s04", "まだ撮っていない"), ("s05", "ツールの紹介")):
        assert heading in texts_at(r, start_of(sid) + SEC - 0.1)
    # 見出しは slides と同じく少し遅れて現れる（LEAD_IN の後）
    ops = scene_ops(r, start_of("s01") + 0.1)
    assert "画面を開く" not in texts_of(ops)
    # 画面テキスト（on_screen_text）は interactive では出さない（字幕の帯と重なるため。本家と同じ）
    assert "条件を入れる" not in texts_at(r, start_of("s01") + SEC - 0.1)


def test_label_heading_and_image_stay_above_the_subtitle_band(tmp_path):
    _, r = build(tmp_path)
    for sid in ("s01", "s02", "s03", "s04", "s05"):
        for key, x, y, _ in scene_ops(r, start_of(sid) + SEC - 0.1):
            if key[0] == "text":
                assert y + key[3] < SUB_TOP, (sid, key[1], y)
            if key[0] == "img":
                assert y + key[3] <= SUB_TOP, (sid, key, y)
    # 来歴ラベルは画像枠の右端にそろえた右寄せ
    lab = [(k, x) for k, x, y, _ in scene_ops(r, start_of("s01") + SEC - 0.1) if k[0] == "text" and k[1] == "実キャプチャ"]
    assert lab and abs(lab[0][1] + engine.tw("実キャプチャ", "R", lab[0][0][3]) + engine.TP - LABEL_RIGHT) <= 1


# ---------------------------------------------------------------- 既定の場面: 台本の注釈（marks.json）

def test_boxes_follow_the_paragraphs_like_slides(tmp_path):
    tl, r = build(tmp_path)
    anns = {s["id"]: s for s in tl["scenes"]}["s01"]["annotations"]
    assert [(a["kind"], a["mark"], a["paragraph"]) for a in anns] == [("box", "first", 1), ("box", "second", 2)]
    s0 = start_of("s01")
    # slides と同じ時刻: 枠 1 は本体（見出し・画像・画面テキスト）の後、枠 2 は段落 2 の始まりから連鎖（deck.recipes）
    base_end = rc.LEAD_IN + rc.FADE + rc.GAP + rc.IMAGE_FADE + rc.GAP + rc.FADE
    assert anns[0]["at_sec"] == round(s0 + (base_end + rc.GAP) / 1000, 3)
    para2 = min(s["start_sec"] for s in tl["sentences"] if s["scene"] == "s01" and s["paragraph"] == 2)
    assert anns[1]["at_sec"] >= para2 and anns[0]["until_sec"] <= anns[1]["at_sec"]
    assert red_boxes(scene_ops(r, anns[0]["at_sec"] - 0.05)) == []                  # 段落 1 の枠の前は無い
    # フェード 0.4 秒 → 点滅 0.6 秒（前半 0.3 秒は隠れる）の後は出ている
    assert red_boxes(scene_ops(r, anns[0]["at_sec"] + 0.5)) == []
    first = red_boxes(scene_ops(r, anns[0]["at_sec"] + 0.8))
    assert len(first) == 1
    later = red_boxes(scene_ops(r, anns[1]["at_sec"] + 1.0))                        # 段落 2 の後は 2 つ目の枠だけ
    assert len(later) == 1 and later[0][1] > first[0][1]


def test_box_is_placed_on_the_mark(tmp_path):
    tl, r = build(tmp_path)
    ops = scene_ops(r, start_of("s01") + SEC - 0.1)
    (key, x, y), = red_boxes(ops)
    (img, ix, iy), = [(k, x_, y_) for k, x_, y_, _ in ops if k[0] == "img"]
    box = {s["id"]: s for s in tl["scenes"]}["s01"]["annotations"][1]["box"]   # 余白込みの枠（slides と同じ）
    assert abs((x + engine.M) - (ix + box["x"] * img[2])) <= 2
    assert abs((y + engine.M) - (iy + box["y"] * img[3])) <= 2
    assert abs(key[1] - box["w"] * img[2]) <= 2 and abs(key[2] - box["h"] * img[3]) <= 2


def test_arrow_appears_after_the_body_and_moves_to_the_mark(tmp_path):
    tl, r = build(tmp_path)
    a, = {s["id"]: s for s in tl["scenes"]}["s02"]["annotations"]
    assert a["kind"] == "arrow" and a["mark"] == "target"
    assert arrows(scene_ops(r, a["at_sec"] - 0.05)) == []
    p0 = arrows(scene_ops(r, a["move_sec"]))
    p1 = arrows(scene_ops(r, a["move_sec"] + a["move_dur_sec"] + 0.1))
    assert len(p0) == 1 and len(p1) == 1 and p1[0][1] > p0[0][1]   # 左から右へ（from_side: left）
    assert p0[0][0][4] == ACCENT


def test_zoom_per_mark_moves_the_view_at_the_paragraph(tmp_path):
    doc = json.loads(json.dumps(DOC))
    doc["scenes"][0]["recipe_params"]["zoom"] = "per_mark"
    tl, r = build(tmp_path, doc)
    sc = {s["id"]: s for s in tl["scenes"]}["s01"]
    a0, a1 = sc["annotations"]
    assert a0["view"] != a1["view"] and sc["view"] == a0["view"] and a1["morph_sec"] == a0["until_sec"]
    crop = lambda sec: [k for k, *_ in scene_ops(r, sec) if k[0] == "img"][0][4]   # noqa: E731
    assert crop(a0["at_sec"] + 0.5) != crop(a1["at_sec"] + 0.5)
    assert len(red_boxes(scene_ops(r, a1["at_sec"] + 1.0))) == 1


# ---------------------------------------------------------------- image 部品（scenes.yaml）

def _image_scene(tmp_path: Path, tl: dict, images: list[dict], copy_from: Path | None = None) -> list[str]:
    """s03 を image 部品で描いた表示リストの文字。"""
    sd = tmp_path / "scenes"
    (sd / "assets").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 200), "white").save(sd / "assets" / "other.png")
    if copy_from is not None:
        shutil.copy2(copy_from, sd / "assets" / "copy.png")
    (sd / "scenes.yaml").write_text(yaml.safe_dump({"version": 1, "scenes": {"s03": {"parts": [
        {"type": "image", "box": [96, 200, 1200, 600], "motion": "cut", "images": images}]}}}, allow_unicode=True),
        encoding="utf-8")
    r = Renderer(Project(timeline=tmp_path / "work" / "render-timeline.json", scenes_dir=sd))
    return texts_at(r, start_of("s03") + SEC - 0.1)


def test_image_part_shows_the_storyboard_label_for_storyboard_images(tmp_path):
    tl, _ = build(tmp_path)
    work = tmp_path / "work"
    # 台本の画像（s01 の実キャプチャ）と同じ中身のファイルを scenes/assets に置いても、台本の来歴を出す
    texts = _image_scene(tmp_path, tl, [{"src": "copy.png"}, {"src": "other.png"}], copy_from=work / "assets" / "s1.png")
    assert texts.count("実キャプチャ") == 1 and texts.count("説明用再構成図") == 1
    # 中間データの画像のパスそのもの（絶対パス）でも同じ
    texts = _image_scene(tmp_path, tl, [{"src": str((work / "assets" / "s3.png").resolve())}])
    assert "説明用再構成図" in texts


def test_image_part_label_cannot_be_removed_or_contradicted(tmp_path):
    tl, _ = build(tmp_path)
    # 台本の画像の来歴と違う label は誤り
    with pytest.raises(LayoutError, match="来歴は「実キャプチャ」"):
        _image_scene(tmp_path, tl, [{"src": "copy.png", "label": "説明用再構成図"}],
                     copy_from=tmp_path / "work" / "assets" / "s1.png")
    # それ以外の静止画は label で来歴を書ける（既定は 説明用再構成図）
    assert "実キャプチャ" in _image_scene(tmp_path, tl, [{"src": "other.png", "label": "実キャプチャ"}])
    # 消す項目は無い: label は 3 つの来歴のどれか（空・false は形の誤り）。部品にも消す項目は無い
    assert IMG_PROPS["label"]["enum"] == LABELS and "" not in LABELS
    for bad in ("", False, None):
        errs = spec.validate_doc({"version": 1, "scenes": {"s03": {"parts": [
            {"type": "image", "images": [{"src": "other.png", "label": bad}]}]}}})
        assert errs, bad
    schema = json.loads(spec.SCHEMA_FILE.read_text(encoding="utf-8"))
    img_props = schema["$defs"]["image"]["properties"]
    assert not {k for k in img_props if "label" in k.lower()}            # 部品の項目に label を消すものは無い
    assert set(img_props["images"]["items"]["properties"]["label"]["enum"]) == set(LABELS)


def test_compare_images_show_labels(tmp_path):
    tl, _ = build(tmp_path)
    sd = tmp_path / "scenes"
    (sd / "assets").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 200), "white").save(sd / "assets" / "other.png")
    shutil.copy2(tmp_path / "work" / "assets" / "s1.png", sd / "assets" / "copy.png")
    (sd / "scenes.yaml").write_text(yaml.safe_dump({"version": 1, "scenes": {"s03": {"parts": [
        {"type": "compare", "box": [96, 200, 1728, 680], "left": {"title": "前", "image": {"src": "copy.png"}},
         "right": {"title": "後", "image": {"src": "other.png"}}}]}}}, allow_unicode=True), encoding="utf-8")
    r = Renderer(Project(timeline=tmp_path / "work" / "render-timeline.json", scenes_dir=sd))
    texts = texts_at(r, start_of("s03") + SEC - 0.1)
    assert "実キャプチャ" in texts and "説明用再構成図" in texts


def test_short_scene_compresses_the_chain_like_slides(tmp_path):
    """スライドの秒に効果が収まらないとき、slides（fit_to_budget）と同じく同じ比率で縮め、場面の中で出し切る。"""
    from explainer_reel_kit.interactive.annotate import scene_display

    assets = tmp_path / "assets"
    _png(assets, "s1.png", (1600, 900), {"first": {"x": 0.1, "y": 0.3, "w": 0.15, "h": 0.2},
                                          "second": {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}})
    scene = DOC["scenes"][0]
    out, _ = scene_display(scene, start=10.0, scene_ms=2500, image_file=assets / "s1.png", has_image=True,
                           sentences=[])
    budget_end = 10.0 + (2500 - rc.TAIL_MS) / 1000
    times = [out["appear"]["heading"], out["appear"]["image"], *out["appear"]["text"]] + \
        [a["at_sec"] for a in out["annotations"]]
    assert all(10.0 <= t < budget_end for t in times) and times == sorted(times)
    long, _ = scene_display(scene, start=10.0, scene_ms=20000, image_file=assets / "s1.png", has_image=True,
                            sentences=[])
    assert long["annotations"][0]["at_sec"] > out["annotations"][0]["at_sec"]


def test_layout_matches_the_main_repository_values():
    """見出し・画像の枠・区分の表示・赤枠と矢印の値（本家の interactive の配置の表と同じ）。"""
    from explainer_reel_kit.interactive import scenes as isc
    from explainer_reel_kit.interactive.parts import image as pimg

    assert (isc.HEAD_X, isc.HEAD_CENTER_Y) == (72, 104)
    assert isc.HEAD_BOX[1] + isc.HEAD_BOX[3] / 2 == 104
    assert isc.HEAD_SIZES[0] == 56 and isc.HEAD_SIZES[-1] == 36
    assert isc.IMAGE_BOX == (72, 180, 1776, 720)
    assert (isc.LABEL_RIGHT, isc.LABEL_TOP, isc.LABEL_SIZE) == (1848, 908, 24)
    assert isc.LABEL_COLOR == "#a9bccf"   # TEXT2（本家 PR #217 の Human 判断）
    assert isc.LABEL_TOP == isc.IMAGE_BOX[1] + isc.IMAGE_BOX[3] + isc.LABEL_GAP   # 枠の下端から 8px
    assert isc.LABEL_TOP + isc.LABEL_SIZE + isc.BAND_GAP == 940                    # 字幕の帯まで 8px
    assert isc.BOX_LINE == 9 and (isc.ARROW_LEN, isc.ARROW_H) == (130, 65)
    assert (isc.BOX_FADE, isc.BOX_EXIT, isc.BLINK, isc.ARROW_FADE) == (0.4, 0.3, 0.6, 0.3)
    assert isc._blink(10.1, 10.0) == 0.0 and isc._blink(10.4, 10.0) == 1.0   # 点滅の前半は隠れる
    assert not hasattr(isc, "IMAGE_BOX_TEXT") and not hasattr(isc, "TEXT_BOX")  # 画面テキストは出さない
    assert pimg.LABEL_ROW == isc.LABEL_ROW == 34
    assert (pimg.LABEL_SIZE, pimg.LABEL_GAP, pimg.LABEL_COLOR) == (isc.LABEL_SIZE, isc.LABEL_GAP, isc.LABEL_COLOR)
