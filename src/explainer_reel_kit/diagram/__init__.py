"""説明図: 台本の ``capture: {tool: html, src: …}`` のシーンの HTML を描いて、PNG と注釈位置を出す（``erkit diagram``）。

- 画像の大きさは画像枠の縦横比に合わせた 2420×1000（スライドの画像枠 12.333in × 5.1in ≒ 2.42:1）
- HTML の中で ``data-mark="名前"`` を付けた要素の位置を ``<画像名>.marks.json``（``explainer-reel/marks@1``、
  ``source: generated``）に書く。台本は ``recipe_params`` の ``mark: 名前`` で指す（座標を手で写さない）
- **外の URL・画像は読まない**。ブラウザはネットワークを止めた状態で描き、http(s) などを読もうとしたら
  そのシーンを失敗にする（画像も書かない）。だから社外秘（confidential）の台本でも使える
- 画像の来歴は必ず ``説明用再構成図``（画面を捏造しない）
- 出力先の既定は台本のフォルダ（``image.ref`` は台本ファイルからの相対）。結果は ``<出力先>/diagram-result.json``

書き方は ``docs/design/diagram.md``。共通の CSS は ``samples/_shared/diagram.css``。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .. import browser as br
from .. import marks as mk
from .. import storyboard as sb

WIDTH, HEIGHT = 2420, 1000
LABEL = "説明用再構成図"
RESULT_NAME = "diagram-result.json"
ALLOWED_SCHEMES = ("file:", "data:", "about:", "blob:")
DEFAULT_TIMEOUT_MS = 15000
SETTLE_MS = 100

# 描いた後に、data-mark の要素と、図の大きさを集める
COLLECT_JS = """() => {
  const out = [];
  for (const el of document.querySelectorAll('[data-mark]')) {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const visible = cs.display !== 'none' && cs.visibility !== 'hidden' && parseFloat(cs.opacity || '1') > 0
                    && r.width > 0 && r.height > 0;
    out.push({name: el.getAttribute('data-mark'), x: r.x, y: r.y, w: r.width, h: r.height, visible,
              tag: el.tagName.toLowerCase()});
  }
  const d = document.documentElement;
  return {marks: out, scroll: [Math.max(d.scrollWidth, document.body ? document.body.scrollWidth : 0),
                               Math.max(d.scrollHeight, document.body ? document.body.scrollHeight : 0)]};
}"""


class DiagramError(Exception):
    """台本・説明図の不備（描き始められない）。"""


def diagram_scenes(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """台本の順に、``image.source: generated`` かつ ``capture.tool: html`` のシーンを返す。"""
    out = []
    for s in doc.get("scenes", []):
        img, cap = s.get("image") or {}, s.get("capture") or {}
        if img.get("source") == "generated" and cap.get("tool") == "html":
            out.append(s)
    return out


def load_storyboard(path: Path) -> dict[str, Any]:
    try:
        doc = sb.load_storyboard(path)
    except (sb.ConversionError, json.JSONDecodeError, OSError) as e:
        raise DiagramError(f"台本を読めません: {e}") from e
    rep = sb.validate_storyboard(doc, base_dir=Path(path).parent)
    if not rep.ok:
        raise DiagramError("台本が検証を通りません:\n  " + "\n  ".join(rep.errors))
    return doc


def preflight(doc: dict[str, Any], base_dir: Path, only: list[str] | None = None) -> list[str]:
    """描く前の確認: 来歴、HTML の有無、--only の id。"""
    errors: list[str] = []
    scenes = diagram_scenes(doc)
    ids = [s["id"] for s in scenes]
    for o in only or []:
        if o not in ids:
            errors.append(f"--only の {o} は説明図（capture.tool: html）のシーンではありません")
    for s in scenes:
        if only and s["id"] not in only:
            continue
        if s["image"].get("label") != LABEL:
            errors.append(f"{s['id']}: 説明図の image.label は「{LABEL}」にしてください（いま: {s['image'].get('label')}）")
        src = Path(base_dir) / s["capture"]["src"]
        if not src.is_file():
            errors.append(f"{s['id']}: 説明図の HTML がありません: {s['capture']['src']}")
    return errors


def measure(collected: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """data-mark の要素を marks.to_image が読む形にする。名前の誤り・重複は理由に入れる。"""
    measured: dict[str, Any] = {}
    errors: list[str] = []
    seen: set[str] = set()
    for m in collected:
        name = (m.get("name") or "").strip()
        if not mk.MARK_NAME.match(name):
            errors.append(f"data-mark「{name}」: mark 名は英小文字・数字・_ で書いてください")
            continue
        if name in seen:
            errors.append(f"data-mark「{name}」が 2 つ以上あります（1 つにしてください）")
            measured.pop(name, None)
            continue
        seen.add(name)
        if not m.get("visible"):
            measured[name] = {"error": "非表示です（display・visibility・大きさ 0）"}
        else:
            measured[name] = {"css": (m["x"], m["y"], m["w"], m["h"]), "how": f"data-mark: <{m.get('tag', '?')}>"}
    return measured, errors


def run_diagram(
    storyboard: Path,
    out_root: Path | None = None,
    only: list[str] | None = None,
    channel: str | None = None,
    executable: str | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """説明図を描いて結果 dict を返す（結果 JSON も保存する）。台本・HTML の不備は DiagramError。"""
    storyboard = Path(storyboard)
    doc = load_storyboard(storyboard)
    base = storyboard.resolve().parent
    errors = preflight(doc, base, only)
    if errors:
        raise DiagramError("説明図を描けません:\n  " + "\n  ".join(errors))
    scenes = [s for s in diagram_scenes(doc) if not only or s["id"] in only]
    if not scenes:
        log("WARN 台本に説明図（capture: {tool: html, src: …}）のシーンがありません")
    out_root = Path(out_root) if out_root else base
    out_root.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)
    t_all = time.perf_counter()
    results: list[dict[str, Any]] = []
    version = ""
    with br.sync_playwright() as pw:
        try:
            browser = br.launch(pw, channel, executable)
        except br.BrowserError as e:
            raise DiagramError(str(e)) from e
        try:
            for sc in scenes:
                results.append(_draw_one(browser, sc, base, out_root, log))
        finally:
            version = browser.version
            browser.close()

    summary = {
        "tool": "erkit diagram",
        "reel_id": doc["reel"]["id"],
        "confidentiality": sb.confidentiality(doc),
        "storyboard": str(storyboard.resolve()),
        "assets_root": str(out_root.resolve()),
        "image_size": {"w": WIDTH, "h": HEIGHT},
        "network": "blocked",
        "started_at": started.isoformat(timespec="seconds"),
        "elapsed_sec": round(time.perf_counter() - t_all, 2),
        "browser": version,
        "ok": sum(r["status"] == "ok" for r in results),
        "failed": sum(r["status"] == "failed" for r in results),
        "scenes": results,
    }
    (out_root / RESULT_NAME).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def _draw_one(browser, sc: dict[str, Any], base: Path, out_root: Path, log) -> dict[str, Any]:
    ref = sc["image"]["ref"]
    src = (base / sc["capture"]["src"]).resolve()
    dest = (out_root / ref).resolve()
    mpath = mk.marks_path(dest)
    rec: dict[str, Any] = {"id": sc["id"], "ref": ref, "src": sc["capture"]["src"], "status": "ok"}
    notes: list[str] = []
    t0 = time.perf_counter()
    for stale in (dest, mpath):  # 前回の画像・位置を残さない（今回の HTML と食い違うため）
        if stale.exists():
            stale.unlink()
    blocked: list[str] = []

    def guard(route) -> None:
        url = route.request.url
        if url.startswith(ALLOWED_SCHEMES):
            route.continue_()
        else:
            blocked.append(url)
            route.abort("blockedbyclient")

    ctx = browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1,
                              locale="ja-JP", offline=True, service_workers="block")
    try:
        ctx.route("**/*", guard)
        page = ctx.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        page.on("websocket", lambda ws: blocked.append(ws.url))
        page.goto(src.as_uri(), wait_until="load")
        page.evaluate("() => document.fonts ? document.fonts.ready.then(() => true) : true")
        page.wait_for_timeout(SETTLE_MS)
        if blocked:
            raise _Blocked(blocked)
        got = page.evaluate(COLLECT_JS)
        sw, sh = got["scroll"]
        if sw > WIDTH + 1 or sh > HEIGHT + 1:
            notes.append(f"図が画像の枠（{WIDTH}×{HEIGHT}）より大きく（{sw}×{sh}）、はみ出した部分は写りません")
        dest.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(dest), full_page=False, animations="disabled", caret="hide")
        if blocked:  # 描いている間に読もうとしたもの
            raise _Blocked(blocked)
        measured, name_errors = measure(got["marks"])
        ok_marks, mark_errors = mk.to_image(measured, (0.0, 0.0), 1, WIDTH, HEIGHT)
        problems = name_errors + mark_errors
        missing = [n for n in mk.storyboard_mark_refs(sc) if n not in ok_marks]
        problems += [f"台本の recipe_params が参照する mark「{n}」が HTML にありません（data-mark=\"{n}\" を付ける）"
                     for n in missing if n not in measured]
        mk.write(mpath, mk.build_doc(sc["id"], "generated", dest, (WIDTH, HEIGHT), ok_marks))
        rec.update({"path": str(dest), "width": WIDTH, "height": HEIGHT, "label": LABEL,
                    "marks_path": str(mpath), "marks": sorted(ok_marks)})
        if problems:
            rec["status"] = "failed"
            rec["error"] = "注釈位置（marks）を記録できません: " + " / ".join(problems)
    except _Blocked as e:
        for p in (dest, mpath):
            if p.exists():
                p.unlink()
        rec["status"] = "failed"
        rec["error"] = "外の URL を読もうとしたため止めました（説明図は HTML の中だけで描く）: " + ", ".join(e.urls[:5]) \
            + (f" ほか {len(e.urls) - 5} 件" if len(e.urls) > 5 else "")
        rec["blocked"] = e.urls
    except Exception as e:  # シーン単位で記録して続行
        rec["status"] = "failed"
        s = str(e)
        rec["error"] = f"{type(e).__name__}: {s.splitlines()[0] if s else ''}"
    finally:
        ctx.close()
    rec["elapsed_sec"] = round(time.perf_counter() - t0, 2)
    if notes:
        rec["notes"] = notes
    head = "OK  " if rec["status"] == "ok" else "FAIL"
    extra = f"{WIDTH}x{HEIGHT} {ref}" + (f" marks={','.join(rec['marks'])}" if rec.get("marks") else "") \
        if rec["status"] == "ok" else rec["error"]
    log(f"{head} {sc['id']} ({rec['elapsed_sec']}s) {extra}")
    for n in notes:
        log(f"WARN {sc['id']}: {n}")
    return rec


class _Blocked(Exception):
    def __init__(self, urls: list[str]):
        super().__init__("blocked")
        self.urls = list(dict.fromkeys(urls))
