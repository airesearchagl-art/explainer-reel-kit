# 解説の説明図の部品（見本）

一般の解説（台本の `kind: explainer`）で使う説明図の部品 7 種の見本です。1 部品 1 ファイルの HTML で、共通の CSS（[`../_shared/diagram.css`](../_shared/diagram.css)）の部品のクラスだけで描いています。
使い方と決まりは [docs/design/diagram.md の「解説の部品」](../../docs/design/diagram.md#解説の部品kind-explainer)。

| 部品 | 見本 | data-mark |
|---|---|---|
| 断面図（層の重なり） | [section.html](section.html) | `layer_glass_in` `layer_air` `layer_coat` |
| 比較表 | [compare.html](compare.html) | `row_single` `row_double` `row_coated` |
| 数値の範囲（帯と目安） | [range.html](range.html) | `band_single` `band_double` `band_coated` `target` |
| フロー（矢印の流れ） | [flow.html](flow.html) | `step_1` `step_2` `step_3` `step_4` |
| カード（2〜4 枚） | [cards.html](cards.html) | `card_1` `card_2` `card_3` |
| 条件の分岐 | [branch.html](branch.html) | `question` `leaf_cold` `leaf_sun` `leaf_both` |
| たとえ（身近なもの） | [analogy.html](analogy.html) | `everyday` `topic` `mapping` |

- 図の中の値・評価は**見本**です（説明のための例で、出典のある値ではない）。自分の台本では、確かめた値に書き換え、出典を `SOURCES.md` に書きます
- 写して使うときは、`<link>` の CSS のパスを、写した先から `samples/_shared/diagram.css` への相対パスに直します

## 全部品の一覧を作る

[`parts.storyboard.md`](parts.storyboard.md) は、7 つの見本を `erkit diagram` で描くための台本です（動画にするためのものではありません）。
キットのフォルダで、仮想環境を有効にしてから:

```bash
erkit diagram samples/_parts/parts.storyboard.md --out output/parts --overlay output/parts/parts-overview.png
```

| できるもの | 中身 |
|---|---|
| `output/parts/assets/<部品>.png` | 各部品の 2420×1000 の PNG |
| `output/parts/assets/<部品>.marks.json` | data-mark の位置 |
| `output/parts/parts-overview.png` | 全部品を 1 枚に並べ、mark の枠を描き込んだ一覧 |

PNG・marks.json は commit しません（`output/` は `.gitignore` に入っています）。
