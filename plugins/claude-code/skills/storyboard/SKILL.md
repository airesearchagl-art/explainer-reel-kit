---
name: storyboard
description: 説明動画の台本（*.storyboard.md）を書く・直す。構成の表から、キットの台本の仕様に合わせて reel・intro・シーン・outro を書き、erkit check が通るまで直す。台本・ナレーション原稿・erkit check のエラーを扱うときに使う。
---

# 台本を書く・直す

手順の正本は `docs/guide/04-storyboard.md`、仕様は `docs/design/storyboard.md`（レシピは `docs/design/recipes.md`、ナレーションは `docs/design/narration.md`）。書く前に Read で読む。
見本は `samples/u-value/u-value.storyboard.md`、ひな形は `src/explainer_reel_kit/data/templates/storyboard.md`。

## 前に確かめること

- 区分（`confidentiality`）が人と決まっていること。決まっていなければ、`make-explainer` スキルの「最初に区分を決める」から。`confidential` なら資料を受け取らずに止まる
- 構成の表を人がよいと言っていること（`docs/guide/03-outline.md`）
- 台本のフォルダが無ければ `/explainer-reel-kit:explainer-new` で作る

## 書くときの要点

- `confidentiality` は人が決めた値のまま。下げない
- 1 シーン＝1 スライド＝主画像 1 枚。本編 5〜8 シーン。見出しは行動で終える
- `image.source` と `image.label` と `capture` の組み合わせを仕様どおりに（説明図は `generated`＋`説明用再構成図`＋`tool: html`）
- 赤枠・矢印は `recipe_params` に mark の名前で。mark を並べた数とナレーションの段落の数をそろえる
- 読み間違いやすい英字・数字・単位・記号は読みで書く
- 数値の根拠は HTML コメントか別のファイルに

## 出典の決まり

`docs/guide/04-storyboard.md` の「出典の決まり」のとおり。

- **規格の番号・出典・数値は、そのセッションで確かめたものだけを書く。記憶で書かない**（覚えている規格の番号・年版・数値は、正しく見えても「未確認」）
- 確かめる＝渡された資料で見つけた、またはそのセッションで原典を開いて読んだ。確かめたら資料の名前と場所をコメントに書く
- 確かめていないものは `<!-- 未確認: … -->` と書き、最後の報告に一覧で挙げる。ナレーションでは番号を言わない・一般的に言う、などで逃がす

## 検証して直す

```bash
erkit check samples/u-value/u-value.storyboard.md
erkit check --strict samples/u-value/u-value.storyboard.md
```

（自分の台本のパスに変える。`erkit` は `.venv/Scripts/erkit` か `.venv/bin/erkit` に読み替える）

- 終了コード 0 で `OK` → 表示の「区分」が人の決めた値か確かめる。`警告:` があれば直すか、直さない理由を人に伝える
- 終了コード 1 で `NG` → 各行の `[schema]` `[recipe]` `[id]` `[image]` などを読んで直し、もう一度。**通るまで繰り返す**
- 終了コード 2 → パスか台本の書式（先頭の `---`、yaml ブロック）の誤り

通ったら、言い回しと数値の根拠を人に確かめてもらい、説明図・撮影（`diagram`・`web-capture` スキル）へ。
