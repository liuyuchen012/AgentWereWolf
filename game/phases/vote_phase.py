"""Vote phase implementation."""

from game.core.game_phase import GamePhase
from game.core.types import GameContext, GameAction, PromptResult, SystemPromptPart
from game_types.game_types import Player, GameState
from lib.prompt_utils import (
    build_game_context,
    build_difficulty_decision_hint,
    get_role_text,
    get_win_condition,
    build_system_text_from_parts,
    build_today_transcript,
)


class VotePhase(GamePhase):
    """Vote phase - handles voting."""

    async def on_enter(self, context: GameContext) -> None:
        """Called when entering vote phase."""
        pass

    def get_prompt(self, context: GameContext, player: Player) -> PromptResult:
        """Generate prompt for voting."""
        state = context.state
        game_context = build_game_context(state, player)
        difficulty_hint = build_difficulty_decision_hint(state.difficulty, player.role)

        # Determine eligible targets
        eligible_seats = None
        if state.pk_source == "vote" and state.pk_targets:
            eligible_seats = set(state.pk_targets)

        alive_players = [
            p for p in state.players
            if p.alive
            and (eligible_seats is None or p.seat in eligible_seats)
        ]

        options = ", ".join([
            f"{p.seat + 1}号 {p.display_name}"
            for p in alive_players
        ])

        today_transcript = build_today_transcript(state, max_chars=10000, player=player)

        base_content = f"""你是 {player.seat + 1}号玩家 {player.display_name}。
你的身份是: {get_role_text(player.role)}
你的胜利条件: {get_win_condition(player.role)}
{difficulty_hint}"""

        task_content = f"""现在是投票阶段。
请根据今天的发言和你的判断，选择一名玩家投出局。

可投票目标: {options}

请选择一个座位号投票。只需回复座位号数字。"""

        system_parts = [
            SystemPromptPart(text=base_content, cacheable=True, ttl="1h"),
            SystemPromptPart(text=task_content),
        ]
        system = build_system_text_from_parts(system_parts)

        user_content = f"""当前游戏状态:
{game_context}

今日发言记录:
{today_transcript if today_transcript else "（暂无发言）"}

请选择你要投票的玩家座位号:"""

        return PromptResult(system=system, user=user_content, system_parts=system_parts)

    async def handle_action(self, context: GameContext, action: GameAction) -> None:
        """Handle vote actions."""
        pass

    async def on_exit(self, context: GameContext) -> None:
        """Called when exiting vote phase."""
        pass
