---
name: diagram
description: 説明動画の説明図を HTML で書き、erkit diagram で PNG と注釈位置（mark）にする。共通の CSS・data-mark・外の URL を読まない決まりを守り、確認画像で赤枠の位置を人に確かめる。台本の image.source が generated で capture.tool が html のシーンに使う。一般の解説（kind explainer）では部品 7 種（断面図・比較表・数値の範囲・フロー・カード・条件の分岐・たとえ）の見本を写して描く。
---

# 説明図（HTML）を書く

手順の正本は `docs/guide/05-visuals.md` の「説明図（HTML）」、仕様は `docs/design/diagram.md`。書く前に Read で読む。
手本は `samples/u-value/diagrams/s01_heat_paths.html`、共通の CSS は `samples/_shared/diagram.css`（クラスの一覧は `prompts/04-diagram-html.md`）。

## 要点

- 1 シーン 1 ファイル。台本の `capture.src` のパスに書く
- 共通の CSS を HTML のファイルからの相対パスで読む（`reels/<id>/diagrams/` なら `../../_shared/diagram.css`。`/explainer-reel-kit:explainer-new` が `reels/_shared` を写してある）
- 大きさは CSS が決める（2420×1000 px）。文字は 32px 未満にしない
- 指したい要素に `data-mark="名前"`。台本の `recipe_params` の mark と同じ名前、1 つの図で 1 回だけ
- **外の URL を読まない**（Web フォント・CDN・外の画像・fetch）。読むとそのシーンは失敗する
- 赤は使わない（注釈とぶつかる）。実際の画面のふりをしない（`説明用再構成図`）

## 解説（kind: explainer）のとき — 部品で描く

部品の選び方は `docs/guide/05-visuals.md` の「解説の部品の選び方」、クラスと決まりは `docs/design/diagram.md` の「解説の部品」。見本は `samples/_parts/`、使った例は `samples/window-condensation/diagrams/`。

| 話したいこと | 部品の見本 |
|---|---|
| 身近なものにたとえる（問い） | `samples/_parts/analogy.html` |
| 層の重なり（しくみ） | `samples/_parts/section.html` |
| 原因から結果までの順番（しくみ） | `samples/_parts/flow.html` |
| 種類を観点で比べる | `samples/_parts/compare.html` |
| 数値の目安を範囲で（出典のある値だけ） | `samples/_parts/range.html` |
| 条件で答えが分かれる（選び方） | `samples/_parts/branch.html` |
| 2〜4 枚並べる（条件・減らし方・まとめ） | `samples/_parts/cards.html` |

- **見本を写して、文字と数値だけを書き換える**。新しい形を一から描かない
- 写したら CSS の参照を `../_shared/diagram.css` から `../../_shared/diagram.css` に直す（`reels/<id>/diagrams/` に置くため）
- `data-mark` は台本の `recipe_params` の名前に合わせる（ひな形は見本の名前のまま）
- 色は意味で 4 色まで（`c-blue` 断熱・冷たい、`c-amber` 日射・暖かい・注意、`c-teal` 結果・おすすめ、`c-gray` その他）
- 見本の値・評価は例。確かめた値（`SOURCES.md` にあるもの）に書き換えるか消す。断面図は「模式。実寸ではない」と書く。数値の範囲の帯の位置は値 ÷ 目盛りの最大 × 100 % で計算する
- 小さい字が 1 文字だけ次の行に落ちるなど、確認画像で崩れが見えたら文を短くする

## 描いて確かめる

```bash
erkit diagram samples/u-value/u-value.storyboard.md --out output/u-value --overlay output/u-value/check-diagram.png
```

（自分の台本のパスと出力先に変える。Chromium が無ければ `--channel msedge` を付ける）

- 終了コード 1 → 失敗したシーンの理由が表示と `diagram-result.json` に出る。外の URL・mark が見つからない・小さすぎる、を直してもう一度
- 終了コード 0 → **確認画像（`--overlay` の PNG）を人に見せ**、赤枠が指したい部品に重なっているか確かめてもらう。ずれていれば `data-mark` を付ける要素を変える（座標は書かない）
