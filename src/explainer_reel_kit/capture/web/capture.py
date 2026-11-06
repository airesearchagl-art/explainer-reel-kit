"""Web 画面の撮影: 台本の ``image.source: web`` のシーンを、操作定義に従って Playwright で撮る。

- 台本の ``capture.steps`` は人が読む手順。機械が実行する操作は操作定義（``explainer-reel/web-actions@1``）に書く
- 操作定義の既定の場所: 台本と同じフォルダの ``<reel id>.actions.yaml``（``--actions`` で変更）
- 画像は ``<保存先>/<image.ref>``。``marks`` を書いたシーンは画像の隣に ``<画像名>.marks.json``
- 結果は ``<保存先>/capture-web-result.json``。失敗したシーンは理由を記録して次へ進む
- 社外秘（confidential）の台本は、この PC の中の URL（file://・localhost・127.0.0.1）しか撮らない

書き方は ``docs/design/capture-web.md``。
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from ... import browser as br
from ... import marks as mk
from ... import storyboard as sb
from .serve import is_local_url, rebase_local, serve_dir

RESULT_NAME = "capture-web-result.json"
ACTIONS_SCHEMA = "explainer-reel/web-actions@1"
ACTIONS_SUFFIX = ".actions.yaml"
ENV_CAPTURES_ROOT = "ERKIT_CAPTURES_ROOT"

DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
DEFAULT_TIMEOUT_MS = 15000
DEFAULT_SETTLE_MS = 400

# op 名 → (必須キー, 任意キー)
OPS: dict[str, tuple[set[str], set[str]]] = {
    "goto": (set(), {"url"}),
    "wait_load": (set(), {"state"}),
    "wait_for": ({"selector"}, {"state"}),
    "wait": ({"ms"}, set()),
    "click": ({"selector"}, set()),
    "hover": ({"selector"}, set()),
    "fill": ({"selector", "value"}, {"commit"}),
    "press": ({"key"}, {"selector"}),
    "scroll_to": ({"selector"}, {"block", "offset"}),
    "scroll": ({"y"}, set()),
    "select": ({"selector", "value"}, set()),
}
LOAD_STATES = {"load", "domcontentloaded", "networkidle"}
WAIT_STATES = {"attached", "detached", "visible", "hidden"}
COMMITS = {"enter", "blur", "none"}
BLOCKS = {"start", "center", "end"}
SHOT_TYPES = {"viewport", "full_page", "element"}
URL_SCHEMES = ("http://", "https://", "file://")


class CaptureError(Exception):
    """台本・操作定義の不備（撮影を始められない）。"""


# ---------------------------------------------------------------- 台本

def load_storyboard(path: Path) -> dict[str, Any]:
    try:
        doc = sb.load_storyboard(path)
    except (sb.ConversionError, json.JSONDecodeError, OSError) as e:
        raise CaptureError(f"台本を読めません: {e}") from e
    rep = sb.validate_storyboard(doc, base_dir=Path(path).parent)
    if not rep.ok:
        raise CaptureError("台本が検証を通りません:\n  " + "\n  ".join(rep.errors))
    return doc


def web_scenes(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """台本の順に、``image.source: web`` のシーンだけを返す。"""
    return [s for s in doc.get("scenes", []) if (s.get("image") or {}).get("source") == "web"]


# ---------------------------------------------------------------- 保存先

def default_captures_root() -> Path:
    """撮影素材のルート: 環境変数 ERKIT_CAPTURES_ROOT ＞ config/kit.yaml の captures_root ＞ ホームの ExplainerReelKit/captures。"""
    from ... import config as kit_config

    if os.environ.get(ENV_CAPTURES_ROOT):
        return Path(os.environ[ENV_CAPTURES_ROOT])
    return kit_config.captures_root(kit_config.load_config_or_default())


def folder_name(name: str) -> str:
    """フォルダ名に使えない文字を落とし、空白を - にする。"""
    s = re.sub(r'[\\/:*?"<>|]', "", name).strip()
    s = re.sub(r"\s+", "-", s)
    if not s or s in (".", ".."):
        raise CaptureError(f"フォルダ名にできません: {name!r}")
    return s


def default_out_dir(doc: dict[str, Any], tool: str | None = None, captures_root: Path | None = None) -> Path:
    """``--out`` を省略したときの保存先: ``<撮影素材のルート>/web/<ツール名（既定は reel id）>``。"""
    root = Path(captures_root) if captures_root else default_captures_root()
    return root / "web" / folder_name(tool or doc["reel"]["id"])


def default_actions_path(storyboard: Path, reel_id: str) -> Path:
    return Path(storyboard).resolve().parent / f"{reel_id}{ACTIONS_SUFFIX}"


# ---------------------------------------------------------------- 操作定義

def load_actions(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise CaptureError(f"操作定義がありません: {path}（`erkit record` で作るか、書き方は docs/design/capture-web.md）")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise CaptureError(f"操作定義の YAML を読めません: {e}") from e


def _check_viewport(v: Any, where: str, errors: list[str]) -> None:
    if not isinstance(v, dict) or set(v) != {"width", "height"}:
        errors.append(f"{where}: viewport は width と height の2項目で書いてください")
        return
    for k, lo in (("width", 320), ("height", 240)):
        if not isinstance(v[k], int) or isinstance(v[k], bool) or v[k] < lo:
            errors.append(f"{where}: viewport.{k} は {lo} 以上の整数にしてください")


def _is_value(v: Any) -> bool:
    return isinstance(v, (str, int, float)) and not isinstance(v, bool)


def _check_op(op: Any, where: str, errors: list[str]) -> None:
    if not isinstance(op, dict) or "op" not in op:
        errors.append(f"{where}: 操作は `op:` を持つ項目で書いてください")
        return
    name = op["op"]
    if name not in OPS:
        errors.append(f"{where}: 未対応の op です: {name}（使えるもの: {', '.join(OPS)}）")
        return
    req, opt = OPS[name]
    keys = set(op) - {"op", "note"}
    for k in sorted(req - keys):
        errors.append(f"{where}: op {name} には {k} が必要です")
    for k in sorted(keys - req - opt):
        errors.append(f"{where}: op {name} に使えない項目です: {k}")
    if "selector" in op and (not isinstance(op["selector"], str) or not op["selector"].strip()):
        errors.append(f"{where}: selector は空でない文字列にしてください")
    if name == "wait_load" and op.get("state", "networkidle") not in LOAD_STATES:
        errors.append(f"{where}: wait_load.state は {sorted(LOAD_STATES)} のいずれかです")
    if name == "wait_for" and op.get("state", "visible") not in WAIT_STATES:
        errors.append(f"{where}: wait_for.state は {sorted(WAIT_STATES)} のいずれかです")
    if name == "fill":
        if not _is_value(op.get("value")):
            errors.append(f"{where}: fill.value は文字列か数値にしてください")
        if op.get("commit", "enter") not in COMMITS:
            errors.append(f"{where}: fill.commit は {sorted(COMMITS)} のいずれかです")
    if name == "scroll_to":
        if op.get("block", "start") not in BLOCKS:
            errors.append(f"{where}: scroll_to.block は {sorted(BLOCKS)} のいずれかです")
        if "offset" in op and not isinstance(op["offset"], int):
            errors.append(f"{where}: scroll_to.offset は整数（px）にしてください")
    if name == "scroll" and (not isinstance(op.get("y"), int) or op["y"] < 0):
        errors.append(f"{where}: scroll.y は 0 以上の整数（ページ先頭からの px）にしてください")
    if name == "select" and not _is_value(op.get("value")):
        errors.append(f"{where}: select.value は文字列か数値（option の value）にしてください")
    if name == "wait" and (not isinstance(op.get("ms"), int) or op["ms"] < 0):
        errors.append(f"{where}: wait.ms は 0 以上の整数にしてください")
    if name == "goto" and "url" in op and not str(op["url"]).startswith(URL_SCHEMES):
        errors.append(f"{where}: goto.url は http(s):// か file:// で始めてください")


def _check_shot(shot: Any, where: str, errors: list[str]) -> None:
    if shot is None:
        return
    if not isinstance(shot, dict):
        errors.append(f"{where}: shot は項目で書いてください")
        return
    t = shot.get("type", "viewport")
    if t not in SHOT_TYPES:
        errors.append(f"{where}: shot.type は {sorted(SHOT_TYPES)} のいずれかです")
    extra = set(shot) - {"type", "selector", "padding"}
    if extra:
        errors.append(f"{where}: shot に使えない項目です: {', '.join(sorted(extra))}")
    if t == "element" and not shot.get("selector"):
        errors.append(f"{where}: shot.type = element には selector が必要です")
    if "padding" in shot and (not isinstance(shot["padding"], int) or shot["padding"] < 0):
        errors.append(f"{where}: shot.padding は 0 以上の整数にしてください")


def mark_selectors(spec: Any) -> list[str]:
    """mark の定義（セレクタ 1 つ、または 1 つの枠にまとめるセレクタの並び）をセレクタの並びにする。"""
    return [spec] if isinstance(spec, str) else list(spec)


def _check_marks(marks: Any, where: str, errors: list[str]) -> None:
    if marks is None:
        return
    if not isinstance(marks, dict) or not marks:
        errors.append(f"{where}: marks は「mark 名: セレクタ」の項目で書いてください")
        return
    for name, spec in marks.items():
        w = f"{where}.marks.{name}"
        if not isinstance(name, str) or not mk.MARK_NAME.match(name):
            errors.append(f"{w}: mark 名は英小文字・数字・_ で書いてください")
        if isinstance(spec, str):
            ok = bool(spec.strip())
        else:
            ok = isinstance(spec, list) and bool(spec) and all(isinstance(x, str) and x.strip() for x in spec)
        if not ok:
            errors.append(f"{w}: セレクタ（文字列）か、セレクタの並び（1つの枠にまとめる）で書いてください")


def validate_actions(data: Any) -> list[str]:
    """操作定義そのものの検証（台本とは突き合わせない）。"""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["操作定義の最上位は項目（mapping）で書いてください"]
    if data.get("schema") != ACTIONS_SCHEMA:
        errors.append(f"schema: {ACTIONS_SCHEMA} を書いてください")
    if not isinstance(data.get("reel_id"), str) or not data["reel_id"]:
        errors.append("reel_id（台本の reel.id）を書いてください")
    extra = set(data) - {"schema", "reel_id", "defaults", "scenes", "note"}
    if extra:
        errors.append(f"最上位に使えない項目です: {', '.join(sorted(extra))}")
    d = data.get("defaults", {}) or {}
    if not isinstance(d, dict):
        errors.append("defaults は項目で書いてください")
        d = {}
    extra = set(d) - {"viewport", "device_scale_factor", "timeout_ms", "settle_ms", "locale"}
    if extra:
        errors.append(f"defaults に使えない項目です: {', '.join(sorted(extra))}")
    if "viewport" in d:
        _check_viewport(d["viewport"], "defaults", errors)
    for k in ("timeout_ms", "settle_ms"):
        if k in d and (not isinstance(d[k], int) or d[k] < 0):
            errors.append(f"defaults.{k} は 0 以上の整数にしてください")
    if "device_scale_factor" in d and (not isinstance(d["device_scale_factor"], (int, float)) or d["device_scale_factor"] <= 0):
        errors.append("defaults.device_scale_factor は正の数にしてください")
    scenes = data.get("scenes")
    if not isinstance(scenes, dict) or not scenes:
        errors.append("scenes に、シーン id ごとの操作を1つ以上書いてください")
        return errors
    for sid, sc in scenes.items():
        where = f"scenes.{sid}"
        if not isinstance(sc, dict):
            errors.append(f"{where}: 項目で書いてください")
            continue
        extra = set(sc) - {"reset", "actions", "shot", "marks", "note"}
        if extra:
            errors.append(f"{where}: 使えない項目です: {', '.join(sorted(extra))}")
        if "reset" in sc and not isinstance(sc["reset"], bool):
            errors.append(f"{where}: reset は true / false です")
        acts = sc.get("actions", [])
        if not isinstance(acts, list):
            errors.append(f"{where}: actions は並び（- op: ...）で書いてください")
            acts = []
        for i, op in enumerate(acts, 1):
            _check_op(op, f"{where}.actions[{i}]", errors)
        _check_shot(sc.get("shot"), where, errors)
        _check_marks(sc.get("marks"), where, errors)
    return errors


@dataclass
class CheckReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def crosscheck(doc: dict[str, Any], actions: dict[str, Any]) -> CheckReport:
    """台本と操作定義の突き合わせ（未定義シーン・余分なシーン・reel id・台本が参照する mark）。"""
    rep = CheckReport(errors=validate_actions(actions))
    if not rep.ok:
        return rep
    reel_id = doc["reel"]["id"]
    if actions["reel_id"] != reel_id:
        rep.errors.append(f"reel_id が台本と違います: 操作定義 {actions['reel_id']} / 台本 {reel_id}")
    web_ids = [s["id"] for s in web_scenes(doc)]
    all_ids = {s["id"] for s in doc.get("scenes", [])}
    defined = set(actions["scenes"])
    for sid in web_ids:
        if sid not in defined:
            rep.errors.append(f"{sid}: 台本の web シーンに対応する操作定義がありません（未定義シーン）")
    for sid in sorted(defined - set(web_ids)):
        if sid in all_ids:
            rep.errors.append(f"{sid}: 台本では web シーンではないため、操作定義は使えません")
        else:
            rep.errors.append(f"{sid}: 台本にないシーンです")
    for sc in web_scenes(doc):
        spec = actions["scenes"].get(sc["id"])
        if spec is None:
            continue
        defined_marks = set(spec.get("marks") or {})
        for name in mk.storyboard_mark_refs(sc):
            if name not in defined_marks:
                rep.errors.append(
                    f"{sc['id']}: 台本の recipe_params が参照する mark「{name}」が操作定義にありません"
                    f"（定義済み: {', '.join(sorted(defined_marks)) or 'なし'}）")
    if not web_ids:
        rep.warnings.append("台本に web シーンがありません")
    elif web_ids[0] in defined and not actions["scenes"][web_ids[0]].get("reset", False):
        rep.warnings.append(f"{web_ids[0]}: 最初の web シーンは reset: true にすると、毎回同じ状態から撮影できます")
    return rep


# ---------------------------------------------------------------- URL

def parse_url_map(items: list[str] | None) -> list[tuple[str, str]]:
    out = []
    for it in items or []:
        if "=" not in it:
            raise CaptureError(f"--url-map は 旧URL=新URL の形で書いてください: {it}")
        old, new = it.split("=", 1)
        out.append((old, new))
    return out


def map_url(url: str, url_map: list[tuple[str, str]], serve_base: str | None = None) -> str:
    """``--url-map`` の置き換え（最初に合ったもの）→ ``--serve`` のときはローカルの URL を配信先へ。"""
    for old, new in url_map:
        if url.startswith(old):
            url = new + url[len(old):]
            break
    return rebase_local(url, serve_base) if serve_base else url


def check_confidential_urls(doc: dict[str, Any], urls: dict[str, str]) -> list[str]:
    """社外秘の台本は、この PC の中の URL しか撮らない。外の URL があれば理由を返す。"""
    if sb.confidentiality(doc) != sb.CONFIDENTIAL:
        return []
    return [f"{sid}: {u}" for sid, u in urls.items() if not is_local_url(u)]


# ---------------------------------------------------------------- 順序

@dataclass
class Step:
    scene: dict[str, Any]
    spec: dict[str, Any]
    shoot: bool  # False = 後のシーンのための準備（操作だけ行い撮影しない）


def plan(doc: dict[str, Any], actions: dict[str, Any], only: list[str] | None) -> list[Step]:
    """撮影の順序。``--only`` のときは、状態を作るために直前の reset シーンから操作だけ再現する。"""
    scenes = web_scenes(doc)
    ids = [s["id"] for s in scenes]
    if not only:
        return [Step(s, actions["scenes"][s["id"]], True) for s in scenes]
    unknown = [o for o in only if o not in ids]
    if unknown:
        raise CaptureError(f"--only に web シーンでない id があります: {', '.join(unknown)}")
    need: set[int] = set()
    for o in only:
        i = ids.index(o)
        j = i
        while j > 0 and not actions["scenes"][ids[j]].get("reset", False):
            j -= 1
        need.update(range(j, i + 1))
    return [Step(scenes[i], actions["scenes"][ids[i]], ids[i] in only) for i in sorted(need)]


# ---------------------------------------------------------------- 実行

def png_size(path: Path) -> tuple[int, int]:
    with Path(path).open("rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise CaptureError(f"PNG ではありません: {path}")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def run_op(page, op: dict[str, Any], base_url: str, timeout: int) -> None:
    name = op["op"]
    if name == "goto":
        page.goto(op.get("url", base_url), wait_until="load", timeout=timeout)
    elif name == "wait_load":
        page.wait_for_load_state(op.get("state", "networkidle"), timeout=timeout)
    elif name == "wait_for":
        page.locator(op["selector"]).first.wait_for(state=op.get("state", "visible"), timeout=timeout)
    elif name == "wait":
        page.wait_for_timeout(op["ms"])
    elif name == "click":
        page.locator(op["selector"]).first.click(timeout=timeout)
    elif name == "hover":
        page.locator(op["selector"]).first.hover(timeout=timeout)
    elif name == "fill":
        loc = page.locator(op["selector"]).first
        loc.fill(str(op["value"]), timeout=timeout)
        commit = op.get("commit", "enter")
        if commit == "enter":
            loc.press("Enter", timeout=timeout)
        elif commit == "blur":
            loc.blur(timeout=timeout)
    elif name == "press":
        if "selector" in op:
            page.locator(op["selector"]).first.press(op["key"], timeout=timeout)
        else:
            page.keyboard.press(op["key"])
    elif name == "scroll_to":
        loc = page.locator(op["selector"]).first
        loc.wait_for(state="attached", timeout=timeout)
        loc.evaluate(
            "(el, a) => { el.scrollIntoView({block: a.block, inline: 'nearest'});"
            " if (a.offset) window.scrollBy(0, a.offset); }",
            {"block": op.get("block", "start"), "offset": op.get("offset", 0)},
        )
    elif name == "select":
        page.locator(op["selector"]).first.select_option(str(op["value"]), timeout=timeout)
    elif name == "scroll":
        page.evaluate("y => window.scrollTo(0, y)", op["y"])
    else:  # validate_actions で弾いているので到達しない
        raise CaptureError(f"未対応の op: {name}")


def _prepare_shot(page, shot: dict[str, Any] | None, timeout: int) -> dict[str, Any]:
    """撮影範囲を決める（必要ならスクロール）。origin は画像の左上に当たるビューポート座標（CSS px）。"""
    shot = shot or {}
    t = shot.get("type", "viewport")
    if t == "viewport":
        return {"type": t, "origin": (0.0, 0.0), "clip": None}
    if t == "full_page":
        sx, sy = page.evaluate("() => [window.scrollX, window.scrollY]")
        return {"type": t, "origin": (-float(sx), -float(sy)), "clip": None}
    loc = page.locator(shot["selector"]).first
    loc.scroll_into_view_if_needed(timeout=timeout)
    box = loc.bounding_box(timeout=timeout)
    if box is None:
        raise CaptureError(f"要素が表示されていません: {shot['selector']}")
    pad = shot.get("padding", 0)
    vp = page.viewport_size or DEFAULT_VIEWPORT
    x0, y0 = max(0, box["x"] - pad), max(0, box["y"] - pad)
    x1 = min(vp["width"], box["x"] + box["width"] + pad)
    y1 = min(vp["height"], box["y"] + box["height"] + pad)
    return {"type": t, "origin": (x0, y0), "clip": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}}


def _shoot(page, prep: dict[str, Any], path: Path, timeout: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    common = {"path": str(path), "animations": "disabled", "caret": "hide", "timeout": timeout}
    if prep["type"] == "full_page":
        page.screenshot(full_page=True, **common)
    elif prep["clip"] is not None:
        page.screenshot(clip=prep["clip"], **common)
    else:
        page.screenshot(full_page=False, **common)


def measure_marks(page, marks: dict[str, Any], timeout: int) -> dict[str, Any]:
    """各 mark の枠（ビューポート座標、CSS px）を測る。見つからない・非表示は error。"""
    out: dict[str, Any] = {}
    for name, spec in marks.items():
        sels = mark_selectors(spec)
        boxes, err = [], None
        for sel in sels:
            loc = page.locator(sel)
            if loc.count() == 0:
                err = f"見つかりません: {sel}"
                break
            first = loc.first
            if not first.is_visible():
                err = f"非表示です: {sel}"
                break
            b = first.bounding_box(timeout=timeout)
            if b is None:
                err = f"非表示です: {sel}"
                break
            boxes.append(b)
        if err:
            out[name] = {"error": err}
            continue
        x0 = min(b["x"] for b in boxes)
        y0 = min(b["y"] for b in boxes)
        x1 = max(b["x"] + b["width"] for b in boxes)
        y1 = max(b["y"] + b["height"] for b in boxes)
        out[name] = {"css": (x0, y0, x1 - x0, y1 - y0), "how": "selector: " + " + ".join(sels)}
    return out


def _first_line(e: Exception) -> str:
    s = str(e)
    return f"{type(e).__name__}: {s.splitlines()[0] if s else ''}"


def run_capture(
    storyboard: Path,
    out_root: Path,
    actions_path: Path | None = None,
    only: list[str] | None = None,
    url_map: list[tuple[str, str]] | None = None,
    channel: str | None = None,
    executable: str | None = None,
    headed: bool = False,
    serve: Path | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """撮影して結果 dict を返す（結果 JSON も保存する）。台本・操作定義の不備は CaptureError。"""
    storyboard = Path(storyboard)
    doc = load_storyboard(storyboard)
    reel_id = doc["reel"]["id"]
    actions_path = Path(actions_path) if actions_path else default_actions_path(storyboard, reel_id)
    actions = load_actions(actions_path)
    rep = crosscheck(doc, actions)
    if not rep.ok:
        raise CaptureError("操作定義が台本と合いません:\n  " + "\n  ".join(rep.errors))
    for w in rep.warnings:
        log(f"WARN {w}")
    steps = plan(doc, actions, only)
    url_map = url_map or []
    if serve is not None and not Path(serve).is_dir():
        raise CaptureError(f"--serve のフォルダがありません: {serve}")

    # 社外秘の台本は、配信先へ置き換えた後の URL がこの PC の中であることを、ブラウザを開く前に確かめる
    probe = "http://127.0.0.1:1/" if serve is not None else None
    outside = check_confidential_urls(doc, {st.scene["id"]: map_url(st.scene["capture"]["url"], url_map, probe)
                                            for st in steps})
    if outside:
        raise CaptureError("社外秘（confidential）の台本は、この PC の中の URL（file://・localhost・127.0.0.1）"
                           "しか撮りません:\n  " + "\n  ".join(outside))

    d = actions.get("defaults", {}) or {}
    timeout = d.get("timeout_ms", DEFAULT_TIMEOUT_MS)
    settle = d.get("settle_ms", DEFAULT_SETTLE_MS)
    scale = d.get("device_scale_factor", 1)
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    t_all = time.perf_counter()
    results: list[dict[str, Any]] = []
    version = ""
    with contextlib.ExitStack() as stack:
        serve_base = stack.enter_context(serve_dir(Path(serve))) if serve is not None else None
        if serve_base:
            log(f"[capture] {serve} を {serve_base} で配信しています")
        pw = stack.enter_context(br.sync_playwright())
        try:
            browser = br.launch(pw, channel, executable, headed)
        except br.BrowserError as e:
            raise CaptureError(str(e)) from e
        ctx = page = None
        cur_vp: dict[str, int] | None = None
        cur_url: str | None = None
        prev_failed = False
        try:
            for st in steps:
                sc, spec = st.scene, st.spec
                cap = sc["capture"]
                # viewport を書いていないシーンは、直前のシーンの viewport を引き継ぐ（状態を保つ）
                vp = cap.get("viewport") or (cur_vp if not spec.get("reset", False) else None) \
                    or d.get("viewport") or DEFAULT_VIEWPORT
                url = map_url(cap["url"], url_map, serve_base)
                ref = sc["image"]["ref"]
                dest = (out_root / ref).resolve()
                rec: dict[str, Any] = {"id": sc["id"], "ref": ref, "status": "ok" if st.shoot else "prepared"}
                notes: list[str] = []
                t0 = time.perf_counter()
                try:
                    fresh = page is None or spec.get("reset", False) or vp != cur_vp
                    if page is not None and not spec.get("reset", False) and vp != cur_vp:
                        notes.append("viewport が前のシーンと違うため、新しいページで開き直しました（状態は引き継がれません）")
                    if prev_failed and not fresh:
                        notes.append("前のシーンが失敗したため、画面の状態が想定と違う可能性があります")
                    if fresh:
                        if ctx is not None:
                            ctx.close()
                        ctx = browser.new_context(viewport=vp, device_scale_factor=scale,
                                                  locale=d.get("locale", "ja-JP"))
                        page = ctx.new_page()
                        page.set_default_timeout(timeout)
                        page.goto(url, wait_until="load", timeout=timeout)
                        cur_vp, cur_url = vp, url
                    elif url != cur_url:
                        page.goto(url, wait_until="load", timeout=timeout)
                        cur_url = url
                    for op in spec.get("actions", []) or []:
                        run_op(page, op, url, timeout)
                    mark_errors: list[str] = []
                    if st.shoot:
                        mpath = mk.marks_path(dest)
                        if mpath.exists():  # 前回の位置を残さない（画像と食い違うため）
                            mpath.unlink()
                        page.wait_for_timeout(settle)
                        prep = _prepare_shot(page, spec.get("shot"), timeout)
                        measured = measure_marks(page, spec.get("marks") or {}, timeout)
                        _shoot(page, prep, dest, timeout)
                        w, h = png_size(dest)
                        rec.update({"path": str(dest), "width": w, "height": h})
                        if spec.get("marks"):
                            ok_marks, mark_errors = mk.to_image(measured, prep["origin"], scale, w, h)
                            mk.write(mpath, mk.build_doc(sc["id"], "web", dest, (w, h), ok_marks))
                            rec.update({"marks_path": str(mpath), "marks": sorted(ok_marks)})
                    rec["url"] = page.url
                    if mark_errors:
                        rec["status"] = "failed"
                        rec["error"] = "注釈位置（marks）を記録できません: " + " / ".join(mark_errors)
                    prev_failed = False
                except Exception as e:  # シーン単位で記録して続行
                    rec["status"] = "failed"
                    rec["error"] = _first_line(e)
                    prev_failed = True
                rec["elapsed_sec"] = round(time.perf_counter() - t0, 2)
                if notes:
                    rec["notes"] = notes
                results.append(rec)
                head = {"ok": "OK  ", "failed": "FAIL", "prepared": "prep"}[rec["status"]]
                extra = f"{rec.get('width')}x{rec.get('height')} {ref}" if rec["status"] == "ok" else rec.get("error", "")
                if rec["status"] == "ok" and rec.get("marks"):
                    extra += f" marks={','.join(rec['marks'])}"
                log(f"{head} {sc['id']} ({rec['elapsed_sec']}s) {extra}")
        finally:
            version = browser.version
            browser.close()

    shot_recs = [r for r in results if r["status"] != "prepared"]
    summary = {
        "tool": "erkit capture",
        "reel_id": reel_id,
        "confidentiality": sb.confidentiality(doc),
        "storyboard": str(storyboard.resolve()),
        "actions": str(actions_path.resolve()),
        "assets_root": str(out_root.resolve()),
        "started_at": started.isoformat(timespec="seconds"),
        "elapsed_sec": round(time.perf_counter() - t_all, 2),
        "browser": version,
        "url_map": [f"{o}={n}" for o, n in url_map],
        "served": str(Path(serve).resolve()) if serve is not None else None,
        "ok": sum(r["status"] == "ok" for r in shot_recs),
        "failed": sum(r["status"] == "failed" for r in shot_recs),
        "scenes": results,
    }
    (out_root / RESULT_NAME).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
