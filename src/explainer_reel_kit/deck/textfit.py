"""文字がテキスト枠からはみ出さないよう、文字サイズを縮める。

PowerPoint の「はみ出す場合は縮小」（normAutofit）は、ファイルを開いて編集するまで反映されず、
動画書き出しや LibreOffice では効かないことがあるため、生成時に文字数から高さを見積もって
文字サイズそのものを小さくする。見積もりは控えめ（全角 1.0、半角 0.55 文字幅）にしている。
"""
from __future__ import annotations

import unicodedata
from typing import Sequence

EMU_PER_PT = 12700
INSET_X = 91440 * 2  # 既定の左右の余白（0.1in × 2）
INSET_Y = 45720 * 2  # 既定の上下の余白（0.05in × 2）
LINE_HEIGHT = 1.2  # 1 行の高さ ＝ 文字サイズ × 1.2 × 行間
MIN_SIZE = 10.0
MIN_SCALE = 0.5
ONE_LINE_MIN_SCALE = 0.75  # タイトルを 1 行に収めるために縮めてよい下限
# 1 行に収めるときの余裕（幅の 90% に収める）。実際の描画は、和文と英数字の間の空き・代替フォントで
# 見積もりより広くなることがあり（LibreOffice の PDF で確認）、ぎりぎりだと最後の 1〜2 文字だけが折り返す
ONE_LINE_MARGIN = 0.90

# 行頭禁則: 行の先頭に来てはいけない文字（閉じ括弧・句読点・長音・小書きの仮名など）
KINSOKU_HEAD = frozenset(
    "）)」』】〕〉》］]｝}〙〗、。，．,.・：；:;！？!?ー…‥ゝゞヽヾ々〜～"
    "ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ"
)


def char_units(ch: str) -> float:
    return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 0.55


def text_units(text: str) -> float:
    """文字幅の合計（全角 = 1.0、半角 = 0.55）。"""
    return sum(char_units(ch) for ch in text)


def wrap_lines(text: str, size: float, width_pt: float) -> list[str]:
    """1 段落（改行なし）を、幅 width_pt で折り返した行（見積もり）。

    行頭禁則: 次の行の先頭が KINSOKU_HEAD の文字になるときは、前の行の最後の文字を次の行へ送る（追い出し）。
    """
    if not text:
        return [""]
    lines: list[str] = []
    cur = ""
    w = 0.0
    for ch in text:
        cw = char_units(ch) * size
        if cur and w + cw > width_pt:
            nxt = ""
            # 追い出し: 次の行が禁則文字で始まらないよう、前の行の末尾を次の行へ送る（1 文字は残す）
            if ch in KINSOKU_HEAD:
                while len(cur) > 1 and (not nxt or nxt[0] in KINSOKU_HEAD):
                    nxt = cur[-1] + nxt
                    cur = cur[:-1]
                    if nxt[0] not in KINSOKU_HEAD:
                        break
            lines.append(cur)
            cur = nxt + ch
            w = text_units(cur) * size
        else:
            cur += ch
            w += cw
    lines.append(cur)
    return lines


def one_line_scale(text: str, size: float, width_emu: int, min_scale: float = ONE_LINE_MIN_SCALE) -> float | None:
    """1 行に収まる倍率（1.0 以下、5% 刻み）。幅は ONE_LINE_MARGIN の余裕を見る。min_scale まで縮めても収まらなければ None。"""
    width_pt = max((width_emu - INSET_X) / EMU_PER_PT, 1.0) * ONE_LINE_MARGIN
    scale = 1.0
    while scale >= min_scale - 1e-9:
        if len(wrap_lines(text, size * scale, width_pt)) == 1:
            return scale
        scale = round(scale - 0.05, 2)
    return None


def estimate_height_pt(paragraphs: Sequence[tuple[str, float]], width_emu: int, line_spacing: float = 1.0,
                       space_after_pt: float = 0.0) -> float:
    """paragraphs: [(文字列, 文字サイズ pt)]。折り返しを考えた高さ（pt）。"""
    width_pt = max((width_emu - INSET_X) / EMU_PER_PT, 1.0)
    total = 0.0
    for i, (text, size) in enumerate(paragraphs):
        lines = 0
        for line in (text or " ").split("\n"):
            lines += len(wrap_lines(line, size, width_pt))
        total += lines * size * LINE_HEIGHT * line_spacing
        if i < len(paragraphs) - 1:
            total += space_after_pt
    return total


def fit_scale(paragraphs: Sequence[tuple[str, float]], width_emu: int, height_emu: int, line_spacing: float = 1.0,
              space_after_pt: float = 0.0) -> float:
    """収まる倍率（1.0 以下、5% 刻み）。最小の文字が MIN_SIZE を下回る手前、または MIN_SCALE で止める。"""
    height_pt = max((height_emu - INSET_Y) / EMU_PER_PT, 1.0)
    smallest = min((s for _, s in paragraphs), default=MIN_SIZE)
    scale = 1.0
    while scale > MIN_SCALE + 1e-9:
        sized = [(t, s * scale) for t, s in paragraphs]
        if estimate_height_pt(sized, width_emu, line_spacing, space_after_pt * scale) <= height_pt:
            return scale
        if smallest * (scale - 0.05) < MIN_SIZE:
            break
        scale = round(scale - 0.05, 2)
    return scale
