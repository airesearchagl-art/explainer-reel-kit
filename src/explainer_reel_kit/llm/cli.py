"""``erkit draft`` と ``erkit llm check``（手元の LLM。任意の段）。

    erkit draft <台本の id> --source <資料> [--source <資料> …]   資料から台本の下書きを reels/<id>/ に作る
    erkit draft <台本の id> --update-marks [--actions <操作定義>]  下書きに mark の名前を入れる（LLM は使わない）
    erkit llm check                                               接続・モデルの有無・応答までの時間

終了コード: 0 できた・合格 / 1 下書きが検証に通らない・LLM の失敗・モデルが無い・社外秘の確かめで止めた・上書きを止めた /
2 引数・設定の誤り
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Sequence

from .. import storyboard as sb
from .client import LLMClient
from .config import Endpoint, LLMConfig, host_kind, load_llm_config, task_settings
from .confidentiality import CONFIDENTIAL, GENERAL, VALUES
from .errors import ConfigError, LLMToolError, ModelNotFoundError
from .thinking import THINKING_MODES, ThinkingSender

CHECK_PROMPT = "「準備できました」とだけ返してください。"
DRAFT_TASK = "draft"
LIGHT_TASK = "light"


# -- 共通の引数 ---------------------------------------------------------------------------------

def add_llm_arguments(parser: argparse.ArgumentParser) -> None:
    g = parser.add_argument_group("手元の LLM")
    g.add_argument("--llm-config", type=Path, default=None,
                   help="LLM の設定（既定: 環境変数 ERKIT_LLM_CONFIG ＞ config/llm.yaml ＞ 組み込みの既定）")
    g.add_argument("--profile", default=None, help="設定の profiles の名前（既定: default_profile。lmstudio / ollama）")
    g.add_argument("--base-url", default=None, help="profile の base_url の代わり（例 http://127.0.0.1:1234/v1）")
    g.add_argument("--model", default=None, help="使うモデルの id（既定: 設定、無ければサーバーに読み込まれている 1 つ）")
    g.add_argument("--llm-timeout", type=float, default=None, help="LLM への 1 回の問い合わせのタイムアウト秒（既定 600）")


def config_from_args(args: argparse.Namespace) -> LLMConfig:
    return load_llm_config(args.llm_config)


def endpoint_from_args(args: argparse.Namespace, config: LLMConfig) -> Endpoint:
    return config.endpoint(args.profile).with_overrides(base_url=args.base_url, model=args.model,
                                                        timeout_sec=args.llm_timeout)


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# -- parser ---------------------------------------------------------------------------------------

def register(sub) -> None:
    d = sub.add_parser("draft", help="資料から、手元の LLM で台本の下書きを作る（reels/<id>/）",
                       description="資料（手元のテキスト）から、手元の LLM で台本の下書きを作り、erkit check で確かめる。"
                                   "できるのは下書き。人が直してから使う")
    d.add_argument("reel_id", metavar="台本の id", help="英小文字・数字・-・_（例 my-tool）")
    d.add_argument("--source", type=Path, action="append", default=[], metavar="資料",
                   help="資料のテキスト（UTF-8。複数可）。手元のファイルだけを読む")
    d.add_argument("--title", default=None, help="動画の題名（省略時は LLM の案）")
    d.add_argument("--audience", choices=["A", "B", "C"], default="A",
                   help="見る人: A 初めての人（既定） / B よく使う人・詳しい人 / C 専門家・作る人")
    d.add_argument("--kind", choices=list(sb.KINDS), default="tool_intro",
                   help="tool_intro ツールの紹介（既定） / work_manual 作業の手順 / explainer 一般の解説（--scenes は 5〜7）")
    d.add_argument("--capture", choices=["diagram", "web", "manual"], default="diagram",
                   help="画像の作り方（全シーン）: diagram 説明図（既定） / web Web 画面の撮影（--url が要る） / manual 人が用意する")
    d.add_argument("--url", default=None, help="--capture web のときの URL")
    d.add_argument("--scenes", type=int, default=None, help="本編のシーン数（intro・outro を除く。既定 5）")
    d.add_argument("--confidentiality", choices=VALUES, default=CONFIDENTIAL,
                   help="台本の区分（既定 confidential）。confidential のとき LLM と --url はこの PC だけ。"
                        "general にしてよいのは、資料が公開済みの情報だけだと人が確かめたとき")
    d.add_argument("--offline", action="store_true",
                   help="ネットワークを使わないことの確かめ。LLM と --url がこの PC でなければ何もせずに止める")
    d.add_argument("--out", type=Path, default=None, help="出力フォルダ（既定 reels/<台本の id>）")
    d.add_argument("--thinking", choices=THINKING_MODES, default=None, help="思考（既定: 設定の task draft、無ければ off）")
    d.add_argument("--max-tokens", type=int, default=None, help="答えの長さの上限（既定: シーン数から決める）")
    d.add_argument("--retries", type=int, default=2, help="検査に通らないときの書き直しの回数（既定 2）")
    d.add_argument("--no-measure", action="store_true", help="資料のトークン数をサーバーで測らず、見積もりだけで決める")
    d.add_argument("--update-marks", action="store_true",
                   help="LLM を使わず、下書きに mark の名前を入れる（操作定義の marks・説明図の data-mark から）")
    d.add_argument("--actions", type=Path, default=None,
                   help="--update-marks の操作定義（既定: 台本の隣の <id>.actions.yaml。あれば）")
    add_llm_arguments(d)
    d.set_defaults(func=run_draft)

    llm = sub.add_parser("llm", help="手元の LLM の確かめ", description="手元の LLM（OpenAI 互換の API）の確かめ")
    llm_sub = llm.add_subparsers(dest="llm_command", metavar="<check>")
    llm_sub.required = True
    c = llm_sub.add_parser("check", help="接続・モデルの有無・応答までの時間",
                           description="決まった短い文だけを送って、接続・モデルの有無・応答までの時間を確かめる（資料は送らない）")
    c.add_argument("--task", default=None,
                   help=f"どの task のモデルを確かめるか（既定: 設定に {DRAFT_TASK} があればそれ。none で task を使わない）")
    c.add_argument("--json", action="store_true", help="結果を JSON で出す")
    add_llm_arguments(c)
    c.set_defaults(func=run_check)


# -- erkit draft ---------------------------------------------------------------------------------

def _print_check(path: Path) -> bool:
    rep = sb.validate_file(path)
    level = sb.confidentiality(sb.load_storyboard(path))
    print(f"{'NG' if rep.errors else 'OK'} {path}（区分: {level}、エラー {len(rep.errors)}、警告 {len(rep.warnings)}）")
    for e in rep.errors:
        print(f"  エラー: {e}")
    for w in rep.warnings:
        print(f"  警告: {w}")
    return not rep.errors


def _cmd_update_marks(args: argparse.Namespace) -> int:
    from .draft import default_out_dir, storyboard_path
    from .marks import update_marks

    path = storyboard_path(args.out or default_out_dir(args.reel_id), args.reel_id)
    result = update_marks(path, args.actions)
    for sid, marks in result.updated.items():
        print(f"{sid}: mark を入れました: {', '.join(marks)}")
    for sid, reason in result.skipped.items():
        print(f"{sid}: そのまま（{reason}）")
    for warning in result.warnings:
        print(f"注意: {warning}", file=sys.stderr)
    if not result.updated:
        print(f"変更なし: {result.path}")
    else:
        print(f"台本: {result.path}（recipe_params の行を足しただけ。ほかの行は変えていない）")
    return 0 if _print_check(path) else 1


def _cmd_draft(args: argparse.Namespace) -> int:
    from .draft import DraftRequest, default_out_dir, draft_storyboard
    from .offline import OfflineError, require, url_check

    if args.update_marks:
        return _cmd_update_marks(args)
    if args.retries < 0:
        raise ConfigError("--retries は 0 以上にしてください")
    config = config_from_args(args)
    req = DraftRequest(reel_id=args.reel_id, sources=list(args.source), title=args.title, audience=args.audience,
                       capture=args.capture, url=args.url, scenes=args.scenes, kind=args.kind,
                       confidentiality=args.confidentiality, avoid_words=config.avoid_words)
    req.validate()  # 何かを送る・作る前に
    endpoint = endpoint_from_args(args, config)
    offline_checks = None
    reasons = (["--offline"] if args.offline else []) + (["社外秘"] if req.confidentiality != GENERAL else [])
    if reasons:  # 社外秘（既定）は、--offline と同じ確かめを自動で行う
        checks = [url_check("LLM の base_url", endpoint.base_url)]
        if req.capture == "web":
            checks.append(url_check("--url（capture.url）", req.url))
        try:
            offline_checks = require(checks)  # 何も送らず・作らずに止める
        except OfflineError as error:
            if "--offline" in reasons:
                raise
            raise OfflineError(str(error).replace("--offline:", "社外秘の区分（confidential）:", 1)
                               + "\n  社外秘の資料は、この PC で動く LLM にだけ送ります。撮影する画面もこの PC で動かしてください") \
                from error
        _log(f"{'・'.join(reasons)}: " + "、".join(f"{c['item']}={c['value']}" for c in offline_checks)
             + " はこの PC（OK）")
    client = LLMClient(endpoint, confidentiality=req.confidentiality)  # ここで区分の確かめ（送る直前にも）
    out_dir = args.out or default_out_dir(req.reel_id)
    result = draft_storyboard(client, req, out_dir, task=config.tasks.get(DRAFT_TASK), explicit_model=args.model,
                              explicit_thinking=args.thinking, explicit_max_tokens=args.max_tokens,
                              retries=args.retries, offline_checks=offline_checks,
                              condense_task=config.tasks.get(LIGHT_TASK), measure=not args.no_measure, log=_log)
    for warning in result.warnings:
        print(f"注意: {warning}", file=sys.stderr)
    if not result.ok:
        print(f"エラー: 台本の下書きを作れませんでした: {result.error}", file=sys.stderr)
        print(f"記録: {result.record}", file=sys.stderr)
        return 1
    print(f"台本の下書き: {result.markdown}")
    print(f"記録:         {result.record}（書き直し {result.rewrites} 回、注意 {len(result.warnings)} 件）")
    ok = _print_check(result.markdown)
    print("次に人がすること: 下書きを読んで直す（ナレーションの言い回し・数値の根拠・区分）→ 説明図・撮影 → erkit check")
    return 0 if ok else 1


# -- erkit llm check ------------------------------------------------------------------------------

def _cmd_check(args: argparse.Namespace) -> int:
    config = config_from_args(args)
    endpoint = endpoint_from_args(args, config)
    client = LLMClient(endpoint, confidentiality=GENERAL)  # 決まった短い文だけを送る（資料は送らない）
    if args.task is None:
        task = config.tasks.get(DRAFT_TASK)
    else:
        task = None if args.task == "none" else config.task(args.task)
    started = time.monotonic()
    models = client.list_models()
    models_sec = time.monotonic() - started
    missing: ModelNotFoundError | None = None
    model: str | None = None
    settings = task_settings(task, endpoint, explicit_model=args.model, default_thinking="off")
    try:
        model = client.require_model(settings.model, models, task=None if args.model else settings.task) \
            if settings.model else client.resolve_model(models)
    except ModelNotFoundError as error:
        missing = error
    answer = None
    if model is not None:
        sender = ThinkingSender(settings.thinking)
        answer = sender.call(lambda extra: client.chat([{"role": "user", "content": CHECK_PROMPT}], model=model,
                                                       max_tokens=1024, temperature=0, extra_body=extra))
    kind = host_kind(urllib.parse.urlsplit(endpoint.base_url).hostname or "")
    notes: list[str] = []
    if kind != "loopback":
        notes.append("接続先がこの PC ではありません（LAN）。社外秘の台本（区分が未記入も）には使えません")
    if answer is not None and not answer.content.strip():
        notes.append("答えの本文が空です（思考で上限に達したかもしれません）。--model か設定の thinking: off を確かめてください")
    result: dict[str, Any] = {
        "config": config.where, "profile": endpoint.name, "base_url": endpoint.base_url, "this_pc": kind == "loopback",
        "models": models, "models_sec": round(models_sec, 3), "task": settings.task, "model": model,
        "model_source": (settings.model_source or "サーバーに読み込まれているモデル") if model else None,
        "reply": answer.content.strip() if answer else None,
        "reply_sec": round(answer.elapsed_sec, 3) if answer else None,
        "notes": notes, "error": str(missing) if missing else None,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return missing.exit_code if missing else 0
    print(f"設定:     {config.where}")
    print(f"接続先:   {endpoint.name} {endpoint.base_url}（{'この PC' if kind == 'loopback' else 'LAN'}）")
    print(f"モデル:   {len(models)} 個（一覧まで {result['models_sec']} 秒）")
    for name in models:
        print(f"  {'*' if name == model else ' '} {name}")
    if model is not None:
        print(f"使うモデル: {model}（{result['model_source']}）")
        print(f"応答:     {result['reply']!r}（{result['reply_sec']} 秒。1 回目はモデルの読み込みを含むことがある）")
    for note in notes:
        print(f"注意: {note}", file=sys.stderr)
    if missing:
        print(f"エラー: {missing}", file=sys.stderr)
        return missing.exit_code
    return 0


# -- 入口 ---------------------------------------------------------------------------------------------

def _run(fn, args: argparse.Namespace) -> int:
    try:
        return fn(args)
    except LLMToolError as error:
        print(f"エラー: {error}", file=sys.stderr)
        return error.exit_code
    except KeyboardInterrupt:
        print("中断しました", file=sys.stderr)
        return 130


def run_draft(args: argparse.Namespace) -> int:
    return _run(_cmd_draft, args)


def run_check(args: argparse.Namespace) -> int:
    return _run(_cmd_check, args)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m explainer_reel_kit.llm``（``erkit draft`` / ``erkit llm`` と同じ）。"""
    parser = argparse.ArgumentParser(prog="python -m explainer_reel_kit.llm")
    sub = parser.add_subparsers(dest="cmd", required=True)
    register(sub)
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    return args.func(args)
