---
name: web-capture
description: 説明動画の Web 画面を撮る。操作定義（台本の id の .actions.yaml）を書く・直す、記録モード（erkit record）を人に案内する、erkit capture で撮って確認画像（overlay）で赤枠を確かめる。台本の image.source が web のシーンに使う。
---

# Web 画面を撮る

手順の正本は `docs/guide/05-visuals.md` の「Web 画面の撮影」、仕様は `docs/design/capture-web.md`（mark は `docs/design/marks.md`）。書く前に Read で読む。
手本は `samples/u-value/u-value.actions.yaml` と、撮るページ `samples/u-value/app/`。

## 要点

- 台本の `capture.steps` は人が読む手順。機械が実行する操作と mark は操作定義に書く（ファイル名は `<台本の id>.actions.yaml`、`reel_id` も同じ id）
- セレクタは `data-testid` を優先。1 つに決まらなければページに `data-testid` を足すか、記録モードを使う
- 他の人が作ったページ・社外秘の画面は、AI に見せずに**記録モード**で作ってもらう（人がクリックする。F8 でシーンを区切る、Shift＋クリックで mark、F10 で終わる）
- 撮るのはこの PC で開けるページ。`--serve` でフォルダを配信して撮れる（ネットワーク不要）
- 社外秘の台本は、この PC の外の URL を撮らない（キットが止める）

## 突き合わせ・記録・撮影

```bash
erkit capture samples/u-value/u-value.storyboard.md --check
erkit record --url http://127.0.0.1:8000/index.html --serve samples/u-value/app --reel u-value --out output/u-value-recorded.actions.yaml
erkit capture samples/u-value/u-value.storyboard.md --serve samples/u-value/app --out output/u-value --overlay output/u-value/check-capture.png
```

（自分の台本・ページ・出力先に変える。`erkit record` はブラウザを開くので、人に操作してもらう）

- `--check` はブラウザを開かず、台本と操作定義が合っているかだけ。まずこれを通す
- 撮影の後、**確認画像を人に見せ**、赤枠・矢印が指したい部品に重なっているか、個人の情報（プロフィール名・通知）が映っていないかを確かめてもらう
- 失敗したら表示の理由（セレクタが見つからない・mark が見えない など）を読んで、操作定義の `wait_for` や セレクタを直す
