"""Phase manager for coordinating game phases."""

from typing import Optional, Dict
from .game_phase import GamePhase
from .types import GameContext, PromptResult
from game_types.game_types import Phase, Player


class PhaseManager:
    """Manages game phases and their implementations."""

    def __init__(self):
        """Initialize phase manager with phase implementations."""
        # Import phase implementations here to avoid circular imports
        from game.phases.night_phase import NightPhase
        from game.phases.vote_phase import VotePhase
        from game.phases.day_speech_phase import DaySpeechPhase
        from game.phases.badge_phase import BadgePhase
        from game.phases.hunter_phase import HunterPhase

        night_phase = NightPhase()
        vote_phase = VotePhase()
        day_speech_phase = DaySpeechPhase()
        badge_phase = BadgePhase()
        hunter_phase = HunterPhase()

        self.phases: Dict[Phase, GamePhase] = {
            "NIGHT_START": night_phase,
            "NIGHT_GUARD_ACTION": night_phase,
            "NIGHT_WOLF_ACTION": night_phase,
            "NIGHT_WITCH_ACTION": night_phase,
            "NIGHT_SEER_ACTION": night_phase,
            "DAY_VOTE": vote_phase,
            "DAY_SPEECH": day_speech_phase,
            "DAY_LAST_WORDS": day_speech_phase,
            "DAY_BADGE_SPEECH": day_speech_phase,
            "DAY_PK_SPEECH": day_speech_phase,
            "DAY_BADGE_SIGNUP": badge_phase,
            "DAY_BADGE_ELECTION": badge_phase,
            "BADGE_TRANSFER": badge_phase,
            "HUNTER_SHOOT": hunter_phase,
        }

    def get_phase(self, phase: Phase) -> Optional[GamePhase]:
        """Get the implementation for a specific phase."""
        return self.phases.get(phase)

    def get_prompt(
        self,
        phase: Phase,
        context: GameContext,
        player: Player
    ) -> Optional[PromptResult]:
        """Get the prompt for a player in a specific phase."""
        phase_impl = self.get_phase(phase)
        if not phase_impl:
            return None
        return phase_impl.get_prompt(context, player)
