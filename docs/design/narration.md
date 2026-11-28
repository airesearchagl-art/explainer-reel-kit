# ナレーション（erkit voice）

音声合成エンジン（既定は AivisSpeech）で、シーンごとの WAV と `durations.json`（スライドの秒数）を作ります。
コード: `src/explainer_reel_kit/narration/`。

```text
erkit voice list                                   # エンジンへの接続と声の一覧（既定の声があるか）
erkit voice synth examples/hello-kit.storyboard.md  # 台本から WAV と durations.json
erkit voice synth narration-input.json --out-dir 出力先
erkit voice kana examples/hello-kit.storyboard.md --dictionary architecture   # 読みの確認（合成しない）
erkit voice review <台本> --run <erkit make の出力フォルダ>                    # 文ごとの読みの確かめの表と試聴ページ
```

| 引数 | 内容 |
|---|---|
| `--out-dir` | WAV と durations.json の出力先。既定は `<出力先のルート>/voice/<台本の id>` |
| `--speaker` | 声（style id）。台本の `reel.voice.speaker` ＞ 設定の `voice.speaker` ＞ 既定の声 より優先 |
| `--engine` / `--engine-url` | エンジンの名前と URL（既定: 台本・設定・`aivisspeech`、URL はエンジンの既定 `http://127.0.0.1:10101`） |
| `--dictionary 名前\|パス` | 読み辞書（複数可）。`--no-dictionary` で使わない |
| `--force` | 内容が変わった既存の WAV を上書きする |
| `--reuse-from フォルダ` | 前の合成の出力先（durations.json のあるフォルダ。読むだけ）。同じ内容の WAV は写し、変わった場面も、変わっていない段落の音声はそこから切り出す（下の「作り直しの決まり」） |
| `--max-chars` | 1 回の合成に渡す最大文字数（既定 120） |
| `--config` | 設定ファイル（既定は `config/kit.yaml` を探す） |

終了コード: 0 成功 / 1 エンジンの失敗 / 2 入力・引数の誤り / 3 上書きを止めた / 4 書き込めない。

## 既定の声とクレジット

- 既定の声は AivisSpeech の「ほのか / ノーマル」（style id `808373280`、ACML 1.0。商用も可・クレジット表記は任意）
- エンジンに既定の声が無いときは、`erkit voice list` が注意を出し、`erkit voice synth` は入っている声の一覧を出して止まる。声を入れるか、一覧から選んで `config/kit.yaml` の `voice.speaker` か `--speaker` で指定する
- 声のライセンスはモデルごとに確かめる（[THIRD_PARTY.md](../../THIRD_PARTY.md)）。クレジットが必要な声は、`config/kit.yaml` の `voice.credits` に名前・文言・style id を書く。台本からの合成のときに、その声なら `erkit deck` に付ける `--credit` を表示する

## 社外秘の台本

台本の区分が `confidential`（未記入も）のときは、エンジンの URL が**この PC（127.0.0.1 / ::1 / localhost）**でなければ、何も送らずに止まる（`voice synth`・`voice kana`・`voice suggest`・`voice review`）。ナレーションの原稿を PC の外へ出さないため。

## エンジンの口（TTSEngine）

`narration.tts.TTSEngine` が差し替えの口です。差し替える側がするのは「1 分割の文章を WAV にする」ことだけです。

```python
class TTSEngine(Protocol):
    name: str            # 台本の reel.voice.engine・--engine の名前
    url: str
    def check(self) -> EngineInfo: ...                      # 接続と版
    def voices(self) -> list[Voice]: ...                     # 声の一覧
    def synthesize(self, text, voice, *, speed, volume) -> bytes: ...   # 1 分割 → WAV（44.1kHz モノラル）
    def reading(self, text, voice) -> str | None: ...        # 読みのカナ（無ければ None）
```

- 分割（段落・最大文字数）、読み辞書の置換、WAV の連結、`durations.json`、再生成の判定は、口の外の共通部分（`narration/synth.py`）が受け持つ
- 既定の `aivisspeech`（`narration/tts/aivisspeech.py`）: `audio_query` → `synthesis`。システムのプロキシは使わない
- 他のエンジンは、パッケージの entry point（グループ `explainer_reel_kit.tts`）に `名前 = モジュール:ファクトリ` を登録すると `--engine 名前` で選べる。ファクトリは `(url, timeout_sec=...)` を受け取って TTSEngine を返す。VOICEVOX ENGINE は同じ形の HTTP なので、少しの違いを直せば使える見込み

## 分割と durations.json

- 原稿の改行が**段落**の区切り（赤枠 1 つ ＝ 段落 1 つ）。1 つの合成は段落をまたがない
- 段落の中は句点（。！？!?）で文に分け、`--max-chars` 以内に詰めて合成し、無音を挟まずにつなぐ

```json
{
  "format": "explainer-reel/narration-durations", "version": 2, "complete": true,
  "engine": "aivisspeech", "engine_url": "http://127.0.0.1:10101",
  "speaker": 808373280, "speed": 1.0, "volume": 1.0, "pre_pause_sec": 0.3, "post_pause_sec": 0.5, "max_chars": 120,
  "items": [
    {"id": "intro", "wav": "intro.wav", "audio_sec": 2.345, "slide_sec": 3.15, "chunks": 3,
     "sample_rate": 44100, "channels": 1, "text_hash": "…", "synth_hash": "…", "paragraph_starts_sec": [0.0, 1.234],
     "chunk_frames": [40000, 30000, 33415], "chunk_hashes": ["…", "…", "…"], "chunk_sentences": [2, 1, 1],
     "synthesized_paragraphs": [2]}
  ]
}
```

- `slide_sec` = 実長 ＋ `pre_pause_sec` ＋ `post_pause_sec` を 0.01 秒単位で切り上げ（余白は WAV に含めない）
- `paragraph_starts_sec` = 各段落の音声の開始秒（スライドの複数の枠の時刻に使う）
- `chunk_frames` = 合成の分割（chunk）ごとのフレーム数（WAV の中の境目。合計は WAV の全フレーム）。`chunk_hashes` は分割ごとの見分け（送った文章・声・話速・音量）、`chunk_sentences` は分割ごとの文の数。interactive の字幕の時刻はこれと WAV の無音から測る
- `synthesized_paragraphs` = この実行でエンジンに送った段落の番号（1 から）。全部使い回したら `[]`
- `reused_from` = 音声を写した・切り出した前の出力先（あるときだけ）
- `fit` = 固定尺の枠で書き換えたときだけ（下の節）
- `complete: false` は途中で失敗した記録（終わった item は次の実行で使い回す）
- 字幕の別表記（台本の `subtitles`）は合成に使わない。字幕だけ直しても `synth_hash` は変わらず、WAV を使い回す

### 作り直しの決まり

| 状態 | 動き |
|---|---|
| WAV が無い | 作る |
| WAV があり、`synth_hash`（合成に送った分割・声・話速・音量）が同じ | 作り直さない（余白の変更は `slide_sec` だけ直す） |
| WAV があり、内容が変わった・記録が無い | **上書きせずに止める**（終了コード 3）。`--force` で変わった item だけ上書き |
| `--reuse-from` の前の出力に、`synth_hash` が同じ WAV がある | 写す（合成しない） |

作り直す item でも、`chunk_hashes` が同じ分割の音声は、同じ item の前の WAV（上書きの前に読む）か `--reuse-from` の WAV から切り出し、
変わった分割だけをエンジンに送ります。前の記録に `chunk_frames` が無い・WAV の形式が今のエンジンの出力と違うときは、その item 全体を合成します。
`erkit make --reuse-run <前の出力フォルダ>` は、その `work/narration` を `--reuse-from` に渡します。

## 固定尺の枠（slot_sec）

台本の `slot_sec`（kit-1.2.0）がある場面は、`erkit make` のナレーションの段の最後に、`slide_sec` を枠の秒にします（`narration/fit.py`）。

- ナレーション（前の余白 ＋ WAV ＋ 後ろの余白）が短ければ、後ろが無音になるだけ
- 長ければ、**音声を伸び縮みさせずに**無音を詰める: ① WAV の頭と終わりの無音・後ろの余白 → ② 文の間の 0.3 秒以上の無音（同じ割合で、0.2 秒までは残す）。詰めた WAV は `<id>.fit.wav`（合成した `<id>.wav` は変えない）
- それでも収まらなければ、durations.json を変えずに止まる（ナレーションの段の失敗。終了コード 1）。超過の秒数と、話速を上げる（目安の値）・文を短くする・枠を延ばす の選択肢を出す
- 書き換えた item は `wav`・`audio_sec`・`slide_sec`・`paragraph_starts_sec` を詰めた後の値にし、合成したときの値を `fit.source` に残す。`fit` には `slot_sec`・`need_sec`・`removed_sec`・`post_pause_sec`、詰めたときは `cuts`（抜いた区間の秒 `[[始まり, 終わり], …]`、合成した WAV の秒）
- 次の合成は `fit.source` に戻して同じ内容かを判定する（枠だけ変えても合成し直さない）

## 読みの確かめの表（erkit voice review）

```text
erkit voice review <台本> --run <出力フォルダ> [--dictionary …] [--no-engine] [--no-transcribe] [--whisper-model small] [--out フォルダ]
```

`erkit make` の出力フォルダ（その `work/narration`）か `erkit voice synth` の出力先の WAV を読み、出力フォルダの `checks/` に書きます。

| ファイル | 中身 |
|---|---|
| `review.tsv` | 文ごとに 場面・文・段落・開始秒・終了秒・原稿・字幕（別表記があるとき）・合成入力（辞書の後）・モーラ（エンジンの読み）・書き起こし・印・辞書・確認語・ずれ。UTF-8（BOM 付き、Excel で開ける） |
| `listen.html` | 印の付いた文だけを並べた試聴ページ。▶ でその文の区間だけを再生する。外の URL は読まない |
| `transcript.json` | 書き起こしをしたときだけ。語ごとの時刻 |

- 印: `ずれ`（書き起こしが原稿と違う。記号・空白・全角半角を除いて比べる）/ `辞書`（辞書で読みを直した語がある）/ `確認語`（辞書の `check_terms` がある）
- 書き起こしは任意。`faster-whisper` が入っているときだけ行い（この PC の中で動かす。音声も原稿も外へ送らない）、無ければ注意を出して列を空にする。書き起こしは確かめる所を絞るためだけのもので、読みの正否はエンジンの読みと試聴で決める
- 文の時刻は interactive の字幕と同じ決まり（合成の分割の境目と WAV の無音）
- `--no-engine` でエンジンに読みを問い合わせない（モーラの列が空）。社外秘の台本でエンジンを使うときは、この PC のエンジンだけ

## 読み辞書

- 既定では使わない。分野に合う辞書を `config/kit.yaml` の `voice.dictionaries` か `--dictionary` で選ぶ
- 名前は `dictionaries/<名前>.yaml`（今のフォルダ ＞ キットのフォルダ）。パスでも書ける。複数なら後のものが勝つ
- 例として建築用語の辞書 [dictionaries/architecture.yaml](../../dictionaries/architecture.yaml) がある
- `entries`（表記 → 読み）は最長一致で 1 回だけ置換する。`check_terms` は置換せず、`erkit voice kana` で読みを一覧に出すだけの語
- `erkit voice kana` は、辞書の語と確認語を、原文のままと辞書を当てた後でエンジンに解析させ、読みを並べる（合成はしない）。抑揚・間の取り方は WAV を聞いて確かめる
