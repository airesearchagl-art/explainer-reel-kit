# -*- coding: utf-8 -*-
"""window-condensation の s03「ガラスの表面温度を比べる」の場面コード（interactive のテスト用の例。一般的な題材）。

表の行・列は見出しの文字で指定する（parts.Table。番号で指定して 1 行ずれるのを防ぐ）。
読み上げに合わせて、1 枚のガラス → Low-E 複層ガラス の行を順に出して強調する。
文言・数値は台本の画面の文字（on_screen_text）とナレーションにあるものだけ。
"""
from explainer_reel_kit.interactive.engine import AMBER, BLUE, CORAL, GREEN, LINE, PANEL2, TEAL, TEXT2, TEXT3, ramp, win
from explainer_reel_kit.interactive.parts import Table

COLS = ['ガラス', '室内側の表面', '露点（約 12℃）と比べて']
ROWS = ['見出し', '1 枚のガラス', 'Low-E 複層ガラス']
TB = Table(96, 300, [560, 480, 688], [80, 150, 150], cols=COLS, rows=ROWS)


def scene(f, t, T):
    sc = T.by_id['s03']
    a = ramp(t, sc['start'], 0.4)
    f.rr(96, 60, 8, 62, r=4, fill=TEAL, a=a)
    f.text('ガラスの表面温度を比べる', 126, 67, size=48, w='B', a=a, maxw=1600)
    f.rr(96, 142, 1728, 2, r=0, fill=LINE, a=a)
    f.text('外 0℃・室内 20℃・湿度 60％のとき（ガラスメーカーの計算例）', 96, 214, size=30, color=TEXT3, a=a,
           maxw=1728)

    for col in COLS:   # 見出しの行
        TB.draw_cell(f, '見出し', col, col, a=a, size=30, w='B', color=TEXT2, fill=PANEL2)

    rows = [
        ('1 枚のガラス', '約 6℃', '低い → 結露する', CORAL, T.S('s03-3'), T.at('s03-3', 'およそ六度'), T.S('s03-4')),
        ('Low-E 複層ガラス', '約 15.5℃', '高い → この条件では結露しない', GREEN, T.S('s03-5'),
         T.at('s03-5', 'およそ十五点五度'), T.S('s03-6')),
    ]
    for k, (row, temp, verdict, color, t_row, t_temp, t_verdict) in enumerate(rows):
        r = ramp(t, t_row, 0.4)
        if r <= 0:
            continue
        TB.draw_cell(f, row, 'ガラス', row, a=r, size=34, w='B')
        TB.draw_cell(f, row, '室内側の表面', temp, a=r * ramp(t, t_temp, 0.4), size=44, w='B', color=BLUE)
        TB.draw_cell(f, row, '露点（約 12℃）と比べて', verdict, a=r * ramp(t, t_verdict, 0.4), size=34, w='B',
                     color=color)
        t_end = rows[k + 1][4] if k + 1 < len(rows) else sc['end']
        on = win(t, t_row, t_end)
        if on > 0:
            f.focus(*TB.row(row), r=8, a=on)

    # 露点の基準（s03 の最初の段落で読む）
    k = ramp(t, T.S('s03-2'), 0.4)
    if k > 0:
        f.rr(96, 700, 1728, 96, r=16, fill='#0b1a2ccc', outline=AMBER, ow=2, a=k)
        f.text('露点 約 12℃ より表面が低いと結露する', 960, 728, size=40, w='B', color=AMBER, a=k, anchor='c', maxw=1660)
