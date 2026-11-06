"""記録モード: 人がブラウザを操作して、操作定義（explainer-reel/web-actions@1）を作る。AI は使わない。

    erkit record --url <URL> --reel <reel id> --out <新しい .actions.yaml>
        [--start 1] [--viewport 1920x1080] [--serve <フォルダ>] [--channel msedge|chrome] [--no-verify]

ブラウザ（画面あり）が開くので、撮りたい画面まで操作する:
- クリック・入力（Enter かフォーカスを外して確定）・選択（<select>）を記録する
- F8: ここまでを 1 シーンとして区切る（その時点のスクロール位置で撮影）。シーン id は s01, s02, …
- Shift＋クリック: その部品を mark（赤枠・矢印の位置）にする。名前を入力する（英小文字・数字・_）。
  名前の後に ^ を付けると 1 つ上の要素（^^ で 2 つ上）を mark にする
- F10 またはウィンドウを閉じる: 記録を終える（F8 で区切っていない最後の操作は捨てる）

セレクタの優先順: data-testid → role＋名前 → テキスト → テキストを手がかりにした祖先 → CSS（最後の手段。警告付き）。
記録後、新しいページで操作を再生して、各セレクタが 1 つの要素に決まるかを確かめる（--no-verify で省略）。
社外秘の画面を記録するときも、記録はこの PC の中だけで行われる（AI には送らない）。
"""
from __future__ import annotations

import contextlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from ... import browser as br
from ... import marks as mk
from .capture import ACTIONS_SCHEMA, DEFAULT_VIEWPORT, URL_SCHEMES, CaptureError, run_op, validate_actions
from .serve import rebase_local, serve_dir

BINDING = "__erkitRecord"
UNSTABLE_CLASS = re.compile(r"(^|[-_])[a-z0-9]*\d[a-z0-9]*$|^(css|sc|jsx|emotion|svelte)-|__\w+--|^_[A-Za-z0-9]{5,}$", re.I)

# ページに入れる記録用スクリプト。候補セレクタと、その候補が今のページで何個に当たるかを返す。
RECORDER_JS = r"""
(() => {
  if (window.__erkitRecordInstalled) return;
  window.__erkitRecordInstalled = true;
  const send = (ev) => { try { window.%(binding)s(ev); } catch (e) {} };
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const esc = (s) => s.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const implicitRole = (el) => {
    const t = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
    if (el.getAttribute('role')) return el.getAttribute('role');
    if (t === 'button' || (t === 'input' && ['button', 'submit', 'reset'].includes(type))) return 'button';
    if (t === 'a' && el.hasAttribute('href')) return 'link';
    if (/^h[1-6]$/.test(t)) return 'heading';
    if (t === 'select') return 'combobox';
    if (t === 'textarea') return 'textbox';
    if (t === 'input') {
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'range') return 'slider';
      if (type === 'number') return 'spinbutton';
      if (['', 'text', 'search', 'email', 'tel', 'url'].includes(type)) return 'textbox';
    }
    return null;
  };
  const accName = (el) => {
    if (el.getAttribute('aria-label')) return norm(el.getAttribute('aria-label'));
    const lb = el.getAttribute('aria-labelledby');
    if (lb) return norm(lb.split(/\s+/).map(id => (document.getElementById(id) || {}).textContent || '').join(' '));
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return norm(l.textContent); }
    const wrap = el.closest('label'); if (wrap && wrap !== el) return norm(wrap.textContent);
    const t = el.tagName.toLowerCase();
    if (['input', 'textarea', 'select'].includes(t)) return norm(el.getAttribute('placeholder') || el.getAttribute('title') || '');
    return norm(el.innerText || el.textContent || el.getAttribute('title') || '');
  };
  const sameRoleMatches = (role, name) => {
    const n = name.toLowerCase(); let c = 0;
    for (const e of document.querySelectorAll('*')) {
      if (implicitRole(e) === role && accName(e).toLowerCase().includes(n)) c++;
    }
    return c;
  };
  const ownText = (el) => norm(el.innerText || el.textContent || '');
  const textMatches = (text) => {
    let c = 0;
    for (const e of document.querySelectorAll('body *')) {
      if (ownText(e) === text && ![...e.children].some(ch => ownText(ch) === text)) c++;
    }
    return c;
  };
  const cssPath = (el) => {
    const parts = [];
    for (let e = el; e && e.nodeType === 1 && e !== document.body; e = e.parentElement) {
      let p = e.tagName.toLowerCase();
      if (e.id && !/\d{3,}/.test(e.id)) { parts.unshift('#' + CSS.escape(e.id)); break; }
      const cls = [...e.classList].filter(c => !/[:\[\]/]/.test(c)).slice(0, 2);
      if (cls.length) p += '.' + cls.map(c => CSS.escape(c)).join('.');
      const sibs = e.parentElement ? [...e.parentElement.children].filter(s => s.tagName === e.tagName) : [];
      if (sibs.length > 1) p += `:nth-of-type(${sibs.indexOf(e) + 1})`;
      parts.unshift(p);
      if (parts.length >= 4) break;
    }
    return parts.join(' > ');
  };
  const candidates = (el) => {
    const out = [];
    const tid = el.getAttribute('data-testid');
    if (tid) out.push({kind: 'testid', selector: `[data-testid="${esc(tid)}"]`,
                       count: document.querySelectorAll(`[data-testid="${CSS.escape(tid)}"]`).length});
    const role = implicitRole(el), name = accName(el);
    if (role && name && name.length <= 80)
      out.push({kind: 'role', selector: `role=${role}[name="${esc(name)}"]`, count: sameRoleMatches(role, name)});
    const text = ownText(el);
    // テキストで指すのは、文字を持つ子要素が無い要素だけ（数値などが入れ替わるコンテナを文字で指さない）
    if (text && text.length <= 40 && ![...el.children].some(ch => ownText(ch)))
      out.push({kind: 'text', selector: `text="${esc(text)}"`, count: textMatches(text)});
    // 祖先: 中の短いテキストを手がかりに、何段上かで指す（コンテナ用）
    const queue = [[el, 0]];
    while (queue.length) {
      const [e, d] = queue.shift();
      if (d > 0) {
        const t = ownText(e);
        if (t && t.length <= 40 && ![...e.children].some(ch => ownText(ch)) && textMatches(t) === 1) {
          let up = 0; for (let p = e; p !== el; p = p.parentElement) up++;
          out.push({kind: 'text_ancestor', selector: `text="${esc(t)}" >> xpath=ancestor::*[${up}]`, count: 1});
          break;
        }
      }
      if (d < 3) for (const ch of e.children) queue.push([ch, d + 1]);
    }
    const css = cssPath(el);
    out.push({kind: 'css', selector: css, count: document.querySelectorAll(css).length});
    return out;
  };
  const describe = (el) => ({tag: el.tagName.toLowerCase(), text: ownText(el).slice(0, 40), candidates: candidates(el)});
  let enterOn = null;
  document.addEventListener('keydown', (e) => {
    if (e.key === 'F8') { e.preventDefault(); send({type: 'shot', scrollY: Math.round(window.scrollY)}); }
    else if (e.key === 'F10') { e.preventDefault(); send({type: 'finish'}); }
    else if (e.key === 'Enter') enterOn = e.target;
  }, true);
  document.addEventListener('click', (e) => {
    const el = e.target instanceof Element ? e.target : null;
    if (!el) return;
    if (e.shiftKey) {
      e.preventDefault(); e.stopPropagation();
      const answer = window.prompt('mark 名（英小文字・数字・_）。1 つ上の要素にするなら名前の後に ^（^^ で 2 つ上）\n選んだ部品: <' +
                                   el.tagName.toLowerCase() + '> ' + ownText(el).slice(0, 30), '');
      if (answer === null) return;
      const m = answer.trim().match(/^(.*?)(\^*)$/);
      let target = el;
      for (let i = 0; i < m[2].length && target.parentElement && target.parentElement !== document.body; i++) target = target.parentElement;
      send({type: 'mark', name: m[1].trim(), up: m[2].length, ...describe(target)});
      return;
    }
    const t = el.tagName.toLowerCase();
    if (t === 'select' || t === 'option') return;            // 選択は change で記録
    if (t === 'input' && !['button', 'submit', 'reset', 'checkbox', 'radio'].includes((el.type || '').toLowerCase())) return;
    if (t === 'textarea') return;
    const target = el.closest('button, a[href], [role="button"], [role="link"], [role="tab"], [role="menuitem"], label, [data-testid]') || el;
    send({type: 'click', ...describe(target)});
  }, true);
  document.addEventListener('change', (e) => {
    const el = e.target; if (!(el instanceof Element)) return;
    const t = el.tagName.toLowerCase(), type = (el.type || '').toLowerCase();
    if (t === 'select') send({type: 'select', value: el.value, ...describe(el)});
    else if ((t === 'input' && !['checkbox', 'radio', 'button', 'submit', 'reset', 'file'].includes(type)) || t === 'textarea')
      send({type: 'fill', value: el.value, commit: enterOn === el ? 'enter' : 'blur', ...describe(el)});
    enterOn = null;
  }, true);
})();
""" % {"binding": BINDING}


# ---------------------------------------------------------------- 変換（記録イベント → 操作定義）

@dataclass
class Picked:
    selector: str
    kind: str
    warnings: list[str] = field(default_factory=list)


def unstable_reasons(selector: str) -> list[str]:
    out = []
    if re.search(r":nth-(of-type|child)\(", selector):
        out.append("位置（nth）に頼るセレクタ")
    for cls in re.findall(r"\.((?:\\.|[A-Za-z0-9_-])+)", selector):
        cls = cls.replace("\\", "")
        if UNSTABLE_CLASS.search(cls):
            out.append(f"自動生成らしい class（{cls}）")
    return out


def pick_selector(ev: dict[str, Any]) -> Picked:
    """優先順（testid → role → text → 祖先 → css）で、1 つの要素に決まる最初の候補を選ぶ。"""
    cands = [c for c in ev.get("candidates") or [] if c.get("selector")]
    if not cands:
        raise CaptureError(f"セレクタの候補がありません: {ev.get('tag')} {ev.get('text', '')}")
    order = {"testid": 0, "role": 1, "text": 2, "text_ancestor": 3, "css": 4}
    cands.sort(key=lambda c: order.get(c.get("kind"), 9))
    unique = [c for c in cands if c.get("count") == 1]
    chosen = unique[0] if unique else cands[0]
    warns = []
    if not unique:
        warns.append(f"1 つの要素に決まりません（{chosen.get('count')} 件に一致）。capture では最初の要素を使います")
    if chosen["kind"] == "css":
        warns.append("CSS セレクタ（最後の手段）。画面の作りが変わると壊れやすいので、自作ツールなら data-testid を付けてください")
        warns += unstable_reasons(chosen["selector"])
    return Picked(chosen["selector"], chosen["kind"], warns)


def events_to_actions(events: list[dict[str, Any]], reel_id: str, *, start: int = 1,
                      viewport: dict[str, int] | None = None) -> tuple[dict[str, Any], list[str]]:
    """記録イベントの列を操作定義（web-actions@1）にする。戻り値の 2 つ目は全体の警告。"""
    if not reel_id or not isinstance(reel_id, str):
        raise CaptureError("--reel（台本の reel.id）を指定してください")
    scenes: dict[str, Any] = {}
    warnings: list[str] = []
    cur_actions: list[dict[str, Any]] = []
    cur_marks: dict[str, Any] = {}
    cur_notes: list[str] = []
    n = start
    for ev in events:
        t = ev.get("type")
        if t in ("click", "fill", "select"):
            p = pick_selector(ev)
            op: dict[str, Any] = {"op": t, "selector": p.selector}
            if t == "fill":
                op["value"] = ev.get("value", "")
                op["commit"] = ev.get("commit", "enter") if ev.get("commit") in ("enter", "blur") else "enter"
            elif t == "select":
                op["value"] = str(ev.get("value", ""))
            # 同じ入力欄への続けての入力は最後の値だけ残す
            if t == "fill" and cur_actions and cur_actions[-1].get("op") == "fill" and cur_actions[-1]["selector"] == p.selector:
                cur_actions[-1] = op
            else:
                cur_actions.append(op)
            cur_notes += [f"{p.selector}: {w}" for w in p.warnings]
        elif t == "mark":
            name = (ev.get("name") or "").strip()
            if not mk.MARK_NAME.match(name):
                warnings.append(f"mark 名「{name}」は使えないため捨てました（英小文字・数字・_）")
                continue
            p = pick_selector(ev)
            if name in cur_marks:
                cur_notes.append(f"mark {name} を選び直しました")
            cur_marks[name] = p.selector
            cur_notes += [f"mark {name}: {w}" for w in p.warnings]
        elif t == "shot":
            sid = f"s{n:02d}"
            n += 1
            acts = list(cur_actions)
            if not scenes:
                acts.insert(0, {"op": "wait_load"})
            acts.append({"op": "scroll", "y": max(0, int(ev.get("scrollY") or 0))})
            sc: dict[str, Any] = {}
            if not scenes:
                sc["reset"] = True
            sc["actions"] = acts
            sc["shot"] = {"type": "viewport"}
            if cur_marks:
                sc["marks"] = dict(cur_marks)
            if cur_notes:
                sc["note"] = " / ".join(dict.fromkeys(cur_notes))
            scenes[sid] = sc
            cur_actions, cur_marks, cur_notes = [], {}, []
        elif t == "finish":
            break
    if cur_actions or cur_marks:
        warnings.append(f"F8 で区切っていない最後の操作 {len(cur_actions)} 件・mark {len(cur_marks)} 件は捨てました")
    if not scenes:
        raise CaptureError("シーンが 1 つも記録されていません（撮影したい画面で F8 を押してください）")
    data = {"schema": ACTIONS_SCHEMA, "reel_id": reel_id,
            "defaults": {"viewport": dict(viewport or DEFAULT_VIEWPORT), "device_scale_factor": 1,
                         "timeout_ms": 20000, "settle_ms": 500, "locale": "ja-JP"},
            "scenes": scenes}
    errs = validate_actions(data)
    if errs:  # 変換の誤り（起きないはず）
        raise CaptureError("記録した操作定義が検証を通りません:\n  " + "\n  ".join(errs))
    return data, warnings


def dump_actions(data: dict[str, Any], url: str, warnings: list[str]) -> str:
    head = [f"# erkit record で作成: {datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"# 記録した URL: {url}",
            "# 台本（.storyboard.md）に同じ id の web シーンを書き、capture.url に同じ URL を入れてから check / capture する"]
    head += [f"# 警告: {w}" for w in warnings]
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=200)
    return "\n".join(head) + "\n" + body


# ---------------------------------------------------------------- 再生による確かめ

def verify_actions(page, data: dict[str, Any], url: str) -> list[str]:
    """新しいページで操作を再生し、各セレクタが 1 つの要素に決まるか・mark が見えるかを確かめる。"""
    problems: list[str] = []
    timeout = int((data.get("defaults") or {}).get("timeout_ms") or 20000)
    page.goto(url, wait_until="load", timeout=timeout)
    for sid, sc in data["scenes"].items():
        for op in sc.get("actions") or []:
            sel = op.get("selector")
            if sel:
                n = page.locator(sel).count()
                if n != 1:
                    problems.append(f"{sid}: {op['op']} {sel} は {n} 件に一致")
                    if n == 0:
                        continue
            try:
                run_op(page, op, url, 5000)
            except Exception as e:
                problems.append(f"{sid}: {op['op']} {sel or ''} を再生できません（{type(e).__name__}）")
        page.wait_for_timeout(200)
        for name, sel in (sc.get("marks") or {}).items():
            loc = page.locator(sel)
            n = loc.count()
            if n != 1:
                problems.append(f"{sid}: mark {name} {sel} は {n} 件に一致")
            elif not loc.first.is_visible():
                problems.append(f"{sid}: mark {name} は撮影時に見えていません")
            else:
                box = loc.first.bounding_box()
                vp = page.viewport_size or DEFAULT_VIEWPORT
                if box and box["width"] > 0 and box["height"] > 0:
                    w = max(0.0, min(box["x"] + box["width"], vp["width"]) - max(box["x"], 0))
                    h = max(0.0, min(box["y"] + box["height"], vp["height"]) - max(box["y"], 0))
                    if w * h / (box["width"] * box["height"]) < mk.MIN_INSIDE:
                        problems.append(f"{sid}: mark {name} は撮影する画面の外にあります（撮影では失敗になります）")
    return problems


# ---------------------------------------------------------------- 記録の実行

class Recorder:
    def __init__(self, log: Callable[[str], None] = print):
        self.events: list[dict[str, Any]] = []
        self.finished = False
        self.log = log

    def _on(self, source, ev):
        if not isinstance(ev, dict):
            return
        self.events.append(ev)
        t = ev.get("type")
        shots = sum(1 for e in self.events if e.get("type") == "shot")
        if t == "shot":
            self.log(f"[record] s{shots:02d} を区切りました（スクロール {ev.get('scrollY', 0)}px）")
        elif t == "mark":
            self.log(f"[record] mark {ev.get('name')}: <{ev.get('tag')}> {ev.get('text', '')}")
        elif t == "finish":
            self.finished = True
            self.log("[record] 記録を終えます")
        else:
            self.log(f"[record] {t}: <{ev.get('tag')}> {ev.get('text', '')}")

    def attach(self, context) -> None:
        context.expose_binding(BINDING, self._on)
        context.add_init_script(RECORDER_JS)


def record(url: str, reel_id: str, out: Path, *, start: int = 1, viewport: dict[str, int] | None = None,
           channel: str | None = None, executable: str | None = None, headed: bool = True,
           verify: bool = True, drive: Callable[[Any], None] | None = None, max_minutes: float = 120,
           serve: Path | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    """ブラウザを開いて記録し、新しいファイルに操作定義を書く。drive はテスト用（人の代わりに操作する）。"""
    out = Path(out)
    if out.exists():
        raise CaptureError(f"出力先がすでにあります: {out}（既存の操作定義には追記しません。新しいファイル名にしてください）")
    if not url.startswith(URL_SCHEMES):
        raise CaptureError("--url は http(s):// か file:// で始めてください")
    if serve is not None and not Path(serve).is_dir():
        raise CaptureError(f"--serve のフォルダがありません: {serve}")
    vp = dict(viewport or DEFAULT_VIEWPORT)
    asked_url = url  # 操作定義の先頭に書く URL（--serve の置き換え前）

    rec = Recorder(log)
    with contextlib.ExitStack() as stack:
        if serve is not None:
            base = stack.enter_context(serve_dir(Path(serve)))
            url = rebase_local(url, base)
            log(f"[record] {serve} を {base} で配信しています（{url}）")
        pw = stack.enter_context(br.sync_playwright())
        try:
            browser = br.launch(pw, channel, executable, headed)
        except br.BrowserError as e:
            raise CaptureError(str(e)) from e
        try:
            ctx = browser.new_context(viewport=vp, locale="ja-JP")
            rec.attach(ctx)
            page = ctx.new_page()
            page.goto(url, wait_until="load")
            if drive is not None:
                drive(page)
            else:
                log("[record] 操作してください。F8: シーンを区切る / Shift＋クリック: mark / F10 かウィンドウを閉じる: 終了")
                t_end = time.monotonic() + max_minutes * 60
                while not rec.finished and not page.is_closed() and time.monotonic() < t_end:
                    try:
                        page.wait_for_timeout(250)
                    except Exception:
                        break
            data, warnings = events_to_actions(rec.events, reel_id, start=start, viewport=vp)
            problems: list[str] = []
            if verify:
                vctx = browser.new_context(viewport=vp, locale="ja-JP")
                try:
                    problems = verify_actions(vctx.new_page(), data, url)
                finally:
                    vctx.close()
                for p in problems:
                    log(f"WARN 再生の確かめ: {p}")
        finally:
            browser.close()
    out.parent.mkdir(parents=True, exist_ok=True)
    text = dump_actions(data, asked_url, warnings + [f"再生の確かめ: {p}" for p in problems])
    with out.open("x", encoding="utf-8", newline="\n") as f:   # 既存のファイルは上書きしない
        f.write(text)
    for w in warnings:
        log(f"WARN {w}")
    log(f"[record] {out}（シーン {len(data['scenes'])} 件、mark "
        f"{sum(len(s.get('marks') or {}) for s in data['scenes'].values())} 件）")
    return {"path": str(out), "data": data, "warnings": warnings, "problems": problems, "events": rec.events}


def parse_viewport(text: str | None) -> dict[str, int] | None:
    if not text:
        return None
    m = re.fullmatch(r"(\d+)\s*[xX×]\s*(\d+)", text.strip())
    if not m:
        raise CaptureError("--viewport は 1920x1080 の形で書いてください")
    return {"width": int(m.group(1)), "height": int(m.group(2))}
