---
description: erkit doctor と erkit check を実行して結果を読み、足りないものと台本の直す所を示す（台本は直してもう一度検証する）
argument-hint: "[台本のパス（省くと環境の確認だけ）]"
disable-model-invocation: true
---

# /explainer-reel-kit:explainer-check — 環境と台本を確かめる

対象の台本: $ARGUMENTS

## 1. 始める前に

`make-explainer` スキルの「始める前に」と同じ確かめをする（キットのフォルダか、erkit の呼び方、`erkit --version` がこのプラグインの版 **0.2.0** と同じか）。

## 2. 環境の確認

```bash
erkit doctor
```

- `NG` の行の下の `→` が入れ方。**ソフトは入れない**（ffmpeg・AivisSpeech・PowerPoint・Python などは人が入れる）。入れ方をまとめて伝える
- Chromium が `NG` で Edge があるなら `erkit doctor --channel msedge` も試し、撮影・説明図に `--channel msedge` を付ければよいと伝える
- 手順の正本: `docs/guide/00-setup.md`、`docs/guide/troubleshooting.md`

## 3. 台本の確認（パスがあるとき）

```bash
erkit check --strict samples/u-value/u-value.storyboard.md
```

（パスは対象の台本に変える）

- 表示の「区分」を見る。`confidential` なら、資料をこの会話に出さないよう人に伝え、資料を読まない（`docs/guide/confidentiality.md`）。区分は下げない
- `NG`・`警告:` の各行を読み、台本を直してもう一度。通るまで繰り返す（要点は `storyboard` スキル）
- 撮影のシーンがあれば、続けて `erkit capture` に `--check` を付けて、操作定義との突き合わせも確かめる（`web-capture` スキル）

## 4. まとめ

環境の足りないもの、台本の直した所と残った警告、次の段（`docs/guide/README.md` の表）を短く伝える。
