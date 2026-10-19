"""Core game types for game phases."""

from typing import Protocol, Any, Dict, Optional, List
from dataclasses import dataclass
from game_types.game_types import GameState, Player, Phase


@dataclass
class SystemPromptPart:
    """A part of the system prompt."""
    text: str
    cacheable: bool = False
    ttl: Optional[str] = None  # "5m" or "1h"


@dataclass
class PromptResult:
    """Result of prompt generation."""
    system: str
    user: str
    system_parts: Optional[List[SystemPromptPart]] = None


# Game action types
@dataclass
class GameAction:
    """Base class for game actions."""
    type: str
    payload: Optional[Dict[str, Any]] = None


@dataclass
class StartNightAction(GameAction):
    """Start night phase."""
    def __init__(self):
        super().__init__(type="START_NIGHT")


@dataclass
class ContinueNightAfterGuardAction(GameAction):
    """Continue night after guard action."""
    def __init__(self):
        super().__init__(type="CONTINUE_NIGHT_AFTER_GUARD")


@dataclass
class ContinueNightAfterWolfAction(GameAction):
    """Continue night after wolf action."""
    def __init__(self):
        super().__init__(type="CONTINUE_NIGHT_AFTER_WOLF")


@dataclass
class ContinueNightAfterWitchAction(GameAction):
    """Continue night after witch action."""
    def __init__(self):
        super().__init__(type="CONTINUE_NIGHT_AFTER_WITCH")


@dataclass
class StartDaySpeechAfterBadgeAction(GameAction):
    """Start day speech after badge phase."""
    def __init__(self, options: Optional[Dict[str, Any]] = None):
        super().__init__(type="START_DAY_SPEECH_AFTER_BADGE", payload=options)


@dataclass
class AdvanceSpeakerAction(GameAction):
    """Advance to next speaker."""
    def __init__(self):
        super().__init__(type="ADVANCE_SPEAKER")


@dataclass
class ResolveVotesAction(GameAction):
    """Resolve voting results."""
    def __init__(self):
        super().__init__(type="RESOLVE_VOTES")


@dataclass
class VoteAction(GameAction):
    """Cast a vote."""
    def __init__(self, target_seat: int):
        super().__init__(type="VOTE", payload={"target_seat": target_seat})


@dataclass
class NightActionAction(GameAction):
    """Perform a night action."""
    def __init__(self, target_seat: int, witch_action: Optional[str] = None):
        super().__init__(
            type="NIGHT_ACTION",
            payload={"target_seat": target_seat, "witch_action": witch_action}
        )


@dataclass
class CustomAction(GameAction):
    """Custom action."""
    def __init__(self, payload: Any):
        super().__init__(type="CUSTOM", payload=payload)


@dataclass
class GameContext:
    """Context for game phase operations."""
    state: GameState
    phase: Optional[Phase] = None
    actor: Optional[Player] = None
    extras: Optional[Dict[str, Any]] = None
