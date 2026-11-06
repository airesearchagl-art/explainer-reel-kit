# 4. 説明図の HTML（チャットだけの AI に貼る）

台本が `erkit check` を通った後、同じ会話に下の枠の中を貼ります。1 回に 1 シーンずつ頼むと、直しやすくなります。
見本として `samples\u-value\diagrams\s01_heat_paths.html` の中身を後ろに貼ると、形がそろいます。

```text
台本の説明図のシーン（image.source: generated、capture.tool: html）の 1 つを、HTML で描いてください。

決まり:
  - 1 シーン 1 ファイル。<!doctype html> から始まる完全な HTML。<meta charset="utf-8"> と <html lang="ja">
  - 共通の CSS を読む: <link rel="stylesheet" href="../../_shared/diagram.css">
    （図の大きさ 2420×1000 px は CSS が決める。自分で body の大きさを変えない）
  - 外の URL を一切読まない: Web フォント、CDN、外の画像、fetch は使わない（ネットワークを止めて描くため、使うと失敗する）
  - 台本の recipe_params の mark の名前と同じ名前で、指したい要素に data-mark="名前" を付ける
    - 名前は英小文字・数字・_。1 つの図で同じ名前は 1 回だけ
    - 指す要素はカード 1 枚か、ひとかたまり（文字 1 つを指さない）。見えていて、図の中に収まること
  - 文字は 32px 未満にしない。カードは横に 2〜4 枚、縦に 2 段まで
  - 色は意味で使う: blue＝操作・入力、teal＝結果、amber＝注意、gray＝その他。赤は使わない（注釈の赤枠とぶつかる）
  - 実際の画面のふりをしない（これは説明用に描き直した図）
  - JavaScript は使ってよいが、図を組み立てる程度に。アニメーションは使わない

共通の CSS のクラス:
  .wrap            全体の枠（縦に並べて中央に寄せる）
  .row / .row.tight  カードを横に並べる（幅の比は style="flex:1.2" など）
  .card            白いカード。.center（中央寄せ）.accent（強調）.warn（注意）
  .tag.blue / .tag.teal / .tag.amber / .tag.gray   カードの種類のラベル
  .t / .t.sm       カードの見出し（62px / 50px）
  .s / .s.sm       本文（46px / 36px）
  .arrow           カードの間の流れ（→ の文字）
  .code / .hl      コード・ファイルの並び / その中の強調
  .term            端末の画面の説明図

出力: HTML だけを 1 つのコードブロックで。後ろに、付けた data-mark の名前の一覧を書いてください。

この後、私が図を描くコマンドを実行します。失敗の理由や、確認画像で枠がずれていると伝えたら、直した HTML の全体をもう一度出してください。

描くシーン:
```

枠の最後の「描くシーン:」の後に、台本のそのシーン（`## s01: …` から次の見出しの前まで）を貼ります。

## 人がすること

1. HTML を台本の `capture.src` のパス（例 `reels\<id>\diagrams\s01_….html`）に UTF-8 で保存する
2. 描いて確認画像を見る（例はサンプルのパス。自分の台本のパスに変える）

```powershell
erkit diagram samples\u-value\u-value.storyboard.md --out output\u-value --overlay output\u-value\check-diagram.png
if ($LASTEXITCODE -eq 0) { Invoke-Item output\u-value\check-diagram.png }
```

3. 失敗したら、表示と `output\u-value\diagram-result.json` の理由を AI に貼る。枠がずれていたら、どの枠がどうずれているかを言葉で伝える

撮影のシーンの操作定義は、記録モード（`erkit record`）で作るのがかんたんです（[05-visuals.md](../docs/guide/05-visuals.md)）。
