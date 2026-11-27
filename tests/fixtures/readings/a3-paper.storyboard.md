---
id: a3-paper-readings
title: 図面を A3 の紙に印刷する（読みと字幕の確かめ用のダミー）
schema_version: kit-1.2.0
audience: A
kind: work_manual
confidentiality: general  # ダミーの原稿（テスト用。公開済みの一般的な内容だけ）
render_mode: interactive
aspect: "16:9"
output_name: a3_paper_readings
---

# 読みと字幕の確かめ用のダミー台本

<!--
「A3用紙」は辞書の語句（A3用紙: エーサンヨウシ）で読みを直す。「A3」だけの所（s02 の 1 段落目）は別の読みのまま。
s01 の 2 段落目は、字幕の別表記を足す・直す確かめに使う。画像は撮影しない。
-->

## intro
```yaml
summary: 図面を A3 の紙に印刷して、線が切れていないかを確かめます。
prerequisites:
  - プリンターにつながったパソコン
```
この動画では、図面をA3用紙に印刷する手順を確かめます。

## s01: 用紙の大きさを選ぶ
```yaml
image:
  source: manual
  ref: images/s01.png
  label: 実キャプチャ
  alt: 印刷の設定の画面
on_screen_text: 用紙の大きさ
recipe: fade_sequence
capture:
  instructions: 印刷の設定の画面を撮る
```
まず、印刷の設定を開きます。用紙の大きさを選ぶ欄があります。

ここではA3用紙を選びます。

## s02: 印刷して確かめる
```yaml
image:
  source: manual
  ref: images/s02.png
  label: 実キャプチャ
  alt: 印刷した紙
on_screen_text: 線が切れていないか
recipe: fade_sequence
capture:
  instructions: 印刷した紙を撮る
```
A3の図面を印刷します。

出てきた紙の端で、線が切れていないかを確かめます。

## outro
```yaml
summary: 図面が A3 の紙に収まれば完了です。
checks:
  - 紙の端の線が切れていない
```
A3用紙に図面が収まっていれば完了です。
