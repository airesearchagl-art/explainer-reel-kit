---
# ===== reel（動画全体の情報）=====
id: my-tool-intro              # 英小文字・数字・- ・_
title: ○○ツールの紹介          # intro スライドの大見出しにもなる
schema_version: kit-1.0.0
audience: B                    # A: 初めての人 / B: よく使う人・詳しい人 / C: 専門家・作る人
kind: tool_intro               # tool_intro（ツールの紹介）/ work_manual（作業の手順）
confidentiality: confidential  # 社外秘の区分。分からなければ confidential のまま。公開済みの情報・一般的な知識だけなら general
aspect: "16:9"                 # 必ず引用符で囲む（いまは 16:9 のみ）
output_name: my_tool_intro     # .pptx / .mp4 のファイル名（拡張子なし）
voice:                         # 任意。省略すると既定の声
  speed: 1.0                   # 話速（0.5〜2.0）
  volume: 1.0                  # 音量（0〜2.0）
---

# ○○ツールの紹介

<!--
書き方
- 「## intro」「## outro」は固定テンプレートのスライド。各 ```yaml ブロックの下に書いた文章がナレーション原稿になる。
- 本編は「## <シーンID>: <行動の見出し>」で 1 シーン＝1 スライド＝主画像 1 枚。5〜8 シーンを推奨。
- 見出しは行動で終える（例: 条件を入力する／結果を確かめる）。
- ナレーション原稿は段落ごとに空行で区切る。段落内の改行は詰めて読まれる。HTML コメントの中は無視される。
- image.source: web（Web 画面の撮影）/ manual（人が用意する画像）/ generated（説明図など）
  image.label : 実キャプチャ / 途中成果 / 説明用再構成図（画像の来歴。画面を捏造しない）
  image.ref   : この台本ファイルからの相対パス。manual は実在必須、他は撮影・説明図の段が書き出す予定パス
- recipe: fade_sequence / highlight_box / arrow_move / morph_transition / text_build
- duration_sec は目安。ナレーション音声の長さ＋余白で上書きされる。
- capture は image.source に合わせて書く
  web: url + steps / manual: instructions / generated: prompt、説明図を HTML で描くなら tool: html + src
- 赤枠・矢印は座標を書かず、撮影・説明図が測った部品の名前（mark）で指す（例 recipe_params: {mark: input_area}）
-->

## intro
```yaml
summary: この動画で分かること（画面に出す 1〜2 文）
prerequisites:                 # 前提ツール・環境（任意。対象 C では書く）
  - ブラウザ（Chrome または Edge）
duration_note: 未計測          # 作業の所要時間。根拠がなければ「未計測」
```
ナレーション原稿。何ができるようになるか、誰向けかを最初に話す。

## s01: 仕組みをつかむ
```yaml
where: 説明図
image:
  source: generated
  ref: assets/s01_overview.png
  label: 説明用再構成図
on_screen_text: 画面に出す短文（任意）
recipe: highlight_box
recipe_params:
  mark: main_point             # 説明図の HTML で data-mark="main_point" を付けた要素
capture:
  tool: html
  src: diagrams/s01_overview.html
  prompt: 全体の流れを示す説明図
```
ナレーション原稿。このシーンで伝えることを話す。

## s02: 画面を開く
```yaml
where: ブラウザ
image:
  source: web
  ref: captures/my-tool/s02.png
  label: 実キャプチャ
recipe: fade_sequence
duration_sec: 6
check: このシーンで確認すること（任意）
capture:
  url: http://127.0.0.1:8000/
  steps:
    - ページを開いて読み込み完了を待つ
```
ナレーション原稿。

## outro
```yaml
summary: まとめ（画面に出す 1〜2 文）
checks:
  - 確認すること・注意点
next: 次の行動・関連リンク
```
ナレーション原稿。最後にできたことと次の行動を話す。
