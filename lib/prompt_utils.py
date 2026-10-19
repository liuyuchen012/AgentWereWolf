"""Prompt utilities for generating AI prompts."""

from typing import List, Optional, Dict, Any
from game_types.game_types import GameState, Player, Role, DifficultyLevel
from game.core.types import SystemPromptPart


def get_role_text(role: Role) -> str:
    """Get role display text in Chinese."""
    role_names = {
        "Villager": "村民",
        "Werewolf": "狼人",
        "Seer": "预言家",
        "Witch": "女巫",
        "Hunter": "猎人",
        "Guard": "守卫",
    }
    return role_names.get(role, role)


def get_win_condition(role: Role) -> str:
    """Get win condition for a role."""
    if role == "Werewolf":
        return "杀死所有好人（村民、预言家、女巫、猎人、守卫），狼人阵营获胜"
    else:
        return "投票处决所有狼人，好人阵营获胜"


def get_role_know_how(role: Role) -> str:
    """Get role-specific strategy tips."""
    tips = {
        "Villager": "作为村民，你需要仔细观察其他玩家的发言，寻找可疑之处。",
        "Werewolf": "作为狼人，你需要隐藏自己的身份，尽量模仿好人的行为和发言。",
        "Seer": "作为预言家，你每晚可以查验一名玩家的身份，合理利用这个信息。",
        "Witch": "作为女巫，你有一瓶解药和一瓶毒药，各只能使用一次，请谨慎使用。",
        "Hunter": "作为猎人，被投票出局或被狼人杀死时可以开枪带走一名玩家（被女巫毒死不能开枪）。",
        "Guard": "作为守卫，每晚可以保护一名玩家免受狼人攻击（不能连续保护同一人）。",
    }
    return tips.get(role, "")


def build_game_context(
    state: GameState,
    player: Player,
    options: Optional[Dict[str, Any]] = None
) -> str:
    """Build game context string for prompts."""
    options = options or {}
    exclude_pending_deaths = options.get("exclude_pending_deaths", False)

    lines = []
    lines.append(f"当前是第 {state.day} 天")
    lines.append(f"当前阶段: {state.phase}")

    # Player status
    alive_players = [p for p in state.players if p.alive]
    alive_count = len(alive_players)
    total_count = len(state.players)
    lines.append(f"存活玩家: {alive_count}/{total_count}")

    # List alive players
    player_list = []
    for p in state.players:
        status = "存活" if p.alive else "已死亡"
        seat_label = f"{p.seat + 1}号 {p.display_name}"
        if p.player_id == player.player_id:
            seat_label += " (你)"
        player_list.append(f"  {seat_label}: {status}")

    lines.append("玩家列表:")
    lines.extend(player_list)

    # Sheriff info
    if state.badge.holder_seat is not None:
        sheriff = next((p for p in state.players if p.seat == state.badge.holder_seat), None)
        if sheriff:
            lines.append(f"警长: {sheriff.seat + 1}号 {sheriff.display_name}")

    return "\n".join(lines)


def build_difficulty_decision_hint(difficulty: DifficultyLevel, role: Role) -> str:
    """Build difficulty-based decision hints."""
    if difficulty == "easy":
        return "这是简单模式，请降低你的推理能力，给人类玩家更多机会。"
    elif difficulty == "hard":
        return "这是困难模式，请发挥你的最佳推理能力，让游戏更具挑战性。"
    return ""


def build_difficulty_speech_hint(difficulty: DifficultyLevel) -> str:
    """Build difficulty-based speech hints."""
    if difficulty == "easy":
        return "请保持简短的发言。"
    elif difficulty == "hard":
        return "请进行详细的分析和推理。"
    return ""


def build_persona_section(player: Player, is_genshin_mode: bool) -> str:
    """Build persona section for prompts."""
    if not player.agent_profile or not player.agent_profile.persona:
        return ""

    persona = player.agent_profile.persona
    lines = []

    if persona.style_label:
        lines.append(f"你的说话风格: {persona.style_label}")

    if persona.mbti:
        lines.append(f"你的性格类型: {persona.mbti}")

    if persona.voice_rules:
        lines.append("说话规则:")
        for rule in persona.voice_rules:
            lines.append(f"  - {rule}")

    return "\n".join(lines)


def build_today_transcript(state: GameState, max_chars: int = 10000, player: "Player" = None) -> str:
    """Build today's message transcript, filtered by player visibility."""
    today_messages = [m for m in state.messages if m.day == state.day]

    lines = []
    total_chars = 0

    for msg in today_messages:
        # 如果指定了 player，过滤掉该玩家不可见的消息
        if player is not None:
            if msg.visible_to_roles is not None:
                if player.role not in msg.visible_to_roles:
                    continue
            if msg.phase == "NIGHT_DISCUSSION" and (not msg.visible_to_roles or player.role not in msg.visible_to_roles):
                continue

        if msg.is_system:
            line = f"[系统] {msg.content}"
        else:
            line = f"{msg.player_name}: {msg.content}"

        total_chars += len(line)
        if total_chars > max_chars:
            break

        lines.append(line)

    return "\n".join(lines)


def build_player_today_speech(state: GameState, player: Player, max_chars: int = 2000) -> str:
    """Build player's own speech from today."""
    player_messages = [
        m for m in state.messages
        if m.day == state.day and m.player_id == player.player_id and not m.is_system
    ]

    lines = [msg.content for msg in player_messages]
    result = "\n".join(lines)

    if len(result) > max_chars:
        result = result[:max_chars] + "..."

    return result


def get_day_start_index(state: GameState) -> int:
    """Get the index of first message from today."""
    for i, msg in enumerate(state.messages):
        if msg.day == state.day:
            return i
    return len(state.messages)


def build_system_text_from_parts(parts: List[SystemPromptPart]) -> str:
    """Build system text from prompt parts."""
    return "\n\n".join([part.text for part in parts])


def build_cached_system_message_from_parts(
    parts: Optional[List[SystemPromptPart]],
    fallback: str,
    use_cache: bool = True
) -> Dict[str, Any]:
    """Build cached system message from parts."""
    if not parts:
        return {"role": "system", "content": fallback}

    if not use_cache:
        return {"role": "system", "content": fallback}

    # Build content with cache control
    content_parts = []
    for part in parts:
        content_part = {"type": "text", "text": part.text}
        if part.cacheable:
            content_part["cache_control"] = {"type": "ephemeral"}
            if part.ttl:
                content_part["cache_control"]["ttl"] = part.ttl
        content_parts.append(content_part)

    return {"role": "system", "content": content_parts}
