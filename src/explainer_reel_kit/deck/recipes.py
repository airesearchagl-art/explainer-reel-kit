"""アニメーションレシピ（台本 recipe 名 → 効果の段）。

形式と既定値: docs/design/recipes.md
すべて「前の動作の後」で連鎖し、各効果の開始遅延と継続時間を明示する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .timing import Effect, Step

# 既定の時間（ms）
LEAD_IN = 300  # スライド表示から最初の効果までの間
FADE = 500
IMAGE_FADE = 700
GAP = 150  # 段と段の間（遅延）
BOX_FADE = 400
BOX_EXIT = 300  # 複数の枠: 前の枠を消す
BLINK = 600
TAIL_MS = 300  # 最後の効果が終わってから切り替わるまでの余裕（builder と同じ値）
ARROW_FADE = 300
ARROW_MOVE = 1200

DEFAULT_BOX = {"x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}
DEFAULT_FROM = {"x": 0.2, "y": 0.5}
DEFAULT_TO = {"x": 0.8, "y": 0.5}

RECIPES = ("fade_sequence", "highlight_box", "arrow_move", "morph_transition", "text_build")


@dataclass
class SceneShapes:
    heading: int | None = None
    image: int | None = None
    text: int | None = None  # on_screen_text
    text_paragraphs: int = 0
    image_is_shape: bool = False  # プレースホルダー（図形）なら True、画像なら False
    box: int | None = None  # highlight_box の赤枠（1 つ目。互換のため）
    boxes: list[int] = field(default_factory=list)  # highlight_box の赤枠（順に出す）
    arrow: int | None = None  # arrow_move の矢印
    label: int | None = None  # 来歴ラベル（アニメーションしない）


def _fade(spid: int, dur: int, delay: int, text: bool, paragraph: int | None = None, anim_bg: bool = False) -> Step:
    return Step([Effect("fade_in", spid, dur=dur, delay=delay, is_text_shape=text, paragraph=paragraph, anim_bg=anim_bg)])


def _base_sequence(sh: SceneShapes, include_text: bool = True) -> list[Step]:
    steps: list[Step] = []
    if sh.heading is not None:
        steps.append(_fade(sh.heading, FADE, LEAD_IN, True))
    if sh.image is not None:
        steps.append(_fade(sh.image, IMAGE_FADE, GAP if steps else LEAD_IN, sh.image_is_shape))
    if include_text and sh.text is not None:
        steps.append(_fade(sh.text, FADE, GAP, True))
    return steps


def box_targets(n: int, base_end_ms: int, adv_ms: int | None, cue_ms: list[int] | None = None) -> list[int]:
    """n 個の枠を出す時刻（スライド開始からの ms）。

    cue_ms（ナレーションの分割ごとの開始時刻）が n 個あればそれに合わせる。
    無ければ、本体（見出し・画像・画面テキスト）が出た後の残り時間を均等に割る。
    """
    first = base_end_ms + GAP
    if cue_ms is not None and len(cue_ms) == n:
        return [max(first, c) if i == 0 else c for i, c in enumerate(cue_ms)]
    if adv_ms is None or n <= 1:
        return [first + i * (BOX_EXIT + BOX_FADE + BLINK + GAP) for i in range(n)]
    window = max(adv_ms - TAIL_MS - first, 0)
    slot = window / n
    return [int(first + i * slot) for i in range(n)]


def _box_steps(boxes: list[int], base_end_ms: int, targets: list[int]) -> list[Step]:
    """枠を順に出す。2 つ目以降は前の枠を消してから出す。"""
    steps: list[Step] = []
    cursor = base_end_ms
    prev: int | None = None
    for spid, t in zip(boxes, targets):
        delay = max(t - cursor, GAP if prev is not None else 0)
        effects = []
        if prev is not None:
            effects.append(Effect("fade_out", prev, dur=BOX_EXIT, delay=delay, is_text_shape=True, anim_bg=True))
            effects.append(Effect("fade_in", spid, dur=BOX_FADE, delay=delay + BOX_EXIT, is_text_shape=True,
                                  anim_bg=True))
        else:
            effects.append(Effect("fade_in", spid, dur=BOX_FADE, delay=delay, is_text_shape=True, anim_bg=True))
        st = Step(effects)
        steps.append(st)
        blink = Step([Effect("blink", spid, dur=BLINK, delay=0, is_text_shape=True, anim_bg=True)])
        steps.append(blink)
        cursor += st.length + blink.length
        prev = spid
    return steps


def scene_steps(recipe: str, sh: SceneShapes, params: dict[str, Any], slide_w: int, slide_h: int,
                arrow_delta: tuple[float, float] = (0.0, 0.0), adv_ms: int | None = None,
                cue_ms: list[int] | None = None) -> tuple[list[Step], bool]:
    """レシピから効果の段を作る。戻り値 (段, フェード切替を使うか)。

    adv_ms: スライドの自動切替秒数（複数の枠の時刻を均等に割るのに使う）
    cue_ms: ナレーションの分割ごとの開始時刻（スライド開始からの ms）。分かるときだけ
    """
    if recipe == "fade_sequence":
        return _base_sequence(sh), False

    if recipe == "highlight_box":
        steps = _base_sequence(sh)
        boxes = sh.boxes or ([sh.box] if sh.box is not None else [])
        if boxes:
            base_end = sum(s.length for s in steps)
            steps += _box_steps(boxes, base_end, box_targets(len(boxes), base_end, adv_ms, cue_ms))
        return steps, False

    if recipe == "arrow_move":
        steps = _base_sequence(sh)
        if sh.arrow is not None:
            dx, dy = arrow_delta
            steps.append(_fade(sh.arrow, ARROW_FADE, GAP, True, anim_bg=True))
            steps.append(Step([Effect("motion", sh.arrow, dur=ARROW_MOVE, delay=0, dx=dx, dy=dy,
                                      is_text_shape=True, anim_bg=True)]))
        return steps, False

    if recipe == "text_build":
        steps = _base_sequence(sh, include_text=False)
        if sh.text is not None:
            for i in range(max(sh.text_paragraphs, 1)):
                steps.append(_fade(sh.text, FADE, GAP, True, paragraph=i))
        return steps, False

    if recipe == "morph_transition":
        # Morph（p159:morph）は mc:AlternateContent が必要。
        # フェード切替で代替し、スライド内の要素は静的に表示する。
        return [], True

    raise ValueError(f"unknown recipe: {recipe}")


def intro_outro_steps(spids: list[tuple[int, bool]]) -> list[Step]:
    """intro / outro は固定テンプレート: 上から順にフェードイン。"""
    steps = []
    for i, (spid, is_text) in enumerate(spids):
        steps.append(_fade(spid, FADE if is_text else IMAGE_FADE, LEAD_IN if i == 0 else GAP, is_text))
    return steps
