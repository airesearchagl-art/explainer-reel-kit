# -*- coding: utf-8 -*-
"""中間データ（render timeline）の読み込み・検証と、場面コードに渡す問い合わせ口 T。

形の正本はパッケージのデータ ``data/schema/render-timeline.schema.json``。
場面コードは秒を直書きせず、T で時刻を指定する:

- ``T.S('s02-1')`` / ``T.E('s02-1')``: 文 s02-1 の開始・終了（秒）
- ``T.at('s02-6', '露点は')``: 文 s02-6 の中でその語が読まれ始める秒。words（実測）があればそれを使い、無ければ推定
  （原稿の文字位置で比例配分 → 語が読点の直後なら一番近い無音の終わりに合わせる → 0.1 秒先行）
- 使われた時刻は ``T.log`` に残り、checks\\cue_points.json に書き出す
"""
from __future__ import annotations

import bisect
import json
import re
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

FORMAT = "explainer-reel/render-timeline@1"
SCHEMA_RESOURCE = "data/schema/render-timeline.schema.json"   # パッケージ explainer_reel_kit のデータ

KANA = re.compile(r'[぀-ヿ]')
# T.at の推定の重み（かな 1、漢字・英字 2、数字 2.6、読点 1.6）。場面コードの AT_WEIGHTS で上書きできる
DEFAULT_WEIGHTS = {'comma': 1.6, 'punct': 0.3, 'punct_chars': '、。「」・', 'kana': 1.0, 'digit': 2.6, 'other': 2.0}


DISPLAY_KEYS = ("heading", "label", "placeholder", "card", "text", "recipe", "appear", "view", "annotations")


class TimelineError(ValueError):
    """中間データの形・並びの誤り、知らない文の id など。"""


# ---------------------------------------------------------------- 検証

@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads(resources.files("explainer_reel_kit").joinpath(SCHEMA_RESOURCE).read_text(encoding="utf-8"))


def validate_timeline(doc: Any) -> list[str]:
    """スキーマと、スキーマで書けない決まり（並び・重なり・参照）を確かめる。戻り値はエラーの並び（空なら合格）。"""
    from jsonschema import Draft202012Validator

    errors = [f"[schema] {'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
              for e in sorted(Draft202012Validator(_schema()).iter_errors(doc), key=lambda e: list(e.absolute_path))]
    if errors:
        return errors
    total = doc["total_frames"]
    fps = doc["fps"]
    scenes = doc["scenes"]
    ids = [s["id"] for s in scenes]
    if len(set(ids)) != len(ids):
        errors.append("[scenes] 場面の id が重複しています")
    if scenes[0]["start_frame"] != 0:
        errors.append(f"[scenes] 最初の場面は 0 フレームから始めてください（{scenes[0]['start_frame']}）")
    for a, b in zip(scenes, scenes[1:]):
        if b["start_frame"] != a["end_frame"]:
            errors.append(f"[scenes] {a['id']} の終わり {a['end_frame']} と {b['id']} の始まり {b['start_frame']} が続いていません")
    for s in scenes:
        if s["end_frame"] <= s["start_frame"]:
            errors.append(f"[scenes] {s['id']}: end_frame は start_frame より後にしてください")
    if scenes[-1]["end_frame"] != total:
        errors.append(f"[scenes] 最後の場面の終わり {scenes[-1]['end_frame']} が total_frames {total} と違います")
    sids = set(ids)
    seen: set[str] = set()
    limit = total / fps + 1.0 / fps
    for v in doc["sentences"]:
        if v["id"] in seen:
            errors.append(f"[sentences] 文の id {v['id']} が重複しています")
        seen.add(v["id"])
        if v["scene"] not in sids:
            errors.append(f"[sentences] 文 {v['id']} の場面 {v['scene']} がありません")
        if v["end_sec"] < v["start_sec"]:
            errors.append(f"[sentences] 文 {v['id']}: end_sec が start_sec より前です")
        if v["end_sec"] > limit:
            errors.append(f"[sentences] 文 {v['id']}: end_sec {v['end_sec']} が動画の長さ {total / fps:.3f}s を超えます")
    prev_end = 0
    for i, c in enumerate(doc["cues"]):
        if c["end_frame"] <= c["start_frame"]:
            errors.append(f"[cues] {i + 1} 番目: end_frame は start_frame より後にしてください")
        if c["start_frame"] < prev_end:
            errors.append(f"[cues] {i + 1} 番目（{c['start_frame']}）が前の字幕（〜{prev_end}）と重なるか、順になっていません")
        if c["end_frame"] > total:
            errors.append(f"[cues] {i + 1} 番目: end_frame {c['end_frame']} が total_frames {total} を超えます")
        if c.get("sentence") is not None and c["sentence"] not in seen:
            errors.append(f"[cues] {i + 1} 番目: 文 {c['sentence']} がありません")
        prev_end = max(prev_end, c["end_frame"])
    return errors


def load_timeline_doc(path: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise TimelineError(f"中間データを読めません: {path}: {e}") from e
    errors = validate_timeline(doc)
    if errors:
        raise TimelineError(f"中間データが検証を通りません（{path}）:\n  " + "\n  ".join(errors[:30]))
    return doc


def write_timeline(doc: dict, path: Path) -> None:
    errors = validate_timeline(doc)
    if errors:
        raise TimelineError("中間データが検証を通りません:\n  " + "\n  ".join(errors[:30]))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_pauses(path: Path | None) -> dict[str, list[list[float]]]:
    if path is None or not Path(path).is_file():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return {str(k): v for k, v in data.items()}


# ---------------------------------------------------------------- 問い合わせ口

def char_weight(ch: str, w: dict) -> float:
    """読み上げ時間の概算に使う文字の重み。"""
    if ch == '、':
        return w['comma']
    if ch in w['punct_chars']:
        return w['punct']
    if KANA.match(ch):
        return w['kana']
    if ch.isdigit():
        return w['digit']
    return w['other']  # 漢字・英字


class Timeline:
    """場面コードに渡す T。中間データの dict から作る（load で JSON から）。"""

    def __init__(self, doc: dict, base_dir: Path | None = None, pauses: dict | None = None,
                 weights: dict | None = None):
        self.doc = doc
        self.base_dir = Path(base_dir) if base_dir else None
        self.fps = doc["fps"]
        self.width, self.height = doc["width"], doc["height"]
        self.nframes = doc["total_frames"]
        self.total = self.nframes / self.fps
        self.meta = doc.get("meta") or {}
        self.weights = dict(DEFAULT_WEIGHTS, **(weights or {}))
        self.scenes: list[dict] = []
        self.by_id: dict[str, dict] = {}
        for i, sc in enumerate(doc["scenes"]):
            d = dict(index=i + 1, id=sc["id"], title=sc.get("title", ""), f0=sc["start_frame"], f1=sc["end_frame"],
                     start=sc["start_frame"] / self.fps, end=sc["end_frame"] / self.fps,
                     image=self._resolve(sc.get("image")), body=list(sc.get("body") or []))
            for k in DISPLAY_KEYS:   # 画面の決まり（見出し・来歴ラベル・注釈など。既定の場面と image 部品が使う）
                if k in sc:
                    d[k] = sc[k]
            self.scenes.append(d)
            self.by_id[d["id"]] = d
        self._scene_starts = [s["f0"] for s in self.scenes]
        self.sent: dict[str, dict] = {}
        for v in doc["sentences"]:
            self.sent[str(v["id"])] = dict(start=v["start_sec"], end=v["end_sec"], text=v["spoken"], scene=v["scene"],
                                           words=list(v.get("words") or []))
        self.cues = [dict(number=i + 1, sentence=c.get("sentence"), text=c["text"], f0=c["start_frame"],
                          f1=c["end_frame"], lines=c.get("lines")) for i, c in enumerate(doc["cues"])]
        self._cue_starts = [c["f0"] for c in self.cues]
        self.pauses = pauses or {}
        self.log: dict[str, float] = {}  # 強調の切替点の記録（checks\cue_points.json）

    @classmethod
    def load(cls, path: Path, pauses_path: Path | None = None, weights: dict | None = None) -> "Timeline":
        doc = load_timeline_doc(path)
        return cls(doc, base_dir=Path(path).parent, pauses=load_pauses(pauses_path), weights=weights)

    def _resolve(self, p: str | None) -> str | None:
        if not p:
            return None
        q = Path(p)
        if not q.is_absolute() and self.base_dir is not None:
            q = self.base_dir / q
        return str(q)

    # ---- フレーム → 字幕・場面
    def cue_at(self, frame: int) -> dict | None:
        i = bisect.bisect_right(self._cue_starts, frame) - 1
        if i >= 0 and self.cues[i]["f0"] <= frame < self.cues[i]["f1"]:
            return self.cues[i]
        return None

    def scene_at(self, frame: int) -> dict:
        i = bisect.bisect_right(self._scene_starts, frame) - 1
        return self.scenes[max(0, min(i, len(self.scenes) - 1))]

    # ---- 文の時刻
    def _sentence(self, sid) -> dict:
        try:
            return self.sent[str(sid)]
        except KeyError:
            raise TimelineError(f"文 {sid} は中間データにありません") from None

    def S(self, sid) -> float:
        return self._sentence(sid)["start"]

    def E(self, sid) -> float:
        return self._sentence(sid)["end"]

    def _word_time(self, se: dict, phrase: str) -> float | None:
        """words（実測）から、phrase の最初の文字を含む語の開始時刻。見つからなければ None。"""
        if not se["words"]:
            return None
        joined, owner = "", []
        for k, w in enumerate(se["words"]):
            joined += w["text"]
            owner += [k] * len(w["text"])
        idx = joined.find(phrase)
        if idx < 0:
            return None
        return float(se["words"][owner[idx]]["start_sec"])

    def at(self, sid, phrase: str, lead: float = 0.10, snap: bool | None = None) -> float:
        """文 sid の中で phrase が読まれ始める時刻（秒）。

        words があれば実測の時刻（から lead 秒先行）。無ければ、読み上げ原稿の文字位置から比例配分で概算し、
        phrase が読点の直後にある場合は音声から検出した無音区間（pauses）の終わりに合わせる（snap=True で常に合わせる）。
        """
        key = '%s|%s' % (sid, phrase)
        if key in self.log:
            return self.log[key]
        se = self._sentence(sid)
        text = se["text"]
        idx = text.find(phrase)
        if idx < 0:
            raise TimelineError(f"文 {sid} の原稿に「{phrase}」がありません: {text}")
        measured = self._word_time(se, phrase)
        if measured is not None:
            t = max(se["start"], measured - lead)
        elif idx == 0:
            t = se["start"]
        else:
            w = self.weights
            total = sum(char_weight(c, w) for c in text)
            t = se["start"] + (se["end"] - se["start"]) * sum(char_weight(c, w) for c in text[:idx]) / total
            if snap or (snap is None and text[idx - 1] == '、'):
                ends = [b for a, b in self.pauses.get(str(sid), [])]
                if ends:
                    best = min(ends, key=lambda b: abs(b - t))
                    if abs(best - t) < (1.5 if snap else 0.9):
                        t = best
            t = max(se["start"], t - lead)
        self.log[key] = round(t, 3)
        return self.log[key]
