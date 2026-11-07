# 5. まとめて進める（チャットだけの AI に貼る）

聞き取りの答えを先にまとめて渡し、**1 回の返事で台本と説明図の HTML と報告**をもらう使い方です（考え方は [batch.md](../docs/guide/batch.md)）。
01〜04 の指示文の代わりに使います。

## 貼る順

1. 下の枠の中の指示文
2. 埋めた**答えのひな形**（[batch.md](../docs/guide/batch.md) の「答えのひな形」。区分の行を先頭に）
3. テンプレート: `src\explainer_reel_kit\data\templates\storyboard.md` の中身（種別が explainer なら `src\explainer_reel_kit\data\templates\explainer.storyboard.md`）
4. 見本: `samples\u-value\u-value.storyboard.md` と `samples\u-value\diagrams\s01_heat_paths.html` の中身（explainer なら `samples\window-condensation\window-condensation.storyboard.md` と、使う部品の見本 `samples\_parts\….html`。文脈が足りない AI では省く）
5. 資料（区分が general のときだけ）

**社外秘を含む・分からない材料は、クラウドの AI に貼らないでください**。この PC の中で動く AI（LM Studio・Ollama など）か、所属先が認めた AI だけに貼ります。

```text
あなたは、説明動画の台本づくりを手伝う書き手です。この後に「答えのひな形」「テンプレート」「見本」「資料」を貼ります。聞き返しを最小にして、1 回の返事で台本・説明図の HTML・報告を出してください。

最初に必ず、答えのひな形の「区分」の行だけを読んでください。
  - general なら続ける
  - 書いていない・confidential・分からない、のどれかなら、ほかの欄も資料も読まずに、次だけを返して止まる:
    「区分が general ではないので止まります。社外秘を含む材料は、この PC の中で動く AI か、所属先が認めた AI で進めてください。」
    （あなたがこの PC の中で動いている AI だと私が明言した場合だけ、confidential のまま続けてよい）
  - 区分を general に変えてよいのは私だけ。あなたから下げる提案はしない

欄が足りないとき: 進められない欄（何を説明するか・資料）が空なら、足りない欄だけをまとめて 1 回聞く。それ以外の空欄は、あなたが決めて報告に書く。

書くもの:
  1. 台本（Markdown 1 枚）。テンプレートの形を正確に守る
     - reel: id は答えの「題材の id」、schema_version はテンプレートの値のまま（explainer は kit-1.1.0）、confidentiality は答えの値のまま、aspect は "16:9"（引用符つき）、output_name は id の - を _ にしたもの
     - intro → 本編 5〜8 シーン（## s01: 見出し …）→ outro。見出しは行動で終える
     - 1 シーン = 1 スライド = 主画像 1 枚。説明図は source: generated / label: 説明用再構成図 / capture: {tool: html, src: diagrams/s01_名前.html}
     - 赤枠・矢印は recipe_params に mark の名前で（座標は書かない）。mark を並べた数とナレーションの段落の数をそろえる
     - ナレーションは話し言葉で短く。英字・数字・単位・記号は読みで書く（U 値 → ユー値、1 m² → 一平方メートル）
     - 種別が explainer なら: 解説のひな形の形（kit-1.1.0、kind: explainer）。順番は 問い → しくみ → 比べる・条件 → 選び方・減らし方 → まとめ（入れ替えない）、本編 5〜7 シーン、全シーン説明図。各シーンの部品と見本の data-mark の名前を使う
  2. 説明図の HTML（説明図のシーンごとに 1 つ）
     - 種別が explainer なら: 部品の見本を写して文字と数値だけを書き換える（CSS の参照は ../../_shared/diagram.css に直す。見本の値は残さない）
     - <link rel="stylesheet" href="../../_shared/diagram.css"> を読む。外の URL（Web フォント・CDN・外の画像・fetch）は使わない
     - 台本の mark と同じ名前で data-mark="名前" を付ける。文字は 32px 未満にしない。赤は使わない。実際の画面のふりをしない
  3. 種別が explainer なら: 出典の一覧 SOURCES.md（使った数値・使った事実・資料（確かめた日）・未確認）。保存先 reels/題材の id/SOURCES.md
  4. 報告（下の形）

出典の決まり（必ず守る）:
  - 規格の番号・出典・数値は、貼られた資料で確かめたものだけを書く。あなたの記憶で書かない（正しく見えても記憶のものは「未確認」）
  - 確かめていないものは、台本の <!-- 未確認: … --> のコメントに書き、報告の「未確認」の表に挙げる。ナレーションでは番号を言わないなどで逃がす
  - 確かめたものは、資料の名前と場所をコメントに書く

出す順と形:
  - 台本: ```markdown のコードブロック 1 つ（先頭に保存先 reels/題材の id/題材の id.storyboard.md を 1 行で）
  - 説明図: シーンごとに ```html のコードブロック（先頭に保存先 reels/題材の id/diagrams/… を 1 行で）
  - SOURCES.md（explainer のとき）: ```markdown のコードブロック 1 つ（先頭に保存先 reels/題材の id/SOURCES.md を 1 行で）
  - 報告:
      ### 構成（表: シーン・見出し・画像・伝えること・注釈）
      ### 決めたこと（ひな形に書かれていなかったので決めたこと。見る人の A・B・C と理由を含む）
      ### 根拠が弱い・未確認の数値と事実（表: 台本の場所・書いたこと・状態・確かめ方）
      ### 次に人がすること（ファイルを保存する → 検証のコマンド → 説明図の確認画像を見る → よければ MP4）

MP4 を作るのは、人が報告と確認画像を見てよいと言ってからです。あなたから「作ってよい」と決めないでください。

この後、私が台本と HTML を保存してコマンドを実行します。エラーや警告の表示を貼ったら、その行を読んで、直したファイルの全体をもう一度出してください。
```

## 人がすること

1. AI が出した台本と HTML を、書いてある保存先に UTF-8 で保存する。共通の CSS がまだ無ければ、先に写す

```powershell
cd $env:USERPROFILE\explainer-reel-kit
New-Item -ItemType Directory reels -Force | Out-Null
if (-not (Test-Path reels\_shared)) { Copy-Item samples\_shared reels\_shared -Recurse }
```

2. 仮想環境を有効にして（[手順書の README](../docs/guide/README.md) の「コマンドの前に」）、検証と説明図を通す。例はサンプルのパスなので、自分の台本のパスに変える

```powershell
erkit check --strict samples\u-value\u-value.storyboard.md
erkit diagram samples\u-value\u-value.storyboard.md --out output\u-value --overlay output\u-value\check-diagram.png
erkit make samples\u-value\u-value.storyboard.md --serve samples\u-value\app --dry-run
```

3. `NG`・`警告:`・失敗したシーンの理由が出たら、表示を全部 AI に貼って直してもらう。通るまで繰り返す
4. 確認画像と報告の「未確認」の表を見る。未確認の項目は人が原典で確かめ、台本を直す
5. よければ MP4 を作る（[07-export.md](../docs/guide/07-export.md)）
