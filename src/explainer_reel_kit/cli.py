"""``erkit`` コマンドの入口。

終了コード: 0 成功 / 1 台本が不合格・読めない、撮影・説明図で失敗したシーンがある / 2 引数の誤り・台本や操作定義の不備で始められない・
まだ実装していないサブコマンド。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from . import storyboard as sb
from . import doctor
from .deck import cli as deck_cli
from .narration import cli as narration_cli
from .reel import cli as make_cli

# 後のパケットで実装するサブコマンド（いまは案内を出して終了コード 2）
PLANNED = {
    "new": "台本のひな形を作る",
    "draft": "手元の LLM で台本のたたき台を作る（社外秘の資料用）",
}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="erkit", description="台本からナレーション付きの説明動画を作るキット")
    p.add_argument("--version", action="version", version=f"erkit {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    c = sub.add_parser("check", help="台本を検証する（区分も表示）")
    c.add_argument("storyboards", nargs="+", type=Path, metavar="台本", help=".storyboard.md / .json")
    c.add_argument("--strict", action="store_true", help="警告も不合格にする")
    c.add_argument("--quiet", action="store_true", help="合格した台本は 1 行だけ表示する")

    v = sub.add_parser("convert", help="Markdown の台本を JSON にする")
    v.add_argument("storyboard", type=Path, metavar="台本.md")
    v.add_argument("-o", "--out", type=Path, help="出力先（既定: 同じ場所の .json）")
    v.add_argument("--stdout", action="store_true", help="ファイルに書かず標準出力へ")

    deck_cli.register(sub)
    narration_cli.register(sub)
    make_cli.register(sub)
    doctor.register(sub)
    _add_media_parsers(sub)

    for name, desc in PLANNED.items():
        sp = sub.add_parser(name, help=f"{desc}（後のパケットで実装）", add_help=False)
        sp.add_argument("rest", nargs=argparse.REMAINDER)
    return p


def _browser_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--channel", help="インストール済みのブラウザを使う（msedge / chrome）")
    p.add_argument("--executable", help="ブラウザの実行ファイルのパス")


def _add_media_parsers(sub) -> None:
    d = sub.add_parser("diagram", help="説明図（HTML）を PNG と注釈位置（marks.json）に描く",
                       description="台本の capture: {tool: html, src: …} のシーンを、ネットワークを止めたブラウザで描く")
    d.add_argument("storyboard", type=Path, metavar="台本")
    d.add_argument("--out", type=Path, help="出力先（既定: 台本のフォルダ。画像は <出力先>/<image.ref>）")
    d.add_argument("--only", nargs="+", metavar="ID", help="このシーンだけ描く")
    d.add_argument("--overlay", type=Path, metavar="PNG", help="注釈位置を描き込んだ確認画像も書く")
    _browser_args(d)

    c = sub.add_parser("capture", help="Web 画面を撮影する（操作定義に従う）",
                       description="台本の image.source: web のシーンを、操作定義に従って撮影する")
    c.add_argument("storyboard", type=Path, metavar="台本")
    c.add_argument("--check", action="store_true", help="撮らずに、操作定義と台本の突き合わせだけ行う（ブラウザ不要）")
    c.add_argument("--actions", type=Path, help="操作定義（既定: 台本と同じフォルダの <reel id>.actions.yaml）")
    c.add_argument("--out", type=Path, help="保存先（既定: <撮影素材のルート>/web/<ツール名>）")
    c.add_argument("--tool", help="ツール名（--out を省略したときのフォルダ名。既定は reel id）")
    c.add_argument("--captures-root", type=Path,
                   help="撮影素材のルート（既定: 環境変数 ERKIT_CAPTURES_ROOT、無ければホームの ExplainerReelKit/captures）")
    c.add_argument("--serve", type=Path, metavar="フォルダ",
                   help="このフォルダをこの PC で配信して撮る（台本の http://localhost/… と http://127.0.0.1/… を置き換える）")
    c.add_argument("--only", nargs="+", metavar="ID", help="このシーンだけ撮る（状態を作る前のシーンの操作は再現する）")
    c.add_argument("--url-map", action="append", default=[], metavar="旧=新", help="URL の先頭を置き換える（file:// にもできる）")
    c.add_argument("--headed", action="store_true", help="画面を表示して実行する（確認用）")
    c.add_argument("--overlay", type=Path, metavar="PNG", help="注釈位置を描き込んだ確認画像も書く")
    _browser_args(c)

    r = sub.add_parser("record", help="人の操作を記録して操作定義を作る（画面ありのブラウザが開く）",
                       description="F8 でシーンを区切る / Shift＋クリックで mark / F10 で終了")
    r.add_argument("--url", required=True, help="記録するページ（http(s):// か file://）")
    r.add_argument("--reel", required=True, help="台本の reel.id（操作定義の reel_id）")
    r.add_argument("--out", required=True, type=Path, help="新しい操作定義のファイル（既存のファイルは上書きしない）")
    r.add_argument("--start", type=int, default=1, help="最初のシーン番号（既定 1 → s01）")
    r.add_argument("--viewport", default="1600x660", help="画面の大きさ（既定 1600x660 ＝ 画像枠の縦横比）")
    r.add_argument("--serve", type=Path, metavar="フォルダ", help="このフォルダをこの PC で配信して記録する")
    r.add_argument("--no-verify", action="store_true", help="記録後の再生による確かめを省く")
    _browser_args(r)


def _overlay(result_json: Path, out: Path) -> None:
    from .capture.web import overlay

    try:
        used = overlay.build_overlay(result_json, out)
        print(f"確認画像: {out}（{', '.join(used)}）")
    except ValueError as e:
        print(f"WARN 確認画像を作れません: {e}", file=sys.stderr)


def _cmd_diagram(args) -> int:
    from . import diagram as dg

    try:
        res = dg.run_diagram(args.storyboard, args.out, args.only, args.channel, args.executable)
    except dg.DiagramError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 2
    result = Path(res["assets_root"]) / dg.RESULT_NAME
    print(f"説明図 {res['ok']} 件 / 失敗 {res['failed']} 件 → {result}")
    if args.overlay:
        _overlay(result, args.overlay)
    return 0 if res["failed"] == 0 else 1


def _cmd_capture(args) -> int:
    from .capture.web import capture as wc

    try:
        if args.check:
            doc = wc.load_storyboard(args.storyboard)
            path = args.actions or wc.default_actions_path(args.storyboard, doc["reel"]["id"])
            rep = wc.crosscheck(doc, wc.load_actions(path))
            for w in rep.warnings:
                print(f"WARN {w}")
            for e in rep.errors:
                print(f"ERROR {e}", file=sys.stderr)
            if rep.ok:
                print(f"OK {path.name}: web シーン {len(wc.web_scenes(doc))} 件すべてに操作定義があります")
            return 0 if rep.ok else 1
        out = args.out or wc.default_out_dir(wc.load_storyboard(args.storyboard), args.tool, args.captures_root)
        res = wc.run_capture(args.storyboard, out, args.actions, args.only, wc.parse_url_map(args.url_map),
                             args.channel, args.executable, args.headed, serve=args.serve)
    except wc.CaptureError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 2
    result = Path(res["assets_root"]) / wc.RESULT_NAME
    print(f"撮影 {res['ok']} 件 / 失敗 {res['failed']} 件 → {result}")
    if args.overlay:
        _overlay(result, args.overlay)
    return 0 if res["failed"] == 0 else 1


def _cmd_record(args) -> int:
    from .capture.web import recorder as rc

    try:
        res = rc.record(args.url, args.reel, args.out, start=args.start, viewport=rc.parse_viewport(args.viewport),
                        channel=args.channel, executable=args.executable, verify=not args.no_verify,
                        serve=args.serve)
    except rc.CaptureError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 2
    return 0 if not res["problems"] else 1


def _cmd_check(args) -> int:
    failed = 0
    for path in args.storyboards:
        if not path.is_file():
            print(f"NG {path}: ファイルがありません", file=sys.stderr)
            failed += 1
            continue
        rep = sb.validate_file(path)
        level = "-"
        try:
            level = sb.confidentiality(sb.load_storyboard(path))
        except Exception:  # 読めない台本は validate_file がエラーとして報告している
            pass
        bad = bool(rep.errors) or (args.strict and bool(rep.warnings))
        head = "NG" if bad else "OK"
        print(f"{head} {path}（区分: {level}、エラー {len(rep.errors)}、警告 {len(rep.warnings)}）")
        if not (args.quiet and not bad):
            for e in rep.errors:
                print(f"  エラー: {e}")
            for w in rep.warnings:
                print(f"  警告: {w}")
        failed += bad
    return 1 if failed else 0


def _cmd_convert(args) -> int:
    try:
        doc = sb.markdown_to_storyboard(args.storyboard.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        print(f"ファイルがありません: {args.storyboard}", file=sys.stderr)
        return 1
    except sb.ConversionError as e:
        print(f"変換できません: {e}", file=sys.stderr)
        return 1
    text = sb.dump_json(doc)
    if args.stdout:
        sys.stdout.write(text)
        return 0
    out = args.out or args.storyboard.with_name(args.storyboard.name.removesuffix(".md") + ".json")
    out.write_text(text, encoding="utf-8")
    print(f"書き出しました: {out}")
    return 0


MEDIA = {"diagram": _cmd_diagram, "capture": _cmd_capture, "record": _cmd_record}


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows のコンソールでも日本語を出す
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # argparse の誤り（2）と --version / --help（0）
        return int(e.code or 0)
    if args.cmd is None:
        parser.print_help()
        return 2
    if args.cmd == "check":
        return _cmd_check(args)
    if args.cmd == "convert":
        return _cmd_convert(args)
    if hasattr(args, "func"):
        return args.func(args)
    if args.cmd in MEDIA:
        return MEDIA[args.cmd](args)
    print(f"erkit {args.cmd}: {PLANNED[args.cmd]} は、後のパケットで実装します（まだ使えません）", file=sys.stderr)
    return 2
