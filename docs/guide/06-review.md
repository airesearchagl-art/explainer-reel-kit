# 6. 確認（試作・スライド・読み）

MP4 にする前に、段の順番・スライドの見え方・ナレーションの読みを確かめます。

## 1. 段の順番を見る（何も作らない）

```powershell
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app --dry-run
```

出力先・声・段ごとの入力と出力が表示されます。社外秘の台本なら、この時点で「この PC の外へ出る設定」が無いかも確かめます（あれば終了コード 1 で止まります）。

## 2. 試作する

画像がまだそろっていなくても、灰色の枠と既定の位置で最後まで作れます。

```powershell
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app --allow-placeholders --label 試作
```

出力フォルダ（`<日付>_u-value_試作`）の中を見ます:

| 見るもの | 確かめること |
|---|---|
| `u_value.pptx`（PowerPoint で開く） | 動き（赤枠・矢印の順番）、文字の大きさ・はみ出し、見出し |
| `work\check\overlay.png` | 赤枠・矢印が、指したい部品に重なっているか。段落の順と枠の順が合っているか |
| `run.json` の `warnings` | 位置の決まらない注釈・足りない画像など |

## 3. 読みを確かめる

AivisSpeech を起動しておいてから:

```powershell
erkit voice kana samples\u-value\u-value.storyboard.md --sentences --out output\u-value\kana.md
```

- 読みが違う語は、読み辞書に書きます。建築の用語なら例の辞書があります: `erkit voice kana samples\u-value\u-value.storyboard.md --dictionary architecture`
- 自分の辞書は `dictionaries\<名前>.yaml` に置き、`config\kit.yaml` の `voice.dictionaries` に名前を書きます（書き方は [narration.md](../design/narration.md)）
- 読みで直せない語は、台本のナレーションを読みのとおりに書き換えます（「ユー値」「ローイー」など）
- 抑揚・間は、試作の MP4 を聞いて確かめます

## 4. 直す

| 気づいたこと | 直す場所 |
|---|---|
| 言い回し・順番 | 台本のナレーション・シーンの並び |
| 枠の位置・大きさ | 説明図の `data-mark` を付ける要素、操作定義の `marks`（座標は書かない） |
| 文字がはみ出す・小さい | 説明図の HTML、台本の `on_screen_text` を短く |
| 読み | 読み辞書か、ナレーションの書き方 |

直したら、もう一度 `erkit check` → 試作 の順で確かめます。

## AI に任せること

- `--dry-run` と試作の表示、`run.json` の `warnings` を読んで、直す場所を提案する
- `erkit voice kana` の結果から、読み辞書に足す語を提案する（足すかは人が決める）
- スライドと確認画像は人が見る（AI は画面を見られないことがある）

## 次へ

[07-export.md](07-export.md) で MP4 にします。
