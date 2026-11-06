# 注釈位置（marks）の仕様 — `explainer-reel/marks@1`

赤枠・矢印の位置は**撮るとき・描くときに測ります**。台本には座標を書かず、部品の**名前（mark 名）**だけを書きます。

| 段 | 名前と部品の対応を書く場所 | 測り方 |
|---|---|---|
| 説明図（`erkit diagram`） | HTML の `data-mark="名前"` | ブラウザで描いた要素の位置 |
| Web 撮影（`erkit capture`） | 操作定義の `marks:`（名前 → セレクタ） | 撮影の直前の要素の位置 |

## ファイル

画像の隣に `<画像のファイル名から拡張子を除いたもの>.marks.json`（例 `s01_page.png` → `s01_page.marks.json`）。

```json
{
  "format": "explainer-reel/marks@1",
  "scene": "s01",
  "source": "generated",
  "image": "s01_page.png",
  "image_size": {"w": 2420, "h": 1000},
  "captured_at": "2026-11-06T10:00:00+09:00",
  "marks": {
    "input_card": {
      "box": {"x": 0.05, "y": 0.1, "w": 0.2, "h": 0.3},
      "px":  {"x": 121, "y": 100, "w": 484, "h": 300},
      "how": "data-mark: <div>"
    }
  }
}
```

- `source`: `generated`（説明図）/ `web`（Web 撮影）
- `box` は**画像に対する 0〜1 の相対座標**（左上が原点）。`px` は画像のピクセル。両方書く
- 点を指すときも `box`（小さな枠）
- 撮り直し・描き直しのたびに上書き（前回のファイルは先に消す）。形式の検査は `explainer_reel_kit.marks.load()`

## 測るときの検証（撮影・説明図の責任）

次のどれかに当たった mark は**記録せず、そのシーンを失敗**にして、理由を結果の JSON に残します。

- 見つからない・非表示
- 幅か高さが 8px 未満
- 面積の 95% 未満しか画像の中にない（95% 以上なら、はみ出した分を画像の範囲に切り詰めて記録する）
- 台本の `recipe_params` が参照する名前が、HTML・操作定義にない
- 名前が英小文字・数字・`_` でない、同じ図に同じ名前が 2 つ（説明図）

**位置が分からないまま既定の位置で出さない**のが原則です。

## 台本での書き方（recipe_params）

| recipe | 書き方 | 動き（スライドの段） |
|---|---|---|
| `highlight_box` | `mark: 名前` または `mark: [名前, 名前, …]`、任意で `pad`（画像幅に対する比） | 枠を mark の位置に出す。複数なら前の枠を消して次の枠を順に（ナレーションの段落ごと） |
| `arrow_move` | `to: {mark: 名前}`、任意で `from_side: left / right / top / bottom`、`from: {x, y}` | 矢印の先端が mark の枠の外側の辺に触れる位置で止まる |

台本のシーンから枠を引くのは `explainer_reel_kit.marks.resolve_refs(scene, marks_doc)`（名前 → `box`、見つからない名前）。
