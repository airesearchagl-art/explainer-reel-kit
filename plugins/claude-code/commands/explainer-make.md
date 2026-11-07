---
description: 台本から説明動画（MP4）を作る。まず erkit make --dry-run を見せ、人がよいと言ってから erkit make を実行し、止まったら続きから作るコマンドを示す
argument-hint: "[台本のパス] [撮るページのフォルダ（--serve に渡す。任意）]"
disable-model-invocation: true
---

# /explainer-reel-kit:explainer-make — MP4 まで作る

引数: $ARGUMENTS

## 1. 始める前に

`make-explainer` スキルの「始める前に」と同じ確かめをする（キットのフォルダか、erkit の呼び方、`erkit --version` がこのプラグインの版 **0.2.1** と同じか）。
手順の正本は `docs/guide/06-review.md` と `docs/guide/07-export.md`。Read で読む。

## 2. 検証と段の順番を見せる（何も作らない）

例はサンプル。台本のパスと `--serve` のフォルダは引数に変える（撮影のシーンが無ければ `--serve` は要らない）。

```bash
erkit check samples/u-value/u-value.storyboard.md
erkit make samples/u-value/u-value.storyboard.md --serve samples/u-value/app --dry-run
```

- `erkit check` が通らなければ、ここで止めて `/explainer-reel-kit:explainer-check` へ
- `--dry-run` の表示（区分・出力先・声・段の順番）を人に見せる。社外秘の確かめで止まったら（終了コード 1）、表示の理由を伝える。区分を下げて回避しない
- 画像がまだそろっていなければ、試作（`--allow-placeholders --label 試作`）にするか人に聞く

## 3. 人に確かめる

**まとめて進めてきたときも、この確かめは省かない**（報告を見せた後でも、ここでもう一度聞く）。


「この内容で作ってよいですか。AivisSpeech を起動し、PowerPoint は閉じておいてください（書き出しの間、キットが PowerPoint を動かします）」。**よいと言われるまで実行しない。**

## 4. 作る

```bash
erkit make samples/u-value/u-value.storyboard.md --serve samples/u-value/app
```

試作なら:

```bash
erkit make samples/u-value/u-value.storyboard.md --serve samples/u-value/app --allow-placeholders --label 試作
```

時間がかかる（数分）。終わったら:

- 終了コード 0 → 出力フォルダ（表示に出る）の MP4・.pptx・`work/check/overlay.png` を人に見てもらう。動画の公開はしない
- 終了コード 1 → 失敗した段と理由を読み、表示の「直したら、そこから」のコマンド（`--from` 付き）を人に示す。原因を直してから、そのコマンドで続ける。ナレーションを書き換えた後は `--force` が要る
- 終了コード 2 → 引数か台本の誤り。直してもう一度
- Windows 以外では .pptx まで作って止まる（正しい動き）。Windows で `--from export` で続けると伝える
