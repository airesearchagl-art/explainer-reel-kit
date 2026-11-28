# -*- coding: utf-8 -*-
"""字幕の折り方と描き方。

- 1 行に収まる短い字幕（幅の 8 割まで）は 1 行
- 2 行にするときは、なるべく読点・句点の直後で、2 行の長さがそろう位置で折る
- 英数字の語の途中・行頭禁則（、。）など）・行末禁則（（「 など）では折らない
- 3 行以上になる字幕はエラー（LayoutError）。台本から作るときは、変換器が字幕を 2 行に収まる長さに分ける
- 読点・句点の直後で折れない字幕は、ほかの位置で折る（verify の記録に「読点以外で折った字幕」として残す）
- SRT: 焼き込みと同じ cues から書く。時刻は表示フレームの始まりをミリ秒に切り捨てた値
  （SRT の時刻以降の最初のフレーム＝表示フレーム、になる。srt_frame で戻すと同じフレーム）
- SRT の読み込み（parse_srt）は verify が使う（verify.yaml の subtitles_reference と、出力の SRT の照合）
"""
from __future__ import annotations

import re
from pathlib import Path

from .engine import NO_HEAD, NO_TAIL, LayoutError, is_ascii_word, tw

SUB_SIZE = 42
SUB_WEIGHT = 'R'
SUB_MAXW = 1720          # 字幕 1 行の最大幅（px）
SUB_ONE_LINE = 0.80      # この割合までの幅なら 1 行のまま
SUB_COLOR = '#ffffff'
SUB_Y1 = 988             # 1 行のときの文字の上端
SUB_Y2 = (960, 1018)     # 2 行のとき
BREAK_AFTER = '、。'
NON_COMMA_COST = 3000    # 読点・句点の直後以外で折るときの重み（避ける）


def wrap_subtitle_info(text: str) -> tuple[list[str], bool]:
    """字幕を 1〜2 行に分ける。戻り値 (行の並び, 読点・句点の直後で折ったか（1 行なら True）)。"""
    if tw(text, SUB_WEIGHT, SUB_SIZE) <= SUB_MAXW * SUB_ONE_LINE:
        return [text], True
    best, best_cost = None, None
    for i in range(1, len(text)):
        a, b = text[:i], text[i:]
        if b[0] in NO_HEAD or a[-1] in NO_TAIL:
            continue
        if is_ascii_word(a[-1]) and is_ascii_word(b[0]):
            continue
        wa, wb = tw(a, SUB_WEIGHT, SUB_SIZE), tw(b, SUB_WEIGHT, SUB_SIZE)
        if wa > SUB_MAXW or wb > SUB_MAXW:
            continue
        cost = abs(wa - wb)
        if a[-1] not in BREAK_AFTER:
            cost += NON_COMMA_COST
        if best is None or cost < best_cost:
            best, best_cost = [a, b], cost
    if not best:
        raise LayoutError(f'字幕が 2 行に収まりません: {text}')
    return best, best[0][-1] in BREAK_AFTER


def wrap_subtitle(text: str) -> list[str]:
    """字幕を 1〜2 行に分ける。"""
    return wrap_subtitle_info(text)[0]


def fits_subtitle(text: str) -> bool:
    try:
        wrap_subtitle_info(text)
    except LayoutError:
        return False
    return True


def cue_lines(cue: dict) -> list[str]:
    """キューの行。lines があればそれを使う（2 行まで・幅に収まることを確かめる）、無ければ折る。"""
    lines = cue.get('lines')
    if lines:
        if len(lines) > 2:
            raise LayoutError(f'字幕は 2 行までです（{len(lines)} 行）: {cue.get("text")}')
        for s in lines:
            if tw(s, SUB_WEIGHT, SUB_SIZE) > SUB_MAXW:
                raise LayoutError(f'字幕の行が幅に収まりません: {s}')
        return list(lines)
    return wrap_subtitle(cue['text'])


def draw_subtitle(f, frame, T):
    """字幕。キューの表示フレームどおりに切り替える（フェードなし）。"""
    c = T.cue_at(frame)
    if not c:
        return
    lines = cue_lines(c)
    ys = [SUB_Y1] if len(lines) == 1 else list(SUB_Y2)
    for s, y in zip(lines, ys):
        f.text(s, 960, y, size=SUB_SIZE, color=SUB_COLOR, w=SUB_WEIGHT, anchor='c')


# ---------------------------------------------------------------- SRT

def frame_ms(frame: int, fps: int) -> int:
    """フレームの始まりの時刻（ミリ秒、切り捨て）。ceil(frame_ms(f) * fps / 1000) == f になる。"""
    return frame * 1000 // fps


def srt_timestamp(ms: int) -> str:
    h, rest = divmod(ms, 3600000)
    m, rest = divmod(rest, 60000)
    sec, msec = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{msec:03d}"


def srt_text(cues: list[dict], fps: int) -> str:
    """cues（中間データの形: text・start_frame・end_frame・lines）→ SRT の本文。行は焼き込みと同じ（cue_lines）。"""
    blocks = []
    for i, c in enumerate(cues, 1):
        head = f"{i}\n{srt_timestamp(frame_ms(c['start_frame'], fps))} --> {srt_timestamp(frame_ms(c['end_frame'], fps))}"
        blocks.append("\n".join([head, *cue_lines(c)]) + "\n")
    return "\n".join(blocks)


def write_srt(cues: list[dict], fps: int, path) -> None:
    Path(path).write_text(srt_text(cues, fps), encoding="utf-8")


_SRT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{3})")


def srt_ms(s: str) -> int:
    from .timeline import TimelineError

    m = _SRT_TIME.search(s)
    if not m:
        raise TimelineError(f"SRT の時刻を読めません: {s!r}")
    h, mi, se, ms = (int(x) for x in m.groups())
    return ((h * 60 + mi) * 60 + se) * 1000 + ms


def srt_frame(ms: int, fps: int = 30) -> int:
    """SRT の時刻 → 表示フレーム: その時刻以降の最初のフレーム。"""
    return (ms * fps + 999) // 1000


def parse_srt(path) -> list[dict]:
    """[{number, start_ms, end_ms, text}]。text は行をつないだもの。"""
    from .timeline import TimelineError

    raw = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    out = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = block.split("\n")
        if len(lines) < 3 or "-->" not in lines[1]:
            raise TimelineError(f"SRT の形が違います: {block[:80]!r}")
        a, b = lines[1].split("-->")
        out.append(dict(number=int(lines[0]), start_ms=srt_ms(a), end_ms=srt_ms(b), text="".join(lines[2:]).strip()))
    return out
