"""Information manager - filters visible information by role."""

from typing import List, Dict, Any, Optional
from game_types.game_types import GameState, Player, ChatMessage, Role


class InformationManager:
    """信息管理器 - 根据角色过滤可见信息（基于机制控制）"""

    def get_visible_messages(
        self,
        player: Player,
        state: GameState
    ) -> List[ChatMessage]:
        """获取玩家可见的消息"""
        visible = []
        for msg in state.messages:
            if self._is_message_visible(msg, player, state):
                visible.append(msg)
        return visible

    def _is_message_visible(
        self,
        msg: ChatMessage,
        player: Player,
        state: GameState
    ) -> bool:
        """判断消息是否对玩家可见"""
        # 公共阶段的消息：所有人可见
        public_phases = [
            "DAY_SPEECH",
            "DAY_LAST_WORDS",
            "DAY_BADGE_SPEECH",
            "DAY_PK_SPEECH",
        ]
        if msg.phase in public_phases:
            return True

        # 系统消息：根据 visibility_type 机制判断
        if msg.is_system:
            return self._is_system_message_visible(msg, player)

        # 夜间狼人对话：仅狼人可见
        if msg.phase == "NIGHT_WOLF_ACTION":
            return player.role == "Werewolf"

        # 夜晚讨论消息：根据 visible_to_roles 判断
        if msg.phase == "NIGHT_DISCUSSION":
            if msg.visible_to_roles:
                return player.role in msg.visible_to_roles
            return False

        # 投票阶段消息：所有人可见
        if msg.phase == "DAY_VOTE":
            return True

        # 默认不可见
        return False

    def _is_system_message_visible(
        self,
        msg: ChatMessage,
        player: Player
    ) -> bool:
        """判断系统消息是否可见（基于 visibility_type 机制控制）"""
        vtype = msg.visibility_type

        # 如果有明确的 visibility_type，按机制判断
        if vtype is not None:
            if vtype == "public":
                return True
            elif vtype == "seer_only":
                return player.role == "Seer"
            elif vtype == "witch_only":
                return player.role == "Witch"
            elif vtype == "guard_only":
                return player.role == "Guard"
            elif vtype == "wolf_only":
                return player.role == "Werewolf"
            elif vtype == "hunter_public":
                return True
            elif vtype == "night_discussion":
                if msg.visible_to_roles:
                    return player.role in msg.visible_to_roles
                return False
            else:
                return False

        # 如果有 visible_to_roles 列表，按角色列表判断
        if msg.visible_to_roles is not None:
            return player.role in msg.visible_to_roles

        # 没有设置 visibility_type 的旧消息，默认公开
        return True

    def get_role_specific_info(
        self,
        player: Player,
        state: GameState
    ) -> Dict[str, Any]:
        """获取角色专属信息"""
        info = {}

        if player.role == "Werewolf":
            teammates = [
                {"seat": p.seat, "name": p.display_name, "alive": p.alive}
                for p in state.players
                if p.role == "Werewolf" and p.player_id != player.player_id
            ]
            info["teammates"] = teammates

        elif player.role == "Seer":
            info["can_check"] = True
            seer_history = state.night_actions.seer_history or []
            info["check_history"] = seer_history

        elif player.role == "Witch":
            info["has_antidote"] = not state.role_abilities.witch_heal_used
            info["has_poison"] = not state.role_abilities.witch_poison_used
            if state.phase == "NIGHT_WITCH_ACTION":
                if state.night_actions.wolf_target is not None:
                    target = state.players[state.night_actions.wolf_target]
                    info["kill_target"] = {
                        "seat": target.seat,
                        "name": target.display_name,
                    }

        elif player.role == "Guard":
            last_protected = state.night_actions.last_guard_target
            if last_protected is not None:
                info["last_protected_seat"] = last_protected

        elif player.role == "Hunter":
            info["can_shoot"] = state.role_abilities.hunter_can_shoot

        return info

    def format_visible_messages(
        self,
        messages: List[ChatMessage],
        max_messages: int = 30
    ) -> str:
        """格式化可见消息为文本"""
        if not messages:
            return "（暂无消息）"

        recent = messages[-max_messages:]
        lines = []
        for msg in recent:
            if msg.is_system:
                lines.append(f"[系统] {msg.content}")
            else:
                lines.append(f"{msg.player_name}: {msg.content}")
        return "\n".join(lines)

    def get_today_speeches(
        self,
        player: Player,
        state: GameState
    ) -> List[ChatMessage]:
        """获取今天的发言消息"""
        today_msgs = [
            m for m in state.messages
            if m.day == state.day
            and not m.is_system
            and m.phase in ("DAY_SPEECH", "DAY_BADGE_SPEECH", "DAY_PK_SPEECH")
        ]
        return today_msgs
