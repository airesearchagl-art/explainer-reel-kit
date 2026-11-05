"""スライドの自動切替（p:transition）とアニメーション（p:timing）を標準 OOXML で書く。

python-pptx にはアニメーション API がないため、XML を直接組み立てる。
PowerPoint の拡張は、変形（Morph）切替だけに使う。Windows での実測で、
mc:AlternateContent（Choice = p159:morph、Fallback = p:fade）を lxml で差し込む書き方が、
修復なしで開け、CreateVideo の動画でも変形が再生されることを確かめた。

構造（PowerPoint が「前の動作の後」で連鎖させたときに書く形と同じ）:

    p:timing/p:tnLst/p:par/cTn[tmRoot]/p:seq/cTn[mainSeq]
        p:par  ← クリックグループ1つ。スライド開始（onBegin）で自動開始
            p:par  cond delay=<その段の開始時刻 ms>   ← 段（step）。前の段の終了後に開始
                p:par cTn[nodeType=afterEffect]   ← 段の先頭の効果
                p:par cTn[nodeType=withEffect]    ← 同時に動く効果
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from lxml import etree

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
P14_NS = "http://schemas.microsoft.com/office/powerpoint/2010/main"
P159_NS = "http://schemas.microsoft.com/office/powerpoint/2015/09/main"
MORPH_MS = 1000  # 変形（Morph）切替の長さの既定
NSMAP = {"p": P_NS, "a": A_NS}


def _p(tag: str) -> str:
    return f"{{{P_NS}}}{tag}"


# ---------------------------------------------------------------- effect model

@dataclass
class Effect:
    """1つのアニメーション効果。

    kind:
        fade_in   — 出現（フェード）
        fade_out  — 消える（フェード）。複数の赤枠を順に出すとき、前の枠を消すのに使う
        blink     — 強調（点滅1回）
        motion    — 移動（直線のモーションパス）。dx, dy はスライド幅・高さに対する比
    """

    kind: str
    spid: int
    dur: int  # ms
    delay: int = 0  # ms（段の開始からの遅延）
    paragraph: int | None = None  # 段落単位の出現（text_build）
    dx: float = 0.0
    dy: float = 0.0
    is_text_shape: bool = False  # bldLst に載せるか（図形・テキスト。画像は載せない）
    anim_bg: bool = False  # テキストを持たない図形（赤枠・矢印）
    grp: int = 0  # bldLst の grpId（build_timing が振る）

    @property
    def end(self) -> int:
        return self.delay + self.dur


@dataclass
class Step:
    """前の段の終了後に始まる効果の組（先頭＝afterPrev、残り＝withPrev）。"""

    effects: list[Effect] = field(default_factory=list)

    @property
    def length(self) -> int:
        return max((e.end for e in self.effects), default=0)


def total_ms(steps: Iterable[Step]) -> int:
    return sum(s.length for s in steps)


def fit_to_budget(steps: list[Step], budget_ms: int, min_dur: int = 50) -> tuple[list[Step], bool]:
    """合計時間が budget_ms を超えるなら、遅延と継続時間を同じ比率で縮める。

    戻り値: (調整後の段, 縮めたかどうか)
    """
    total = total_ms(steps)
    if total <= budget_ms or total == 0:
        return steps, False
    ratio = max(budget_ms, 0) / total
    for st in steps:
        for e in st.effects:
            e.delay = int(e.delay * ratio)
            e.dur = max(min_dur, int(e.dur * ratio))
    return steps, True


# ---------------------------------------------------------------- XML builders

class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return str(self.n)


def _sub(parent, tag, **attrs):
    el = etree.SubElement(parent, _p(tag))
    for k, v in attrs.items():
        el.set(k, str(v))
    return el


def _cond(parent, delay):
    return _sub(parent, "cond", delay=delay)


def _target(cbhvr, e: Effect):
    tgt = _sub(cbhvr, "tgtEl")
    sp = _sub(tgt, "spTgt", spid=e.spid)
    if e.paragraph is not None:
        txel = _sub(sp, "txEl")
        _sub(txel, "pRg", st=e.paragraph, end=e.paragraph)


def _effect_par(parent, e: Effect, node_type: str, ids: _Ids):
    par = _sub(parent, "par")
    attrs = {"id": ids.next()}
    if e.kind == "fade_in":
        attrs.update(presetID="10", presetClass="entr", presetSubtype="0")
    elif e.kind == "fade_out":
        attrs.update(presetID="10", presetClass="exit", presetSubtype="0")
    elif e.kind == "blink":
        attrs.update(presetID="35", presetClass="emph", presetSubtype="0")
    elif e.kind == "motion":
        attrs.update(presetID="0", presetClass="path", presetSubtype="0", accel="50000", decel="50000")
    else:  # pragma: no cover - guarded by builder
        raise ValueError(f"unknown effect kind: {e.kind}")
    attrs.update(fill="hold")
    if e.is_text_shape:
        attrs["grpId"] = str(e.grp)
    attrs["nodeType"] = node_type
    ctn = _sub(par, "cTn", **attrs)
    _cond(_sub(ctn, "stCondLst"), e.delay)
    kids = _sub(ctn, "childTnLst")

    if e.kind == "fade_in":
        st = _sub(kids, "set")
        cb = _sub(st, "cBhvr")
        c = _sub(cb, "cTn", id=ids.next(), dur="1", fill="hold")
        _cond(_sub(c, "stCondLst"), 0)
        _target(cb, e)
        names = _sub(cb, "attrNameLst")
        etree.SubElement(names, _p("attrName")).text = "style.visibility"
        to = _sub(st, "to")
        _sub(to, "strVal", val="visible")

        ae = _sub(kids, "animEffect", transition="in", filter="fade")
        cb = _sub(ae, "cBhvr")
        _sub(cb, "cTn", id=ids.next(), dur=e.dur)
        _target(cb, e)

    elif e.kind == "fade_out":
        ae = _sub(kids, "animEffect", transition="out", filter="fade")
        cb = _sub(ae, "cBhvr")
        _sub(cb, "cTn", id=ids.next(), dur=e.dur)
        _target(cb, e)

        st = _sub(kids, "set")
        cb = _sub(st, "cBhvr")
        c = _sub(cb, "cTn", id=ids.next(), dur="1", fill="hold")
        _cond(_sub(c, "stCondLst"), max(e.dur - 1, 0))
        _target(cb, e)
        names = _sub(cb, "attrNameLst")
        etree.SubElement(names, _p("attrName")).text = "style.visibility"
        to = _sub(st, "to")
        _sub(to, "strVal", val="hidden")

    elif e.kind == "blink":
        an = _sub(kids, "anim", calcmode="discrete", valueType="str")
        cb = _sub(an, "cBhvr", override="childStyle")
        _sub(cb, "cTn", id=ids.next(), dur=e.dur, fill="hold")
        _target(cb, e)
        names = _sub(cb, "attrNameLst")
        etree.SubElement(names, _p("attrName")).text = "style.visibility"
        tav = _sub(an, "tavLst")
        for tm, val in ((0, "hidden"), (50000, "visible")):
            t = _sub(tav, "tav", tm=tm)
            v = _sub(t, "val")
            _sub(v, "strVal", val=val)

    elif e.kind == "motion":
        path = f"M 0 0 L {e.dx:.4f} {e.dy:.4f} E"
        am = _sub(kids, "animMotion", origin="layout", path=path, pathEditMode="relative", ptsTypes="AA")
        cb = _sub(am, "cBhvr")
        _sub(cb, "cTn", id=ids.next(), dur=e.dur, fill="hold")
        _target(cb, e)
        names = _sub(cb, "attrNameLst")
        etree.SubElement(names, _p("attrName")).text = "ppt_x"
        etree.SubElement(names, _p("attrName")).text = "ppt_y"
        _sub(am, "rCtr", x=int(e.dx * 50000), y=int(e.dy * 50000))
    return par


def build_timing(steps: list[Step]):
    """段のリストから p:timing 要素を作る。効果がなければ None。"""
    steps = [s for s in steps if s.effects]
    if not steps:
        return None
    # grpId: 図形ごと・効果の種類ごとに 0, 1, 2 …（PowerPoint と同じく出現・強調・移動を別グループに）
    groups: dict[tuple[int, str], int] = {}
    per_shape: dict[int, int] = {}
    for st in steps:
        for e in st.effects:
            if not e.is_text_shape:
                continue
            key = (e.spid, e.kind)
            if key not in groups:
                groups[key] = per_shape.get(e.spid, 0)
                per_shape[e.spid] = groups[key] + 1
            e.grp = groups[key]
    ids = _Ids()
    timing = etree.Element(_p("timing"), nsmap={"p": P_NS})
    tnlst = _sub(timing, "tnLst")
    root_par = _sub(tnlst, "par")
    root = _sub(root_par, "cTn", id=ids.next(), dur="indefinite", restart="never", nodeType="tmRoot")
    root_kids = _sub(root, "childTnLst")
    seq = _sub(root_kids, "seq", concurrent="1", nextAc="seek")
    main_id = ids.next()
    main = _sub(seq, "cTn", id=main_id, dur="indefinite", nodeType="mainSeq")
    main_kids = _sub(main, "childTnLst")

    # クリックグループ（スライド開始で自動開始）
    grp_par = _sub(main_kids, "par")
    grp = _sub(grp_par, "cTn", id=ids.next(), fill="hold")
    sc = _sub(grp, "stCondLst")
    _cond(sc, "indefinite")
    on_begin = _sub(sc, "cond", evt="onBegin", delay="0")
    _sub(on_begin, "tn", val=main_id)
    grp_kids = _sub(grp, "childTnLst")

    t = 0
    for st in steps:
        step_par = _sub(grp_kids, "par")
        sctn = _sub(step_par, "cTn", id=ids.next(), fill="hold")
        _cond(_sub(sctn, "stCondLst"), t)
        skids = _sub(sctn, "childTnLst")
        for i, e in enumerate(st.effects):
            _effect_par(skids, e, "afterEffect" if i == 0 else "withEffect", ids)
        t += st.length

    prev = _sub(seq, "prevCondLst")
    c = _sub(prev, "cond", evt="onPrev", delay="0")
    _sub(_sub(c, "tgtEl"), "sldTgt")
    nxt = _sub(seq, "nextCondLst")
    c = _sub(nxt, "cond", evt="onNext", delay="0")
    _sub(_sub(c, "tgtEl"), "sldTgt")

    # bldLst: テキスト・図形の出現（画像は載せない）
    bld: dict[tuple[int, int], dict[str, str]] = {}
    for st in steps:
        for e in st.effects:
            if not e.is_text_shape:
                continue
            entry = bld.setdefault((e.spid, e.grp), {"spid": str(e.spid), "grpId": str(e.grp)})
            if e.paragraph is not None:
                entry["build"] = "p"
            if e.anim_bg:
                entry["animBg"] = "1"
    if bld:
        bl = _sub(timing, "bldLst")
        for entry in bld.values():
            _sub(bl, "bldP", **entry)
    return timing


def build_transition(adv_ms: int, fade: bool = False):
    """自動切替（クリック進行なし）。fade=True ならフェード切替。"""
    tr = etree.Element(_p("transition"), nsmap={"p": P_NS})
    if fade:
        tr.set("spd", "med")
    tr.set("advClick", "0")
    tr.set("advTm", str(int(adv_ms)))
    if fade:
        etree.SubElement(tr, _p("fade"))
    return tr


def build_morph_transition(adv_ms: int, dur_ms: int = MORPH_MS):
    """変形（Morph）切替。Choice = p159:morph（p14:dur で長さ）、Fallback = 同じ advTm のフェード。

    Requires="p159" の接頭辞は Choice 自身で宣言する（子の p159:morph に付くと Choice の位置で解決できない）。
    変形はスライド表示の前に再生され、その後 advTm のタイマーが始まる。
    """
    ac = etree.Element(f"{{{MC_NS}}}AlternateContent", nsmap={"mc": MC_NS, "p": P_NS})
    choice = etree.SubElement(ac, f"{{{MC_NS}}}Choice", nsmap={"p159": P159_NS, "p14": P14_NS})
    choice.set("Requires", "p159")
    tr = etree.SubElement(choice, _p("transition"))
    tr.set("spd", "slow")
    tr.set(f"{{{P14_NS}}}dur", str(int(dur_ms)))
    tr.set("advClick", "0")
    tr.set("advTm", str(int(adv_ms)))
    etree.SubElement(tr, f"{{{P159_NS}}}morph").set("option", "byObject")
    fb = etree.SubElement(ac, f"{{{MC_NS}}}Fallback")
    ftr = etree.SubElement(fb, _p("transition"))
    ftr.set("spd", "slow")
    ftr.set("advClick", "0")
    ftr.set("advTm", str(int(adv_ms)))
    etree.SubElement(ftr, _p("fade"))
    return ac


def attach(slide, transition, timing) -> None:
    """切替（p:transition または Morph の mc:AlternateContent）と p:timing をスキーマ順（clrMapOvr の後）に差し込む。"""
    sld = slide._element
    for tag in ("transition", "timing"):
        for old in sld.findall(_p(tag)):
            sld.remove(old)
    for old in sld.findall(f"{{{MC_NS}}}AlternateContent"):
        if old.find(f".//{{{P_NS}}}transition") is not None:
            sld.remove(old)
    anchor = sld.find(_p("clrMapOvr"))
    if anchor is None:
        anchor = sld.find(_p("cSld"))
    idx = list(sld).index(anchor) + 1
    sld.insert(idx, transition)
    if timing is not None:
        sld.insert(idx + 1, timing)
