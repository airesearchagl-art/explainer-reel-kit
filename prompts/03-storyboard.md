# 3. 台本（チャットだけの AI に貼る）

構成の表を確かめた後、同じ会話に下の枠の中を貼ります。枠の後ろに、次の 2 つのファイルの中身を続けて貼ってください。

1. テンプレート: `src\explainer_reel_kit\data\templates\storyboard.md`（種別が explainer なら `src\explainer_reel_kit\data\templates\explainer.storyboard.md`）
2. 見本の台本: `samples\u-value\u-value.storyboard.md`（explainer なら `samples\window-condensation\window-condensation.storyboard.md`。文脈が足りない AI では省く）

```text
構成の表を、説明動画の台本（Markdown 1 枚）にしてください。この後にテンプレートと見本を貼ります。テンプレートの形を正確に守ってください。

全体の形:
  - 先頭の --- と --- の間（reel）: id, title, schema_version: kit-1.0.0（explainer は kit-1.1.0）, audience, kind, confidentiality, aspect: "16:9", output_name
    - id は英小文字・数字・- ・_ だけ。output_name はファイル名（英小文字・数字・_）
    - confidentiality は聞き取りで私が決めた値をそのまま書く。変えない
    - aspect は必ず引用符で囲む
  - 「## intro」→「## s01: 見出し」…→「## outro」。各見出しのすぐ下に ```yaml のブロック、その下にナレーション
  - intro の yaml: summary, prerequisites（一覧）, duration_note
  - outro の yaml: summary, checks（一覧）, next
  - シーンの yaml: where, image（source, ref, label）, recipe, recipe_params, capture。任意で on_screen_text

画像（image）と撮影の指示（capture）の組み合わせ:
  - 説明図: source: generated / label: 説明用再構成図 / ref: assets/s01_名前.png
      capture: {tool: html, src: diagrams/s01_名前.html, prompt: 何を描く図か}
  - 撮影:   source: web / label: 実キャプチャ / ref: captures/台本のid/s03_名前.png
      capture: {url: http://127.0.0.1:8000/index.html, steps: [人が読む手順]}
  - 人が用意: source: manual / label: 実キャプチャ か 途中成果 / ref: 置くファイルのパス
      capture: {instructions: 用意のしかた}
  - 説明図で実際の画面のふりをしない

注釈（recipe と recipe_params）:
  - recipe は fade_sequence / highlight_box / arrow_move / morph_transition / text_build のどれか
  - 位置は座標で書かず、部品の名前（mark）で指す。名前は英小文字・数字・_
      highlight_box: recipe_params: {mark: 名前} か {mark: [名前1, 名前2]}
      arrow_move:    recipe_params: {to: {mark: 名前}, from_side: right}
  - mark を 3 つ並べたら、ナレーションの段落も 3 つにする（段落ごとに枠が切り替わる）

ナレーション:
  - 話し言葉。1 文は短く（40 字まで目安）、1 段落 1〜3 文。段落は空行で区切る
  - 読み間違いやすいものは読みで書く: 英字（U 値 → ユー値）、数字と単位（1 m² → 一平方メートル、15℃ → 十五度）、記号
  - 画面に出す文字（on_screen_text）とナレーションを同じにしない
  - 根拠の無い数値を書かない。製品で変わる値は「目安」「およそ」と言い、範囲で示す
  - 数値の根拠は、先頭近くの <!-- --> のコメントに書く（コメントの中は読み上げられない）

種別が explainer（一般の解説）のとき:
  - 解説のひな形の形を守る: schema_version: kit-1.1.0、kind: explainer。シーンの順番（問い → しくみ → 比べる・条件 → 選び方・減らし方）は入れ替えない。本編 5〜7 シーン
  - 全シーン説明図。各シーンのコメントの「部品」と、見本の data-mark の名前（everyday・step_1・row_…・card_1 など）を使う。使わないシーンは消してよい
  - 台本の後ろに、出典の一覧 SOURCES.md（ひな形の最後のコメントの形: 使った数値・使った事実・資料（確かめた日）・未確認）を別のコードブロックで出す

対になるものの決まり（種別によらず必ず守る）:
  - 原因と対策、条件と減らし方、問題と解決のように対になるものは、同じ番号・同じ順で並べる
  - 対策の側でも原因の番号で言う（「① の窓が冷えるには…」）
  - 片方にしかないものを作らない（原因はあるが対策が無い、など）
  - 図の番号・色も対でそろえる

出典の決まり（必ず守る）:
  - 規格の番号・出典・数値は、この会話で貼られた資料で確かめたものだけを書く。あなたの記憶で書かない（正しく見えても記憶のものは「未確認」）
  - 確かめていないものは <!-- 未確認: … --> のコメントに書き、台本の後ろに「未確認の一覧」（台本の場所・書いたこと・確かめ方）として挙げる
  - 確かめたものは、資料の名前と場所（頁・節・URL）をコメントに書く

出力:
  - 台本だけを 1 つのコードブロックで出す（説明は後ろに短く）
  - 後ろに、使った mark の名前と、それぞれ何を指すかの一覧を書く（説明図の HTML と撮影の操作定義で同じ名前を使うため）
  - その後ろに、未確認の一覧（無ければ「なし」）

この後、私が台本をファイルに保存して検証のコマンドを実行します。エラーや警告の表示を貼ったら、その行を読んで、直した台本の全体をもう一度出してください。
```

## 人がすること

1. AI が出した台本を `reels\<id>\<id>.storyboard.md` に UTF-8 で保存する
2. 検証する（例はサンプルのパス。自分の台本のパスに変える）

```powershell
erkit check samples\u-value\u-value.storyboard.md
```

3. `NG` や `警告:` が出たら、表示を全部コピーして AI に貼り、「この表示を直してください」と頼む。`OK` になるまで繰り返す
4. `OK` の行の「区分」が、自分で決めた値になっているか確かめる
