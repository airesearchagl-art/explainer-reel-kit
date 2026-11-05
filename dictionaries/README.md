# dictionaries

ナレーションの読み辞書（分野ごと）を置きます。**既定では使いません**。台本の分野に合う辞書を、
`config/kit.yaml` の `voice.dictionaries` か `erkit voice synth … --dictionary <名前>` で選びます。

| 辞書 | 中身 |
|---|---|
| [architecture.yaml](architecture.yaml) | 建築用語の例（部位・納まり・建具など） |

自分の辞書は、このフォルダか、作業するフォルダの `dictionaries/` に `<名前>.yaml` で置きます。書き方は [docs/design/narration.md](../docs/design/narration.md)。
