# -*- coding: utf-8 -*-
"""合成の前の確かめ: ``erkit make`` の interactive で、ナレーションを合成する前に scenes.yaml を確かめる。

台本の原稿から、文の時刻を文字の重みで仮に置いた中間データを作り、scenes.yaml の場面を部品に組み立てて試し描きする
（``SceneSet.compile`` → ``spec.compile_scene``・``spec.dry_run``。描くときと同じ確かめ）。ここで見つける誤りは
時刻に依らない: 知らない型・項目・動き、場面 id、語句がナレーションに無い・2 つの文にある、文の番号、表の列、
文字が枠に入らない。時刻は合成の後に測った値で、描くときにもう一度確かめる。

文の分け方は合成の後の中間データ（``convert.from_storyboard``・``sync.measure``）と同じなので、``sentence: 3`` は
合成の後も同じ文を指す。
"""
from __future__ import annotations

from pathlib import Path

from . import engine
from . import spec as specmod
from .convert import _scene_card
from .engine import FPS, H, W
from .scenes import load_scenes
from .timeline import DEFAULT_WEIGHTS, FORMAT, Timeline, char_weight

SEC_PER_WEIGHT = 0.13   # 文字の重み 1 あたりの秒（仮の時刻。おおよそ 1 秒に 7〜8 字）
PRE_SEC = 0.5           # 場面の始まりから最初の文まで
GAP_SEC = 0.35          # 文と文の間
POST_SEC = 1.0          # 最後の文から場面の終わりまで


def sentences_of(text: str) -> list[list[str]]:
    """原稿 → 段落ごとの文（合成の後の中間データと同じ分け方）。"""
    from .convert import paragraph_sentences, paragraphs_of

    return [paragraph_sentences(p) or [p] for p in paragraphs_of(text or "")]


def provisional_timeline(doc: dict, ids: list[str], texts: dict[str, str], weights: dict | None = None) -> dict:
    """台本 → 仮の中間データ（文の時刻は文字の重みで置く。字幕は作らない）。"""
    w = dict(DEFAULT_WEIGHTS, **(weights or {}))
    scenes, sents, t = [], [], 0.0
    for sid in ids:
        start = t
        t += PRE_SEC
        n = 0
        for para, ss in enumerate(sentences_of(texts.get(sid, "")), 1):
            for s in ss:
                n += 1
                d = max(0.5, sum(char_weight(ch, w) for ch in s) * SEC_PER_WEIGHT)
                sents.append({"id": f"{sid}-{n}", "scene": sid, "paragraph": para, "spoken": s,
                              "start_sec": round(t, 3), "end_sec": round(t + d, 3), "timing": "estimated"})
                t += d + GAP_SEC
        t += POST_SEC
        scenes.append({"id": sid, "title": _scene_card(doc, sid)["title"],
                       "start_frame": int(round(start * FPS)), "end_frame": int(round(t * FPS))})
    total = scenes[-1]["end_frame"] if scenes else 1
    return {"format": FORMAT, "fps": FPS, "width": W, "height": H,
            "total_frames": total, "scenes": scenes, "sentences": sents, "cues": [],
            "source": {"kind": "storyboard", "timing": "provisional"}}


def check_before_synthesis(doc: dict, ids: list[str], texts: dict[str, str], scenes_dir: Path | None, *,
                           asset_roots: list[Path] | None = None) -> dict:
    """scenes.yaml を合成の前に確かめる。戻り値は run.json に残す記録。

    誤りは spec.SpecError（scenes.yaml の誤り。erkit make は終了コード 2）か scenes.SceneError（Python の場面コードを
    読み込めない）。scenes.yaml が無ければ確かめない（status: skipped）。
    asset_roots: 静止画を読んでよいフォルダ（engine.set_asset_roots。確かめの後に外す）。
    """
    if scenes_dir is None or not (Path(scenes_dir) / specmod.SPEC_NAME).is_file():
        return {"status": "skipped", "reason": "scenes.yaml が無い"}
    engine.set_asset_roots(asset_roots or [])
    try:
        sset = load_scenes(Path(scenes_dir), ids)
        tl = provisional_timeline(doc, ids, texts, weights=sset.at_weights)
        T = Timeline(tl, weights=sset.at_weights)
        sset.compile(T)
    finally:
        engine.set_asset_roots([])
    return {"status": "ok", "spec": str(sset.spec_file), "timing": "provisional",
            "scenes": sorted(sset.specs), "shadowed_by_python": list(sset.shadowed),
            "parts": sum(len(c.parts) for c in sset.compiled.values())}


__all__ = ["check_before_synthesis", "provisional_timeline", "sentences_of"]
