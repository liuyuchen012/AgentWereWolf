"""Game type definitions for WolfCha (狼人杀游戏)."""

from typing import Literal, Optional, Dict, List, Any, Union
from dataclasses import dataclass, field
from datetime import datetime
import uuid


# Type aliases
Role = Literal["Villager", "Werewolf", "Seer", "Witch", "Hunter", "Guard"]
MessageVisibility = Literal[
    "public",           # 所有人可见（死亡公告、天亮、平安夜、阶段提示等）
    "seer_only",        # 仅预言家可见（查验结果）
    "witch_only",       # 仅女巫可见（女巫用药信息）
    "guard_only",       # 仅守卫可见（守卫保护信息）
    "wolf_only",        # 仅狼人可见（狼人夜间行动信息）
    "hunter_public",    # 猎人信息（公开的，如开枪）
    "night_discussion", # 夜晚讨论消息（仅同角色阵营可见）
]
DifficultyLevel = Literal["easy", "normal", "hard"]
SpeechDirection = Literal["clockwise", "counterclockwise"]
DevPreset = Literal["MILK_POISON_TEST", "LAST_WORDS_TEST"]
Alignment = Literal["village", "wolf"]
GameEventType = Literal[
    "GAME_START",
    "ROLE_ASSIGNED",
    "PHASE_CHANGED",
    "CHAT_MESSAGE",
    "SYSTEM_MESSAGE",
    "NIGHT_ACTION",
    "VOTE_CAST",
    "PLAYER_DIED",
    "GAME_END",
]
Phase = Literal[
    "LOBBY",
    "SETUP",
    "NIGHT_START",
    "NIGHT_DISCUSSION",
    "NIGHT_GUARD_ACTION",
    "NIGHT_WOLF_ACTION",
    "NIGHT_WITCH_ACTION",
    "NIGHT_SEER_ACTION",
    "NIGHT_RESOLVE",
    "DAY_START",
    "DAY_BADGE_SIGNUP",
    "DAY_BADGE_SPEECH",
    "DAY_BADGE_ELECTION",
    "DAY_PK_SPEECH",
    "DAY_SPEECH",
    "DAY_LAST_WORDS",
    "DAY_VOTE",
    "DAY_RESOLVE",
    "BADGE_TRANSFER",
    "HUNTER_SHOOT",
    "GAME_END",
]


@dataclass
class StartGameOptions:
    """Options for starting a new game."""
    fixed_roles: Optional[List[Role]] = None
    dev_preset: Optional[DevPreset] = None
    difficulty: DifficultyLevel = "normal"
    player_count: int = 10
    is_genshin_mode: bool = False


@dataclass
class GameScenario:
    """A game scenario template."""
    id: str
    title: str
    description: str
    roles_hint: str


@dataclass
class ModelRef:
    """Reference to an AI model."""
    provider: Literal["zenmux", "dashscope"]
    model: str


@dataclass
class Persona:
    """AI personality configuration."""
    style_label: str
    voice_rules: List[str]
    mbti: str
    gender: Literal["male", "female", "nonbinary"]
    age: int
    voice_id: Optional[str] = None
    relationships: Optional[List[str]] = None
    logic_style: Optional[str] = None
    trigger_topics: Optional[List[str]] = None
    social_habit: Optional[str] = None
    humor_style: Optional[str] = None


@dataclass
class AgentProfile:
    """AI agent profile with model and persona."""
    model_ref: ModelRef
    persona: Persona


@dataclass
class Player:
    """A game player."""
    player_id: str
    seat: int
    display_name: str
    alive: bool
    role: Role
    alignment: Alignment
    is_human: bool
    agent_profile: Optional[AgentProfile] = None


@dataclass
class GameEvent:
    """A game event."""
    id: str
    ts: float
    type: GameEventType
    visibility: Literal["public", "private"]
    payload: Any
    visible_to: Optional[List[str]] = None


@dataclass
class ChatMessage:
    """A chat message in the game."""
    id: str
    player_id: str
    player_name: str
    content: str
    timestamp: float
    day: Optional[int] = None
    phase: Optional[Phase] = None
    is_system: bool = False
    is_streaming: bool = False
    is_last_words: bool = False
    visibility_type: Optional[MessageVisibility] = None
    visible_to_roles: Optional[List[Role]] = None


@dataclass
class DailySummaryFact:
    """A structured fact from daily summary."""
    fact: str
    day: Optional[int] = None
    speaker_seat: Optional[int] = None
    speaker_name: Optional[str] = None
    target_seat: Optional[int] = None
    target_name: Optional[str] = None
    type: Optional[Literal["vote", "claim", "suspicion", "defense", "alignment", "death", "switch", "other"]] = None
    evidence: Optional[str] = None


@dataclass
class DailySummaryVoteData:
    """Structured vote data from daily summary."""
    sheriff_election: Optional[Dict[str, Any]] = None
    execution_vote: Optional[Dict[str, Any]] = None


@dataclass
class NightActions:
    """Night phase actions."""
    guard_target: Optional[int] = None
    last_guard_target: Optional[int] = None
    wolf_votes: Optional[Dict[str, int]] = None
    wolf_target: Optional[int] = None
    witch_save: Optional[bool] = None
    witch_poison: Optional[int] = None
    seer_target: Optional[int] = None
    seer_result: Optional[Dict[str, Any]] = None
    seer_history: Optional[List[Dict[str, Any]]] = None
    pending_wolf_victim: Optional[int] = None
    pending_poison_victim: Optional[int] = None


@dataclass
class RoleAbilities:
    """Role ability tracking."""
    witch_heal_used: bool = False
    witch_poison_used: bool = False
    hunter_can_shoot: bool = True


@dataclass
class BadgeInfo:
    """Sheriff badge information."""
    holder_seat: Optional[int] = None
    candidates: List[int] = field(default_factory=list)
    signup: Dict[str, bool] = field(default_factory=dict)
    votes: Dict[str, int] = field(default_factory=dict)
    history: Dict[int, Dict[str, int]] = field(default_factory=dict)
    revote_count: int = 0


@dataclass
class GameState:
    """The complete game state."""
    game_id: str
    phase: Phase
    day: int
    difficulty: DifficultyLevel
    players: List[Player]
    events: List[GameEvent] = field(default_factory=list)
    messages: List[ChatMessage] = field(default_factory=list)
    current_speaker_seat: Optional[int] = None
    next_speaker_seat_override: Optional[int] = None
    day_speech_start_seat: Optional[int] = None
    speech_direction: SpeechDirection = "clockwise"
    pk_targets: Optional[List[int]] = None
    pk_source: Optional[Literal["badge", "vote"]] = None
    badge: BadgeInfo = field(default_factory=BadgeInfo)
    votes: Dict[str, int] = field(default_factory=dict)
    vote_reasons: Optional[Dict[str, str]] = None
    last_vote_reasons: Optional[Dict[str, str]] = None
    vote_history: Dict[int, Dict[str, int]] = field(default_factory=dict)
    night_history: Optional[Dict[int, Dict[str, Any]]] = None
    day_history: Optional[Dict[int, Dict[str, Any]]] = None
    daily_summaries: Dict[int, List[str]] = field(default_factory=dict)
    daily_summary_facts: Dict[int, List[DailySummaryFact]] = field(default_factory=dict)
    daily_summary_vote_data: Optional[Dict[int, DailySummaryVoteData]] = None
    night_actions: NightActions = field(default_factory=NightActions)
    role_abilities: RoleAbilities = field(default_factory=RoleAbilities)
    winner: Optional[Alignment] = None
    dev_mutation_id: Optional[int] = None
    dev_phase_jump: Optional[Dict[str, Any]] = None
    is_paused: bool = False
    scenario: Optional[GameScenario] = None
    is_genshin_mode: bool = False


# Model configurations
GENERATOR_MODEL = "google/gemini-2.5-flash-lite"
SUMMARY_MODEL = "google/gemini-2.5-flash-lite"

AVAILABLE_MODELS: List[ModelRef] = [
    ModelRef(provider="dashscope", model="deepseek-v3.2"),
    ModelRef(provider="dashscope", model="qwen-plus"),
    ModelRef(provider="dashscope", model="Moonshot-Kimi-K2-Instruct"),
    ModelRef(provider="dashscope", model="qwen3-max"),
    ModelRef(provider="dashscope", model="qwen3-next-80b-a3b-instruct"),
    ModelRef(provider="zenmux", model="google/gemini-2.5-flash-lite"),
    ModelRef(provider="zenmux", model="google/gemini-3-flash-preview"),
]

NON_PLAYER_MODELS = [GENERATOR_MODEL, SUMMARY_MODEL]

ALL_MODELS: List[ModelRef] = [
    ModelRef(provider="dashscope", model="deepseek-v3.2"),
    ModelRef(provider="dashscope", model="qwen-plus-2025-12-01"),
    ModelRef(provider="dashscope", model="Moonshot-Kimi-K2-Instruct"),
    ModelRef(provider="dashscope", model="qwen3-next-80b-a3b-instruct"),
    ModelRef(provider="dashscope", model="qwen3-max"),
    ModelRef(provider="zenmux", model="deepseek/deepseek-v3.2"),
    ModelRef(provider="zenmux", model="google/gemini-3-flash-preview"),
    ModelRef(provider="zenmux", model="moonshotai/kimi-k2-0905"),
    ModelRef(provider="zenmux", model="qwen/qwen3-max"),
    ModelRef(provider="zenmux", model="volcengine/doubao-seed-1.8"),
    ModelRef(provider="zenmux", model="google/gemini-2.5-flash-lite"),
    ModelRef(provider="zenmux", model="openai/gpt-5.2-chat"),
    ModelRef(provider="zenmux", model="anthropic/claude-haiku-4.5"),
    ModelRef(provider="zenmux", model="anthropic/claude-sonnet-4.5"),
    ModelRef(provider="zenmux", model="anthropic/claude-opus-4.5"),
    ModelRef(provider="zenmux", model="x-ai/grok-4"),
    ModelRef(provider="zenmux", model="google/gemini-3-pro-preview"),
]


def filter_player_models(models: List[ModelRef]) -> List[ModelRef]:
    """Filter out non-player models."""
    return [m for m in models if m.model not in NON_PLAYER_MODELS]


PLAYER_MODELS: List[ModelRef] = filter_player_models(AVAILABLE_MODELS)
