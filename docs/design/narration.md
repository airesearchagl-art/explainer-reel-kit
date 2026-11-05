# ナレーション（erkit voice）

音声合成エンジン（既定は AivisSpeech）で、シーンごとの WAV と `durations.json`（スライドの秒数）を作ります。
コード: `src/explainer_reel_kit/narration/`。

```text
erkit voice list                                   # エンジンへの接続と声の一覧（既定の声があるか）
erkit voice synth examples/hello-kit.storyboard.md  # 台本から WAV と durations.json
erkit voice synth narration-input.json --out-dir 出力先
erkit voice kana examples/hello-kit.storyboard.md --dictionary architecture   # 読みの確認（合成しない）
```

| 引数 | 内容 |
|---|---|
| `--out-dir` | WAV と durations.json の出力先。既定は `<出力先のルート>/voice/<台本の id>` |
| `--speaker` | 声（style id）。台本の `reel.voice.speaker` ＞ 設定の `voice.speaker` ＞ 既定の声 より優先 |
| `--engine` / `--engine-url` | エンジンの名前と URL（既定: 台本・設定・`aivisspeech`、URL はエンジンの既定 `http://127.0.0.1:10101`） |
| `--dictionary 名前\|パス` | 読み辞書（複数可）。`--no-dictionary` で使わない |
| `--force` | 内容が変わった既存の WAV を上書きする |
| `--max-chars` | 1 回の合成に渡す最大文字数（既定 120） |
| `--config` | 設定ファイル（既定は `config/kit.yaml` を探す） |

終了コード: 0 成功 / 1 エンジンの失敗 / 2 入力・引数の誤り / 3 上書きを止めた / 4 書き込めない。

## 既定の声とクレジット

- 既定の声は AivisSpeech の「ほのか / ノーマル」（style id `808373280`、ACML 1.0。商用も可・クレジット表記は任意）
- エンジンに既定の声が無いときは、`erkit voice list` が注意を出し、`erkit voice synth` は入っている声の一覧を出して止まる。声を入れるか、一覧から選んで `config/kit.yaml` の `voice.speaker` か `--speaker` で指定する
- 声のライセンスはモデルごとに確かめる（[THIRD_PARTY.md](../../THIRD_PARTY.md)）。クレジットが必要な声は、`config/kit.yaml` の `voice.credits` に名前・文言・style id を書く。台本からの合成のときに、その声なら `erkit deck` に付ける `--credit` を表示する

## 社外秘の台本

台本の区分が `confidential`（未記入も）のときは、エンジンの URL が**この PC（127.0.0.1 / ::1 / localhost）**でなければ、何も送らずに止まる（`voice synth`・`voice kana`）。ナレーションの原稿を PC の外へ出さないため。

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
     "sample_rate": 44100, "channels": 1, "text_hash": "…", "synth_hash": "…", "paragraph_starts_sec": [0.0, 1.234]}
  ]
}
```

- `slide_sec` = 実長 ＋ `pre_pause_sec` ＋ `post_pause_sec` を 0.01 秒単位で切り上げ（余白は WAV に含めない）
- `paragraph_starts_sec` = 各段落の音声の開始秒（スライドの複数の枠の時刻に使う）
- `complete: false` は途中で失敗した記録（終わった item は次の実行で使い回す）

### 作り直しの決まり

| 状態 | 動き |
|---|---|
| WAV が無い | 作る |
| WAV があり、`synth_hash`（合成に送った分割・声・話速・音量）が同じ | 作り直さない（余白の変更は `slide_sec` だけ直す） |
| WAV があり、内容が変わった・記録が無い | **上書きせずに止める**（終了コード 3）。`--force` で変わった item だけ上書き |

## 読み辞書

- 既定では使わない。分野に合う辞書を `config/kit.yaml` の `voice.dictionaries` か `--dictionary` で選ぶ
- 名前は `dictionaries/<名前>.yaml`（今のフォルダ ＞ キットのフォルダ）。パスでも書ける。複数なら後のものが勝つ
- 例として建築用語の辞書 [dictionaries/architecture.yaml](../../dictionaries/architecture.yaml) がある
- `entries`（表記 → 読み）は最長一致で 1 回だけ置換する。`check_terms` は置換せず、`erkit voice kana` で読みを一覧に出すだけの語
- `erkit voice kana` は、辞書の語と確認語を、原文のままと辞書を当てた後でエンジンに解析させ、読みを並べる（合成はしない）。抑揚・間の取り方は WAV を聞いて確かめる
