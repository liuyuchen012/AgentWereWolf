"""LLM 配置加载器 - 为每个玩家 Agent 加载独立的模型和超参数配置

配置格式：
  - default: 字符串（模型配置文件名，不含 .json）或内联字典
  - players.seat_N: 字符串（模型配置文件名）或 {"config": "模型名", ...覆盖参数}

每个模型维护一个独立的 JSON 文件（如 qwen-plus.json, deepseek-v3.2.json）。
配置文件的 api_key / api_base 留空时，按 provider 从环境变量读取
（deepseek -> DEEPSEEK_API_KEY，dashscope -> DASHSCOPE_API_KEY，
zenmux -> ZENMUX_API_KEY，通用兜底 LLM_API_KEY / LLM_API_BASE）。
密钥一律不写进配置文件，只在 .env 或系统环境变量中配置。
"""

import json
import os
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass


_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))

# 各 provider 对应的环境变量名：(API_KEY, API_BASE)
# 配置文件的 api_key / api_base 留空时，回退到这里读取，密钥不入库
_PROVIDER_ENV: Dict[str, Tuple[str, str]] = {
    "deepseek": ("DEEPSEEK_API_KEY", "DEEPSEEK_API_BASE"),
    "dashscope": ("DASHSCOPE_API_KEY", "DASHSCOPE_API_BASE"),
    "openai": ("OPENAI_API_KEY", "OPENAI_API_BASE"),
    "moonshot": ("MOONSHOT_API_KEY", "MOONSHOT_API_BASE"),
    "zenmux": ("ZENMUX_API_KEY", "ZENMUX_API_BASE"),
}

# provider 对应的默认 API 端点（环境变量未设置时使用）
_PROVIDER_DEFAULT_BASE: Dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "openai": "https://api.openai.com/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "zenmux": "",
}

# 通用兜底环境变量，适用于任何 provider
_GENERIC_KEY_ENVS = ("LLM_API_KEY", "DEEPSEEK_API_KEY")
_GENERIC_BASE_ENVS = ("LLM_API_BASE", "DEEPSEEK_API_BASE")


@dataclass
class PlayerLLMConfig:
    """单个玩家的 LLM 配置"""
    provider: str = "dashscope"
    model: str = "qwen-plus"
    temperature: float = 0.7
    max_tokens: int = 2000
    api_base: str = ""
    api_key: str = ""


def _load_model_json(name: str) -> Dict[str, Any]:
    """加载单个模型的 JSON 配置文件

    Args:
        name: 模型配置名（不含 .json 后缀），如 "qwen-plus"

    Returns:
        模型配置字典
    """
    path = os.path.join(_CONFIG_DIR, f"{name}.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 移除 description 字段，不参与配置合并
    data.pop("description", None)
    return data


def _resolve_seat_config(seat_value: Any, default_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """解析单个座位的配置，合并默认值

    Args:
        seat_value: 字符串（模型名）或字典（含 config 键 + 覆盖参数）
        default_cfg: 默认配置字典

    Returns:
        合并后的完整配置字典
    """
    if isinstance(seat_value, str):
        # 纯字符串：直接加载模型 JSON，用默认值兜底
        model_cfg = _load_model_json(seat_value)
        return {**default_cfg, **model_cfg}

    if isinstance(seat_value, dict):
        config_name = seat_value.get("config")
        if config_name:
            # 有 config 键：先加载模型 JSON，再用内联参数覆盖
            model_cfg = _load_model_json(config_name)
            overrides = {k: v for k, v in seat_value.items() if k != "config"}
            return {**default_cfg, **model_cfg, **overrides}
        else:
            # 纯内联字典（兼容旧格式）
            return {**default_cfg, **seat_value}

    return dict(default_cfg)


def _env_api_key(provider: str) -> str:
    """按 provider 从环境变量读取 API Key

    读取顺序：provider 专属变量 -> LLM_API_KEY -> DEEPSEEK_API_KEY（兼容旧配置）
    """
    names = list(_GENERIC_KEY_ENVS)
    if provider in _PROVIDER_ENV:
        names.insert(0, _PROVIDER_ENV[provider][0])
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _env_api_base(provider: str) -> str:
    """按 provider 从环境变量读取 API Base，读不到则用 provider 默认端点"""
    names = list(_GENERIC_BASE_ENVS)
    if provider in _PROVIDER_ENV:
        names.insert(0, _PROVIDER_ENV[provider][1])
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return _PROVIDER_DEFAULT_BASE.get(provider, "https://api.deepseek.com")


def _fill_credentials(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """api_key / api_base 留空时，统一回退到环境变量

    配置 JSON 里这两个字段通常为空字符串，仅靠 setdefault 是填不进去的，
    必须显式判空后从环境变量取，否则密钥永远读不到。
    """
    cfg = dict(cfg)
    provider = str(cfg.get("provider") or "deepseek").strip().lower()
    if not str(cfg.get("api_key") or "").strip():
        cfg["api_key"] = _env_api_key(provider)
    if not str(cfg.get("api_base") or "").strip():
        cfg["api_base"] = _env_api_base(provider)
    return cfg


def _get_default_config_path() -> str:
    """获取默认配置文件路径"""
    return os.path.join(_CONFIG_DIR, "example.json")


def get_default_config_path() -> str:
    """获取默认配置文件路径（公开接口）"""
    return _get_default_config_path()


def load_llms_config(
    config_path: Optional[str] = None,
    human_seats: Optional[list] = None,
) -> Dict[str, Any]:
    """加载 LLM 配置文件

    Args:
        config_path: 配置文件路径，默认加载 llms_config/example.json
        human_seats: 人类玩家座位号列表，这些座位会被标记为 human 并跳过 LLM 配置

    Returns:
        配置字典，包含 default 和 players 两个键
    """
    if config_path is None:
        config_path = _get_default_config_path()

    human_seats = set(human_seats or [])

    if not os.path.exists(config_path):
        return {
            "default": _fill_credentials({
                "provider": "dashscope",
                "model": "qwen-plus",
                "temperature": 0.7,
                "max_tokens": 2000,
            }),
            "players": {},
        }

    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 解析 default：可以是字符串或字典
    raw_default = data.get("default", {})

    if isinstance(raw_default, str):
        default_cfg = _load_model_json(raw_default)
    elif isinstance(raw_default, dict):
        default_cfg = dict(raw_default)
    else:
        default_cfg = {}

    # 环境变量作为 api_key / api_base 的兜底
    default_cfg = _fill_credentials(default_cfg)
    default_cfg.setdefault("provider", "dashscope")
    default_cfg.setdefault("model", "qwen-plus")
    default_cfg.setdefault("temperature", 0.7)
    default_cfg.setdefault("max_tokens", 2000)

    # 解析每个座位
    raw_players = data.get("players", {})
    resolved_players = {}
    for seat_key, seat_value in raw_players.items():
        # 提取座位号
        seat_num = int(seat_key.split("_")[1]) if seat_key.startswith("seat_") else -1
        if seat_num in human_seats:
            # 人类座位：标记为 human，不需要 LLM 配置
            resolved_players[seat_key] = {"is_human": True}
        else:
            # 模型 JSON 里的空 api_key 会覆盖 default，合并后仍需回填环境变量
            resolved_players[seat_key] = _fill_credentials(
                _resolve_seat_config(seat_value, default_cfg)
            )

    return {
        "default": default_cfg,
        "players": resolved_players,
    }


def get_player_llm_config(seat: int, config_data: Optional[Dict[str, Any]] = None) -> PlayerLLMConfig:
    """获取指定座位玩家的 LLM 配置

    Args:
        seat: 玩家座位号（0-indexed）
        config_data: 已加载的配置数据，为 None 则重新加载

    Returns:
        PlayerLLMConfig 实例
    """
    if config_data is None:
        config_data = load_llms_config()

    default_cfg = config_data.get("default", {})
    players_cfg = config_data.get("players", {})

    seat_key = f"seat_{seat}"
    # players 中的值已经在 load_llms_config 中解析合并过了
    merged = players_cfg.get(seat_key, default_cfg)

    # 人类座位不需要 LLM 配置，返回空默认值
    if merged.get("is_human"):
        return PlayerLLMConfig()

    merged = _fill_credentials(merged)

    return PlayerLLMConfig(
        provider=merged.get("provider", "dashscope"),
        model=merged.get("model", "qwen-plus"),
        temperature=merged.get("temperature", 0.7),
        max_tokens=merged.get("max_tokens", 2000),
        api_base=merged.get("api_base", ""),
        api_key=merged.get("api_key", ""),
    )
