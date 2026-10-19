"""Badge phase implementation."""

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


class BadgePhase(GamePhase):
    """Badge phase - handles sheriff election and transfer."""

    async def on_enter(self, context: GameContext) -> None:
        """Called when entering badge phase."""
        pass

    def get_prompt(self, context: GameContext, player: Player) -> PromptResult:
        """Generate prompt for badge phase."""
        state = context.state

        if state.phase == "DAY_BADGE_SIGNUP":
            return self._build_signup_prompt(state, player)
        elif state.phase == "DAY_BADGE_ELECTION":
            return self._build_election_prompt(state, player)
        elif state.phase == "BADGE_TRANSFER":
            return self._build_transfer_prompt(state, player)

        return self._build_election_prompt(state, player)

    async def handle_action(self, context: GameContext, action: GameAction) -> None:
        """Handle badge actions."""
        pass

    async def on_exit(self, context: GameContext) -> None:
        """Called when exiting badge phase."""
        pass

    def _build_signup_prompt(self, state: GameState, player: Player) -> PromptResult:
        """Build prompt for sheriff signup."""
        game_context = build_game_context(state, player)
        difficulty_hint = build_difficulty_decision_hint(state.difficulty, player.role)

        base_content = f"""你是 {player.seat + 1}号玩家 {player.display_name}。
你的身份是: {get_role_text(player.role)}
你的胜利条件: {get_win_condition(player.role)}
{difficulty_hint}"""

        task_content = """现在是警长竞选报名阶段。
作为警长，你的投票权重为1.5票，并且拥有一些特权。

请决定是否参加警长竞选。回复 "yes" 参选，回复 "no" 不参选。"""

        system_parts = [
            SystemPromptPart(text=base_content, cacheable=True, ttl="1h"),
            SystemPromptPart(text=task_content),
        ]
        system = build_system_text_from_parts(system_parts)

        user = f"当前游戏状态:\n{game_context}\n\n请决定是否参加警长竞选:"

        return PromptResult(system=system, user=user, system_parts=system_parts)

    def _build_election_prompt(self, state: GameState, player: Player) -> PromptResult:
        """Build prompt for sheriff election."""
        game_context = build_game_context(state, player)
        difficulty_hint = build_difficulty_decision_hint(state.difficulty, player.role)

        candidates = state.badge.candidates or []
        alive_candidates = [
            p for p in state.players
            if p.alive and p.seat in candidates and p.player_id != player.player_id
        ]

        options = ", ".join([
            f"{p.seat + 1}号 {p.display_name}"
            for p in alive_candidates
        ])

        base_content = f"""你是 {player.seat + 1}号玩家 {player.display_name}。
你的身份是: {get_role_text(player.role)}
你的胜利条件: {get_win_condition(player.role)}
{difficulty_hint}"""

        task_content = f"""现在是警长选举阶段。
请投票选出警长。

候选人: {options}

请选择一个座位号投票。只需回复座位号数字。"""

        system_parts = [
            SystemPromptPart(text=base_content, cacheable=True, ttl="1h"),
            SystemPromptPart(text=task_content),
        ]
        system = build_system_text_from_parts(system_parts)

        user = f"当前游戏状态:\n{game_context}\n\n请选择你支持的警长候选人:"

        return PromptResult(system=system, user=user, system_parts=system_parts)

    def _build_transfer_prompt(self, state: GameState, player: Player) -> PromptResult:
        """Build prompt for sheriff transfer."""
        game_context = build_game_context(state, player)
        difficulty_hint = build_difficulty_decision_hint(state.difficulty, player.role)

        alive_players = [p for p in state.players if p.alive and p.player_id != player.player_id]

        options = ", ".join([
            f"{p.seat + 1}号 {p.display_name}"
            for p in alive_players
        ])

        base_content = f"""你是 {player.seat + 1}号玩家 {player.display_name}。
你的身份是: {get_role_text(player.role)}
你的胜利条件: {get_win_condition(player.role)}
{difficulty_hint}"""

        task_content = f"""你即将被淘汰，作为警长需要移交警徽。

可移交目标: {options}

请选择一个座位号移交警徽。只需回复座位号数字。"""

        system_parts = [
            SystemPromptPart(text=base_content, cacheable=True, ttl="1h"),
            SystemPromptPart(text=task_content),
        ]
        system = build_system_text_from_parts(system_parts)

        user = f"当前游戏状态:\n{game_context}\n\n请选择警徽移交给谁:"

        return PromptResult(system=system, user=user, system_parts=system_parts)
