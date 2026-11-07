---
# ===== reel（動画全体の情報）=====
id: my-explainer               # 英小文字・数字・- ・_
title: ○○のしくみと選び方      # intro スライドの大見出しにもなる
schema_version: kit-1.1.0      # kind: explainer は kit-1.1.0 から
audience: A                    # A: 初めての人 / B: よく使う人・詳しい人 / C: 専門家・作る人
kind: explainer                # 一般の解説（問い → しくみ → 比べる → 選び方 → まとめ）
confidentiality: general       # 公開済みの情報・一般的な知識だけ。社外秘が少しでも入る・分からないなら confidential
aspect: "16:9"                 # 必ず引用符で囲む（いまは 16:9 のみ）
output_name: my_explainer      # .pptx / .mp4 のファイル名（拡張子なし）
---

# ○○のしくみと選び方

<!--
解説（kind: explainer）のひな形。構成の決まりのとおりにシーンを並べてある。

構成の決まり（5〜7 シーン、2〜3 分）
  問い（身近な場面）→ しくみ → 比べる・条件 → 選び方・減らし方 → まとめ（確認すること）
  使わないシーンは消してよい（5 シーン以上は残す）。順番は入れ替えない。

説明図
- 全シーン説明図（image.source: generated、label: 説明用再構成図）。HTML で描き、erkit diagram で PNG にする
- 各シーンのコメントの「部品」の見本（キットの samples/_parts/<部品>.html）を diagrams/ に写して書き換える
  - 写したら、共通の CSS の参照（<link rel="stylesheet" href="…/diagram.css">）を、写した先から
    キットの samples/_shared/diagram.css への相対パスに直す
    （例 reels/<id>/diagrams/ に置くなら ../../../samples/_shared/diagram.css）
  - recipe_params.mark の名前は、見本の data-mark の名前に合わせてある。指したい部品に合わせて変える
- 色は意味で 4 色まで（青＝断熱・冷たい、黄＝遮熱・日射・注意、緑＝結果・おすすめ、灰＝その他）。赤は使わない
- 部品の一覧と使い方: docs/design/diagram.md の「解説の部品」

出典の決まり
- 数値・規格の番号・事実は、確かめたものだけを書く。確かめたものは、この台本の隣の SOURCES.md
  （資料名・URL・確かめた日）に書く。ひな形の最後に置き場のひな形がある
- 確かめていないものは、そのシーンに <!-- 未確認: … --> と書き、ナレーションでは番号・数値を言わない
- 製品で変わる値は「目安」「およそ」と言い、範囲で示す
-->

## intro
```yaml
summary: ○○は、なぜ起きて、どう選べば減らせるのかを解説します。
duration_note: 未計測
```
問いかけから入る。見る人の身近な場面を一言で示し、この動画で分かることを話す。

## s01: 身近な場面で考える
```yaml
# 問い。部品: たとえ（analogy.html）か カード（cards.html）
where: 説明図
image:
  source: generated
  ref: assets/s01_question.png
  label: 説明用再構成図
on_screen_text: ○○はなぜ起きる？
recipe: highlight_box
recipe_params:
  mark: everyday
capture:
  tool: html
  src: diagrams/s01_question.html
  prompt: 身近なもののたとえ（左）と本題（右）を並べた図
```
身近な場面を話す。見る人が「見たことがある」と思える場面から始める。

問いを 1 つにしぼって投げかける。

## s02: しくみをつかむ
```yaml
# しくみ。部品: 断面図（section.html）。層の名前と、どの層が効くかを指す
where: 説明図
image:
  source: generated
  ref: assets/s02_section.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: [layer_air, layer_coat]
capture:
  tool: html
  src: diagrams/s02_section.html
  prompt: 層の重なりの断面図（模式。実寸ではないと図に書く）
```
しくみの全体を話す。どの部分が何をしているかを、図の層の順に。

効いている層を 1 つ取り上げる（段落ごとに赤枠が切り替わる）。

## s03: 起きる順にたどる
```yaml
# しくみの続き。部品: フロー（flow.html）。原因から結果までを 3〜4 段で
where: 説明図
image:
  source: generated
  ref: assets/s03_flow.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: step_2
capture:
  tool: html
  src: diagrams/s03_flow.html
  prompt: 原因から結果までを矢印でつないだ流れ
```
起きる順に話す。1 段に 1 文。

いちばん大事な段を指して、なぜそこが分かれ目かを話す。

## s04: 種類を比べる
```yaml
# 比べる。部品: 比較表（compare.html）。行＝比べるもの、列＝観点。おすすめの行は class="best"
where: 説明図
image:
  source: generated
  ref: assets/s04_compare.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: row_coated
capture:
  tool: html
  src: diagrams/s04_compare.html
  prompt: 2〜4 種類を 2〜3 の観点で比べた表
```
何と何を比べるか、観点は何かを話す。

違いがいちばん大きい行を取り上げる。評価の根拠は SOURCES.md に。

## s05: 目安の範囲を知る
```yaml
# 条件。部品: 数値の範囲（range.html）。値は範囲で、出典のあるものだけ。位置は目盛りに合わせる
where: 説明図
image:
  source: generated
  ref: assets/s05_range.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: band_coated
capture:
  tool: html
  src: diagrams/s05_range.html
  prompt: 種類ごとの数値の範囲を帯で示した図（単位と、小さい・大きいのどちらが良いか）
```
数値の意味を先に話す（大きいほど・小さいほど、どうなるか）。

範囲で話す。製品や条件で変わることを添える。

## s06: 条件で選ぶ
```yaml
# 選び方。部品: 条件の分岐（branch.html）。問い 1 つから 2〜3 本に分ける
where: 説明図
image:
  source: generated
  ref: assets/s06_branch.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: question
capture:
  tool: html
  src: diagrams/s06_branch.html
  prompt: 条件で選び方が分かれる図
```
何で選び方が変わるかを話す。

分かれた先を 1 つずつ短く話す。

## s07: 減らし方を並べる
```yaml
# 減らし方。部品: カード（cards.html）。2〜4 枚。すぐできる順に
where: 説明図
image:
  source: generated
  ref: assets/s07_cards.png
  label: 説明用再構成図
recipe: highlight_box
recipe_params:
  mark: [card_1, card_2, card_3]
capture:
  tool: html
  src: diagrams/s07_cards.html
  prompt: 減らし方を 2〜4 枚のカードで並べた図
```
すぐできることから話す。

1 枚に 1 段落。段落ごとに赤枠が次のカードへ移る。

最後のカードは、人に相談するとよいことなど、手に負えない場合を話す。

## outro
```yaml
summary: ○○は△△で起き、□□で減らせます。
checks:
  - 確認すること（見る人が自分で確かめられること）
next: 次の行動（例 自分の家の窓を確かめる）
```
しくみと選び方を一言でまとめる。最後に、見る人が自分で確かめられることを話す。

<!--
出典の一覧の置き場（この台本の隣に SOURCES.md として置く。台本と一緒に直す）

# 数値の根拠（○○のしくみと選び方）

## 使った数値
| 値 | 使った場所 | 根拠 |
|---|---|---|
| ○○ 〜 ○○（単位） | s05 の説明図・ナレーション | [1] の 表 ○（頁） |

## 資料
1. 発行者「資料名」（版・年）頁・節 — URL（確かめた日 YYYY-MM-DD）

## 未確認
- （確かめられなかった数値・規格の番号。台本ではまだ言わない）
-->
