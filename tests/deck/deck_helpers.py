"""tests/deck 共通の定数と XML 読み出し。"""
import re
import zipfile
from pathlib import Path

from lxml import etree

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
SAMPLES = {
    # Web 撮影の台本（6 シーン、mark・zoom・per_mark・arrow_move を使う）
    "web": FIXTURES / "compat" / "compat-web.storyboard.json",
    # 説明図の台本（6 シーン、座標指定の highlight_box）
    "generated": FIXTURES / "compat" / "compat-generated.storyboard.json",
    # 例の台本（kit-1.0.0、説明図の HTML・Web・text_build）
    "example": REPO_ROOT / "examples" / "hello-kit.storyboard.md",
    # 画像の種類を混ぜた台本（説明図・Web・手で用意した画像 1 枚。fade_sequence を含む）
    "mixed": FIXTURES / "deck_mixed.storyboard.json",
    # すべてのレシピ（既定枠・text_build・fade_sequence・arrow_move・morph_transition）を使うテスト専用台本
    "recipes": FIXTURES / "deck_recipes.storyboard.json",
}
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
    "p159": "http://schemas.microsoft.com/office/powerpoint/2015/09/main",
}


def variant(key: str, tmp_path: Path, edit) -> Path:
    """SAMPLES[key] を読み、edit(doc) で書き換えた台本を tmp_path に書いてそのパスを返す（画像の参照はそのまま）。"""
    import json

    from explainer_reel_kit import storyboard as sb

    doc = sb.load_storyboard(SAMPLES[key])
    edit(doc)
    out = tmp_path / f"{key}.storyboard.json"
    out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return out


def slide_transition(sld):
    """スライドの切替要素と種類（none / fade / morph）。Morph は mc:AlternateContent の Choice を返す。"""
    tr = sld.find("p:transition", NS)
    if tr is not None:
        return tr, ("fade" if tr.find("p:fade", NS) is not None else "none")
    ac = sld.find("mc:AlternateContent", NS)
    assert ac is not None, "スライドに切替がありません"
    return ac.find("mc:Choice/p:transition", NS), "morph"


def slide_roots(pptx_path: Path) -> list[etree._Element]:
    with zipfile.ZipFile(pptx_path) as zf:
        names = [n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        names.sort(key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        return [etree.fromstring(zf.read(n)) for n in names]


def all_xml_text(pptx_path: Path) -> str:
    with zipfile.ZipFile(pptx_path) as zf:
        return "\n".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist() if n.endswith(".xml") or n.endswith(".rels"))




P14 = "{http://schemas.microsoft.com/office/powerpoint/2010/main}dur"
TRANSITION_SPEED_MS = {"fast": 500, "med": 750, "slow": 1000}


def pptx_total_sec(pptx_path: Path) -> float:
    """.pptx の全スライドの表示時間の合計（advTm ＋ 切替効果の長さ。切替効果の後にタイマーが始まる前提）。

    通し生成の音声の合成（mux）が使う計算と同じ。deck の BuildResult.video_sec をこれと突き合わせる。
    """
    total = 0
    for sld in slide_roots(pptx_path):
        tr, _ = slide_transition(sld)
        total += int(tr.get("advTm"))
        if len(tr):
            dur = tr.get(P14)
            total += int(dur) if dur is not None else TRANSITION_SPEED_MS.get(tr.get("spd", "fast"), 500)
    return total / 1000


# Web 撮影の台本（SAMPLES["web"]）の部品の位置（撮影側が出す marks.json の代わり）
WEB_MARK_BOXES = {
    "input_a": {"x": 0.02, "y": 0.12, "w": 0.22, "h": 0.30},
    "input_b": {"x": 0.02, "y": 0.46, "w": 0.22, "h": 0.08},
    "choice_a": {"x": 0.02, "y": 0.58, "w": 0.22, "h": 0.10},
    "choice_b": {"x": 0.02, "y": 0.72, "w": 0.22, "h": 0.10},
    "main_view": {"x": 0.32, "y": 0.10, "w": 0.34, "h": 0.80},
    "meter": {"x": 0.72, "y": 0.10, "w": 0.24, "h": 0.30},
    "alert": {"x": 0.72, "y": 0.62, "w": 0.24, "h": 0.22},
}


def scene_mark_names(scene: dict) -> list[str]:
    rp = scene.get("recipe_params") or {}
    m = rp.get("mark")
    if isinstance(m, str):
        return [m]
    if isinstance(m, list):
        return list(m)
    to = rp.get("to")
    if isinstance(to, dict) and isinstance(to.get("mark"), str):
        return [to["mark"]]
    return []


def write_marks(image_path: Path, scene_id: str, boxes: dict, size=(1920, 1080), source="web") -> Path:
    """<画像名>.marks.json（explainer-reel/marks@1）を書く（撮影側の出力の代わり）。"""
    import json

    w, h = size
    marks = {name: {"box": b, "px": {"x": round(b["x"] * w), "y": round(b["y"] * h),
                                    "w": round(b["w"] * w), "h": round(b["h"] * h)}, "how": "test"}
             for name, b in boxes.items()}
    path = Path(image_path).with_name(Path(image_path).stem + ".marks.json")
    path.write_text(json.dumps({"format": "explainer-reel/marks@1", "scene": scene_id, "source": source,
                                "image": Path(image_path).name, "image_size": {"w": w, "h": h},
                                "captured_at": "2026-10-29T10:00:00+09:00", "marks": marks},
                               ensure_ascii=False), encoding="utf-8")
    return path
