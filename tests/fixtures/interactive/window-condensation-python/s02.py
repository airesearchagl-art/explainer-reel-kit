# -*- coding: utf-8 -*-
"""window-condensation の s02「しくみをつかむ」の場面コード（interactive のテスト用の例。一般的な題材）。

暖かい空気 → 窓で冷える → 露点 → 水滴 の 4 枚のカードを、読み上げの順に出して、読んでいるカードだけを明るくする。
時刻は秒で書かず、文の id（<場面 id>-<番号>。段落の文を上から数える）で T に聞く。
文言・数値は台本の画面の文字（on_screen_text）とナレーションにあるものだけ。
"""
from explainer_reel_kit.interactive.engine import AMBER, LINE, TEAL, TEXT2, ramp, win
from explainer_reel_kit.interactive.parts import card_text

CARDS = [
    ('① 暖かい空気', '目に見えない水蒸気を含む。暖かいほど多く含める'),
    ('② 窓で冷える', '冷たい窓ガラスに触れて、空気が冷やされる'),
    ('③ 露点', '水蒸気を抱えきれなくなり、水滴ができ始める温度'),
    ('④ 結露', 'ガラスの表面が露点より冷えると、水滴がつく'),
]
X0, Y0, CW, CH, GAP = 96, 250, 396, 220, 48


def scene(f, t, T):
    sc = T.by_id['s02']
    a = ramp(t, sc['start'], 0.4)
    f.rr(96, 60, 8, 62, r=4, fill=TEAL, a=a)
    f.text('しくみをつかむ', 126, 67, size=48, w='B', a=a, maxw=1600)
    f.rr(96, 142, 1728, 2, r=0, fill=LINE, a=a)

    # 各カードが出る時刻（読み上げの順）
    starts = [T.S('s02-1'), T.S('s02-3'), T.S('s02-4'), T.S('s02-7')]
    ends = starts[1:] + [sc['end']]
    for i, ((title, body), t0, t1) in enumerate(zip(CARDS, starts, ends)):
        x = X0 + i * (CW + GAP)
        shown = ramp(t, t0, 0.4)
        if shown <= 0:
            continue
        card_text(f, x, Y0, CW, CH, title=title, body=body, a=shown, title_size=36, body_size=28)
        on = win(t, t0, t1)
        if on < 1:   # 読んでいないカードは沈める
            f.veil(x - 3, Y0 - 3, CW + 6, CH + 6, shown * (1 - on) * 0.55, r=16)
        if on > 0:
            f.focus(x, Y0, CW, CH, r=16, a=on)
        if i > 0:    # 前のカードからの矢印
            xa = x - GAP + 8
            f.path([(xa, Y0 + CH / 2), (x - 8, Y0 + CH / 2)], color=TEXT2, width=4, head=True,
                   prog=ramp(t, t0, 0.5), a=shown)

    # 下の要点（数値は台本の画面の文字のまま）
    k = ramp(t, T.at('s02-6', '露点は'), 0.4)
    if k > 0:
        f.rr(96, 560, 1728, 120, r=16, fill='#0b1a2ccc', outline=AMBER, ow=2, a=k)
        f.text('室温 20℃・湿度 60％なら露点は約 12℃', 960, 600, size=44, w='B', color=AMBER, a=k, anchor='c',
               maxw=1660)
