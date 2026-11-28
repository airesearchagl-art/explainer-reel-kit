# サンプル題材: 窓の断熱性能（U 値）の見方

キットの一通りを見せるサンプルです。建築の一般的な知識と、キットの中の計算ページだけを使い、外のサイトに頼りません（`confidentiality: general`）。

| 何を見せるか | どこで |
|---|---|
| 説明図（HTML → PNG と注釈位置） | s01 熱の逃げ方（赤枠 3 つを順に）、s02 U 値の意味（赤枠 2 つ） |
| Web 画面の撮影（操作定義に従う） | s03 計算ページを開く、s04 ガラスの種類を選ぶ（赤枠 2 つ）、s05 結果を比べる（矢印） |
| この PC だけで配信して撮る | `--serve samples/u-value/app`（ネットワークなしで動く） |

## ファイル

| ファイル | 内容 |
|---|---|
| `u-value.storyboard.md` | 台本（intro・5 シーン・outro）。先頭のコメントに数値の扱い |
| `diagrams/s01_heat_paths.html`・`s02_u_value.html` | 説明図。共通の CSS（`../../_shared/diagram.css`）と `data-mark` |
| `app/index.html` | 計算ページ（素の HTML と JavaScript だけ。外の URL を読まない）。撮影の既定の画面（1600×660）に 1 画面で収まる並び。撮るための `data-testid` |
| `u-value.actions.yaml` | 操作定義（s03〜s05 の操作と注釈の部品） |
| `SOURCES.md` | 使った数値と根拠 |
| `scenes/u-value/scenes.yaml` | コード描画（interactive）の場面の指定。s01・s02 は説明図の中身を部品（カード・表・囲み）で描き、outro は確かめることの一覧。撮影の場面（s03〜s05）と intro は既定の場面（撮影画像をそのまま・見出しと文のカード） |

## 作り方の順番

```bash
erkit check   samples/u-value/u-value.storyboard.md                         # 1. 台本の検証
erkit diagram samples/u-value/u-value.storyboard.md --out output/u-value    # 2. 説明図（s01・s02）
erkit capture samples/u-value/u-value.storyboard.md --serve samples/u-value/app --out output/u-value
                                                                            # 3. 計算ページを撮る（s03〜s05）
erkit deck    samples/u-value/u-value.storyboard.md --assets-root output/u-value \
              --out output/u-value/u_value.pptx --overlay output/u-value/check.png
                                                                            # 4. スライド（--overlay で赤枠・矢印の位置を確かめる）
```

ナレーション（`erkit voice synth`）の `durations.json` を `erkit deck --durations` に渡すと、スライドの秒数が声の長さに合います。
MP4 への書き出しは Windows と PowerPoint で行います（書き出しの段）。

PowerPoint の無い PC（Linux・PowerPoint の入っていない Windows）では、コード描画で MP4 まで作れます（字幕の焼き込み・SRT・検証つき）:

```bash
erkit make samples/u-value/u-value.storyboard.md --serve samples/u-value/app --render-mode interactive
```

台本の版は kit-1.0.0 のまま（映像の作り方はコマンドで決める）。場面の指定は `scenes/u-value/scenes.yaml` で、合成の前に確かめます。

自分の題材を作るときは、このフォルダを写して、台本 → 説明図の HTML → 撮るページと操作定義（`erkit record` でも作れる）の順に置き換えます。
