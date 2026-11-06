"""文書の中の `erkit …` を抜き出して、erkit の引数の解析と照らし合わせる道具（test_guide・test_plugin が使う）。

- コードブロックの行と、行内のコード（`erkit …`）を抜き出す
- 後で実装するサブコマンド（new）、PowerShell で記号になる `<` `>`、省略の `…` を禁止する
- サンプルのパス（samples/・examples/・src/ など）が実在するかを確かめる
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

from explainer_reel_kit import cli
from explainer_reel_kit.cli import PLANNED

ROOT = Path(__file__).resolve().parent.parent

FENCE = re.compile(r"^\s*```")
INLINE = re.compile(r"`([^`\n]+)`")
# erkit の前が語の一部（explainer-reel-kit・.venv/Scripts/erkit のパス）でないもの。} や | や # の手前まで
CMD_IN_LINE = re.compile(r"(?<![\w./\\-])(?:\.\\erkit\.ps1|\./erkit\.ps1|erkit)\s+([^}|#`]*)")
PATH_PREFIXES = ("samples/", "examples/", "src/", "dictionaries/", "config/")


def extract_commands(path: Path) -> list[tuple[int, str]]:
    """(行番号, erkit の後ろの引数の文字列)。"""
    found: list[tuple[int, str]] = []
    in_code = False
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            in_code = not in_code
            continue
        if in_code:
            found += [(no, m.group(1).strip()) for m in CMD_IN_LINE.finditer(line)]
        else:
            for span in INLINE.findall(line):
                m = re.match(r"^(?:\.\\erkit\.ps1|erkit)\s+(.+)$", span.strip())
                if m:
                    found.append((no, m.group(1).strip()))
    return found


def _choices(parser) -> dict:
    for act in parser._actions:  # argparse のサブコマンドの一覧
        if getattr(act, "choices", None) and isinstance(act.choices, dict):
            return act.choices
    return {}


def _is_name_only(parser, tokens: list[str]) -> bool:
    """引数の無いサブコマンドの名前だけ（例 `erkit check`・`erkit voice kana`）。名前は実在しなければならない。"""
    top = _choices(parser)
    if tokens[0] not in top or len(tokens) > 2:
        return False
    if len(tokens) == 1:
        return True
    sub = _choices(top[tokens[0]])
    return bool(sub) and tokens[1] in sub


def check_command(args: str, where: str) -> list[str]:
    """問題の一覧を返す（空なら合格）。"""
    if "<" in args or ">" in args:
        return [f"仮の文字（< >）が残っている: {where}"]
    if "…" in args:
        return [f"省略の記号が残っている: {where}"]
    tokens = shlex.split(args.replace("\\", "/"))
    if not tokens:
        return [f"引数が無い: {where}"]
    if tokens[0] in PLANNED:
        return [f"まだ使えないサブコマンド: {where}"]
    parser = cli._build_parser()
    if _is_name_only(parser, tokens):
        return []  # 文の中でサブコマンドの名前を挙げただけ（`erkit check` が通るまで…）
    try:
        parser.parse_args(tokens)
    except SystemExit as e:
        if e.code not in (0, None):  # --version・--help は 0 で終わる
            return [f"引数が erkit と合わない（{e.code}）: {where}"]
    return [f"無いパス {tok}: {where}" for tok in tokens
            if tok.startswith(PATH_PREFIXES) and not (ROOT / tok).exists()]
