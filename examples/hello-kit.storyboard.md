---
id: hello-kit
title: 台本 1 枚から説明動画ができるまで
schema_version: kit-1.0.0
audience: A
kind: tool_intro
confidentiality: general       # このキット自体の説明。公開済みの情報だけ
aspect: "16:9"
output_name: hello_kit
---

# 台本 1 枚から説明動画ができるまで（例の台本）

<!--
キットの例の台本。`erkit check examples/hello-kit.storyboard.md` で検証できる。
説明図: `erkit diagram examples/hello-kit.storyboard.md --out <出力先>`（diagrams/*.html を描く）。
撮影: `erkit capture examples/hello-kit.storyboard.md --serve examples/hello-page --out <出力先>`（hello-kit.actions.yaml に従う）。
-->

## intro
```yaml
summary: 台本を 1 枚書くと、説明図・画面の撮影・ナレーション・スライドを経て MP4 ができます。
prerequisites:
  - Windows と PowerPoint（デスクトップ版）
duration_note: 未計測
```
このキットは、台本を一枚書くだけで、ナレーション付きの説明動画を作る仕組みです。

ここでは、台本から動画ができるまでの流れを、順番にご紹介します。

## s01: 台本を書く
```yaml
where: 台本（Markdown のファイル）
image:
  source: generated
  ref: assets/s01_storyboard.png
  label: 説明用再構成図
on_screen_text: シーンごとに 見出し・画像・ナレーション
recipe: highlight_box
recipe_params:
  mark: scene_block
capture:
  tool: html
  src: diagrams/s01_storyboard.html
  prompt: 台本の構成（冒頭・シーン・まとめ）を示す説明図
```
まず、台本を書きます。台本は、シーンごとに、見出し、画像、そしてナレーションを並べた文書です。

AI と相談しながら書くと、構成を整えやすくなります。

## s02: 説明図を描く
```yaml
where: 説明図の HTML
image:
  source: generated
  ref: assets/s02_diagram.png
  label: 説明用再構成図
recipe: fade_sequence
capture:
  tool: html
  src: diagrams/s02_diagram.html
  prompt: HTML から画像と注釈の位置ができる流れ
```
説明図は、HTML で描きます。赤枠で指したい部分に名前を付けておくと、位置が自動で測られます。

## s03: 画面を撮影する
```yaml
where: ブラウザ
image:
  source: web
  ref: captures/hello-kit/s03_page.png
  label: 実キャプチャ
recipe: arrow_move
recipe_params:
  to: {mark: result_area}
capture:
  url: http://127.0.0.1:8000/
  steps:
    - ページを開いて読み込み完了を待つ
    - 結果の欄が見える状態で撮影する
```
ツールの画面は、ブラウザを自動で操作して撮影します。手で画面を切り取る必要はありません。

## s04: ナレーションを作る
```yaml
where: 音声合成エンジン
image:
  source: generated
  ref: assets/s04_voice.png
  label: 説明用再構成図
recipe: text_build
on_screen_text: 文章／声／秒数
recipe_params:
  lines: [文章, 声, 秒数]
capture:
  prompt: ナレーションの文章が声と秒数になる流れ
```
ナレーションは、手元の音声合成エンジンで作ります。声の長さに合わせて、スライドの秒数が決まります。

## s05: 動画に書き出す
```yaml
where: PowerPoint
image:
  source: generated
  ref: assets/s05_export.png
  label: 説明用再構成図
recipe: fade_sequence
capture:
  prompt: スライドから MP4 ができる流れ
```
最後に、アニメーション付きのスライドを PowerPoint で動画に書き出し、ナレーションを重ねて完成です。

## outro
```yaml
summary: 台本 → 説明図・撮影 → ナレーション → スライド → MP4 の順に進みます。
checks:
  - 見出しが行動で終わっているか
  - 社外秘の区分を書いたか
next: テンプレートから自分の台本を書いてみる
```
台本を書けば、あとは仕組みが順番に進めます。スライドも残るので、手で直してから書き出し直すこともできます。
