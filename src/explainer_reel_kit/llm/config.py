"""手元の LLM の設定（config/llm.yaml）と、接続先の確かめ。

探す順: ``--llm-config`` ＞ 環境変数 ``ERKIT_LLM_CONFIG`` ＞ 今のフォルダの ``config/llm.yaml`` ＞
キットのフォルダの ``config/llm.yaml`` ＞ 組み込みの既定（LM Studio ``http://127.0.0.1:1234/v1``・Ollama）。
ひな形は ``config/llm.example.yaml``。

- 接続は ``route: local`` だけ。接続先がこの PC か LAN の IP アドレスでなければ、**コードで送信を止める**
  （設定に何と書いても）。LAN の PC は IP アドレスで書く（localhost 以外のホスト名は止める）
- **クラウドの AI の接続（route: cloud）と API キーは無い**。設定に ``route: cloud``・``api_key``・
  ``api_key_env`` があればエラー
- 社外秘の台本（区分が未記入も）は、さらに **この PC だけ**（LAN も不可）。それは LLMClient が確かめる
- モデル: 引数 ＞ tasks の model ＞ profiles の model ＞ **サーバーに読み込まれている 1 つ**。空は「指定しない」
"""

from __future__ import annotations

import ipaddress
import os
import urllib.parse
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import ConfigError, RouteBlockedError

KIT_ROOT = Path(__file__).resolve().parents[3]
CONFIG_RELPATH = Path("config") / "llm.yaml"
ENV_CONFIG = "ERKIT_LLM_CONFIG"
ROUTES = ("local",)
DEFAULT_TIMEOUT_SEC = 600.0  # 思考するモデルは数分かかることがある
THINKING_VALUES = ("auto", "off", "on")
PROFILE_KEYS = {"route", "base_url", "model", "timeout_sec"}
TASK_KEYS = {"model", "thinking", "max_tokens", "expected_context"}
TOP_KEYS = {"version", "default_profile", "profiles", "tasks", "avoid_words"}

#: 設定ファイルが無いときの既定（config/llm.example.yaml と同じ接続先）
BUILTIN: dict[str, Any] = {
    "version": 1,
    "default_profile": "lmstudio",
    "profiles": {
        "lmstudio": {"route": "local", "base_url": "http://127.0.0.1:1234/v1", "model": "", "timeout_sec": 600},
        "ollama": {"route": "local", "base_url": "http://127.0.0.1:11434/v1", "model": "", "timeout_sec": 600},
    },
    "tasks": {
        "draft": {"model": "", "thinking": "off", "max_tokens": 4096, "expected_context": 8192},
        "light": {"model": "", "thinking": "off", "max_tokens": 2048, "expected_context": 8192},
    },
    "avoid_words": [],
}

_LAN_NETWORKS = [
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "fc00::/7", "fe80::/10")
]


@dataclass(frozen=True)
class Endpoint:
    name: str
    base_url: str
    model: str = ""
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    route: str = "local"

    def with_overrides(self, *, base_url: str | None = None, model: str | None = None,
                       timeout_sec: float | None = None) -> "Endpoint":
        changes: dict[str, Any] = {}
        if base_url:
            changes["base_url"] = normalize_base_url(base_url)
        if model:
            changes["model"] = model
        if timeout_sec is not None:
            if timeout_sec <= 0:
                raise ConfigError("--llm-timeout は 0 より大きくしてください")
            changes["timeout_sec"] = float(timeout_sec)
        updated = replace(self, **changes)
        check_route(updated)
        return updated


@dataclass(frozen=True)
class Task:
    """用途ごとの既定: モデル（空ならサーバーに読み込まれている 1 つ）・思考・答えの長さの上限・想定する文脈長。"""

    name: str
    model: str = ""
    thinking: str = "off"
    max_tokens: int = 2048
    expected_context: int | None = None


@dataclass(frozen=True)
class TaskSettings:
    """呼び出しで実際に使う値（引数が task より優先）。"""

    task: str | None
    model: str | None
    thinking: str
    max_tokens: int
    expected_context: int | None
    model_source: str  # "引数" / "task <名前>" / "profile" / ""（サーバーに読み込まれている 1 つ）
    thinking_source: str


@dataclass(frozen=True)
class LLMConfig:
    path: Path | None  # 読んだファイル（無ければ None ＝ 組み込みの既定）
    endpoints: dict[str, Endpoint]
    default_profile: str | None
    tasks: dict[str, Task] = field(default_factory=dict)
    avoid_words: tuple[str, ...] = ()

    @property
    def where(self) -> str:
        return str(self.path) if self.path else "組み込みの既定"

    def endpoint(self, profile: str | None = None) -> Endpoint:
        name = profile or self.default_profile or next(iter(self.endpoints))
        if name not in self.endpoints:
            raise ConfigError(f"profile {name!r} がありません（{', '.join(self.endpoints)}）")
        return self.endpoints[name]

    def task(self, name: str | None) -> Task | None:
        if name is None:
            return None
        if name not in self.tasks:
            raise ConfigError(f"task {name!r} がありません（{', '.join(self.tasks) or 'tasks がありません'}）")
        return self.tasks[name]


def normalize_base_url(url: str) -> str:
    return url.strip().rstrip("/")


def host_kind(host: str) -> str:
    """URL のホストが 'loopback'（この PC）/ 'lan' / 'other' のどれか。"""
    name = host.strip("[]").lower()
    if name == "localhost" or name.endswith(".localhost"):
        return "loopback"
    try:
        address = ipaddress.ip_address(name.split("%", 1)[0])  # IPv6 のゾーン ID を除く
    except ValueError:
        return "other"  # localhost 以外のホスト名: どこに解決されるか分からない
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if address.is_unspecified:
        return "other"
    if address.is_loopback:
        return "loopback"
    if any(address in net for net in _LAN_NETWORKS if net.version == address.version):
        return "lan"
    return "other"


def check_route(endpoint: Endpoint) -> None:
    """接続先がこの PC・LAN 内でなければ RouteBlockedError（route: local だけ）。"""
    if endpoint.route not in ROUTES:
        raise RouteBlockedError(f"{endpoint.name}: route={endpoint.route} は使えません。キットの接続は route: local だけです")
    parsed = urllib.parse.urlsplit(endpoint.base_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConfigError(f"{endpoint.name}: base_url は http(s)://ホスト[:ポート]/... で書いてください: {endpoint.base_url}")
    if parsed.username or parsed.password:
        raise ConfigError(f"{endpoint.name}: base_url に利用者名・パスワードを入れないでください")
    if host_kind(parsed.hostname) == "other":
        raise RouteBlockedError(
            f"{endpoint.name}: 接続先 {parsed.hostname} はこの PC・LAN 内ではありません。送信しません。"
            "（LAN 内の PC は IP アドレスで指定。キットはクラウドの AI に送りません）"
        )


def _thinking_value(raw: Any, where: str) -> str:
    if raw is False:  # YAML 1.1 では引用符なしの off が false になる
        return "off"
    if raw is True:
        return "on"
    if raw in THINKING_VALUES:
        return raw
    raise ConfigError(f"{where}.thinking は auto / off / on のどれかです（{raw!r}）")


def find_config(explicit: str | Path | None = None, env: Mapping[str, str] | None = None,
                cwd: Path | None = None) -> Path | None:
    env = os.environ if env is None else env
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise ConfigError(f"LLM の設定ファイルがありません: {p}")
        return p
    if env.get(ENV_CONFIG):
        p = Path(env[ENV_CONFIG])
        if not p.is_file():
            raise ConfigError(f"環境変数 {ENV_CONFIG} の LLM の設定ファイルがありません: {p}")
        return p
    for base in (cwd or Path.cwd(), KIT_ROOT):
        p = base / CONFIG_RELPATH
        if p.is_file():
            return p
    return None


def parse_config(data: Any, path: Path | None = None) -> LLMConfig:
    where = str(path) if path else "LLM の設定"
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict) or not data["profiles"]:
        raise ConfigError(f"{where}: profiles（接続先の一覧）が必要です")
    unknown_top = set(data) - TOP_KEYS
    if unknown_top:
        raise ConfigError(f"{where} に知らない項目があります: {', '.join(sorted(map(str, unknown_top)))}")
    endpoints: dict[str, Endpoint] = {}
    for name, raw in data["profiles"].items():
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: profiles.{name} はキーと値で書いてください")
        if "api_key" in raw or "api_key_env" in raw:
            raise ConfigError(f"{where}: profiles.{name}: キットは API キーを使いません（クラウドの AI には送りません）。"
                              "api_key / api_key_env を消してください")
        unknown = set(raw) - PROFILE_KEYS
        if unknown:
            raise ConfigError(f"{where}: profiles.{name} に知らない項目があります: {', '.join(sorted(unknown))}")
        route = raw.get("route", "local")
        if route != "local":
            raise ConfigError(f"{where}: profiles.{name}.route は local だけです（{route!r}）。"
                              "キットにクラウドの AI の接続はありません")
        base_url = raw.get("base_url")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ConfigError(f"{where}: profiles.{name}.base_url がありません")
        model = raw.get("model") or ""
        if not isinstance(model, str):
            raise ConfigError(f"{where}: profiles.{name}.model は文字列です")
        timeout = raw.get("timeout_sec", DEFAULT_TIMEOUT_SEC)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ConfigError(f"{where}: profiles.{name}.timeout_sec は 0 より大きい数です")
        endpoint = Endpoint(str(name), normalize_base_url(base_url), model.strip(), float(timeout))
        check_route(endpoint)  # 読み込んだ時点で、外を向いた接続先は止める
        endpoints[str(name)] = endpoint
    default = data.get("default_profile")
    if default is not None and default not in endpoints:
        raise ConfigError(f"{where}: default_profile {default!r} が profiles にありません")

    tasks: dict[str, Task] = {}
    raw_tasks = data.get("tasks") or {}
    if not isinstance(raw_tasks, dict):
        raise ConfigError(f"{where}: tasks は名前ごとのキーと値で書いてください")
    for name, raw in raw_tasks.items():
        w = f"{where}: tasks.{name}"
        if not isinstance(raw, dict):
            raise ConfigError(f"{w} はキーと値で書いてください")
        unknown = set(raw) - TASK_KEYS
        if unknown:
            raise ConfigError(f"{w} に知らない項目があります: {', '.join(sorted(unknown))}")
        model = raw.get("model") or ""
        if not isinstance(model, str):
            raise ConfigError(f"{w}.model は文字列です（空ならサーバーに読み込まれている 1 つ）")
        max_tokens = raw.get("max_tokens", 2048)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 16:
            raise ConfigError(f"{w}.max_tokens は 16 以上の整数です")
        context = raw.get("expected_context")
        if context is not None and (isinstance(context, bool) or not isinstance(context, int) or context < 512):
            raise ConfigError(f"{w}.expected_context は 512 以上の整数です")
        tasks[str(name)] = Task(str(name), model.strip(), _thinking_value(raw.get("thinking", "off"), w),
                                max_tokens, context)

    avoid = data.get("avoid_words") or []
    if not isinstance(avoid, list) or not all(isinstance(a, str) and a.strip() for a in avoid):
        raise ConfigError(f"{where}: avoid_words は語（文字列）のリストで書いてください")
    return LLMConfig(path, endpoints, default, tasks, tuple(a.strip() for a in avoid))


def load_llm_config(explicit: str | Path | None = None, env: Mapping[str, str] | None = None,
                    cwd: Path | None = None) -> LLMConfig:
    path = find_config(explicit, env, cwd)
    if path is None:
        return parse_config(BUILTIN, None)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, yaml.YAMLError) as cause:
        raise ConfigError(f"LLM の設定ファイルを読めません（UTF-8 の YAML で保存してください）: {path}: {cause}") from cause
    except OSError as cause:
        raise ConfigError(f"LLM の設定ファイルを読めません: {path}: {cause}") from cause
    return parse_config(data, path)


def task_settings(task: Task | None, endpoint: Endpoint, *, explicit_model: str | None = None,
                  explicit_thinking: str | None = None, explicit_max_tokens: int | None = None,
                  default_thinking: str = "auto", default_max_tokens: int = 2048) -> TaskSettings:
    """引数 ＞ task ＞ profile ＞ サーバー（モデル）/ 既定（思考・max_tokens）。"""
    if explicit_model:
        model, model_source = explicit_model, "引数"
    elif task is not None and task.model:
        model, model_source = task.model, f"task {task.name}"
    elif endpoint.model:
        model, model_source = endpoint.model, "profile"
    else:
        model, model_source = None, ""
    if explicit_thinking:
        thinking, thinking_source = explicit_thinking, "引数"
    elif task is not None:
        thinking, thinking_source = task.thinking, f"task {task.name}"
    else:
        thinking, thinking_source = default_thinking, "既定"
    if explicit_max_tokens:
        max_tokens = explicit_max_tokens
    elif task is not None:
        max_tokens = task.max_tokens
    else:
        max_tokens = default_max_tokens
    return TaskSettings(task.name if task else None, model, thinking, max_tokens,
                        task.expected_context if task else None, model_source, thinking_source)
