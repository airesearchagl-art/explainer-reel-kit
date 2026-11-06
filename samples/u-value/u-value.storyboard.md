---
id: u-value
title: 窓の断熱性能（U 値）の見方
schema_version: kit-1.0.0
audience: A
kind: tool_intro
confidentiality: general       # 建築の一般的な知識と、キットの中の計算ページだけ
aspect: "16:9"
output_name: u_value
---

# 窓の断熱性能（U 値）の見方（キットのサンプル題材）

<!--
キットのサンプル題材。説明図（HTML）と Web 撮影（キットの中の計算ページ）の両方を使う。
  erkit check   samples/u-value/u-value.storyboard.md
  erkit diagram samples/u-value/u-value.storyboard.md --out <出力先>
  erkit capture samples/u-value/u-value.storyboard.md --serve samples/u-value/app --out <出力先>
  erkit deck    samples/u-value/u-value.storyboard.md --assets-root <出力先> --out <出力先>/u_value.pptx

数値の扱い（根拠は samples/u-value/SOURCES.md）
- U 値はガラス中央部の熱貫流率（Ug、W/(m²·K)）の一般的な目安。製品・中空層の厚さ・ガスの有無で変わるため、範囲で示す
  - 単板ガラス 5.8〜6.0（板硝子協会「ビルと複層ガラス」表 2.1 の透明単板 5.8。上限 6.0 は JIS R 3107 による 3mm 単板の計算値で、公的な資料での確認は未了）
  - 複層ガラス（空気層） 2.7〜4.0（JIS R 3209:2018 の断熱性の区分 T1。代表の構成は中空層 12mm で、板硝子協会の表では 2.9）
  - Low-E 複層ガラス（空気層） 1.6〜2.7（JIS 区分の T2〜T3、板硝子協会の表の 1.6〜1.9）
  - ガス入り Low-E 複層ガラス 1.1〜1.9（JIS 区分の T4〜T5）
- 窓全体（枠を含む）の U 値は建具の材質で変わる。このサンプルはガラスだけを比べる
- 熱の損失（W）＝ U 値 × 面積（m²）× 室内外の温度差（℃）。日射・すき間風・枠は含めない
-->

## intro
```yaml
summary: 窓ガラスの U 値が何を表すかと、ガラスの種類で熱の逃げ方がどれくらい変わるかを、計算ページで確かめます。
prerequisites:
  - ブラウザ（キットの中の計算ページを開く）
duration_note: 約 2 分
```
窓は、家の中で熱が出入りしやすい場所です。

この動画では、窓ガラスの断熱性能を表す、ユー値の見方をご紹介します。家づくりやリフォームで、窓を選ぶときの手がかりにしてください。

## s01: 熱の逃げ方を知る
```yaml
where: 説明図
image:
  source: generated
  ref: assets/s01_heat_paths.png
  label: 説明用再構成図
on_screen_text: 伝導・対流・放射
recipe: highlight_box
recipe_params:
  mark: [conduction, convection, radiation]
capture:
  tool: html
  src: diagrams/s01_heat_paths.html
  prompt: 窓を通って熱が逃げる 3 つの道（伝導・対流・放射）
```
まず、熱が窓から逃げる道を見てみましょう。ひとつめは伝導です。ガラスや枠そのものを、熱が伝わっていきます。

ふたつめは対流です。窓の近くで冷やされた空気が下に流れ、部屋の空気と入れ替わることで、熱が運ばれます。

みっつめは放射です。暖かい部屋から冷たいガラスへ、熱が光と同じように飛んでいきます。

## s02: U 値の意味をつかむ
```yaml
where: 説明図
image:
  source: generated
  ref: assets/s02_u_value.png
  label: 説明用再構成図
on_screen_text: 1 m²・温度差 1℃ あたりに流れる熱（W）
recipe: highlight_box
recipe_params:
  mark: [u_formula, range_chart]
capture:
  tool: html
  src: diagrams/s02_u_value.html
  prompt: U 値の定義と、ガラスの種類ごとの U 値の目安の範囲
```
ユー値は、ガラス一平方メートルあたり、室内と室外の温度差が一度のときに、何ワットの熱が流れるかを表す数字です。小さいほど、熱を通しにくい窓になります。

ガラスの種類ごとに、おおよその範囲があります。一枚だけの単板ガラスはおよそ六、ローイー複層ガラスでは二前後まで下がります。ただし、製品や空気の層の厚さで変わるので、あくまで目安として見てください。

## s03: 計算ページを開く
```yaml
where: 計算ページ（キットの中の samples/u-value/app）
image:
  source: web
  ref: captures/u-value/s03_open.png
  label: 実キャプチャ
recipe: highlight_box
recipe_params:
  mark: input_panel
capture:
  url: http://127.0.0.1:8000/index.html
  viewport: {width: 1600, height: 660}
  steps:
    - 計算ページを開いて、読み込みが終わるのを待つ
    - 左の「条件」の欄が見える状態で撮影する
```
ここからは、キットに入っている小さな計算ページを使います。インターネットにはつながず、このパソコンの中だけで動きます。

左側の条件の欄で、ガラスの種類、窓の面積、室内と室外の温度差を入れます。

## s04: ガラスの種類を選ぶ
```yaml
where: 計算ページ
image:
  source: web
  ref: captures/u-value/s04_glass.png
  label: 実キャプチャ
recipe: highlight_box
recipe_params:
  mark: [glass_select, u_row_lowe]
capture:
  url: http://127.0.0.1:8000/index.html
  steps:
    - ガラスの種類で「Low-E 複層ガラス（空気層）」を選ぶ
    - 右下の U 値の目安の表で、選んだ行が強調された状態で撮影する
```
ガラスの種類を、ローイー複層ガラスに切り替えてみます。

すると、右下の表で、選んだガラスのユー値の目安が強調されます。数字は一つではなく、幅で表示されます。

## s05: 結果を比べる
```yaml
where: 計算ページ
image:
  source: web
  ref: captures/u-value/s05_compare.png
  label: 実キャプチャ
recipe: arrow_move
recipe_params:
  to: {mark: loss_lowe}           # Low-E 複層の行の「48〜81 W」
  from_side: left                 # 棒の右の空いたところを通って数字を指す
capture:
  url: http://127.0.0.1:8000/index.html
  steps:
    - 面積に 2.0、温度差に 15 を入れる
    - 熱の損失の比較のグラフが見える状態で撮影する
```
面積を二平方メートル、温度差を十五度にすると、熱の損失がグラフで比べられます。

単板ガラスでは百七十から百八十ワットほど逃げるのに対して、ローイー複層ガラスでは、その半分以下の目安になります。

## outro
```yaml
summary: U 値は 1 m²・温度差 1℃ あたりの熱の流れ。ガラスの種類で目安の範囲が大きく変わります。
checks:
  - U 値はガラスだけの値か、枠を含む窓全体の値か
  - 製品ごとの値は、カタログや性能の表示で確かめる
next: 気になる窓の面積と温度差で、計算ページの数字を比べてみる
```
ユー値を見るときは、ガラスだけの値か、枠を含めた窓全体の値かを、確かめるようにしましょう。

実際に選ぶときは、製品ごとの性能の表示も合わせて確認してください。
