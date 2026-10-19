"""Strategy library - provides role-specific strategies from roles/*.json."""

import json
from typing import List, Dict, Optional
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Strategy:
    """策略定义"""
    name: str
    description: str
    actions: List[str]
    priority: int = 10


class StrategyLibrary:
    """策略库 - 从 roles/*.json 加载角色策略"""

    def __init__(self, roles_dir: str = "roles"):
        self.roles_dir = Path(roles_dir)
        self.role_data: Dict[str, dict] = {}
        self.role_strategies: Dict[str, List[Strategy]] = {}
        self._load_all()

    def _load_all(self):
        """加载所有角色数据"""
        role_files = {
            "Villager": "villager.json",
            "Werewolf": "werewolf.json",
            "Seer": "seer.json",
            "Witch": "witch.json",
            "Hunter": "hunter.json",
            "Guard": "guard.json",
        }
        for role, filename in role_files.items():
            filepath = self.roles_dir / filename
            if filepath.exists():
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.role_data[role] = data
                self.role_strategies[role] = self._parse_strategies(data)

    def _parse_strategies(self, data: dict) -> List[Strategy]:
        """从 JSON 数据解析策略"""
        strategies = []
        strats = data.get("strategies", {})

        for i, item in enumerate(strats.get("basic", [])):
            strategies.append(Strategy(
                name=f"基础策略{i+1}",
                description=item.get("zh", ""),
                actions=[item.get("zh", "")],
                priority=10,
            ))

        for i, item in enumerate(strats.get("advanced", [])):
            strategies.append(Strategy(
                name=f"进阶策略{i+1}",
                description=item.get("zh", ""),
                actions=[item.get("zh", "")],
                priority=15,
            ))

        for i, item in enumerate(strats.get("expert", [])):
            strategies.append(Strategy(
                name=f"专家策略{i+1}",
                description=item.get("zh", ""),
                actions=[item.get("zh", "")],
                priority=20,
            ))

        return strategies

    def get_strategies_for_role(
        self,
        role: str,
        difficulty: str = "normal",
        max_strategies: int = 4,
    ) -> List[Strategy]:
        """获取角色适用的策略"""
        all_strategies = self.role_strategies.get(role, [])
        if not all_strategies:
            return []

        if difficulty == "easy":
            filtered = [s for s in all_strategies if s.priority <= 10]
        elif difficulty == "hard":
            filtered = sorted(all_strategies, key=lambda s: s.priority, reverse=True)
        else:
            # normal: 基础 + 部分进阶
            filtered = [s for s in all_strategies if s.priority <= 15]

        return filtered[:max_strategies]

    def get_role_description(self, role: str) -> str:
        """获取角色描述"""
        data = self.role_data.get(role, {})
        desc = data.get("description", {})
        return desc.get("zh", "")

    def get_role_abilities(self, role: str) -> Dict[str, str]:
        """获取角色能力"""
        data = self.role_data.get(role, {})
        abilities = data.get("abilities", {})
        result = {}
        for key in ("night", "day", "passive"):
            ab = abilities.get(key, {})
            text = ab.get("zh", "")
            if text:
                result[key] = text
        return result

    def get_win_condition(self, role: str) -> str:
        """获取胜利条件"""
        data = self.role_data.get(role, {})
        wc = data.get("win_condition", {})
        return wc.get("zh", "")

    def get_common_mistakes(self, role: str) -> List[str]:
        """获取常见错误"""
        data = self.role_data.get(role, {})
        mistakes = data.get("common_mistakes", [])
        return [m.get("zh", "") for m in mistakes if m.get("zh")]

    def get_tips(self, role: str) -> List[str]:
        """获取提示"""
        data = self.role_data.get(role, {})
        tips = data.get("tips", [])
        return [t.get("zh", "") for t in tips if t.get("zh")]

    def format_strategies_for_prompt(
        self,
        strategies: List[Strategy],
    ) -> str:
        """格式化策略用于 Prompt"""
        if not strategies:
            return ""

        lines = ["【可用策略】"]
        for i, s in enumerate(strategies, 1):
            lines.append(f"{i}. {s.description}")
        return "\n".join(lines)

    def format_role_info_for_prompt(self, role: str) -> str:
        """格式化角色完整信息用于 Prompt"""
        lines = []

        desc = self.get_role_description(role)
        if desc:
            lines.append(f"【角色说明】\n{desc}")

        abilities = self.get_role_abilities(role)
        if abilities:
            lines.append("\n【能力】")
            ability_names = {"night": "夜间", "day": "白天", "passive": "被动"}
            for key, text in abilities.items():
                lines.append(f"  {ability_names.get(key, key)}: {text}")

        wc = self.get_win_condition(role)
        if wc:
            lines.append(f"\n【胜利条件】{wc}")

        tips = self.get_tips(role)
        if tips:
            lines.append("\n【提示】")
            for tip in tips[:3]:
                lines.append(f"  - {tip}")

        return "\n".join(lines)
