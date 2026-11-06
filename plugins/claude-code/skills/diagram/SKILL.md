---
name: diagram
description: 説明動画の説明図を HTML で書き、erkit diagram で PNG と注釈位置（mark）にする。共通の CSS・data-mark・外の URL を読まない決まりを守り、確認画像で赤枠の位置を人に確かめる。台本の image.source が generated で capture.tool が html のシーンに使う。
---

# 説明図（HTML）を書く

手順の正本は `docs/guide/05-visuals.md` の「説明図（HTML）」、仕様は `docs/design/diagram.md`。書く前に Read で読む。
手本は `samples/u-value/diagrams/s01_heat_paths.html`、共通の CSS は `samples/_shared/diagram.css`（クラスの一覧は `prompts/04-diagram-html.md`）。

## 要点

- 1 シーン 1 ファイル。台本の `capture.src` のパスに書く
- 共通の CSS を HTML のファイルからの相対パスで読む（`reels/<id>/diagrams/` なら `../../_shared/diagram.css`。`/explainer-reel-kit:explainer-new` が `reels/_shared` を写してある）
- 大きさは CSS が決める（2420×1000 px）。文字は 32px 未満にしない
- 指したい要素に `data-mark="名前"`。台本の `recipe_params` の mark と同じ名前、1 つの図で 1 回だけ
- **外の URL を読まない**（Web フォント・CDN・外の画像・fetch）。読むとそのシーンは失敗する
- 赤は使わない（注釈とぶつかる）。実際の画面のふりをしない（`説明用再構成図`）

## 描いて確かめる

```bash
erkit diagram samples/u-value/u-value.storyboard.md --out output/u-value --overlay output/u-value/check-diagram.png
```

（自分の台本のパスと出力先に変える。Chromium が無ければ `--channel msedge` を付ける）

- 終了コード 1 → 失敗したシーンの理由が表示と `diagram-result.json` に出る。外の URL・mark が見つからない・小さすぎる、を直してもう一度
- 終了コード 0 → **確認画像（`--overlay` の PNG）を人に見せ**、赤枠が指したい部品に重なっているか確かめてもらう。ずれていれば `data-mark` を付ける要素を変える（座標は書かない）
