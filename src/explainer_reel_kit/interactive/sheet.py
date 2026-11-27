# -*- coding: utf-8 -*-
"""確かめ用の一覧画像: 指定した秒のフレームを 2×2 に並べる。

全編を描く前に、気になる秒の静止画で文字のはみ出し・表の強調のずれ・細線の消え・矢印と文字の重なりを見る。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from .render import Renderer

CELL = (956, 538)
STEP = (964, 542)


def make_sheets(r: Renderer, name: str, times: list[float], out_dir: Path) -> list[Path]:
    """times（秒）のフレームを 4 枚ずつ並べ、<out_dir>/<name>_NN.jpg に書く。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for k in range(0, len(times), 4):
        sheet = Image.new('RGB', (1920, 1080), '#cad5df')
        for i, ts in enumerate(times[k:k + 4]):
            fr = min(r.T.nframes - 1, max(0, int(round(float(ts) * r.T.fps))))
            im = r.frame_image(fr).resize(CELL, Image.LANCZOS)
            sheet.paste(im, (i % 2 * STEP[0], i // 2 * STEP[1]))
        p = out_dir / f'{name}_{k // 4:02d}.jpg'
        sheet.save(p, quality=90)
        out.append(p)
    return out


def make_stills(r: Renderer, times: list[float], out_dir: Path) -> list[Path]:
    """指定秒の静止画を 1 枚ずつ（t<秒>_f<フレーム>.jpg）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for ts in times:
        fr = min(r.T.nframes - 1, max(0, int(round(float(ts) * r.T.fps))))
        p = out_dir / ('t%07.2f_f%05d.jpg' % (fr / r.T.fps, fr))
        r.frame_image(fr).save(p, quality=90)
        out.append(p)
    return out


# ---------------------------------------------------------------- scenes.yaml のきっかけごとの 3 枚

CUE_CELL = (620, 349)
CUE_PAD = 15
LABEL_H = 44
BEFORE, AFTER = 0.2, 0.2   # きっかけの前・直後（秒）


def cue_times(T, sid: str, cue_t: float, end_t: float) -> list[float]:
    """きっかけの前（0.2 秒前）・直後（0.2 秒後）・動きの終わり。場面の中に収める。"""
    sc = T.by_id[sid]
    lo, hi = sc["start"], sc["end"] - 1.0 / T.fps
    return [min(hi, max(lo, cue_t - BEFORE)), min(hi, max(lo, cue_t + AFTER)), min(hi, max(lo, end_t))]


def _label(sheet, text: str, xy) -> None:
    from PIL import ImageDraw

    from .engine import font
    ImageDraw.Draw(sheet).text(xy, text, font=font('B', 24), fill=(20, 32, 46))


def _frame(r: Renderer, ts: float):
    fr = min(r.T.nframes - 1, max(0, int(round(float(ts) * r.T.fps))))
    r.activate()
    return r.frame_image(fr).resize(CUE_CELL, Image.LANCZOS)


def make_cue_sheets(r: Renderer, out_dir: Path, *, against: Renderer | None = None, against_name: str = '比べる側',
                    scenes: list[str] | None = None, rows_per_sheet: int = 6) -> list[Path]:
    """scenes.yaml の場面ごとに、きっかけ 1 つにつき 3 枚（前・直後・終わり）を並べた一覧（<場面 id>_cues_NN.jpg）。

    against を渡すと、同じ時刻の絵（Python の場面コードの版など）を次の行に並べて見比べられる。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    for sid, cs in r.scenes.compiled.items():
        if scenes and sid not in scenes:
            continue
        groups: dict[int, list] = {}   # 同じ時刻のきっかけは 1 行に（部品の名前をまとめる）
        for label, cue, end in cs.cues():
            key = int(round(cue.t * r.T.fps))
            g = groups.setdefault(key, [cue, end, []])
            g[1] = max(g[1], end)
            if f'{label} {cue.label}' not in g[2]:
                g[2].append(f'{label} {cue.label}')
        rows = []
        for key in sorted(groups):
            cue, end, labels = groups[key]
            times = cue_times(r.T, sid, cue.t, end)
            rows.append((f'{sid}  {cue.t:.2f}s  ' + '・'.join(labels), times, r))
            if against is not None:
                rows.append((f'{sid}  {against_name}（同じ時刻）', times, against))
        for k in range(0, len(rows), rows_per_sheet):
            chunk = rows[k:k + rows_per_sheet]
            h = len(chunk) * (LABEL_H + CUE_CELL[1] + CUE_PAD) + CUE_PAD
            sheet = Image.new('RGB', (1920, h), '#cad5df')
            y = CUE_PAD
            for text, times, rr in chunk:
                _label(sheet, text + '    前 ' + ' / 直後 '.join(f'{x:.2f}s' for x in times[:2]) + f' / 終わり {times[2]:.2f}s',
                       (CUE_PAD, y + 8))
                y += LABEL_H
                for i, ts in enumerate(times):
                    sheet.paste(_frame(rr, ts), (CUE_PAD + i * (CUE_CELL[0] + CUE_PAD), y))
                y += CUE_CELL[1] + CUE_PAD
            p = out_dir / f'{sid}_cues_{k // rows_per_sheet:02d}.jpg'
            sheet.save(p, quality=88)
            out.append(p)
    r.activate()
    return out
