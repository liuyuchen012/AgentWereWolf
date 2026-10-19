"""Night phase implementation."""

from typing import Optional, Dict, Any
from game.core.game_phase import GamePhase
from game.core.types import GameContext, GameAction, PromptResult, SystemPromptPart
from game_types.game_types import Player, GameState
from lib.prompt_utils import (
    build_game_context,
    build_difficulty_decision_hint,
    get_role_text,
    get_win_condition,
    build_system_text_from_parts,
)


class NightPhase(GamePhase):
    """Night phase - handles all night actions."""

    async def on_enter(self, context: GameContext) -> None:
        """Called when entering night phase."""
        pass

    def get_prompt(self, context: GameContext, player: Player) -> PromptResult:
        """Generate prompt for player based on current phase."""
        state = context.state
        extras = context.extras or {}

        phase = state.phase
        if phase == "NIGHT_GUARD_ACTION":
            return self._build_guard_prompt(state, player)
        elif phase == "NIGHT_WOLF_ACTION":
            existing_votes = extras.get("existing_votes", {})
            return self._build_wolf_prompt(state, player, existing_votes)
        elif phase == "NIGHT_WITCH_ACTION":
            wolf_target = extras.get("wolf_target")
            return self._build_witch_prompt(state, player, wolf_target)
        elif phase == "NIGHT_SEER_ACTION":
            return self._build_seer_prompt(state, player)
        else:
            return self._build_wolf_prompt(state, player, {})

    async def handle_action(self, context: GameContext, action: GameAction) -> None:
        """Handle night actions."""
        # Night actions are typically handled by the game flow controller
        # This is a simplified version
        pass

    async def on_exit(self, context: GameContext) -> None:
        """Called when exiting night phase."""
        pass

    def _build_guard_prompt(self, state: GameState, player: Player) -> PromptResult:
        """Build prompt for guard action."""
        game_context = build_game_context(state, player)
        difficulty_hint = build_difficulty_decision_hint(state.difficulty, player.role)

        alive_players = [p for p in state.players if p.alive]
        last_target = state.night_actions.last_guard_target

        # Filter out last target
        valid_targets = [p for p in alive_players if p.seat != last_target]

        options = ", ".join([
            f"{p.seat + 1}号 {p.display_name}"
            for p in valid_targets
        ])

        base_content = f"""你是 {player.seat + 1}号玩家 {player.display_name}。
你的身份是: {get_role_text("Guard")}
你的胜利条件: {get_win_condition("Guard")}
{difficulty_hint}"""

        task_content = f"""今晚你要保护一名玩家免受狼人攻击。
你不能连续两晚保护同一个人。
{f"上一晚你保护了 {last_target + 1}号，今晚不能选择这个人。" if last_target is not None else ""}

可选目标: {options}

请选择一个座位号来保护。只需回复座位号数字。"""

        system_parts = [
            SystemPromptPart(text=base_content, cacheable=True, ttl="1h"),
            SystemPromptPart(text=task_content),
        ]
        system = build_system_text_from_parts(system_parts)

        user = f"当前游戏状态:\n{game_context}\n\n请选择你要保护的玩家座位号:"

        return PromptResult(system=system, user=user, system_parts=system_parts)

    def _build_wolf_prompt(
        self,
        state: GameState,
        player: Player,
        existing_votes: Dict[str, int]
    ) -> PromptResult:
        """Build prompt for wolf action."""
        game_context = build_game_context(state, player)
        difficulty_hint = build_difficulty_decision_hint(state.difficulty, player.role)

        alive_players = [p for p in state.players if p.alive]
        teammates = [
            p for p in state.players
            if p.role == "Werewolf" and p.player_id != player.player_id and p.alive
        ]

        teammate_info = ""
        if teammates:
            teammate_list = ", ".join([f"{t.seat + 1}号 {t.display_name}" for t in teammates])
            teammate_info = f"你的狼队友: {teammate_list}"
        else:
            teammate_info = "你是唯一的狼人"

        # Show teammate votes if any
        vote_info = ""
        if existing_votes:
            votes = []
            for teammate in teammates:
                if teammate.player_id in existing_votes:
                    target_seat = existing_votes[teammate.player_id]
                    target = next((p for p in state.players if p.seat == target_seat), None)
                    if target:
                        votes.append(f"{teammate.display_name} 选择了 {target.seat + 1}号")
            if votes:
                vote_info = "队友的选择:\n" + "\n".join(votes)

        options = ", ".join([
            f"{p.seat + 1}号 {p.display_name}"
            for p in alive_players
        ])

        base_content = f"""你是 {player.seat + 1}号玩家 {player.display_name}。
你的身份是: {get_role_text("Werewolf")}
{teammate_info}
你的胜利条件: {get_win_condition("Werewolf")}
{difficulty_hint}"""

        task_content = f"""今晚狼人要杀死一名玩家。
{vote_info}

可选目标: {options}

请选择一个座位号来击杀。只需回复座位号数字。"""

        system_parts = [
            SystemPromptPart(text=base_content, cacheable=True, ttl="1h"),
            SystemPromptPart(text=task_content),
        ]
        system = build_system_text_from_parts(system_parts)

        user = f"当前游戏状态:\n{game_context}\n\n请选择你要击杀的玩家座位号:"

        return PromptResult(system=system, user=user, system_parts=system_parts)

    def _build_witch_prompt(
        self,
        state: GameState,
        player: Player,
        wolf_target: Optional[int]
    ) -> PromptResult:
        """Build prompt for witch action."""
        game_context = build_game_context(state, player)
        difficulty_hint = build_difficulty_decision_hint(state.difficulty, player.role)

        alive_players = [p for p in state.players if p.alive and p.player_id != player.player_id]

        can_save = not state.role_abilities.witch_heal_used
        can_poison = not state.role_abilities.witch_poison_used

        heal_status = "未使用" if not state.role_abilities.witch_heal_used else "已使用"
        poison_status = "未使用" if not state.role_abilities.witch_poison_used else "已使用"

        # Wolf target info
        victim_info = ""
        if wolf_target is not None and not state.role_abilities.witch_heal_used:
            victim = next((p for p in state.players if p.seat == wolf_target), None)
            if victim:
                victim_info = f"今晚狼人击杀了 {wolf_target + 1}号 {victim.display_name}。"
        elif state.role_abilities.witch_heal_used:
            victim_info = "你已经使用过解药，无法感知今晚的死亡信息。"
        else:
            victim_info = "今晚没有人被狼人击杀。"

        poison_targets = ", ".join([f"{p.seat + 1}号" for p in alive_players])

        base_content = f"""你是 {player.seat + 1}号玩家 {player.display_name}。
你的身份是: {get_role_text("Witch")}
你的胜利条件: {get_win_condition("Witch")}
{difficulty_hint}"""

        task_content = f"""药水状态:
- 解药: {heal_status}
- 毒药: {poison_status}

{victim_info}

你的选择:
- 如果要救人（使用解药），回复 "save"
- 如果要毒人（使用毒药），回复 "poison X"（X为座位号）
- 如果不使用药水，回复 "pass"

可毒杀的目标: {poison_targets}"""

        system_parts = [
            SystemPromptPart(text=base_content, cacheable=True, ttl="1h"),
            SystemPromptPart(text=task_content),
        ]
        system = build_system_text_from_parts(system_parts)

        user = f"当前游戏状态:\n{game_context}\n\n请选择你的行动:"

        return PromptResult(system=system, user=user, system_parts=system_parts)

    def _build_seer_prompt(self, state: GameState, player: Player) -> PromptResult:
        """Build prompt for seer action."""
        game_context = build_game_context(state, player)
        difficulty_hint = build_difficulty_decision_hint(state.difficulty, player.role)

        alive_players = [p for p in state.players if p.alive and p.player_id != player.player_id]

        # Get seer history
        seer_history = state.night_actions.seer_history or []
        checked_seats = [h.get("targetSeat") for h in seer_history]

        unchecked_players = [p for p in alive_players if p.seat not in checked_seats]
        target_players = unchecked_players if unchecked_players else alive_players

        options = ", ".join([
            f"{p.seat + 1}号 {p.display_name}"
            for p in target_players
        ])

        # History info
        history_info = ""
        if seer_history:
            history_lines = []
            for record in seer_history:
                seat = record.get("targetSeat")
                is_wolf = record.get("isWolf")
                result = "狼人" if is_wolf else "好人"
                history_lines.append(f"- {seat + 1}号: {result}")
            history_info = "你的查验记录:\n" + "\n".join(history_lines)

        base_content = f"""你是 {player.seat + 1}号玩家 {player.display_name}。
你的身份是: {get_role_text("Seer")}
你的胜利条件: {get_win_condition("Seer")}
{difficulty_hint}"""

        task_content = f"""今晚你要查验一名玩家的身份。
{history_info}

可查验目标: {options}

请选择一个座位号来查验。只需回复座位号数字。"""

        system_parts = [
            SystemPromptPart(text=base_content, cacheable=True, ttl="1h"),
            SystemPromptPart(text=task_content),
        ]
        system = build_system_text_from_parts(system_parts)

        user = f"当前游戏状态:\n{game_context}\n\n请选择你要查验的玩家座位号:"

        return PromptResult(system=system, user=user, system_parts=system_parts)
