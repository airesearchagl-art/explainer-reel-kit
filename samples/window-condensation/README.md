# サンプル題材: 冬の窓の結露のしくみと減らし方（解説）

一般の解説（台本の `kind: explainer`）のサンプルです。全シーンを説明図の部品で描き、撮影はありません（`confidentiality: general`）。
解説の型の決まりは [docs/guide/03-outline.md](../../docs/guide/03-outline.md)（構成）と [docs/guide/05-visuals.md](../../docs/guide/05-visuals.md)（部品の選び方）にあります。

| シーン | 構成の段 | 部品（見本） | 注釈 |
|---|---|---|---|
| s01 身近な場面で考える | 問い | たとえ（`analogy.html`） | 身近なもの → 本題 |
| s02 水滴ができる順にたどる | しくみ | フロー（`flow.html`） | 4 段を順に |
| s03 結露の二つの条件を知る | 条件 | カード（`cards.html`） | 3 枚を順に |
| s04 暖房の種類を比べる | 比べる | 比較表（`compare.html`） | 2 行を順に |
| s05 結露を減らす | 減らし方 | カード（`cards.html`） | 3 枚を順に |

## ファイル

| ファイル | 内容 |
|---|---|
| `window-condensation.storyboard.md` | 台本（intro・5 シーン・outro）。解説のひな形から作った |
| `diagrams/s01_question.html` 〜 `s05_reduce.html` | 説明図。[部品の見本](../_parts/README.md)を写して書き換え、共通の CSS（`../../_shared/diagram.css`）を読む |
| `SOURCES.md` | 使った数値・事実と根拠（資料名・URL・確かめた日）。確かめた資料に無い数値（ガラスの種類ごとの性能など）は使っていない |

## 作り方の順番

キットのフォルダで、仮想環境を有効にしてから:

```bash
erkit check --strict samples/window-condensation/window-condensation.storyboard.md
erkit diagram samples/window-condensation/window-condensation.storyboard.md --out output/window-condensation --overlay output/window-condensation/check-diagram.png
erkit make samples/window-condensation/window-condensation.storyboard.md --dry-run
erkit make samples/window-condensation/window-condensation.storyboard.md
```

撮影のシーンが無いので `--serve` は要りません。最後の `erkit make` は MP4 まで作ります（Windows ＋ PowerPoint、AivisSpeech を起動しておく）。
