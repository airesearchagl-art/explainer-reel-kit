"""``erkit`` コマンドの入口。

終了コード: 0 成功 / 1 台本が不合格・読めない / 2 引数の誤り・まだ実装していないサブコマンド。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from . import storyboard as sb

# 後のパケットで実装するサブコマンド（いまは案内を出して終了コード 2）
PLANNED = {
    "doctor": "環境の確認（Python・ffmpeg・AivisSpeech・PowerPoint など）",
    "new": "台本のひな形を作る",
    "diagram": "説明図（HTML）を PNG と注釈位置に描く",
    "capture": "Web 画面を撮影する",
    "record": "操作定義を人の操作で記録する",
    "voice": "声の一覧・読みの確認",
    "make": "台本から MP4 までの通し生成",
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

    for name, desc in PLANNED.items():
        sp = sub.add_parser(name, help=f"{desc}（後のパケットで実装）", add_help=False)
        sp.add_argument("rest", nargs=argparse.REMAINDER)
    return p


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
    print(f"erkit {args.cmd}: {PLANNED[args.cmd]} は、後のパケットで実装します（まだ使えません）", file=sys.stderr)
    return 2
