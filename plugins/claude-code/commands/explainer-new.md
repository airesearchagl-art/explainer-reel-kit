---
description: 説明動画の台本のフォルダを作る（区分を確かめてから、種別に合ったひな形を reels/ に置く。解説なら解説のひな形）
argument-hint: "[題材の id（英小文字・数字・-・_）]"
disable-model-invocation: true
---

# /explainer-reel-kit:explainer-new — 台本のフォルダを作る

題材の id: $ARGUMENTS

## 1. 始める前に

`make-explainer` スキルの「始める前に」と同じ確かめをする: キットのフォルダか（`AGENTS.md` と `pyproject.toml` がある）、erkit の呼び方（`.venv/Scripts/erkit` か `.venv/bin/erkit`）、`erkit --version` がこのプラグインの版 **0.2.1** と同じか。

## 2. 区分を聞く（何よりも先に）

人に聞く: 「この動画の材料に、社外秘（所属先の外に出せない情報）は含まれますか。含まない＝general、含む・分からない＝confidential」

- `confidential`・分からない → **ここで止まる**。資料を受け取らない。「Claude Code はクラウドの AI で動くので、社外秘の材料はこの PC の中で動く AI（LM Studio・Ollama など）で進めてください。手順は `docs/guide/confidentiality.md`、貼る指示文は `prompts/`」と伝える
- `general` → 次へ。区分を下げる提案はしない
- 答えのひな形（`docs/guide/batch.md`）がこの会話に貼られていれば、その「区分」の行を答えとする（ほかの欄・資料より先に読む）。書いていない・`confidential`・分からないなら、上と同じくここで止まる

## 3. id と種別を決める

- id が空なら聞く。英小文字・数字・`-`・`_` だけ（例 `glass-choice`）。`reels/` に同じ名前のフォルダがあれば、上書きせずに別の id を聞く
- 種別を聞く（`docs/guide/01-intake.md` の「種別の見分け方」で見分けて確かめる）: `tool_intro`（ツールや考え方の紹介）/ `work_manual`（作業の手順）/ `explainer`（一般の解説。身近なことの「なぜ」と「どう選ぶ・減らす」。ツールの操作は出てこない）

## 4. フォルダとひな形を作る

`docs/guide/04-storyboard.md` の「自分の題材のフォルダを作る」と同じ置き方にする（PowerShell の代わりに Bash で）。

1. `reels/_shared/` が無ければ `samples/_shared/` を写す（説明図の共通の CSS）
2. `reels/` の下に題材の id のフォルダと、その中の `diagrams/` を作る
3. 種別に合ったひな形を、そのフォルダの「id ＋ `.storyboard.md`」に写す
   - `tool_intro`・`work_manual` → `src/explainer_reel_kit/data/templates/storyboard.md`
   - `explainer` → `src/explainer_reel_kit/data/templates/explainer.storyboard.md`（シーンの並び・部品・出典の一覧の置き場が書いてある）
4. 写した台本の先頭（reel）を書き換える: `id` ＝ 題材の id、`output_name` ＝ id の `-` を `_` にしたもの、`confidentiality: general`（人が決めた値）、`title` は仮のままでよい。`tool_intro`・`work_manual` なら `kind` ＝ 決めた種別。`explainer` のひな形は `kind: explainer`・`schema_version: kit-1.1.0` のまま変えない
5. 検証する（パスは作った台本に変える）:

```bash
erkit check samples/u-value/u-value.storyboard.md
```

`tool_intro`・`work_manual` のひな形のままなら「シーン数 2（推奨 5〜8）」の警告が出るのは正しい。`explainer` のひな形は 7 シーンあるので警告は出ない（中身はまだ仮）。`NG` なら書き換えを見直す。

`explainer` なら、説明図は台本のシーンのコメントにある部品の見本（`samples/_parts/`）をシーンの段で写す（`diagram` スキル。CSS の参照を `../../_shared/diagram.css` に直す）。出典の一覧 `SOURCES.md` も台本の隣に置く（`storyboard` スキル）。

## 5. 次へ

**まとめて進めるとき**（人が答えのひな形を埋めて渡した・「まとめて」と頼んだ）: 区分は 2 で聞いたとおり（ひな形の区分の行が general でなければ止まる。2 と食い違えば、確かな方＝`confidential` として止まる）。id・種別はひな形の値を使い、3 で聞き直さない。フォルダを作ったら `make-explainer` スキルの「進め方を選ぶ」の**まとめて**の手順（`docs/guide/batch.md`）で、台本・説明図・`erkit check`（`--strict` 付き）・`erkit diagram`・`erkit make` の `--dry-run` まで進み、報告で止まる。MP4 は作らない。

**段ごとのとき**:

作ったファイルを人に伝え、`make-explainer` スキルの段 1（聞き取り、`docs/guide/01-intake.md`）から進める。台本の中身は構成の表を人が確かめてから `storyboard` スキルで書く。

`reels/` は利用者の作業のフォルダ。キットのリポジトリに commit しない。
