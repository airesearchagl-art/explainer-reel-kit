# 会社の PC で GitHub Copilot と使う

会社の PC で、VS Code の **GitHub Copilot（エージェント）** と一緒に台本・説明図を作る手順です。
社外秘（`confidential`）を含む題材を、**所属先が認めた AI** で進めるための準備も書いてあります（区分の考え方は [confidentiality.md](confidentiality.md)）。

進め方は 2 段に分けます。

| 段 | できること | 入れるもの |
|---|---|---|
| **段 1（すぐできる）** | 聞き取り → 構成 → 台本 → `erkit check`、説明図の HTML を書く | VS Code・GitHub Copilot・Python・Git・キット |
| **段 2（後で）** | 説明図の PNG・Web 画面の撮影・ナレーション・スライド・MP4（`erkit make`） | ブラウザ・ffmpeg・AivisSpeech・PowerPoint |

## 何が PC の外に出るか

| 段 | 外に出るもの（行き先） | PC の中だけで終わるもの |
|---|---|---|
| 段 1 | **Copilot が読んだもの**と、チャットに書いた文（GitHub Copilot）。読んだものは、人が見せたもの・**Copilot が自分で開いたファイル**（台本・資料・説明図の HTML・許可リストなど）・**Copilot が読んだターミナルの出力**（`erkit check` の結果など）。ほかに、会社の非公開リポジトリに push したもの（会社の GitHub） | `erkit check` の処理（台本の検証。出力を Copilot が読めば、その出力は外に出る）。許可リスト（`config/approved_ai.yaml`）は `.gitignore` で外してあり push されない |
| 段 2 | 段 1 と同じ（Copilot が読んだもの） | 説明図の描画（ネットワークを止めて描く）、撮影（`confidential` なら PC の中の URL だけ）、音声合成（AivisSpeech は PC の中で動く）、スライド・動画の書き出し（PowerPoint・ffmpeg） |

- キットの本体（`erkit`）は、クラウドの AI を呼びません。外に出るのは、**Copilot が読んだもの（人が見せたもの・Copilot が開いたファイル・ターミナルの出力）と、チャットに書いた文**です
- エージェントの Copilot は、頼まれなくても、開いているフォルダ（ワークスペース）のファイルを自分で開いて読むことがあります。**社外秘の資料は、区分を決めて許可リストを確かめるまで、ワークスペースの中に置きません**（Copilot が先に読むのを防ぐため。資料はワークスペースの外に置き、確かめた後で `reels/` の下などに写す）
- 社外秘の資料を Copilot に見せてよいのは、所属先が GitHub Copilot に社外秘の扱いを認めているときだけです。認められていなければ、許可リストに書かず、社外秘の題材では使いません

## 準備 1: 会社のアカウントで非公開のリポジトリを作る

公開のキットを、会社の GitHub アカウントの**非公開（Private）の新しいリポジトリ**に取り込みます。社外秘の台本は、このリポジトリ（会社の管理の下）に置きます。

- GitHub の「フォーク（Fork）」は使いません。公開のリポジトリのフォークは公開になります
- 取り込み方は次のどちらか

**A. GitHub の Import を使う**

1. 会社のアカウントで GitHub を開き、右上の「+」→「Import repository」
2. 元の URL に `https://github.com/airesearchagl-art/explainer-reel-kit` を入れる
3. 持ち主を会社のアカウント（か組織）、名前を決め（例 `explainer-reel-kit-work`）、**Private** を選んで「Begin import」
4. できたら、下の「B」の 2 番目から（`git clone` で PC に取ってくる）

**B. 手元に取ってきて、新しいリポジトリへ push する**

1. 会社のアカウントで、**空の Private のリポジトリ**を作る（README・.gitignore・ライセンスは付けない）。例の名前 `explainer-reel-kit-work`
2. PowerShell で次を実行する。1 行目は、作ったリポジトリの URL に書き換える

```powershell
$CompanyRepo = "https://github.com/YOUR-ORG/explainer-reel-kit-work.git"
cd $env:USERPROFILE
git clone https://github.com/airesearchagl-art/explainer-reel-kit.git explainer-reel-kit
cd explainer-reel-kit
git remote rename origin upstream
git remote add origin $CompanyRepo
git remote set-url --push upstream no-push
git push -u origin main
```

- `upstream` は公開のキット（取り込む元）、`origin` は会社の非公開リポジトリ（台本を置く先）です
- `git remote set-url --push upstream no-push` で、公開のキットへの push が失敗するようにしてあります（間違えて台本を公開しないため）
- Import で作ったときは、`git clone` で会社のリポジトリを取ってきたあと、`git remote add upstream https://github.com/airesearchagl-art/explainer-reel-kit.git` と `git remote set-url --push upstream no-push` を実行します

### キットの更新を取り込む

```powershell
cd $env:USERPROFILE\explainer-reel-kit
git fetch upstream
git merge upstream/main
git push origin main
```

### 台本をリポジトリに残すか

- 台本の置き場 `reels/` は、キットの `.gitignore` で外してあります（公開のキットに台本を入れないため）
- 会社の非公開リポジトリで台本を残したいときは、所属先の決まりを確かめてから、`.gitignore` の `reels/` の行を消して commit します（キットの更新を取り込むときにこの行がぶつかったら、会社のリポジトリの側を残します）
- 許可リスト `config/approved_ai.yaml` も `.gitignore` で外してあります（その PC だけの設定）

## 準備 2: 許可リストに GitHub Copilot を書く（人が書く）

社外秘の題材で Copilot を使うには、**所属先の規程・申請の結果を確かめてから**、人が `config/approved_ai.yaml` に書きます。
Copilot は、このリストに自分（`github-copilot`）が載っていなければ、社外秘の資料を扱わずに止まります（[AGENTS.md](../../AGENTS.md) の 2 節、[.github/copilot-instructions.md](../../.github/copilot-instructions.md)）。

`config\approved_ai.yaml`（`install.ps1` がひな形から写します）の `approved: []` を消して、次のように書きます。`approved_on` と `basis` は自分の所属先のものに。

```yaml
version: 1
approved:
  - id: github-copilot
    name: GitHub Copilot（エージェント）
    kind: agent
    approved_on: 2026-01-15
    basis: 生成 AI 利用規程・GitHub Copilot 利用申請（承認番号など）
    allows: [confidential]
    notes: 決まりは .github/copilot-instructions.md
```

- 書くのは人だけです。Copilot に書かせません
- 書いたら `erkit doctor` の「社内で認められた AI（許可リスト）」の行で、名前が出ること・`NG` でないことを確かめます
- 社外秘を扱わない（`general` の題材だけ）なら、書かなくてかまいません
- 許可リストに載っていても、キットの区分の確かめ（撮影・音声合成などは PC の中だけ）は変わりません

## 段 1: 台本と説明図の HTML まで

### 入れるもの

| もの | 用途 | 入れ方 |
|---|---|---|
| VS Code | エディタ | 所属先の配布か `winget install Microsoft.VisualStudioCode` |
| GitHub Copilot（VS Code の拡張機能） | エージェント | VS Code の拡張機能から入れ、**会社の GitHub アカウント**でサインインする |
| Python 3.10 以上 | キットの本体 | `winget install Python.Python.3.12` か python.org |
| Git | リポジトリの取得 | `winget install Git.Git` |

入れたら、準備 1 で取ってきたフォルダでキットを入れます。段 1 ではブラウザを入れません。

```powershell
cd $env:USERPROFILE\explainer-reel-kit
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -SkipBrowser
```

確かめます。

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
erkit doctor --skip-browser --skip-llm
```

段 1 では、ffmpeg・PowerPoint・AivisSpeech の行が `NG` でかまいません（段 2 で入れます。そのため最後は「足りないもの」と出ます）。見るのは次の行です。

- `Python`・`Python のライブラリ` が `OK`
- `社内で認められた AI（許可リスト）` が `OK` で、社外秘を扱うなら `GitHub Copilot（エージェント）（github-copilot、agent）` と出ている

### Copilot に頼む

1. VS Code で `explainer-reel-kit` のフォルダを開く（「ファイル」→「フォルダーを開く」）
2. Copilot のチャットを開き、モードを **Agent（エージェント）** にする
3. 次の指示文を貼る（`…` の所は自分の題材に）

```text
このリポジトリの .github/copilot-instructions.md と AGENTS.md を読んで、説明動画の台本を作りたいです。

- 題材: …（何を説明するか）
- 見る人: …（例 初めて使う人）
- 資料: …（ファイルの場所。区分が決まるまでは開かないでください）

進め方:
1. 最初に区分（general / confidential）を私に聞いてください。confidential なら config/approved_ai.yaml を読み、
   あなた（github-copilot）が載っているかを、載っていた項目（name・approved_on・basis）と一緒に私に伝えてください。
   載っていなければ、資料を開かずに止まってください
2. docs/guide/ の 01〜04 の順に、聞き取り → 見る人 → 構成（台本を書く前に一覧を見せる）→ 台本 と進めてください
3. 台本は reels/（台本の id）/ に置き、ターミナルで erkit check を実行して、通るまで直してください
4. 説明図は HTML を書くところまでにしてください（PNG にするのは後で）
5. 許可リストは書き換えないでください。git push は、私が頼んだときに origin へだけしてください
```

### 段 1 でできること・できないこと

| できる | 段 2 で |
|---|---|
| 聞き取り・見る人・構成・台本（`erkit check` が通るまで） | 説明図の PNG と確認画像（`erkit diagram`。ブラウザが要る） |
| 説明図の HTML を書く（Edge で HTML を開けば見た目は確かめられる） | Web 画面の撮影（`erkit capture`） |
| 台本の読みの下書き（ナレーションの文） | ナレーションの音声・スライド・MP4（`erkit make`） |

台本の確かめは、人もターミナルで打てます（台本の id が `my-tool` のとき）。

```powershell
erkit check reels\my-tool\my-tool.storyboard.md
```

## 段 2: 説明図の PNG から MP4 まで（後で）

段 2 に進む前に、入れるソフトを所属先に申請します。次の表は申請にそのまま使える形にしてあります（キットはどれも同梱しません）。

| ソフト | 用途 | 入手先 | ライセンス・条件 | 通信 |
|---|---|---|---|---|
| Chromium（Playwright が入れる）か Microsoft Edge | 説明図の描画・Web 画面の撮影 | `python -m playwright install chromium`（Chromium の各ライセンス）。Edge は Windows 標準 | Chromium: BSD ほか。Edge: Windows の一部 | 説明図はネットワークを止めて描く。撮影は `confidential` なら PC の中の URL だけ |
| ffmpeg / ffprobe | 音声と映像の合成 | https://www.gyan.dev/ffmpeg/builds/（`winget install Gyan.FFmpeg`） | LGPL-2.1 以降 または GPL-2.0 以降（ビルドによる） | 使わない（PC の中のファイルだけ） |
| AivisSpeech | ナレーションの音声合成 | https://aivis-project.com/ | エンジンは LGPL-3.0。声のモデルはモデルごと（ACML 1.0・ACML-NC 1.0 など） | PC の中（`127.0.0.1:10101`）だけで呼ぶ。`confidential` で外の URL なら原稿を送らずに止まる |
| PowerPoint（デスクトップ版） | スライドを MP4 に書き出す | 所属先の Microsoft 365 / Office | 所属先のライセンス | 書き出しは PC の中 |

Python のライブラリ（jsonschema・PyYAML・python-pptx・lxml・Pillow・Playwright）は段 1 の `install.ps1` で入っています。ライセンスは [THIRD_PARTY.md](../../THIRD_PARTY.md) にあります。

入れたら、ブラウザを入れて確かめます（Chromium を入れられないときは Edge を使う: `erkit doctor --channel msedge`）。

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
erkit doctor
```

全部 `OK` になれば、[05-visuals.md](05-visuals.md) から先（説明図 → 確認 → 書き出し）に進めます。

```powershell
erkit make reels\my-tool\my-tool.storyboard.md --dry-run
```

自分の声のモデルを会社の PC に入れるかなど、声の選び方は [00-setup.md](00-setup.md) の「声のライセンスを確かめる」を見て、所属先と決めてください。

## AI に任せること

- 区分を聞く。`confidential` なら許可リストを読み、自分が載っているかを人に伝える（載っていなければ止まる）
- 聞き取り → 構成 → 台本 → `erkit check`、説明図の HTML を書く
- 許可リストを書き換えない。区分を下げない。公開のキット（`upstream`）へ push しない

## 人が打つコマンド

- 準備 1 の取り込み、準備 2 の許可リスト、`install.ps1`、`erkit doctor`
- 段 2 のソフトの申請と導入
