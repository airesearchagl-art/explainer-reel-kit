#!/usr/bin/env python3
"""公開してよいかの点検（標準ライブラリだけ）。

リポジトリの追跡ファイル（git ls-files）を、個人の情報・秘密情報・持ち込んではいけないものの
パターンで検査する。1 件でも当たれば終了コード 1。

    python tools/check_public.py                  # 追跡ファイルを検査
    python tools/check_public.py --history        # あわせて commit の名前・メールを検査（noreply 以外は失敗）
    python tools/check_public.py --history --head-only   # 履歴は HEAD から辿れるものだけ（CI 用）
    python tools/check_public.py --root DIR       # git を使わず DIR の下を全部検査（テスト・確認用）

持ち主だけが知っている語（個人名・会社名・別のプロジェクト名など）は、このファイルにもリポジトリにも書かない。
次のどちらか（両方なら両方）で渡す。どちらも無ければ、その検査は飛ばして注意を出す。

- 環境変数 KIT_DENY_WORDS: 語を | で区切る（正規表現。CI では GitHub の Secrets から渡す）
- ファイル: 環境変数 KIT_DENY_WORDS_FILE のパス、無ければリポジトリ直下の .kit-deny-words（.gitignore 済み）。
  1 行 1 語（正規表現）。# で始まる行と空行は無視

意図して残すものは tools/check_public.allow に `<パスの glob>:<行に当てる正規表現>` を 1 行ずつ書く
（理由は # のコメントで）。当たった行がどれかに合えば数えない。
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve()
ALLOW_FILE = Path("tools/check_public.allow")
DENY_FILE_DEFAULT = ".kit-deny-words"
SELF_EXCLUDE = ("tools/check_public.py", "tools/check_public.allow")

BIG_EXT = re.compile(r"\.(mp4|wav|pptx|mov|aivm|aivmx|onnx)$", re.I)

# (番号, 名前, パターン)。点検表の 1〜3・5〜9。4 は持ち主の語（下の deny）、0 は大きな生成物（BIG_EXT）
PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("1", "Notion の ID・URL", re.compile(
        r"(?:^|[^0-9a-f])[0-9a-f]{32}(?:[^0-9a-f]|$)"
        r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        r"|notion\.(?:so|site|com)", re.I)),
    ("2", "メールアドレス", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("3", "個人のパス", re.compile(r"\b[A-Za-z]:[\\/]|/Users/|\\Users\\|/home/[a-z]")),
    ("5", "動画の公開先・個人のサイト", re.compile(r"youtube\.com|youtu\.be|\bUC[0-9A-Za-z_-]{22}\b|vercel\.app", re.I)),
    ("6", "開発体制の言葉", re.compile(r"Hub review|派生スレッド|\b98(?:77|80)\b|\b[A-D]-M[0-9]+-[0-9]{2}\b")),
    ("7", "秘密情報の名前・置き場所", re.compile(
        r"NOTION_TOKEN|client_secret|token\.json|\.explainer-reel[\\/]|api_key\s*[:=]\s*\S")),
    ("8", "秘密情報そのものの形", re.compile(
        r"sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|AIza[0-9A-Za-z_-]{35}|secret_[A-Za-z0-9]{40,}|ntn_[A-Za-z0-9]{40,}")),
    ("9", "仕事・取引先の言葉", re.compile(r"施主|ゼネコン|設計部|社内専門家|案件")),
]
NOREPLY = re.compile(r"(?:^|[.+])noreply@|@users\.noreply\.github\.com$", re.I)


@dataclass
class Hit:
    path: str
    line: int
    rule: str
    text: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.text}"


def _run_git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def list_files(root: Path, use_git: bool) -> list[str]:
    if use_git:
        out = _run_git(root, "ls-files", "-z")
        return [p for p in out.split("\0") if p]
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and ".git" not in p.relative_to(root).parts)


def load_deny(root: Path, env: dict[str, str]) -> tuple[re.Pattern[str] | None, list[str]]:
    words: list[str] = []
    sources: list[str] = []
    raw = env.get("KIT_DENY_WORDS", "").strip()
    if raw:
        words += [w for w in raw.split("|") if w.strip()]
        sources.append("環境変数 KIT_DENY_WORDS")
    fpath = Path(env["KIT_DENY_WORDS_FILE"]) if env.get("KIT_DENY_WORDS_FILE") else root / DENY_FILE_DEFAULT
    if fpath.is_file():
        for ln in fpath.read_text(encoding="utf-8-sig").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                words.append(ln)
        sources.append(f"ファイル {fpath.name}")
    if not words:
        return None, sources
    return re.compile("|".join(f"(?:{w.strip()})" for w in words), re.I), sources


def load_allow(root: Path) -> list[tuple[str, re.Pattern[str]]]:
    path = root / ALLOW_FILE
    rules = []
    if path.is_file():
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            glob, _, rx = ln.partition(":")
            rules.append((glob.strip(), re.compile(rx.strip())))
    return rules


def _allowed(rel: str, text: str, allow: list[tuple[str, re.Pattern[str]]]) -> bool:
    return any(fnmatch.fnmatch(rel, g) and rx.search(text) for g, rx in allow)


def scan(root: Path, files: list[str], deny: re.Pattern[str] | None,
         allow: list[tuple[str, re.Pattern[str]]]) -> list[Hit]:
    hits: list[Hit] = []
    rules = list(PATTERNS) + ([("4", "持ち主の語", deny)] if deny is not None else [])
    for rel in files:
        if rel in SELF_EXCLUDE or rel == DENY_FILE_DEFAULT:
            continue
        if BIG_EXT.search(rel):
            hits.append(Hit(rel, 0, "0 大きな生成物", "追跡してはいけない種類のファイル"))
            continue
        path = root / rel
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue  # バイナリ（画像など）は文字の検査をしない
        text = data.decode("utf-8", errors="replace")
        for no, line in enumerate(text.splitlines(), 1):
            for num, name, rx in rules:
                if num == "2":
                    found = [m for m in rx.findall(line) if not NOREPLY.search(m)]
                    if not found:
                        continue
                elif not rx.search(line):
                    continue
                if _allowed(rel, line, allow):
                    continue
                shown = "（持ち主の語。表示しません）" if num == "4" else line.strip()[:120]
                hits.append(Hit(rel, no, f"{num} {name}", shown))
    return hits


def scan_history(root: Path, rev: str = "--all") -> list[Hit]:
    """commit の作者・コミッター・Co-authored-by のメールが noreply だけか（rev: --all か HEAD）。"""
    out = _run_git(root, "log", rev, "--format=%H%x1f%ae%x1f%ce%x1f%(trailers:key=Co-authored-by,valueonly,separator=%x1e)")
    hits = []
    for row in out.splitlines():
        if not row.strip():
            continue
        sha, author, committer, trailers = (row.split("\x1f") + ["", "", ""])[:4]
        mails = [author, committer] + re.findall(r"<([^>]+)>", trailers)
        for m in mails:
            if m and not NOREPLY.search(m):
                hits.append(Hit(f"commit {sha[:7]}", 0, "履歴のメール", "noreply 以外のアドレス（表示しません）"))
    return hits


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="公開してよいかの点検")
    ap.add_argument("--root", type=Path, help="git を使わず、このフォルダの下を全部検査する")
    ap.add_argument("--history", action="store_true", help="commit の名前・メールも検査する")
    ap.add_argument("--head-only", action="store_true",
                    help="履歴は HEAD から辿れる commit だけを見る（CI で、GitHub が作る仮のマージ commit を除くため）")
    ap.add_argument("--require-deny-words", action="store_true", help="持ち主の語が無ければ失敗にする")
    args = ap.parse_args(argv)

    use_git = args.root is None
    root = (args.root or HERE.parent.parent).resolve()
    deny, sources = load_deny(root, dict(os.environ))
    files = list_files(root, use_git)
    hits = scan(root, files, deny, load_allow(root))
    if args.history:
        hits += scan_history(root, "HEAD" if args.head_only else "--all")

    for h in hits:
        print(h)
    print(f"検査したファイル {len(files)}、当たり {len(hits)}")
    if deny is None:
        msg = "持ち主の語（KIT_DENY_WORDS / .kit-deny-words）が無いため、その検査は飛ばしました"
        print(("エラー: " if args.require_deny_words else "注意: ") + msg, file=sys.stderr)
        if args.require_deny_words:
            return 1
    else:
        print(f"持ち主の語: {', '.join(sources)}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
