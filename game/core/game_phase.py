"""Base class for game phases."""

from abc import ABC, abstractmethod
from typing import Optional
from .types import GameContext, GameAction, PromptResult
from game_types.game_types import Player


class GamePhase(ABC):
    """Abstract base class for game phases."""

    @abstractmethod
    async def on_enter(self, context: GameContext) -> None:
        """Called when entering this phase."""
        pass

    @abstractmethod
    def get_prompt(self, context: GameContext, player: Player) -> PromptResult:
        """Generate prompt for the player in this phase."""
        pass

    @abstractmethod
    async def handle_action(self, context: GameContext, action: GameAction) -> None:
        """Handle an action in this phase."""
        pass

    @abstractmethod
    async def on_exit(self, context: GameContext) -> None:
        """Called when exiting this phase."""
        pass
