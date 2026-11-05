"""``erkit deck <台本> --out <.pptx>``: 台本からアニメーション付きの .pptx を作る。

終了コード: 0 成功 / 1 生成できない（台本不正・manual 画像の欠落・durations.json の形式違い） / 2 引数の誤り
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .builder import DEFAULT_SLIDE_SEC, BuildError, build_deck

HELP = "台本からアニメーション付きの .pptx を作る"


def configure(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument("storyboard", type=Path, metavar="台本", help="台本（.storyboard.md / .json）")
    p.add_argument("--out", required=True, type=Path, help="出力 .pptx")
    p.add_argument("--durations", type=Path, help="ナレーションの durations.json（slide_sec を自動切替の秒数に使う）")
    p.add_argument("--assets-root", type=Path, help="画像の起点フォルダ（既定: 台本ファイルのあるフォルダ）")
    p.add_argument("--overlay", type=Path, help="確認用の一覧画像（赤枠・矢印を画像に描いたもの）の出力先 .png")
    p.add_argument("--credit", help="outro に表示する音声のクレジット（クレジットが必要な声のとき）")
    p.add_argument("--default-sec", type=float, default=DEFAULT_SLIDE_SEC,
                   help=f"秒数の指定がないスライドの秒数（既定 {DEFAULT_SLIDE_SEC}）")
    p.set_defaults(func=run)
    return p


def register(sub) -> None:
    configure(sub.add_parser("deck", help=HELP, description=HELP))


def run(args) -> int:
    if not args.storyboard.is_file():
        print(f"エラー: 台本がありません: {args.storyboard}", file=sys.stderr)
        return 2
    if args.durations and not args.durations.is_file():
        print(f"エラー: durations.json がありません: {args.durations}", file=sys.stderr)
        return 2
    if args.out.suffix.lower() != ".pptx":
        print("エラー: --out は .pptx を指定してください", file=sys.stderr)
        return 2
    if args.default_sec <= 0:
        print("エラー: --default-sec は正の数にしてください", file=sys.stderr)
        return 2
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        res = build_deck(args.storyboard, args.out, durations=args.durations, assets_root=args.assets_root,
                         default_sec=args.default_sec, credit=args.credit, overlay=args.overlay)
    except BuildError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    for w in res.warnings:
        print(f"警告: {w}", file=sys.stderr)
    if res.unresolved:
        print(f"警告: 未確定の注釈が {len(res.unresolved)} 件あります（既定位置で置きました）: {res.unresolved_text()}",
              file=sys.stderr)
    if res.overlay:
        print(f"確認用の一覧画像: {res.overlay}")
    total = sum(res.adv_ms) / 1000
    print(f"書き出しました: {res.output}（slides={res.slide_count}, total={total:.2f}s, "
          f"placeholders={len(res.placeholders)}, unresolved_marks={len(res.unresolved)}, warnings={len(res.warnings)}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = configure(argparse.ArgumentParser(prog="erkit deck", description=HELP))
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    return run(args)
