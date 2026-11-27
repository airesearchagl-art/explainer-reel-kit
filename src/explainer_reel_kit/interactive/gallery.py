# -*- coding: utf-8 -*-
"""部品の見本の静止画: 型ごとに、ダミーの中身で 1 場面を作り、読み終えた絵とその途中の絵を書き出す。

``python -m explainer_reel_kit.interactive gallery --out <フォルダ>`` → ``<型>.png``（読み終えた絵）と
``<型>_cues.jpg``（きっかけごとの前・直後・終わり）。PNG はリポジトリに入れない。
中身はすべてダミー（実際の題材の内容は使わない）。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from .engine import FPS, H, W

SENTENCES = ["一つ目の文です。ここで最初の項目を読みます。", "二つ目の文です。次の項目に移ります。",
             "三つ目の文では、数値を読みます。", "四つ目の文で、まとめの一言を読みます。"]

SAMPLES: dict[str, list[dict]] = {
    "header": [{"type": "header", "title": "見出しの見本", "label": "見本｜", "label_accent": "2  部品",
                "progress": {"total": 4, "current": 2}, "foot": "ダミーの中身"}],
    "heading": [{"type": "header", "title": "段の見出し"},
                {"type": "heading", "text": "段の見出しの見本", "badge": 1, "sub": "続きの文", "sentence": 1},
                {"type": "heading", "text": "罫線つきの見出し", "rule": True, "sentence": 2}],
    "title": [{"type": "title", "box": [96, 160, 1728, 700], "lines": [
        {"text": "中央の題の見本", "size": 50, "color": "text2"},
        {"text": "大きな一行", "size": 96, "sentence": 2},
        {"text": "4 段階", "size": 104, "color": "teal", "sentence": 3}]}],
    "cards": [{"type": "header", "title": "カードを読み上げ順に点灯"},
              {"type": "cards", "numbered": True, "arrows": True, "box": [96, 230, 1728, 420],
               "height": 240, "bracket": {"text": "まとめの札", "sentence": 4},
               "items": [{"title": "一つ目", "body": "説明の文。", "sentence": 1},
                         {"title": "二つ目", "body": "説明の文。", "sentence": 2},
                         {"title": "三つ目", "checks": [{"text": "確かめる点", "sentence": 3}], "sentence": 3},
                         {"title": "四つ目", "note": "強調の文", "sentence": 4}]}],
    "steps": [{"type": "header", "title": "手順の番号付きリスト"},
              {"type": "steps", "box": [96, 220, 1100, 400], "items": [
                  {"text": "最初の手順", "sub": "補足の文", "sentence": 1}, {"text": "次の手順", "sentence": 2},
                  {"text": "最後の手順", "sentence": 3}]},
              {"type": "steps", "box": [1240, 220, 584, 300], "marker": "check", "boxed": True, "dim": 0,
               "items": [{"text": "確かめた", "sentence": 2}, {"text": "残す", "sentence": 4}]}],
    "table": [{"type": "header", "title": "表の行・列の強調"},
              {"type": "table", "box": [96, 220, 1728, 460], "columns": ["項目", "案 A", "案 B"],
               "widths": [480, 624, 624], "row_height": 120,
               "highlights": [{"col": "案 B", "sentence": 4}],
               "rows": [{"name": "一つ目の行", "sentence": 1, "cells": {"案 A": "10", "案 B": "12"}},
                        {"name": "二つ目の行", "sentence": 2, "cells": {"案 A": "あり", "案 B": {"text": "なし", "color": "coral"}}},
                        {"name": "三つ目の行", "sentence": 3, "cells": {"案 A": "低い", "案 B": {"text": "高い", "color": "green"}}}]}],
    "number": [{"type": "header", "title": "数値の強調"},
               {"type": "number", "box": [96, 230, 1300, 240], "items": [
                   {"value": "1,200", "unit": "件", "caption": "全体", "ratio": 1.0, "sentence": 1},
                   {"value": "480", "unit": "件", "caption": "うち回答", "ratio": 0.4, "sentence": 2},
                   {"value": "36.5", "unit": "%", "caption": "割合", "ratio": 0.15, "sentence": 3}]}],
    "image": [{"type": "header", "title": "画像と注釈"},
              {"type": "image", "box": [96, 200, 1100, 660], "images": [{"src": "gallery-plan.png", "paper": True,
                                                                         "caption": "ダミーの図"}],
               "annotations": [{"shape": "box", "rect": [120, 80, 260, 160], "text": "枠", "sentence": 2},
                               {"shape": "label", "xy": [620, 220], "text": "引き出し線の注記", "sentence": 3},
                               {"shape": "point", "xy": [900, 500], "sentence": 4}]}],
    "compare": [{"type": "header", "title": "比較の左右"},
                {"type": "compare", "box": [96, 220, 1728, 560],
                 "left": {"title": "前の方法", "points": ["手で写す", "時間がかかる"], "marker": "cross",
                          "verdict": "手間が多い", "verdict_color": "coral", "sentence": 1},
                 "right": {"title": "新しい方法", "points": ["部品で書く", "すぐ直せる"], "marker": "check",
                           "verdict": "手間が少ない", "verdict_color": "green", "sentence": 2}}],
    "callout": [{"type": "header", "title": "要点の囲み・帯"},
                {"type": "callout", "text": "要点の一言に マーカー を引く", "mark": {"text": "マーカー", "sentence": 2},
                 "sentence": 1},
                {"type": "callout", "style": "band", "texts": [{"text": "入れ替わる文 1", "sentence": 2},
                                                               {"text": "入れ替わる文 2", "sentence": 3}],
                 "more": {"text": "添え書き", "sentence": 3}},
                {"type": "callout", "style": "pill", "text": "次へ進む", "arrow": True, "sentence": 4}],
    "flow": [{"type": "header", "title": "流れ（札を矢印でつなぐ）"},
             {"type": "flow", "box": [96, 400, 1728, 90], "items": [
                 {"text": "調べる", "sentence": 1}, {"text": "整理する", "sentence": 2},
                 {"text": "道具にする", "sentence": 3}, {"text": "任せる", "sentence": 4}]}],
}


def _dummy_plan(path: Path) -> None:
    """ダミーの図（方眼と箱）。"""
    im = Image.new("RGB", (1200, 700), "#f4f6f8")
    d = ImageDraw.Draw(im)
    for x in range(0, 1200, 50):
        d.line((x, 0, x, 700), fill="#d5dde5", width=1)
    for y in range(0, 700, 50):
        d.line((0, y, 1200, y), fill="#d5dde5", width=1)
    d.rectangle((100, 60, 1100, 640), outline="#1c2b3a", width=4)
    d.rectangle((120, 80, 380, 240), outline="#1c2b3a", width=2)
    d.line((600, 60, 600, 640), fill="#1c2b3a", width=3)
    d.ellipse((860, 460, 940, 540), outline="#1c2b3a", width=3)
    im.save(path)


def _timeline(types: list[str]) -> dict:
    scenes, sents, t = [], [], 0.0
    for sid in types:
        f0 = int(round(t * FPS))
        t += 0.5
        for k, s in enumerate(SENTENCES, 1):
            sents.append({"id": f"{sid}-{k}", "scene": sid, "spoken": s, "start_sec": round(t, 3),
                          "end_sec": round(t + 1.8, 3)})
            t += 2.1
        t += 1.0
        scenes.append({"id": sid, "title": sid, "start_frame": f0, "end_frame": int(round(t * FPS))})
    return {"format": "explainer-reel/render-timeline@1", "fps": FPS, "width": W, "height": H,
            "total_frames": scenes[-1]["end_frame"], "scenes": scenes, "sentences": sents, "cues": []}


def make_gallery(out_dir: Path, types: list[str] | None = None) -> list[Path]:
    """型ごとの見本の静止画を out_dir に書く。戻り値は書いたファイル。"""
    import yaml

    from .render import Project, Renderer
    from .sheet import make_cue_sheets

    types = types or list(SAMPLES)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        scenes_dir = tmp / "scenes"
        (scenes_dir / "assets").mkdir(parents=True)
        _dummy_plan(scenes_dir / "assets" / "gallery-plan.png")
        (scenes_dir / "scenes.yaml").write_text(
            yaml.safe_dump({"version": 1, "scenes": {k: {"parts": SAMPLES[k]} for k in types}}, allow_unicode=True),
            encoding="utf-8")
        tl = tmp / "render-timeline.json"
        tl.write_text(json.dumps(_timeline(types), ensure_ascii=False), encoding="utf-8")
        r = Renderer(Project(timeline=tl, scenes_dir=scenes_dir))
        out: list[Path] = []
        for sid in types:
            sc = r.T.by_id[sid]
            p = out_dir / f"{sid}.png"
            r.frame_image(sc["f1"] - 1).save(p)
            out.append(p)
        for p in make_cue_sheets(r, tmp / "cues", rows_per_sheet=8):
            q = out_dir / p.name.replace("_cues_00", "_cues")
            p.replace(q)
            out.append(q)
    return out
