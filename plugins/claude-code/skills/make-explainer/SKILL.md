---
name: make-explainer
description: 題材から説明動画（ナレーション付きの MP4）を作る全体の進め方。聞き取り → 見る人 → 構成 → 台本 → 説明図・撮影 → 確認 → 書き出しを、キット（explainer-reel-kit）の手順書の順に、段ごとに人に確かめながら進める。「説明動画を作りたい」「解説動画」「ツールの紹介動画」「作業手順の動画」と言われたときに使う。
---

# 説明動画を作る（全体の進め方）

このプラグインは、キットのコマンド `erkit` を呼ぶ**薄い層**です。動画を作る処理はすべて `erkit` が持ち、手順の正本はキットの `docs/guide/` です。ここには要点と、どのファイルを読むかだけを書きます。

## 始める前に（毎回）

1. **キットのフォルダか確かめる**: 作業のフォルダに `AGENTS.md` と `pyproject.toml`（`name = "explainer-reel-kit"`）があること。無ければ、キットのフォルダで Claude Code を開き直すよう人に伝えて止まる（キットの入れ方は `docs/guide/00-setup.md`）
2. **erkit の呼び方**: 仮想環境の中の erkit を使う。Windows は `.venv/Scripts/erkit`、それ以外は `.venv/bin/erkit`（以下の `erkit` はこれに読み替える）。無ければ `install.ps1` を案内して止まる
3. **版を確かめる**: `erkit --version` を実行する。このプラグインの版は **0.1.0**。違えば「キットとプラグインの版が違う（キット X、プラグイン 0.1.0）。`git pull` と `/plugin marketplace update explainer-reel-kit` でそろえる」と知らせる（止まらなくてよい）
4. **`AGENTS.md` を読む**。ここに書いた約束より、`AGENTS.md` と `docs/guide/` が正

## 最初に区分を決める（資料を読む前に）

人に、この動画の材料に社外秘（所属先の外に出せない情報）が含まれるかを聞く。

- `general`（公開済みの情報・一般的な知識だけ）→ 進める
- `confidential`（含む・**分からない**）→ **資料を受け取らずに止まる**。Claude Code はクラウドの AI で動くため。この PC の中で動く AI（LM Studio・Ollama など）に `prompts/` を貼って進めるよう伝える（`docs/guide/confidentiality.md`）
- 区分を `confidential` から `general` に変えるのは人だけ。こちらからは下げない・下げる提案をしない

## 段ごとの進め方

各段の前に、その段の手順書を Read で読む。段の終わりに結果を人に見せ、よいと言われてから次へ。

| 段 | 読む手順書 | すること | 使うスキル・コマンド |
|---|---|---|---|
| 0 準備 | `docs/guide/00-setup.md` | `erkit doctor` を読み、足りないものの入れ方を伝える（入れるのは人） | `/explainer-check` |
| 1 聞き取り | `docs/guide/01-intake.md` | 1〜3 個ずつ聞き、まとめて確かめる | — |
| 2 見る人 | `docs/guide/02-audience.md` | A・B・C を理由と一緒に提案 | — |
| 3 構成 | `docs/guide/03-outline.md` | シーンの表を見せる。**台本を書く前に** | — |
| 4 台本 | `docs/guide/04-storyboard.md` | 台本のフォルダを作り、台本を書き、`erkit check` を通す | `/explainer-new`、`storyboard` |
| 5 説明図・撮影 | `docs/guide/05-visuals.md` | 説明図の HTML、操作定義、確認画像 | `diagram`、`web-capture` |
| 6 確認 | `docs/guide/06-review.md` | `--dry-run`、試作、読みの確認 | `/explainer-make` |
| 7 書き出し | `docs/guide/07-export.md` | MP4。止まったら `--from` で続きから | `/explainer-make` |

見本は `samples/u-value/`（台本・説明図・操作定義・撮るページがそろっている）。

## 守ること

- 画面を捏造しない（撮った画面は `実キャプチャ`、説明図は `説明用再構成図`）。赤枠・矢印は座標ではなく mark の名前で指す
- 数値・事実は根拠付きで。分からないことは聞く
- キットの `src/` は変えない。MP4・WAV・.pptx・撮影画像を commit しない
- 動画の公開（アップロード）はしない
