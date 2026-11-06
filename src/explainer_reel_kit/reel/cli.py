"""``erkit make <台本>``: 台本から MP4 までの通し生成。

終了コード: 0 できた（Windows 以外では .pptx まで作り、書き出しの手順を表示して 0） /
1 前提が足りない・社外秘の確かめで止めた・段が失敗した / 2 引数・台本の誤り
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import config as kit_config
from .make import STAGE_TITLES, STAGES, Hooks, MakeError, MakeOptions, make

HELP = "台本から MP4 までを通しで作る（撮影 → 説明図 → ナレーション → スライド → 書き出し → 音声の合成）"


def configure(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument("storyboard", type=Path, metavar="台本", help=".storyboard.md / .json")
    p.add_argument("--from", dest="from_stage", choices=STAGES, metavar="段",
                   help="この段から再開する（" + " / ".join(STAGES) + "）。前回の出力フォルダを使う")
    p.add_argument("--dry-run", action="store_true", help="何もせず、段の順番・入力・出力を表示する")
    p.add_argument("--offline", action="store_true", help="この PC の外へ出る設定があれば何もせずに止める（社外秘の台本は常に確かめる）")
    p.add_argument("--label", help="出力フォルダ名の最後に付ける一言（例: 試作）")
    p.add_argument("--allow-placeholders", action="store_true",
                   help="画像の無いシーン・位置の決まらない注釈があっても作る（灰色の枠・既定の位置。試作用）")
    p.add_argument("--force", action="store_true", help="内容が変わったナレーションの WAV を上書きする")
    p.add_argument("--config", type=Path, help="設定ファイル（既定: config/kit.yaml を探す）")
    g = p.add_argument_group("場所")
    g.add_argument("--output-root", type=Path, help="出力先のルート（既定: 設定、無ければユーザーのフォルダの ExplainerReelKit/output）")
    g.add_argument("--out-dir", type=Path, help="出力フォルダそのもの（--from では再開するフォルダ）")
    g.add_argument("--captures-root", type=Path, help="撮影素材のルート（既定: 設定、無ければユーザーのフォルダの ExplainerReelKit/captures）")
    g.add_argument("--assets-root", type=Path, help="画像をすべてこのフォルダから使う（撮影は省略）")
    c = p.add_argument_group("撮影・説明図")
    c.add_argument("--no-capture", action="store_true", help="撮影せず、撮影素材のフォルダにある画像を使う（撮影済みのとき）")
    c.add_argument("--actions", type=Path, help="操作定義（既定: 台本と同じフォルダの <reel id>.actions.yaml）")
    c.add_argument("--serve", type=Path, metavar="フォルダ", help="このフォルダをこの PC で配信して撮る（台本の localhost / 127.0.0.1 の URL を置き換える）")
    c.add_argument("--url-map", action="append", default=[], metavar="旧=新", help="撮影の URL の先頭を置き換える")
    c.add_argument("--channel", help="ブラウザ（msedge / chrome）。既定は Playwright の Chromium")
    c.add_argument("--executable", help="ブラウザの実行ファイルのパス")
    v = p.add_argument_group("ナレーション")
    v.add_argument("--engine", help="音声合成エンジン（既定: 台本・設定・aivisspeech）")
    v.add_argument("--engine-url", help="エンジンの URL（既定: 設定、無ければ http://127.0.0.1:10101）")
    v.add_argument("--speaker", type=int, help="声（style id）。台本・設定より優先する")
    v.add_argument("--dictionary", action="append", default=None, metavar="名前|パス", help="読み辞書（既定: 設定の voice.dictionaries）")
    p.set_defaults(func=run)
    return p


def register(sub) -> None:
    configure(sub.add_parser("make", help=HELP, description=HELP))


def options_from_args(args) -> MakeOptions:
    from ..capture.web.capture import CaptureError, parse_url_map

    try:
        url_map = parse_url_map(args.url_map)
    except CaptureError as e:
        raise MakeError(str(e)) from e
    if args.serve is not None and not args.serve.is_dir():
        raise MakeError(f"--serve のフォルダがありません: {args.serve}")
    return MakeOptions(
        storyboard=args.storyboard, label=args.label, output_root=args.output_root, out_dir=args.out_dir,
        captures_root=args.captures_root, assets_root=args.assets_root, actions=args.actions, serve=args.serve,
        url_map=url_map, channel=args.channel, executable=args.executable, engine=args.engine,
        engine_url=args.engine_url, speaker=args.speaker, dictionaries=args.dictionary,
        allow_placeholders=args.allow_placeholders, no_capture=args.no_capture, from_stage=args.from_stage, dry_run=args.dry_run,
        offline=args.offline, force=args.force)


def run(args, *, hooks: Hooks | None = None, platform: str | None = None) -> int:
    try:
        cfg = kit_config.load_config(args.config)
        opts = options_from_args(args)
        if platform is not None:
            opts.platform = platform
        make(opts, cfg, hooks)
    except kit_config.ConfigError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    except MakeError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return e.exit_code
    return 0


def main(argv: list[str] | None = None, **kw) -> int:
    parser = configure(argparse.ArgumentParser(prog="erkit make", description=HELP))
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    return run(args, **kw)


__all__ = ["STAGES", "STAGE_TITLES", "configure", "main", "register", "run"]
