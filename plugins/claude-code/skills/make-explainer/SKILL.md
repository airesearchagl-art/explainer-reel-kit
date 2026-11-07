---
name: make-explainer
description: 題材から説明動画（ナレーション付きの MP4）を作る全体の進め方。聞き取り → 見る人 → 構成 → 台本 → 説明図・撮影 → 確認 → 書き出しを、キット（explainer-reel-kit）の手順書の順に、段ごとに人に確かめながら進める。「説明動画を作りたい」「解説動画」「しくみの解説」「ツールの紹介動画」「作業手順の動画」と言われたときに使う。種別（ツールの紹介・作業の手順・一般の解説）を見分けて、解説なら解説の型で進める。
---

# 説明動画を作る（全体の進め方）

このプラグインは、キットのコマンド `erkit` を呼ぶ**薄い層**です。動画を作る処理はすべて `erkit` が持ち、手順の正本はキットの `docs/guide/` です。ここには要点と、どのファイルを読むかだけを書きます。

## 始める前に（毎回）

1. **キットのフォルダか確かめる**: 作業のフォルダに `AGENTS.md` と `pyproject.toml`（`name = "explainer-reel-kit"`）があること。無ければ、キットのフォルダで Claude Code を開き直すよう人に伝えて止まる（キットの入れ方は `docs/guide/00-setup.md`）
2. **erkit の呼び方**: 仮想環境の中の erkit を使う。Windows は `.venv/Scripts/erkit`、それ以外は `.venv/bin/erkit`（以下の `erkit` はこれに読み替える）。無ければ `install.ps1` を案内して止まる
3. **版を確かめる**: `erkit --version` を実行する。このプラグインの版は **0.2.1**。違えば「キットとプラグインの版が違う（キット X、プラグイン 0.2.1）。`git pull` と `/plugin marketplace update explainer-reel-kit` でそろえる」と知らせる（止まらなくてよい）
4. **`AGENTS.md` を読む**。ここに書いた約束より、`AGENTS.md` と `docs/guide/` が正

## 最初に区分を決める（資料を読む前に）

人に、この動画の材料に社外秘（所属先の外に出せない情報）が含まれるかを聞く。

- `general`（公開済みの情報・一般的な知識だけ）→ 進める
- `confidential`（含む・**分からない**）→ **資料を受け取らずに止まる**。Claude Code はクラウドの AI で動くため。この PC の中で動く AI（LM Studio・Ollama など）に `prompts/` を貼って進めるよう伝える（`docs/guide/confidentiality.md`）
- 区分を `confidential` から `general` に変えるのは人だけ。こちらからは下げない・下げる提案をしない

## 種別を見分ける（ツールの紹介 / 作業の手順 / 解説）

区分が決まったら、`docs/guide/01-intake.md` の「種別の見分け方」で種別を決め、人に確かめる（まとめて進めるときは、ひな形の種別の欄を使う）。

| 種別 | 見分け方 | ひな形 | 説明図 |
|---|---|---|---|
| `tool_intro` / `work_manual` | 画面の操作が中心 | `src/explainer_reel_kit/data/templates/storyboard.md` | 自由に描く（`diagram` スキル）＋撮影（`web-capture`） |
| `explainer` | 身近なことの「なぜ」と「どう選ぶ・減らす」。ツールの操作は出てこない | `src/explainer_reel_kit/data/templates/explainer.storyboard.md` | 部品 7 種（`samples/_parts/`）を写して書き換える。撮影なし |

**解説（`explainer`）のとき**:

- 構成の決まり（`docs/guide/03-outline.md` の「解説（explainer）の構成の決まり」）: 問い → しくみ → 比べる・条件 → 選び方・減らし方 → まとめ。本編 5〜7 シーン。順番は入れ替えない
- 台本は解説のひな形から（`/explainer-reel-kit:explainer-new` が種別に合わせて選ぶ）。`SOURCES.md` を台本の隣に一緒に書く（`docs/guide/04-storyboard.md` の「出典の一覧」）
- 説明図は `docs/guide/05-visuals.md` の「解説の部品の選び方」で部品を選ぶ（`diagram` スキル）
- 見本は `samples/window-condensation/`（台本・部品で描いた説明図・SOURCES.md）
- 区分の約束と、MP4 の前に人が確かめる約束は、種別によらず同じ

## 進め方を選ぶ（段ごと / まとめて）

- **まとめて**: 人が「答えのひな形」（`docs/guide/batch.md`）を埋めて渡した、または「まとめて進めて」と頼んだとき。`docs/guide/batch.md` を Read で読み、その手順で進める
  1. **区分の行を最初に読む**。書いていない・`confidential`・分からない、のどれかなら、ほかの欄も資料も読まずに**止まる**（上の「最初に区分を決める」と同じ。まとめて進めるときも変えない）
  2. 進められない欄（何を説明するか・資料）が空なら、足りない欄だけをまとめて 1 回聞く。ほかの空欄は決めて報告に書く
  3. 段 1〜3 の人への確認を省き、台本（`storyboard` スキル。出典の決まりを守る）・説明図（`diagram`）・撮影があれば操作定義（`web-capture`）を書く。種別が `explainer` なら、解説のひな形・部品・`SOURCES.md` で（上の「種別を見分ける」）
  4. `erkit check`（`--strict` 付き） → `erkit diagram`（`--overlay` 付き）→ 撮影があれば `erkit capture` の `--check` → `erkit make` の `--dry-run` まで通す。失敗したら直してもう一度
  5. **そこで止まり**、`docs/guide/batch.md` の「報告の形」で返す（構成の表・決めたこと・根拠が弱い/未確認の数値と事実・確認画像・次に人が打つコマンド）
  6. **MP4（`erkit make`）は実行しない**。人が報告と確認画像を見てよいと言ってから `/explainer-reel-kit:explainer-make` で（人の確認を省かない）
- **段ごと**: それ以外。下の表の順に、段ごとに人に確かめる

## 段ごとの進め方

各段の前に、その段の手順書を Read で読む。段の終わりに結果を人に見せ、よいと言われてから次へ。

| 段 | 読む手順書 | すること | 使うスキル・コマンド |
|---|---|---|---|
| 0 準備 | `docs/guide/00-setup.md` | `erkit doctor` を読み、足りないものの入れ方を伝える（入れるのは人） | `/explainer-reel-kit:explainer-check` |
| 1 聞き取り | `docs/guide/01-intake.md` | 1〜3 個ずつ聞き、まとめて確かめる | — |
| 2 見る人 | `docs/guide/02-audience.md` | A・B・C を理由と一緒に提案 | — |
| 3 構成 | `docs/guide/03-outline.md` | シーンの表を見せる。**台本を書く前に** | — |
| 4 台本 | `docs/guide/04-storyboard.md` | 台本のフォルダを作り、台本を書き、`erkit check` を通す | `/explainer-reel-kit:explainer-new`、`storyboard` |
| 5 説明図・撮影 | `docs/guide/05-visuals.md` | 説明図の HTML、操作定義、確認画像 | `diagram`、`web-capture` |
| 6 確認 | `docs/guide/06-review.md` | `--dry-run`、試作、読みの確認 | `/explainer-reel-kit:explainer-make` |
| 7 書き出し | `docs/guide/07-export.md` | MP4。止まったら `--from` で続きから | `/explainer-reel-kit:explainer-make` |

見本は `samples/u-value/`（台本・説明図・操作定義・撮るページがそろっている）。解説なら `samples/window-condensation/`。

## 守ること

- 画面を捏造しない（撮った画面は `実キャプチャ`、説明図は `説明用再構成図`）。赤枠・矢印は座標ではなく mark の名前で指す
- **対になるものの決まり**（`docs/guide/03-outline.md`）: 原因と対策、条件と減らし方、問題と解決のように対になるものは、同じ番号・同じ順で並べ、対策の側でも原因の番号で言う（「① の窓が冷えるには…」）。片方にしかないものを作らない。図の番号・色も対でそろえる
- 数値・事実は根拠付きで。規格の番号・出典・数値は、そのセッションで確かめたものだけを書き、確かめていないものは「未確認」として報告に挙げる（記憶で書かない）。分からないことは聞く
- キットの `src/` は変えない。MP4・WAV・.pptx・撮影画像を commit しない
- 動画の公開（アップロード）はしない
