"""ナレーション: 音声合成エンジン（既定 AivisSpeech）でシーンごとの WAV と durations.json を作る。

入力はナレーションの入力 JSON（data/schema/narration-input.schema.json。台本スキーマとは別の、段の中の形式）。
台本からの変換は narration.adapter。エンジンの口は narration.tts.TTSEngine。コマンドは ``erkit voice``。
"""

from .errors import EngineError, EngineErrorKind, InputError, NarrationError, OverwriteRefusedError
from .synth import NarrationInput, NarrationItem, load_input, parse_input, run_synth
from .textproc import PronunciationDictionary, split_text
from .tts import TTSEngine, Voice, get_engine
from .tts.aivisspeech import AivisSpeechClient, AivisSpeechEngine

__all__ = [
    "AivisSpeechClient",
    "AivisSpeechEngine",
    "EngineError",
    "EngineErrorKind",
    "InputError",
    "NarrationError",
    "NarrationInput",
    "NarrationItem",
    "OverwriteRefusedError",
    "PronunciationDictionary",
    "TTSEngine",
    "Voice",
    "get_engine",
    "load_input",
    "parse_input",
    "run_synth",
    "split_text",
]
