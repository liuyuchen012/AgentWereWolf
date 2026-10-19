"""Hunter phase implementation."""

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


class HunterPhase(GamePhase):
    """Hunter phase - handles hunter shooting."""

    async def on_enter(self, context: GameContext) -> None:
        """Called when entering hunter phase."""
        pass

    def get_prompt(self, context: GameContext, player: Player) -> PromptResult:
        """Generate prompt for hunter shooting."""
        state = context.state
        game_context = build_game_context(state, player)
        difficulty_hint = build_difficulty_decision_hint(state.difficulty, player.role)

        alive_players = [p for p in state.players if p.alive and p.player_id != player.player_id]

        options = ", ".join([
            f"{p.seat + 1}号 {p.display_name}"
            for p in alive_players
        ])

        base_content = f"""你是 {player.seat + 1}号玩家 {player.display_name}。
你的身份是: {get_role_text("Hunter")}
你的胜利条件: {get_win_condition("Hunter")}
{difficulty_hint}"""

        task_content = f"""你即将被淘汰。
作为猎人，你可以开枪带走一名玩家。

可射击目标: {options}

请选择一个座位号射击。只需回复座位号数字。"""

        system_parts = [
            SystemPromptPart(text=base_content, cacheable=True, ttl="1h"),
            SystemPromptPart(text=task_content),
        ]
        system = build_system_text_from_parts(system_parts)

        user = f"当前游戏状态:\n{game_context}\n\n请选择你要射击的玩家座位号:"

        return PromptResult(system=system, user=user, system_parts=system_parts)

    async def handle_action(self, context: GameContext, action: GameAction) -> None:
        """Handle hunter actions."""
        pass

    async def on_exit(self, context: GameContext) -> None:
        """Called when exiting hunter phase."""
        pass
