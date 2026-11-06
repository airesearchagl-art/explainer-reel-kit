# Web 画面の撮影（erkit capture / erkit record）

台本の `image.source: web` のシーンを、Playwright でブラウザを操作して撮影します。手で画面を切り取りません。

```text
台本（capture.url / viewport / steps）  ── 人が読む手順
        ＋
操作定義 <reel id>.actions.yaml          ── 機械が実行する操作（セレクタ）と、指したい部品（marks）
        ↓  erkit capture <台本>
<保存先>/<image.ref>.png ＋ <画像名>.marks.json（注釈位置）＋ <保存先>/capture-web-result.json
```

`capture.steps` は人向けの説明のまま残し、実際の操作は操作定義に書きます。操作定義は台本と同じフォルダの
`<reel id>.actions.yaml` が既定です（`--actions` で変更）。

## 撮る

```bash
erkit capture examples/hello-kit.storyboard.md --check          # 操作定義と台本の突き合わせだけ（ブラウザ不要）
erkit capture examples/hello-kit.storyboard.md --serve examples/hello-page --out OUT --overlay OUT/check.png
```

| オプション | 内容 |
|---|---|
| `--out <保存先>` | 画像は `<保存先>/<image.ref>`。省略時は `<撮影素材のルート>/web/<ツール名>` |
| `--captures-root` / `--tool` | 撮影素材のルート（既定: 環境変数 `ERKIT_CAPTURES_ROOT`、無ければホームの `ExplainerReelKit/captures`）、フォルダ名（既定は reel id） |
| `--serve <フォルダ>` | そのフォルダをこの PC だけで配信して撮る（127.0.0.1、空いている番号）。台本の `http://localhost:<番号>/…` と `http://127.0.0.1:<番号>/…` の先頭が配信先に置き換わる |
| `--url-map 旧=新` | URL の先頭を置き換える（手元で起動した版を撮るとき）。`file:///…/` にもできる |
| `--only s03 s05` | 指定したシーンだけ撮る。状態を作るため、直前の `reset: true` のシーンから操作だけ再現する |
| `--overlay <png>` | 注釈位置を描き込んだ確認画像（枠が指したい部品に重なっているかを目で確かめる） |
| `--channel msedge` / `--executable <path>` | インストール済みのブラウザを使う |
| `--headed` | 画面を表示して動きを見ながら実行 |

- 撮った画像は日付を付けず、撮り直したら上書きします。リポジトリには入れません
- **社外秘（confidential）の台本は、この PC の中の URL（`file://`・`localhost`・`127.0.0.1`）しか撮りません**。`--url-map`・`--serve` で置き換えた後の URL で確かめ、外の URL があればブラウザを開く前に止めます
- 終了コード: 0 すべて撮れた / 1 失敗したシーンがある・`--check` が不合格 / 2 台本・操作定義の不備で始められない

### シーン間の状態

- 台本の順に、同じページで操作を続けます。`reset: true` のシーンだけ開き直します
- `capture.viewport` を書いていないシーンは、直前のシーンの viewport を引き継ぎます。違う viewport を書いたシーンは開き直しになります（結果の `notes` に記録）
- 失敗したシーンは理由を記録して次へ進みます。直後のシーンには「状態が想定と違う可能性」の注記が付きます

### 結果（capture-web-result.json）

`ok` / `failed` の件数と、シーンごとの `status`（ok / failed / prepared＝`--only` で操作だけ再現）・`path`・`width`/`height`・`url`・`marks_path`・`marks`・`elapsed_sec`、失敗時は `error`。

## 画面の大きさ — 動画で文字が読めるように

スライドの画像枠は 12.333in × 5.1in（≒ 2.42:1）です。画像は縦横比を保って枠に収めるので、
**撮影の画面を枠と同じ縦横比にする**と左右の余白が出ず、画面がいちばん大きく映ります。

| 撮影の画面（CSS px） | 画像 | 動画（横 1920px）での画像の幅 | 1 CSS px の見え方 | 本文 22px の文字 |
|---|---|---|---|---|
| 1920×1080（16:9。以前の既定） | 1920×1080 | 約 1306px（左右に余白） | 約 0.68px | 約 15px（読めない） |
| **1600×660（既定、≈2.42:1）×1.5 倍** | 2400×990 | 約 1776px（枠いっぱい） | 約 1.1px | 約 24px（読める） |

- 既定は **1600×660、device_scale_factor 1.5**（画像 2400×990）。操作定義の `defaults` と台本の `capture.viewport` で変えられます。`erkit record` の `--viewport` の既定も同じ
- 幅 1600 は、動画で文字が縮まない大きさ（1 CSS px ≒ 1.1px）で、多くのページが狭い画面向けの並びに切り替わらない幅です。1.5 倍で撮るので、縮んでもにじみません
- 高さが 660 しかないので、**撮るページは 1 画面に収まる並びにする**（自分のツールなら、余白を詰め、文字は 18px 以上）。収まらないときは `scroll_to` で見せたい所まで動かすか、`shot: {type: element}` で部分を撮る
- 1920×1080 などで撮った画面（以前の撮影・作り直せないページ）や、小さな部品を見せるときは、台本で **拡大（`zoom`）** を使います（次の節）

### Web の画面は拡大して見せる（zoom）

台本の `recipe_params` に `zoom: true`（注釈のまわりを拡大）か、`highlight_box` で枠が 2 つ以上なら `zoom: per_mark`（枠ごとに拡大して Morph でつなぐ）を書きます（[recipes.md](recipes.md#拡大zoom)）。

```yaml
recipe: arrow_move
recipe_params:
  to: {mark: result_area}
  zoom: true
```

- 既定の 1600×660 で撮った画面は、そのままで読めます。拡大は、細かい部品に目を向けさせたいときに使う
- 1920×1080 で撮った画面は、注釈のあるシーンに `zoom` を付けると読める大きさになります
- 矢印は画像の外からは出ません（出発点は画像の端で止まる）。部品が画像の端にあるときは、`from_side` を部品の内側の向き（右端の部品なら `left`）にするか、`from: {x, y}` で出発点を書く

## 記録モード（erkit record）— 操作定義を人の操作で作る

新しいツールの操作定義とセレクタを、AI に頼らず、画面をクリックして作る。記録はこの PC の中だけで行われる（AI には送らない）。

```bash
erkit record --url http://localhost:8000/ --serve examples/hello-page --reel hello-kit --out my.actions.yaml
# --serve: そのフォルダをこの PC で配信して記録（URL の先頭が置き換わる）。ローカルのファイルなら --url file:///…/index.html でもよい。Chromium を入れていない場合は --channel msedge
# 2 本目以降のシーン番号から始めるなら --start 7
```

開いたブラウザ（画面あり）で、撮りたい画面まで操作する。

| 操作 | 記録されるもの |
|---|---|
| クリック | `click`（ボタン・リンク・タブなど） |
| 入力して Enter、またはフォーカスを外す | `fill`（`commit: enter` / `blur`）。同じ欄に続けて入力したら最後の値だけ |
| `<select>` で選ぶ | `select` |
| **F8** | ここまでを 1 シーンとして区切る（`s01`, `s02`, …）。その時点のスクロール位置を `scroll` に入れ、画面全体を撮影する指定（`shot: viewport`）にする |
| **Shift＋クリック** | その部品を mark（赤枠・矢印の位置）にする。名前（英小文字・数字・_）を入力。**名前の後に `^` を付けると 1 つ上の要素**（`^^` で 2 つ上。小さな文字ではなくカード全体を囲みたいとき） |
| **F10**、またはウィンドウを閉じる | 記録を終える（最後に F8 で区切っていない操作は捨てる） |

- 最初のシーンには `reset: true` と `wait_load` が自動で入る
- セレクタの優先順: `data-testid` → role＋名前（`role=button[name="…"]`）→ テキスト（`text="…"`。文字だけを持つ要素）→ テキストを手がかりにした祖先（`text="…" >> xpath=ancestor::*[2]`。カードなどのコンテナ）→ CSS（最後の手段）。その時点で 1 つの要素に決まる最初の候補を使う
- 警告（シーンの `note` と、ファイル先頭のコメント）: 1 つに決まらない、CSS を使った、位置（`nth-of-type`）や自動生成らしい class に頼っている
- 記録の後、新しいページで操作を再生して確かめる（各セレクタが 1 件に決まるか、mark が撮影する画面の中にあるか）。問題があれば表示して終了コード 1（`--no-verify` で省略）
- 出力は既存の操作定義と同じ形式で、**新しいファイルにだけ書く**（既存のファイルは上書きも追記もしない）
- 記録の後: 台本（.storyboard.md）に同じ id の web シーンを書き、`capture.url` に記録した URL を入れて、`erkit capture --check` → `erkit capture --overlay <確認画像>` で確かめる。必要なら YAML を手で直す（`wait_for` の追加など）

### 自分のツールに `data-testid` を付ける

記録モードは `data-testid` を最優先で使う。自分で作るツールの、操作する部品と mark にしたい部品には、`data-testid` を付けておくと、画面の文言や作りが変わっても操作定義が壊れない。

```html
<button data-testid="calc">計算する</button>
<section data-testid="result-area">…</section>
```

- 名前は英小文字とハイフン（`<部品の役割>`）。表示文言や位置を入れない
- 図（SVG）や、文字を持たないコンテナは、テキストでも role でも指せないため、特に付けておく（付けないと CSS の最後の手段になり、警告が出る）

## 操作定義の書き方

```yaml
schema: explainer-reel/web-actions@1
reel_id: hello-kit               # 台本の reel.id
defaults:                        # すべて任意
  viewport: {width: 1600, height: 660}   # 既定（画像枠と同じ ≈2.42:1）。上の「画面の大きさ」
  device_scale_factor: 1.5               # 既定。画像は 2400×990
  timeout_ms: 20000
  settle_ms: 500                 # 撮影直前の待ち（CSS の transition 終了待ち）
  locale: ja-JP
scenes:
  s01:
    reset: true                  # 新しいページで開き直す（最初のシーンは true 推奨）
    actions:
      - op: wait_load
    shot: {type: viewport}       # viewport（既定）/ full_page / element（selector, padding）
  s02:                           # reset なし = 前のシーンの画面状態を引き継ぐ
    actions:
      - op: click
        selector: 'button:has-text("計算する")'
```

| op | 項目 | 内容 |
|---|---|---|
| `goto` | `url`（任意） | ページを開く（省略時は台本の capture.url）。`http(s)://` か `file://` |
| `wait_load` | `state`（任意: load / domcontentloaded / networkidle） | 読み込み完了を待つ（既定 networkidle） |
| `wait_for` | `selector`, `state`（任意） | 要素が出るまで待つ |
| `wait` | `ms` | 固定時間待つ |
| `click` / `hover` | `selector` | クリック／マウスを重ねる |
| `fill` | `selector`, `value`, `commit`（enter / blur / none） | 入力して確定（既定 Enter） |
| `press` | `key`, `selector`（任意） | キーを押す |
| `scroll_to` | `selector`, `block`（start / center / end）, `offset`（px） | 要素が見える位置へスクロール |
| `scroll` | `y` | ページ先頭からの位置へスクロール |
| `select` | `selector`, `value` | `<select>` で option の value を選ぶ |

セレクタは Playwright の書式（CSS に `:has-text()`・`:text-is()`、`text=...` など）。
各シーン・各操作に `note:` を書いてよい（実行には使わない）。

### 注釈位置（marks）

赤枠・矢印が指す部品を、シーンごとに「mark 名 → セレクタ」で書く。台本には座標を書かず、
`recipe_params` で mark 名だけを参照する（例: `mark: [inputs, result_area]`、`to: {mark: result_area}`）。

```yaml
scenes:
  s05:
    actions: [...]
    marks:
      result_area: '[data-testid="result-area"]'   # セレクタ 1 つ（最初に見つかった要素）
      inputs:                                       # 並びにすると、各セレクタの要素をすべて囲む 1 つの枠になる
        - 'label:text-is("幅（m）")'
        - '#h'
```

- mark 名は英小文字・数字・`_`。各セレクタは最初に一致した要素を使う
- 測るのは撮影の直前（`settle_ms` の後、撮影と同じスクロール位置）。座標は撮影画像に対する値（element 撮影なら切り抜いた画像の左上が原点、`device_scale_factor` も反映）
- 画像の隣に `<画像名>.marks.json`（例 `s01_config.png` → `s01_config.marks.json`）を出す。形式は [`explainer-reel/marks@1`](marks.md)（`box` は 0〜1、`px` は画像のピクセル、`how` は使ったセレクタ）
- 次のどれかに当たった mark は記録せず、**シーンを失敗**にして理由を結果 JSON の `error` に残す: 見つからない／非表示／幅か高さが 8px 未満／面積の 95% 未満しか画像内にない。95% 以上が画像内なら、はみ出した分を画像の範囲に切り詰めて記録する
- 撮影のたびに前回の marks.json を消してから書き直す（画像と食い違わないため）

確認画像: `erkit capture … --overlay <png>` が、結果 JSON の順に、marks.json の `box` を画像へ描き込んで 1 枚に並べる（スライドの段が使う値そのものを描く）。撮影素材と同じく commit しない。
