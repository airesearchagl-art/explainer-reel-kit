"""解説の型（kind: explainer）を、手順書・prompts・プラグインが案内していること。サンプル window-condensation。

- 手順書: 種別の見分け方（01）、構成の決まり（03）、解説のひな形と SOURCES.md（04）、部品 7 種の選び方（05）、
  答えのひな形の種別とまとめての例（batch）
- prompts と プラグインにも同じ分岐がある。解説の分岐でも、区分で止まる・MP4 の前に人が確かめる約束は変わらない
- サンプル: erkit check --strict、説明図の HTML と mark・CSS、SOURCES.md の形、erkit diagram（ブラウザがあれば）
- 文書の `erkit …` と `/explainer-reel-kit:…` の照合は test_guide・test_plugin・test_batch が新しい文書も含めて行う
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from explainer_reel_kit.cli import main

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "guide"
PROMPTS = ROOT / "prompts"
PLUGIN = ROOT / "plugins" / "claude-code"
TEMPLATE = "src/explainer_reel_kit/data/templates/explainer.storyboard.md"
PARTS = ["analogy", "section", "flow", "compare", "range", "branch", "cards"]
ORDER = ["問い", "しくみ", "比べる・条件", "選び方・減らし方"]
SAMPLE = ROOT / "samples" / "window-condensation"
SAMPLE_SB = SAMPLE / "window-condensation.storyboard.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _section(text: str, start: str, end: str | None = None) -> str:
    i = text.index(start)
    j = text.index(end, i + len(start)) if end else len(text)
    return text[i:j]


def _in_order(text: str, words: list[str]) -> bool:
    pos = [text.find(w) for w in words]
    return all(p >= 0 for p in pos) and pos == sorted(pos)


# ---- 手順書

def test_intake_tells_kinds_apart():
    text = _read(GUIDE / "01-intake.md")
    part = _section(text, "## 種別の見分け方", "## AI に任せること")
    for kind in ("`tool_intro`", "`work_manual`", "`explainer`"):
        assert kind in part, kind
    assert TEMPLATE in part
    assert "src/explainer_reel_kit/data/templates/storyboard.md" in part
    assert "迷ったら" in part


def test_outline_has_explainer_rule():
    text = _read(GUIDE / "03-outline.md")
    part = _section(text, "## 解説（explainer）の構成の決まり", "## AI に任せること")
    assert "5〜7 シーン" in part and "2〜3 分" in part
    assert _in_order(part, ORDER + ["まとめ"])
    assert "入れ替えません" in part
    assert "window-condensation" in part


def test_storyboard_guide_has_template_and_sources():
    text = _read(GUIDE / "04-storyboard.md")
    part = _section(text, "## 解説（explainer）のとき", "## 台本の形")
    assert "explainer.storyboard.md" in part
    assert "SOURCES.md" in part
    for h in ("## 使った数値", "## 資料", "## 未確認", "確かめた日"):
        assert h in part, h
    assert "../../_shared/diagram.css" in part


def test_visuals_guide_lists_all_parts():
    text = _read(GUIDE / "05-visuals.md")
    part = _section(text, "### 解説の部品の選び方", "## Web 画面の撮影")
    for name in PARTS:
        assert f"samples/_parts/{name}.html" in part, name
        assert (ROOT / "samples" / "_parts" / f"{name}.html").is_file()
    assert "../../_shared/diagram.css" in part


def test_batch_has_explainer_kind_and_example():
    text = _read(GUIDE / "batch.md")
    kinds_line = next(ln for ln in text.splitlines() if ln.startswith("- 種別: tool_intro"))
    assert "explainer" in kinds_line
    example = _section(text, "### 解説（explainer）の例", "## AI がすること")
    block = example[example.index("```markdown"):]
    items = [ln[2:].split(":", 1) for ln in block.splitlines() if ln.startswith("- ")]
    fields = {k.strip(): v.strip() for k, v in (i for i in items if len(i) == 2)}
    assert list(fields)[0] == "区分" and fields["区分"] == "general"
    assert fields["種別"] == "explainer"
    assert fields["撮影"] == "なし"


# ---- prompts

@pytest.mark.parametrize("name", ["01-intake", "02-outline", "03-storyboard", "04-diagram-html", "05-batch"])
def test_prompts_have_explainer_branch(name):
    text = _read(PROMPTS / f"{name}.md")
    assert "explainer" in text, name


def test_prompt_outline_order_and_parts():
    text = _read(PROMPTS / "02-outline.md")
    text = text[text.index("種別が explainer"):]  # 「聞き取りのまとめ」など、前の文の語を拾わない
    assert _in_order(text, ["問い（身近な場面）", "しくみ", "比べる・条件", "選び方・減らし方", "まとめ"])
    for word in ("たとえ", "断面図", "フロー", "比較表", "数値の範囲", "カード", "条件の分岐"):
        assert word in text, word


def test_prompts_point_to_explainer_template_and_parts():
    for name in ("03-storyboard", "05-batch"):
        text = _read(PROMPTS / f"{name}.md").replace("\\", "/")
        assert TEMPLATE in text, name
        assert "SOURCES.md" in text, name
    text = _read(PROMPTS / "04-diagram-html.md").replace("\\", "/")
    assert "samples/_parts/" in text
    assert "../../_shared/diagram.css" in text


# ---- プラグイン

SKILL = PLUGIN / "skills" / "make-explainer" / "SKILL.md"


@pytest.mark.parametrize("path", [SKILL, PLUGIN / "skills" / "storyboard" / "SKILL.md",
                                  PLUGIN / "commands" / "explainer-new.md"],
                         ids=lambda p: p.parent.name if p.name == "SKILL.md" else p.stem)
def test_plugin_points_to_explainer_template(path):
    text = _read(path)
    assert "explainer" in text
    assert TEMPLATE in text


def test_diagram_skill_lists_parts():
    text = _read(PLUGIN / "skills" / "diagram" / "SKILL.md")
    part = _section(text, "## 解説（kind: explainer）のとき", "## 描いて確かめる")
    for name in PARTS:
        assert f"samples/_parts/{name}.html" in part, name
    assert "../../_shared/diagram.css" in part


def test_make_explainer_branch_keeps_promises():
    """解説の分岐を足しても、区分で止まる・MP4 の前に人が確かめる約束は変わらない。"""
    text = _read(SKILL)
    branch = _section(text, "## 種別を見分ける", "## 進め方を選ぶ")
    assert "区分の約束と、MP4 の前に人が確かめる約束は、種別によらず同じ" in branch
    assert _in_order(branch, ORDER)
    # 区分は種別より先に決める
    assert text.index("## 最初に区分を決める") < text.index("## 種別を見分ける")
    assert "資料を受け取らずに止まる" in _section(text, "## 最初に区分を決める", "## 種別を見分ける")
    assert "MP4（`erkit make`）は実行しない" in text


def test_explainer_new_asks_confidentiality_before_kind():
    text = _read(PLUGIN / "commands" / "explainer-new.md")
    assert text.index("## 2. 区分を聞く") < text.index("## 3. id と種別を決める")
    assert "ここで止まる" in _section(text, "## 2. 区分を聞く", "## 3.")
    step3 = _section(text, "## 3. id と種別を決める", "## 4.")
    assert "`explainer`" in step3


def test_explainer_new_flow_with_template(tmp_path, capsys):
    """/explainer-reel-kit:explainer-new の手順（explainer）で作った台本が erkit check を通る。"""
    dest = tmp_path / "reels" / "cold-draft"
    (dest / "diagrams").mkdir(parents=True)
    shutil.copytree(ROOT / "samples" / "_shared", tmp_path / "reels" / "_shared")
    sb = dest / "cold-draft.storyboard.md"
    text = _read(ROOT / TEMPLATE)
    text = re.sub(r"^id: \S+", "id: cold-draft", text, count=1, flags=re.M)
    text = re.sub(r"^output_name: \S+", "output_name: cold_draft", text, count=1, flags=re.M)
    sb.write_text(text, encoding="utf-8")
    assert main(["check", "--strict", str(sb)]) == 0
    out = capsys.readouterr().out
    assert "区分: general" in out and "種別: explainer" in out


# ---- サンプル

def _scenes(path: Path) -> list[tuple[str, dict]]:
    text = _read(path)
    found = []
    for m in re.finditer(r"^## (s\d+): .+?\n```yaml\n(.*?)```", text, re.M | re.S):
        found.append((m.group(1), yaml.safe_load(m.group(2))))
    return found


def test_sample_passes_strict_check(capsys):
    assert main(["check", "--strict", str(SAMPLE_SB)]) == 0
    out = capsys.readouterr().out
    assert "区分: general" in out and "種別: explainer" in out


def test_sample_structure():
    head = yaml.safe_load(_read(SAMPLE_SB).split("---", 2)[1])
    assert head["kind"] == "explainer" and head["schema_version"] == "kit-1.1.0"
    assert head["confidentiality"] == "general"
    scenes = _scenes(SAMPLE_SB)
    assert 5 <= len(scenes) <= 7
    for sid, data in scenes:
        assert data["image"]["source"] == "generated", sid
        assert data["image"]["label"] == "説明用再構成図", sid
        assert data["capture"]["tool"] == "html", sid


@pytest.mark.parametrize("sid,data", _scenes(SAMPLE_SB), ids=lambda v: v if isinstance(v, str) else "")
def test_sample_diagram_html(sid, data):
    html_path = SAMPLE / data["capture"]["src"]
    html = _read(html_path)
    # 共通の CSS が見つかる・外の URL を読まない
    hrefs = re.findall(r'href="([^"]+\.css)"', html)
    assert hrefs and all((html_path.parent / h).resolve().is_file() for h in hrefs)
    assert not re.search(r'(src|href)="https?://', html)
    assert "@import" not in html and "fetch(" not in html
    # 台本の mark が HTML の data-mark にある
    marks = data["recipe_params"]["mark"]
    marks = [marks] if isinstance(marks, str) else marks
    found = set(re.findall(r'data-mark="([^"]+)"', html))
    assert set(marks) <= found, (sid, set(marks) - found)


def test_sample_sources():
    text = _read(SAMPLE / "SOURCES.md")
    for h in ("## 使った数値", "## 使った事実", "## 資料", "## 未確認"):
        assert h in text, h
    sources = _section(text, "## 資料", "## 未確認")
    entries = re.findall(r"^(\d+)\. (.+)$", sources, re.M)
    assert entries
    for no, line in entries:
        assert "https://" in line, no
        assert re.search(r"確かめた日 \d{4}-\d{2}-\d{2}", line), no
    cited = set(re.findall(r"\[(\d+)\]", _section(text, "## 使った数値", "## 資料")))
    assert cited and cited <= {no for no, _ in entries}


def test_sample_is_listed():
    assert "window-condensation/" in _read(ROOT / "samples" / "README.md")
    assert "samples/window-condensation/" in _read(ROOT / "README.md")


def test_sample_diagram_renders(tmp_path, browser_opts):
    ch = ["--channel", browser_opts["channel"]] if browser_opts["channel"] else []
    out = tmp_path / "out"
    assert main(["diagram", str(SAMPLE_SB), "--out", str(out), "--overlay", str(out / "check.png"), *ch]) == 0
    for sid, data in _scenes(SAMPLE_SB):
        assert (out / data["image"]["ref"]).is_file(), sid
