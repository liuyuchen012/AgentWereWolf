"""Game master - core game logic and state management."""

import uuid
import random
import json
from typing import List, Dict, Optional, Tuple
from game_types.game_types import (
    GameState,
    Player,
    Role,
    Phase,
    ChatMessage,
    Alignment,
    NightActions,
    RoleAbilities,
    BadgeInfo,
)
from lib.llm import LLMMessage, generate_completion, strip_markdown_code_fences
from lib.game_constants import GAME_TEMPERATURE
from game.core.phase_manager import PhaseManager
from lib.prompt_utils import build_cached_system_message_from_parts


# Global phase manager
phase_manager = PhaseManager()


def shuffle_array(array: List) -> List:
    """Shuffle an array."""
    result = array.copy()
    random.shuffle(result)
    return result


def create_initial_game_state() -> GameState:
    """Create initial game state."""
    return GameState(
        game_id=str(uuid.uuid4()),
        phase="LOBBY",
        day=0,
        difficulty="normal",
        players=[],
    )


def get_role_configuration(player_count: int) -> List[Role]:
    """Get role configuration for player count."""
    configs: Dict[int, List[Role]] = {
        8: ["Werewolf", "Werewolf", "Werewolf", "Seer", "Witch", "Hunter", "Villager", "Villager"],
        9: ["Werewolf", "Werewolf", "Werewolf", "Seer", "Witch", "Hunter", "Villager", "Villager", "Villager"],
        10: ["Werewolf", "Werewolf", "Werewolf", "Seer", "Witch", "Hunter", "Guard", "Villager", "Villager", "Villager"],
        11: ["Werewolf", "Werewolf", "Werewolf", "Werewolf", "Seer", "Witch", "Hunter", "Guard", "Villager", "Villager", "Villager"],
        12: ["Werewolf", "Werewolf", "Werewolf", "Werewolf", "Seer", "Witch", "Hunter", "Guard", "Villager", "Villager", "Villager", "Villager"],
    }

    roles = configs.get(player_count, configs[10])
    return roles.copy()


def setup_players(
    player_count: int = 10,
    fixed_roles: Optional[List[Role]] = None,
    human_seat: int = 0,
    human_name: str = "你",
    human_seats: Optional[Dict[int, str]] = None,
) -> List[Player]:
    """Setup players for a new game.

    Args:
        human_seats: dict of {seat: name} for all human players.
                     If provided, human_seat/human_name are ignored.
    """
    total_players = player_count
    roles = get_role_configuration(total_players)

    # Assign roles
    if fixed_roles and len(fixed_roles) == total_players:
        assigned_roles = fixed_roles
    else:
        assigned_roles = shuffle_array(roles)

    # Build human seats map
    if human_seats is None:
        human_seats = {human_seat: human_name or "你"}

    players: List[Player] = []

    for seat in range(total_players):
        role = assigned_roles[seat]
        alignment: Alignment = "wolf" if role == "Werewolf" else "village"

        if seat in human_seats:
            player = Player(
                player_id=str(uuid.uuid4()),
                seat=seat,
                display_name=f"玩家{seat + 1}号",
                alive=True,
                role=role,
                alignment=alignment,
                is_human=True,
            )
        else:
            player = Player(
                player_id=str(uuid.uuid4()),
                seat=seat,
                display_name=f"玩家{seat + 1}号",
                alive=True,
                role=role,
                alignment=alignment,
                is_human=False,
            )

        players.append(player)

    return players


def add_system_message(
    state: GameState,
    content: str,
    visibility_type: str = "public",
    visible_to_roles: list = None,
) -> GameState:
    """Add a system message to the game."""
    message = ChatMessage(
        id=str(uuid.uuid4()),
        player_id="system",
        player_name="主持人",
        content=content,
        timestamp=0,  # Use time.time() in production
        day=state.day,
        phase=state.phase,
        is_system=True,
        visibility_type=visibility_type,
        visible_to_roles=visible_to_roles,
    )

    new_messages = state.messages.copy()
    new_messages.append(message)

    return GameState(
        **{**state.__dict__, "messages": new_messages}
    )


def add_player_message(
    state: GameState,
    player_id: str,
    content: str,
    is_last_words: bool = False
) -> GameState:
    """Add a player message to the game."""
    player = next((p for p in state.players if p.player_id == player_id), None)
    if not player:
        return state

    if not content.strip():
        return state

    message = ChatMessage(
        id=str(uuid.uuid4()),
        player_id=player_id,
        player_name=player.display_name,
        content=content,
        timestamp=0,
        day=state.day,
        phase=state.phase,
        is_last_words=is_last_words,
    )

    new_messages = state.messages.copy()
    new_messages.append(message)

    return GameState(
        **{**state.__dict__, "messages": new_messages}
    )


def transition_phase(state: GameState, new_phase: Phase) -> GameState:
    """Transition to a new phase."""
    is_night_phase = new_phase.startswith("NIGHT_")
    should_clear_speaker = is_night_phase or new_phase in ["DAY_VOTE", "DAY_RESOLVE"]

    updates = {"phase": new_phase}
    if should_clear_speaker:
        updates["current_speaker_seat"] = None

    return GameState(
        **{**state.__dict__, **updates}
    )


def check_win_condition(state: GameState) -> Optional[Alignment]:
    """Check if there's a winner."""
    alive_players = [p for p in state.players if p.alive]
    alive_wolves = [p for p in alive_players if p.alignment == "wolf"]
    alive_villagers = [p for p in alive_players if p.alignment == "village"]

    if len(alive_wolves) == 0:
        return "village"

    if len(alive_wolves) >= len(alive_villagers):
        return "wolf"

    return None


def kill_player(state: GameState, seat: int) -> GameState:
    """Kill a player."""
    new_players = []
    for p in state.players:
        if p.seat == seat:
            new_players.append(Player(**{**p.__dict__, "alive": False}))
        else:
            new_players.append(p)

    return GameState(
        **{**state.__dict__, "players": new_players}
    )


def get_next_alive_seat(
    state: GameState,
    current_seat: int,
    stop_at_sheriff: bool,
    direction: str = "clockwise"
) -> Optional[int]:
    """Get next alive player seat."""
    alive_seats = [p.seat for p in state.players if p.alive]
    if not alive_seats:
        return None

    alive_seats.sort()
    total = len(state.players)

    if direction == "clockwise":
        for step in range(1, total + 1):
            next_seat = (current_seat + step) % total
            if next_seat in alive_seats:
                if stop_at_sheriff and next_seat == state.badge.holder_seat:
                    return state.badge.holder_seat
                return next_seat
    else:  # counterclockwise
        for step in range(1, total + 1):
            next_seat = (current_seat - step) % total
            if next_seat in alive_seats:
                if stop_at_sheriff and next_seat == state.badge.holder_seat:
                    return state.badge.holder_seat
                return next_seat

    return None


def tally_votes(state: GameState) -> Optional[Dict[str, int]]:
    """Tally votes and return the result."""
    vote_counts: Dict[int, float] = {}

    sheriff_seat = state.badge.holder_seat
    sheriff_player = None
    if sheriff_seat is not None:
        sheriff_player = next((p for p in state.players if p.seat == sheriff_seat and p.alive), None)

    alive_player_ids = {p.player_id for p in state.players if p.alive}
    alive_seats = {p.seat for p in state.players if p.alive}

    for voter_id, target_seat in state.votes.items():
        if voter_id not in alive_player_ids:
            continue
        if target_seat not in alive_seats:
            continue

        # Sheriff gets 1.5 votes
        weight = 1.5 if (sheriff_player and voter_id == sheriff_player.player_id) else 1.0
        vote_counts[target_seat] = vote_counts.get(target_seat, 0) + weight

    if not vote_counts:
        return None

    max_votes = max(vote_counts.values())
    top_seats = [seat for seat, count in vote_counts.items() if count == max_votes]

    # If there's a tie, return None
    if len(top_seats) > 1:
        return None

    return {"seat": top_seats[0], "count": max_votes}


async def generate_ai_vote(state: GameState, player: Player) -> Dict[str, any]:
    """Generate AI vote decision."""
    # This would use the phase manager to get the prompt
    # and then call the LLM to make a decision
    # Simplified version for now

    alive_players = [p for p in state.players if p.alive and p.player_id != player.player_id]
    if not alive_players:
        return {"seat": 0, "reason": "No valid targets"}

    # Random vote for now - in full implementation would use LLM
    target = random.choice(alive_players)
    return {"seat": target.seat, "reason": f"投票给{target.display_name}"}


async def generate_guard_action(state: GameState, player: Player) -> int:
    """Generate guard action."""
    alive_players = [p for p in state.players if p.alive]
    last_target = state.night_actions.last_guard_target

    # Can't guard the same person twice in a row
    valid_targets = [p for p in alive_players if p.seat != last_target]

    if not valid_targets:
        valid_targets = alive_players

    if valid_targets:
        return random.choice(valid_targets).seat

    return 0


async def generate_wolf_action(
    state: GameState,
    player: Player,
    existing_votes: Dict[str, int]
) -> int:
    """Generate wolf kill action."""
    alive_players = [p for p in state.players if p.alive and p.alignment == "village"]

    if alive_players:
        return random.choice(alive_players).seat

    return 0


async def generate_witch_action(
    state: GameState,
    player: Player,
    wolf_target: Optional[int]
) -> Dict[str, any]:
    """Generate witch action."""
    can_save = not state.role_abilities.witch_heal_used and wolf_target is not None
    can_poison = not state.role_abilities.witch_poison_used

    # Simplified logic - in full implementation would use LLM
    if can_save and random.random() > 0.5:
        return {"type": "save", "target": None}

    if can_poison:
        alive_players = [p for p in state.players if p.alive and p.player_id != player.player_id]
        if alive_players and random.random() > 0.7:
            target = random.choice(alive_players)
            return {"type": "poison", "target": target.seat}

    return {"type": "pass", "target": None}


async def generate_seer_action(state: GameState, player: Player) -> int:
    """Generate seer check action."""
    alive_players = [p for p in state.players if p.alive and p.player_id != player.player_id]

    # Avoid checking same person twice
    if state.night_actions.seer_history:
        checked_seats = {h["targetSeat"] for h in state.night_actions.seer_history}
        unchecked = [p for p in alive_players if p.seat not in checked_seats]
        if unchecked:
            alive_players = unchecked

    if alive_players:
        return random.choice(alive_players).seat

    return 0
