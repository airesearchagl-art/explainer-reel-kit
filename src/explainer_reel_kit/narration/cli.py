"""``erkit voice``: 声の一覧・ナレーションの合成・読みの確認。

    erkit voice list                          エンジンへの接続と声の一覧（既定の声があるか）
    erkit voice synth <台本 | 入力.json>       シーンごとの WAV と durations.json
    erkit voice kana <台本> [<台本> …]         辞書の語・確認語をエンジンがどう読むか（合成しない）

終了コード: 0 成功 / 1 エンジンの失敗 / 2 入力・引数の誤り / 3 上書きを止めた / 4 書き込めない
"""

from __future__ import annotations

import argparse
import dataclasses
import ipaddress
import json
import sys
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

from .. import config as kit_config
from .. import storyboard as sb
from .adapter import AdapterError, storyboard_to_narration_input
from .dictionaries import load_dictionaries
from .errors import InputError, NarrationError, OutputError
from .synth import DURATIONS_FILENAME, NarrationInput, load_input, parse_input, resolve_engine_url, run_synth
from .textproc import DEFAULT_MAX_CHARS, PronunciationDictionary
from .tts import TTSEngine, get_engine
from .tts.aivisspeech import DEFAULT_TIMEOUT_SEC, Transport

HELP = "声の一覧・ナレーションの合成・読みの確認"
NARRATION_INPUT_FILENAME = "narration-input.json"


# -- parser -----------------------------------------------------------------------


def configure(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    sub = parser.add_subparsers(dest="voice_command", metavar="<list|synth|kana>")
    sub.required = True

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, help="設定ファイル（既定: config/kit.yaml を探す）")
    common.add_argument("--engine", help="音声合成エンジン（既定: 台本・設定・aivisspeech の順）")
    common.add_argument("--engine-url", help="エンジンの URL（既定: 設定、無ければエンジンの既定）")
    common.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SEC,
                        help=f"1 リクエストのタイムアウト秒（既定 {DEFAULT_TIMEOUT_SEC:g}）")

    dicts = argparse.ArgumentParser(add_help=False)
    g = dicts.add_mutually_exclusive_group()
    g.add_argument("--dictionary", action="append", default=None, metavar="名前|パス",
                   help="読み辞書（複数可。名前は dictionaries/<名前>.yaml）。既定は設定の voice.dictionaries、無ければ使わない")
    g.add_argument("--no-dictionary", action="store_true", help="読み辞書を使わない（設定の辞書も使わない）")

    p = sub.add_parser("list", parents=[common], help="エンジンへの接続と声の一覧")
    p.add_argument("--json", action="store_true", help="結果を JSON で出力する")

    s = sub.add_parser("synth", parents=[common, dicts], help="台本（またはナレーションの入力 JSON）から WAV と durations.json を作る")
    s.add_argument("source", type=Path, metavar="台本|入力.json", help=".storyboard.md / .storyboard.json / narration-input.json")
    s.add_argument("--out-dir", type=Path,
                   help="WAV と durations.json の出力先（既定: <出力先のルート>/voice/<台本の id>）")
    s.add_argument("--output-root", type=Path, help="出力先のルート（--out-dir が無いときに使う）")
    s.add_argument("--speaker", type=int, help="声（style id）。台本・設定より優先する")
    s.add_argument("--force", action="store_true", help="内容が変わった既存の WAV を上書きする")
    s.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                   help=f"1 回の合成に渡す最大文字数。段落ごとに、超える分は句点で分割（既定 {DEFAULT_MAX_CHARS}）")

    k = sub.add_parser("kana", parents=[common, dicts], help="辞書の語と確認語の読みを一覧にする（合成しない）")
    k.add_argument("sources", type=Path, nargs="+", metavar="台本|入力.json")
    k.add_argument("--speaker", type=int, help="声（style id）。省略時は台本・入力・設定の値")
    k.add_argument("--sentences", action="store_true", help="合成に送る単位（段落ごとの文）の読みも出す")
    k.add_argument("--all-terms", action="store_true", help="本文に出ない辞書の語も一覧に出す")
    k.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS, help=argparse.SUPPRESS)
    k.add_argument("--out", type=Path, help="結果を UTF-8 の Markdown ファイルにも書く")
    parser.set_defaults(func=run)
    return parser


def register(sub) -> None:
    configure(sub.add_parser("voice", help=HELP, description=HELP))


# -- helpers ----------------------------------------------------------------------


def _is_loopback(url: str) -> bool:
    host = (urlparse(url).hostname or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _engine(name: str | None, url: str | None, timeout: float, transport: Transport | None) -> TTSEngine:
    kwargs: dict[str, Any] = {"timeout_sec": timeout}
    if transport is not None:
        kwargs["transport"] = transport
    return get_engine(name, url, **kwargs)


def _dictionary(args, cfg: kit_config.KitConfig) -> tuple[PronunciationDictionary, list[Path]]:
    if args.no_dictionary:
        return PronunciationDictionary.empty(), []
    specs = args.dictionary if args.dictionary is not None else cfg.dictionaries
    if not specs:
        return PronunciationDictionary.empty(), []
    return load_dictionaries(specs)


def _is_storyboard(path: Path) -> bool:
    if path.suffix.lower() == ".md":
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False  # load_input が理由を付けて報告する
    return isinstance(data, dict) and "reel" in data


def _load_storyboard(path: Path) -> dict[str, Any]:
    try:
        doc = sb.load_storyboard(path)
    except FileNotFoundError as e:
        raise InputError(f"台本が見つかりません: {path}") from e
    except (sb.ConversionError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise InputError(f"台本を読めません: {path}: {e}") from e
    rep = sb.validate_storyboard(doc, base_dir=path.parent)
    errors = [e for e in rep.errors if not e.startswith("[image]")]  # 画像の有無はナレーションに関係しない
    if errors:
        raise InputError("台本が検証を通りません（erkit check で確かめてください）:\n  " + "\n  ".join(errors))
    return doc


def _guard_confidential(doc: dict[str, Any] | None, url: str) -> None:
    """社外秘の台本（未記入も）は、音声合成エンジンがこの PC のときだけ使う。"""
    if doc is not None and sb.confidentiality(doc) == sb.CONFIDENTIAL and not _is_loopback(url):
        raise InputError(
            f"この台本は社外秘（confidential）の扱いです。ナレーションの原稿をこの PC の外（{url}）へ送れません。"
            " エンジンをこの PC（127.0.0.1 / localhost）で動かすか、公開済みの情報だけなら台本に confidentiality: general と書いてください"
        )


def _narration_for(args, cfg: kit_config.KitConfig) -> tuple[NarrationInput, dict[str, Any] | None, dict[str, Any] | None]:
    """(入力, 台本, 台本から作った入力の dict)。"""
    path: Path = args.source
    if not path.is_file():
        raise InputError(f"ファイルがありません: {path}")
    if _is_storyboard(path):
        doc = _load_storyboard(path)
        try:
            data = storyboard_to_narration_input(doc, default_speaker=cfg.voice_speaker,
                                                 default_engine=cfg.voice_engine)
        except AdapterError as e:
            raise InputError(str(e)) from e
        if args.speaker is not None:
            data["speaker"] = args.speaker
        return parse_input(data), doc, data
    narration = load_input(path)
    if args.speaker is not None:
        narration = dataclasses.replace(narration, speaker=args.speaker)
    return narration, None, None


# -- commands ---------------------------------------------------------------------


def _cmd_list(args, cfg: kit_config.KitConfig, transport: Transport | None) -> int:
    engine = _engine(args.engine or cfg.voice_engine, args.engine_url or cfg.voice_url, args.timeout, transport)
    info = engine.check()
    voices = engine.voices()
    default = cfg.voice_speaker
    has_default = any(v.style_id == default for v in voices)
    if args.json:
        print(json.dumps({
            "engine": info.name, "engine_url": info.url, "version": info.version,
            "default_speaker": default, "default_speaker_found": has_default,
            "voices": [{"style_id": v.style_id, "speaker_name": v.speaker_name, "style_name": v.style_name,
                        "speaker_uuid": v.speaker_uuid} for v in voices],
            "models": info.models,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"engine:  {info.name} {info.url}（version {info.version}）")
        print(f"voices:  {len(voices)}")
        for v in voices:
            mark = "  ← 既定の声" if v.style_id == default else ""
            print(f"  {v.style_id:>12}  {v.label}{mark}")
        if info.models is not None:
            print(f"models:  {len(info.models)}")
            for m in info.models:
                print(f"  {m.get('name') or '(名前なし)'}  v{m.get('version') or '?'}  {m['uuid']}")
    if not voices:
        print("エラー: エンジンに声（音声モデル）が 1 つもありません。AivisSpeech の画面から声を入れてください", file=sys.stderr)
        return 1
    if not has_default:
        label = kit_config.DEFAULT_SPEAKER_LABEL if default == kit_config.DEFAULT_SPEAKER else ""
        print(f"注意: 既定の声 {default} {label}がエンジンにありません。声を入れるか、上の一覧から選んで"
              " config/kit.yaml の voice.speaker か --speaker で指定してください", file=sys.stderr)
    return 0


def _cmd_synth(args, cfg: kit_config.KitConfig, transport: Transport | None) -> int:
    if args.max_chars < 1:
        raise InputError("--max-chars は 1 以上を指定してください")
    narration, doc, data = _narration_for(args, cfg)
    engine_name = args.engine or narration.engine or cfg.voice_engine
    url = resolve_engine_url(args.engine_url, narration) or cfg.voice_url
    engine = _engine(engine_name, url, args.timeout, transport)
    _guard_confidential(doc, engine.url)
    dictionary, dict_paths = _dictionary(args, cfg)

    out_dir = args.out_dir
    if out_dir is None:
        name = doc["reel"]["id"] if doc else args.source.name.split(".")[0]
        out_dir = kit_config.output_root(cfg, args.output_root) / "voice" / name
    if data is not None:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / NARRATION_INPUT_FILENAME).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                                            encoding="utf-8")
        except OSError as e:
            raise OutputError(f"{out_dir} に書き込めません: {e}") from e
    for p in dict_paths:
        print(f"読み辞書: {p}", file=sys.stderr)
    run_synth(narration, out_dir, engine, dictionary=dictionary, force=args.force, max_chars=args.max_chars)
    print(f"書き出しました: {out_dir / DURATIONS_FILENAME}")
    if doc is not None:
        credit = cfg.credit_for(narration.speaker)
        if credit:
            print(f"クレジット: この声はクレジットの表記が必要です（{credit}）。erkit deck に --credit \"{credit}\" を付けてください")
    return 0


def _cmd_kana(args, cfg: kit_config.KitConfig, transport: Transport | None) -> int:
    from .kana import build_report, load_input_texts, load_storyboard_texts

    if args.max_chars < 1:
        raise InputError("--max-chars は 1 以上を指定してください")
    texts = []
    speakers: list[int] = []
    docs: list[dict[str, Any]] = []
    for path in args.sources:
        if not path.is_file():
            raise InputError(f"ファイルがありません: {path}")
        if _is_storyboard(path):
            found, speaker = load_storyboard_texts(path)
            docs.append(_load_storyboard(path))
        else:
            found, speaker = load_input_texts(path)
        texts += found
        if speaker is not None:
            speakers.append(speaker)
    speaker = args.speaker if args.speaker is not None else (speakers[0] if speakers else cfg.voice_speaker)
    engine = _engine(args.engine or cfg.voice_engine, args.engine_url or cfg.voice_url, args.timeout, transport)
    for doc in docs:
        _guard_confidential(doc, engine.url)
    dictionary, _ = _dictionary(args, cfg)
    report = build_report(texts, dictionary, engine, speaker=speaker, include_absent=args.all_terms,
                          sentences=args.sentences, max_chars=args.max_chars, sources=[str(p) for p in args.sources])
    print(report, end="")
    if args.out is not None:
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(report, encoding="utf-8")
        except OSError as cause:
            raise OutputError(f"{args.out} を書き込めません: {cause}") from cause
        print(f"書き出しました: {args.out}", file=sys.stderr)
    return 0


def run(args, *, transport: Transport | None = None) -> int:
    try:
        cfg = kit_config.load_config(args.config)
    except kit_config.ConfigError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return InputError.exit_code
    try:
        if args.voice_command == "list":
            return _cmd_list(args, cfg, transport)
        if args.voice_command == "kana":
            return _cmd_kana(args, cfg, transport)
        return _cmd_synth(args, cfg, transport)
    except NarrationError as error:
        print(f"エラー: {error}", file=sys.stderr)
        return error.exit_code
    except KeyboardInterrupt:
        print("中断しました", file=sys.stderr)
        return 130


def main(argv: Sequence[str] | None = None, *, transport: Transport | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # e.g. cp932 consoles on Windows
        except (AttributeError, ValueError):
            pass
    parser = configure(argparse.ArgumentParser(prog="erkit voice", description=HELP))
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    return run(args, transport=transport)
