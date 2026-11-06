"""キットの設定（config/kit.yaml）。

探す順: 引数で渡したパス ＞ 環境変数 ERKIT_CONFIG ＞ 今のフォルダの config/kit.yaml ＞ キットのフォルダの config/kit.yaml。
どれも無ければ既定値で動く。ひな形は config/kit.example.yaml（写して使う。kit.yaml は commit しない）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

#: キットのフォルダ（src/explainer_reel_kit/config.py → リポジトリの直下）。pip install -e . で使う前提
KIT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_RELPATH = Path("config") / "kit.yaml"

#: 既定の声: AivisSpeech「ほのか（ノーマル）」の style id（ACML 1.0。クレジット表記は任意）
DEFAULT_SPEAKER = 808373280
DEFAULT_SPEAKER_LABEL = "ほのか / ノーマル"


class ConfigError(ValueError):
    """設定ファイルを読めない・形式が違う。"""


@dataclass(frozen=True)
class VoiceCredit:
    name: str
    credit: str
    style_ids: tuple[int, ...]


@dataclass
class KitConfig:
    path: Path | None = None  # 読んだ設定ファイル（無ければ None）
    output_root: Path | None = None
    captures_root: Path | None = None
    voice_engine: str = "aivisspeech"
    voice_url: str | None = None  # None ならエンジンの既定（AivisSpeech は http://127.0.0.1:10101）
    voice_speaker: int = DEFAULT_SPEAKER
    dictionaries: list[str] = field(default_factory=list)  # 名前（dictionaries/<名前>.yaml）かパス。既定は使わない
    credits: list[VoiceCredit] = field(default_factory=list)

    def credit_for(self, speaker: int) -> str | None:
        """話者がクレジットの必要な声なら文言を返す。"""
        for c in self.credits:
            if speaker in c.style_ids:
                return c.credit
        return None


def find_config(explicit: Path | str | None = None, env: Mapping[str, str] | None = None,
                cwd: Path | None = None) -> Path | None:
    env = os.environ if env is None else env
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise ConfigError(f"設定ファイルがありません: {p}")
        return p
    if env.get("ERKIT_CONFIG"):
        p = Path(env["ERKIT_CONFIG"])
        if not p.is_file():
            raise ConfigError(f"環境変数 ERKIT_CONFIG の設定ファイルがありません: {p}")
        return p
    for base in (cwd or Path.cwd(), KIT_ROOT):
        p = base / CONFIG_RELPATH
        if p.is_file():
            return p
    return None


def _int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)) or (isinstance(value, str) and not value.strip().isdigit()):
        raise ConfigError(f"{where} は整数で書いてください: {value!r}")
    return int(value)


def parse_config(data: Any, path: Path | None = None) -> KitConfig:
    where = str(path) if path else "設定"
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: key: value の形式で書いてください")
    cfg = KitConfig(path=path)
    for key in ("output_root", "captures_root"):
        root = data.get(key)
        if root not in (None, ""):
            if not isinstance(root, str):
                raise ConfigError(f"{where}: {key} はフォルダのパス（文字列）で書いてください")
            setattr(cfg, key, Path(os.path.expandvars(os.path.expanduser(root))))
    voice = data.get("voice") or {}
    if not isinstance(voice, dict):
        raise ConfigError(f"{where}: voice は key: value で書いてください")
    if voice.get("engine") not in (None, ""):
        cfg.voice_engine = str(voice["engine"])
    if voice.get("url") not in (None, ""):
        cfg.voice_url = str(voice["url"])
    if voice.get("speaker") is not None:
        cfg.voice_speaker = _int(voice["speaker"], f"{where}: voice.speaker")
    dicts = voice.get("dictionaries") or []
    if not isinstance(dicts, list) or not all(isinstance(d, str) and d.strip() for d in dicts):
        raise ConfigError(f"{where}: voice.dictionaries は辞書の名前かパスのリストで書いてください")
    cfg.dictionaries = [d.strip() for d in dicts]
    credits = voice.get("credits") or []
    if not isinstance(credits, list):
        raise ConfigError(f"{where}: voice.credits はリストで書いてください")
    for i, c in enumerate(credits):
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or not isinstance(c.get("credit"), str) \
                or not c["credit"].strip():
            raise ConfigError(f"{where}: voice.credits[{i}] に name と credit（文字列）が必要です")
        ids = c.get("style_ids") or []
        if not isinstance(ids, list):
            raise ConfigError(f"{where}: voice.credits[{i}].style_ids は整数のリストで書いてください")
        cfg.credits.append(VoiceCredit(c["name"], c["credit"].strip(),
                                       tuple(_int(x, f"{where}: voice.credits[{i}].style_ids") for x in ids)))
    return cfg


def load_config(explicit: Path | str | None = None, env: Mapping[str, str] | None = None,
                cwd: Path | None = None) -> KitConfig:
    path = find_config(explicit, env, cwd)
    if path is None:
        return KitConfig()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"設定ファイルを読めません: {path}: {e}") from e
    return parse_config(data, path)


def output_root(cfg: KitConfig, explicit: Path | str | None = None, env: Mapping[str, str] | None = None) -> Path:
    """出力先のルート: 引数 ＞ 環境変数 ERKIT_OUTPUT_ROOT ＞ 設定の output_root ＞ ユーザーのフォルダ\\ExplainerReelKit\\output。"""
    env = os.environ if env is None else env
    if explicit:
        return Path(explicit)
    if env.get("ERKIT_OUTPUT_ROOT"):
        return Path(env["ERKIT_OUTPUT_ROOT"])
    if cfg.output_root is not None:
        return cfg.output_root
    return Path.home() / "ExplainerReelKit" / "output"


def captures_root(cfg: KitConfig, explicit: Path | str | None = None, env: Mapping[str, str] | None = None) -> Path:
    """撮影素材のルート: 引数 ＞ 環境変数 ERKIT_CAPTURES_ROOT ＞ 設定の captures_root ＞ ユーザーのフォルダ\\ExplainerReelKit\\captures。"""
    env = os.environ if env is None else env
    if explicit:
        return Path(explicit)
    if env.get("ERKIT_CAPTURES_ROOT"):
        return Path(env["ERKIT_CAPTURES_ROOT"])
    if cfg.captures_root is not None:
        return cfg.captures_root
    return Path.home() / "ExplainerReelKit" / "captures"


def load_config_or_default(explicit: Path | str | None = None) -> KitConfig:
    """設定を読む。読めなければ既定値（呼ぶ側が設定の誤りで止まる必要がないとき）。"""
    try:
        return load_config(explicit)
    except ConfigError:
        return KitConfig()
