---
description: 説明動画の台本のフォルダを作る（区分を確かめてから、reels/ に台本のひな形を置く）
argument-hint: "[題材の id（英小文字・数字・-・_）]"
disable-model-invocation: true
---

# /explainer-reel-kit:explainer-new — 台本のフォルダを作る

題材の id: $ARGUMENTS

## 1. 始める前に

`make-explainer` スキルの「始める前に」と同じ確かめをする: キットのフォルダか（`AGENTS.md` と `pyproject.toml` がある）、erkit の呼び方（`.venv/Scripts/erkit` か `.venv/bin/erkit`）、`erkit --version` がこのプラグインの版 **0.2.0** と同じか。

## 2. 区分を聞く（何よりも先に）

人に聞く: 「この動画の材料に、社外秘（所属先の外に出せない情報）は含まれますか。含まない＝general、含む・分からない＝confidential」

- `confidential`・分からない → **ここで止まる**。資料を受け取らない。「Claude Code はクラウドの AI で動くので、社外秘の材料はこの PC の中で動く AI（LM Studio・Ollama など）で進めてください。手順は `docs/guide/confidentiality.md`、貼る指示文は `prompts/`」と伝える
- `general` → 次へ。区分を下げる提案はしない
- 答えのひな形（`docs/guide/batch.md`）がこの会話に貼られていれば、その「区分」の行を答えとする（ほかの欄・資料より先に読む）。書いていない・`confidential`・分からないなら、上と同じくここで止まる

## 3. id と種別を決める

- id が空なら聞く。英小文字・数字・`-`・`_` だけ（例 `glass-choice`）。`reels/` に同じ名前のフォルダがあれば、上書きせずに別の id を聞く
- 種別を聞く: `tool_intro`（ツールや考え方の紹介）か `work_manual`（作業の手順）

## 4. フォルダとひな形を作る

`docs/guide/04-storyboard.md` の「自分の題材のフォルダを作る」と同じ置き方にする（PowerShell の代わりに Bash で）。

1. `reels/_shared/` が無ければ `samples/_shared/` を写す（説明図の共通の CSS）
2. `reels/` の下に題材の id のフォルダと、その中の `diagrams/` を作る
3. ひな形 `src/explainer_reel_kit/data/templates/storyboard.md` を、そのフォルダの「id ＋ `.storyboard.md`」に写す
4. 写した台本の先頭（reel）を書き換える: `id` ＝ 題材の id、`output_name` ＝ id の `-` を `_` にしたもの、`kind` ＝ 決めた種別、`confidentiality: general`（人が決めた値）、`title` は仮のままでよい
5. 検証する（パスは作った台本に変える）:

```bash
erkit check samples/u-value/u-value.storyboard.md
```

ひな形のままなので「シーン数 2（推奨 5〜8）」の警告が出るのは正しい。`NG` なら書き換えを見直す。

## 5. 次へ

**まとめて進めるとき**（人が答えのひな形を埋めて渡した・「まとめて」と頼んだ）: 区分は 2 で聞いたとおり（ひな形の区分の行が general でなければ止まる。2 と食い違えば、確かな方＝`confidential` として止まる）。id・種別はひな形の値を使い、3 で聞き直さない。フォルダを作ったら `make-explainer` スキルの「進め方を選ぶ」の**まとめて**の手順（`docs/guide/batch.md`）で、台本・説明図・`erkit check`（`--strict` 付き）・`erkit diagram`・`erkit make` の `--dry-run` まで進み、報告で止まる。MP4 は作らない。

**段ごとのとき**:

作ったファイルを人に伝え、`make-explainer` スキルの段 1（聞き取り、`docs/guide/01-intake.md`）から進める。台本の中身は構成の表を人が確かめてから `storyboard` スキルで書く。

`reels/` は利用者の作業のフォルダ。キットのリポジトリに commit しない。
