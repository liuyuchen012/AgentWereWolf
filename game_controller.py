"""游戏流程控制器 - 协调完整的游戏流程（集成 Agent 系统）"""

import asyncio
import json
import re
import os
from typing import Optional, Dict, Any, List, Callable, Awaitable
from dataclasses import dataclass, field
from collections import Counter

from game_types.game_types import GameState, Player, Phase, Alignment, NightActions, RoleAbilities, ChatMessage
from lib.game_master import (
    create_initial_game_state,
    setup_players,
    transition_phase,
    check_win_condition,
    kill_player,
    add_system_message,
    add_player_message,
    tally_votes,
)
from game.core.phase_manager import PhaseManager
from game.core.types import GameContext
from lib.llm import LLMMessage, generate_completion, strip_markdown_code_fences
from lib.game_constants import GAME_TEMPERATURE

# Agent 系统
from agent.information import InformationManager
from agent.memory import AgentMemory, MemorySystem, init_agent_memory, Reflection
from agent.strategy import StrategyLibrary
from agent.decision import DecisionEngine
from llms_config import get_default_config_path
from lib.game_logger import GameLogger


@dataclass
class GameEvent:
    """游戏事件"""
    type: str  # "system", "speech", "action", "phase_change", "death", "vote", "game_end"
    data: Dict[str, Any]


def _create_roles_dir_path() -> str:
    """获取 roles 目录的绝对路径"""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "roles")


@dataclass
class GameController:
    """游戏控制器（集成 Agent 系统）"""
    state: GameState = field(default_factory=create_initial_game_state)
    phase_manager: PhaseManager = field(default_factory=PhaseManager)
    event_callback: Optional[Callable[[GameEvent], Awaitable[None]]] = None
    is_paused: bool = False
    _stop_flag: bool = False
    llm_config_path: Optional[str] = None  # LLM 配置文件路径，默认加载 example.json

    # Agent 系统组件
    info_manager: InformationManager = field(default_factory=InformationManager)
    memory_system: MemorySystem = field(default_factory=MemorySystem)
    strategy_lib: StrategyLibrary = field(default=None)
    decision_engine: DecisionEngine = field(default=None)
    agent_memories: Dict[str, AgentMemory] = field(default_factory=dict)

    def __post_init__(self):
        """初始化 Agent 组件"""
        if self.llm_config_path is None:
            self.llm_config_path = get_default_config_path()
        self._logger = GameLogger()
        if self.strategy_lib is None:
            self.strategy_lib = StrategyLibrary(roles_dir=_create_roles_dir_path())
        if self.decision_engine is None:
            self.decision_engine = DecisionEngine(
                info_manager=self.info_manager,
                memory_system=self.memory_system,
                strategy_lib=self.strategy_lib,
                llm_config_path=self.llm_config_path,
                logger=self._logger,
            )

    def _init_agent_memories(self):
        """在角色分配后初始化所有 AI 玩家的 Agent 记忆"""
        self.agent_memories = {}
        for player in self.state.players:
            if not player.is_human:
                self.agent_memories[player.player_id] = init_agent_memory(player, self.state)

    def _get_agent_memory(self, player: Player) -> AgentMemory:
        """获取玩家的 Agent 记忆，不存在则创建"""
        if player.player_id not in self.agent_memories:
            self.agent_memories[player.player_id] = init_agent_memory(player, self.state)
        return self.agent_memories[player.player_id]

    def _update_all_memories_from_speech(self, speaker_seat: int, speech: str):
        """所有 AI 玩家的记忆从发言更新"""
        for pid, memory in self.agent_memories.items():
            if memory.player_memories.get(speaker_seat, None) is not None:
                self.memory_system.update_from_speech(memory, speaker_seat, speech, self.state)

    def _update_wolf_memories_from_speech(self, speaker_seat: int, speech: str):
        """只更新狼人 AI 玩家的记忆（用于夜间狼人讨论）"""
        wolf_pids = {p.player_id for p in self.state.players if p.role == "Werewolf"}
        for pid, memory in self.agent_memories.items():
            if pid in wolf_pids:
                if memory.player_memories.get(speaker_seat, None) is not None:
                    self.memory_system.update_from_speech(memory, speaker_seat, speech, self.state)

    def _update_all_memories_from_vote(self, voter_seat: int, target_seat: int):
        """所有 AI 玩家的记忆从投票更新"""
        for pid, memory in self.agent_memories.items():
            self.memory_system.update_from_vote(memory, voter_seat, target_seat)

    def _update_all_memories_from_death(self, seat: int, cause: str):
        """所有 AI 玩家的记忆从死亡事件更新"""
        for pid, memory in self.agent_memories.items():
            self.memory_system.update_from_death(memory, seat, cause, self.state.day)

    def _update_trust_from_speech(self, speaker_seat: int, speech: str):
        """所有 AI 玩家根据发言更新信任分数（轻量规则，不调 LLM）"""
        for pid, memory in self.agent_memories.items():
            player = next((p for p in self.state.players if p.player_id == pid), None)
            if player and player.alive and player.seat != speaker_seat:
                self.memory_system.update_trust_from_speech(
                    memory, speaker_seat, speech, player.seat,
                )

    async def _trigger_observation_reflections(self, event_description: str, action_type: str = "observation"):
        """为所有存活 AI 玩家触发观察反思（LLM 调用）"""
        ai_players = [p for p in self.state.players if not p.is_human and p.alive]
        for player in ai_players:
            memory = self._get_agent_memory(player)
            try:
                llm_config = self.decision_engine._get_llm_config_dict(player)
                await self.memory_system.generate_reflection(
                    memory=memory,
                    event_description=event_description,
                    action_type=action_type,
                    day=self.state.day,
                    phase=self.state.phase,
                    player=player,
                    llm_config=llm_config,
                )
            except Exception as e:
                print(f"[观察反思失败] {player.display_name}: {e}")

    async def _init_agent_personalities(self):
        """为所有 AI 玩家并行生成性格（使用 LLM）"""
        ai_players = [p for p in self.state.players if not p.is_human]
        if not ai_players:
            return

        await self.emit_event("system", {"message": f"正在为 {len(ai_players)} 名玩家生成性格..."})

        # 逐个生成，避免并发导致的超时问题
        for idx, player in enumerate(ai_players, 1):
            try:
                # 发送开始生成的消息，保持连接活跃
                await self.emit_event("system", {
                    "message": f"正在生成 {player.display_name} 的性格... ({idx}/{len(ai_players)})",
                    "visibility_type": "init_progress",
                })

                personality = await self.decision_engine.generate_personality(player)

                await self.emit_event("system", {
                    "message": f"✓ {player.display_name} 性格生成完成 ({idx}/{len(ai_players)})",
                    "visibility_type": "init_progress",
                })
                print(f"[性格生成] {player.display_name}: {personality[:50]}...")
            except Exception as e:
                print(f"[性格生成失败] {player.display_name}: {e}")
                await self.emit_event("system", {
                    "message": f"✗ {player.display_name} 性格生成失败，使用默认性格",
                    "visibility_type": "init_progress",
                })

            # 每个玩家之间短暂延迟
            await asyncio.sleep(0.2)

    async def emit_event(self, event_type: str, data: Dict[str, Any]):
        """发送游戏事件"""
        event = GameEvent(type=event_type, data=data)
        if self.event_callback:
            await self.event_callback(event)

    async def start_game(
        self,
        player_count: int = 10,
        human_seat: int = 0,
        human_name: str = "玩家",
        difficulty: str = "normal",
        human_seats: Optional[List[int]] = None,
        room=None,
    ):
        """开始新游戏

        Args:
            human_seats: 人类玩家座位列表。为 None 时使用 [human_seat]。
            room: Room 对象，用于获取玩家名字。
        """
        self._stop_flag = False

        # 重置游戏状态，保留 game_id
        old_game_id = self.state.game_id
        self.state = create_initial_game_state()
        self.state.game_id = old_game_id
        self.state.difficulty = difficulty

        # 确定人类座位列表
        if human_seats is None:
            human_seats = [human_seat]

        # 构建 human_seats_map: {seat: name}
        human_seats_map = {}
        if room:
            for s in human_seats:
                info = room.seats.get(s)
                human_seats_map[s] = info["name"] if info else f"玩家{s + 1}"
        else:
            for s in human_seats:
                human_seats_map[s] = human_name if s == human_seat else f"玩家{s + 1}"

        # 重新加载 LLM 配置，标记人类座位
        from llms_config import load_llms_config
        self.decision_engine._llm_config_data = load_llms_config(
            self.llm_config_path, human_seats=human_seats
        )

        # 设置玩家（传入多人类座位）
        players = setup_players(
            player_count=player_count,
            human_seat=human_seat,
            human_name=human_name,
            human_seats=human_seats_map,
        )
        self.state.players = players
        self.state.day = 1

        # 初始化日志
        self._logger.start_game(
            game_id=self.state.game_id,
            players=players,
            config_data=self.decision_engine._llm_config_data,
        )

        # 发送游戏开始事件
        await self.emit_event("game_start", {
            "game_id": self.state.game_id,
            "players": [self._player_to_dict(p) for p in self.state.players],
            "human_seat": human_seat,
        })

        # 给每个人类玩家发送角色揭示（通过 target_seats 限定推送范围）
        for p in self.state.players:
            if p.is_human:
                event = GameEvent(type="role_reveal", data={
                    "seat": p.seat,
                    "role": p.role,
                    "role_text": self._get_role_text(p.role),
                    "teammates": self._get_teammates_info(p),
                })
                if self.event_callback:
                    await self.event_callback(event, [p.seat])

        # 角色分配完成后，初始化所有 AI 玩家的 Agent 记忆
        self._init_agent_memories()

        # 为所有 AI 玩家生成性格
        await self._init_agent_personalities()

        # 开始游戏循环
        await self.game_loop()

    async def game_loop(self):
        """游戏主循环"""
        while not self._stop_flag:
            # 检查胜利条件
            winner = check_win_condition(self.state)
            if winner:
                await self._handle_game_end(winner)
                break

            # 夜晚阶段
            await self._run_night_phase()

            if self._stop_flag:
                break

            # 检查胜利条件
            winner = check_win_condition(self.state)
            if winner:
                await self._handle_game_end(winner)
                break

            # 白天阶段
            await self._run_day_phase()

            if self._stop_flag:
                break

            # 检查胜利条件
            winner = check_win_condition(self.state)
            if winner:
                await self._handle_game_end(winner)
                break

            # 进入下一天
            self.state.day += 1

    async def _run_night_phase(self):
        """运行夜晚阶段"""
        # 夜晚开始
        self.state = transition_phase(self.state, "NIGHT_START")
        await self.emit_event("phase_change", {
            "phase": "NIGHT_START",
            "day": self.state.day,
            "message": f"第{self.state.day}夜，天黑请闭眼"
        })
        await self.emit_event("system", {"message": f"第{self.state.day}夜，天黑请闭眼"})
        await asyncio.sleep(1.5)

        # 重置夜晚行动
        self.state.night_actions = NightActions(
            last_guard_target=self.state.night_actions.last_guard_target,
            seer_history=self.state.night_actions.seer_history,
        )

        # 夜晚讨论阶段（每人最多3次发言）
        await self._night_discussion_phase()
        if self._stop_flag:
            return

        # 守卫行动
        await self._guard_action()
        if self._stop_flag:
            return

        # 狼人行动
        await self._wolf_action()
        if self._stop_flag:
            return

        # 女巫行动
        await self._witch_action()
        if self._stop_flag:
            return

        # 预言家行动
        await self._seer_action()
        if self._stop_flag:
            return

        # 夜晚结算
        await self._resolve_night()

    async def _night_discussion_phase(self):
        """夜晚讨论阶段 - 有人类狼人时讨论+选择同时进行"""
        alive_wolves = [p for p in self.state.players if p.alive and p.role == "Werewolf"]
        ai_wolves = [p for p in alive_wolves if not p.is_human]
        human_wolves = [p for p in alive_wolves if p.is_human]

        if not ai_wolves and not human_wolves:
            return

        human_is_wolf = len(human_wolves) > 0

        if human_is_wolf:
            # 合并讨论+选择阶段
            await self._wolf_discussion_and_vote(alive_wolves, ai_wolves, human_wolves)
        else:
            # 纯 AI 狼人：只讨论，选择在 _wolf_action 里
            self.state = transition_phase(self.state, "NIGHT_DISCUSSION")
            await self.emit_event("phase_change", {"phase": "NIGHT_DISCUSSION", "day": self.state.day})

            speech_counts: Dict[str, int] = {p.player_id: 0 for p in ai_wolves}
            discussion_history: List[Dict[str, str]] = []
            max_ai_speeches = 3

            for round_num in range(1, max_ai_speeches + 1):
                if self._stop_flag:
                    break
                can_speak = any(speech_counts[p.player_id] < max_ai_speeches for p in ai_wolves)
                if not can_speak:
                    break
                for player in ai_wolves:
                    if self._stop_flag or speech_counts[player.player_id] >= max_ai_speeches:
                        continue
                    self.state.current_speaker_seat = player.seat
                    memory = self._get_agent_memory(player)
                    speech = await self.decision_engine.generate_night_discussion_speech(
                        player, self.state, memory, discussion_history, round_num,
                    )
                    if speech:
                        if "[达成共识]" in speech or "达成共识" in speech:
                            speech = "达成共识，确认击杀目标。"
                        speech_counts[player.player_id] += 1
                        discussion_history.append({"name": player.display_name, "content": speech})
                        msg = ChatMessage(
                            id=str(__import__('uuid').uuid4()),
                            player_id=player.player_id, player_name=player.display_name,
                            content=speech, timestamp=0, day=self.state.day,
                            phase="NIGHT_DISCUSSION", visible_to_roles=["Werewolf"],
                        )
                        new_messages = self.state.messages.copy()
                        new_messages.append(msg)
                        self.state = GameState(**{**self.state.__dict__, "messages": new_messages})
                        self._update_wolf_memories_from_speech(player.seat, speech)
                    await asyncio.sleep(0.3)
            self.state.current_speaker_seat = None

    async def _wolf_discussion_and_vote(self, alive_wolves, ai_wolves, human_wolves):
        """狼人讨论+选择同时进行（有人类狼人时）"""
        import random as _random

        self.state = transition_phase(self.state, "NIGHT_WOLF_ACTION")
        await self.emit_event("phase_change", {"phase": "NIGHT_WOLF_ACTION", "day": self.state.day})
        await self.emit_event("system", {"message": "狼人请睁眼，讨论并选择击杀目标", "visibility_type": "wolf_only"})
        await asyncio.sleep(0.5)

        speech_counts: Dict[str, int] = {p.player_id: 0 for p in ai_wolves}
        discussion_history: List[Dict[str, str]] = []
        max_ai_speeches = 3
        wolf_votes: Dict[str, int] = {}

        # 人类狼人的选择通过异步收集
        human_vote_futures: Dict[int, asyncio.Future] = {}

        async def _emit_wolf_speech(player, speech):
            """推送狼人发言"""
            discussion_history.append({"name": player.display_name, "content": speech})
            msg = ChatMessage(
                id=str(__import__('uuid').uuid4()),
                player_id=player.player_id, player_name=player.display_name,
                content=speech, timestamp=0, day=self.state.day,
                phase="NIGHT_DISCUSSION", visible_to_roles=["Werewolf"],
            )
            new_messages = self.state.messages.copy()
            new_messages.append(msg)
            self.state = GameState(**{**self.state.__dict__, "messages": new_messages})
            await self.emit_event("speech", {
                "seat": player.seat, "name": player.display_name,
                "content": speech, "phase": "NIGHT_DISCUSSION",
                "visibility": "wolf_only",
            })
            self._update_wolf_memories_from_speech(player.seat, speech)

        async def _ai_wolves_speak_once(round_num):
            """AI 狼人各发一次言"""
            for player in ai_wolves:
                if self._stop_flag or speech_counts[player.player_id] >= max_ai_speeches:
                    continue
                self.state.current_speaker_seat = player.seat
                await self.emit_event("speaker_change", {"seat": player.seat, "name": player.display_name})
                memory = self._get_agent_memory(player)
                speech = await self.decision_engine.generate_night_discussion_speech(
                    player, self.state, memory, discussion_history, round_num,
                )
                if speech:
                    if "[达成共识]" in speech or "达成共识" in speech:
                        speech = "达成共识，确认击杀目标。"
                    speech_counts[player.player_id] += 1
                    await _emit_wolf_speech(player, speech)
                await asyncio.sleep(0.3)

        async def _discussion_and_vote():
            """讨论+投票合并阶段，总共 60s"""
            import time as _time
            phase_deadline = _time.monotonic() + 60

            # 发送投票面板（讨论期间随时可以提交）
            for hw in human_wolves:
                seat = hw.seat
                self._human_action_types[seat] = "wolf_vote"
                self._human_action_futures[seat] = asyncio.get_event_loop().create_future()
                await self.emit_event("wait_human", {
                    "action_type": "wolf_vote",
                    "player_seat": hw.seat,
                    "extra": {"wolf_votes": wolf_votes, "timeout": 60},
                })

            round_num = 1
            # AI 先说一轮
            await _ai_wolves_speak_once(round_num)

            while not self._stop_flag:
                remaining = phase_deadline - _time.monotonic()
                if remaining <= 0:
                    break

                # 等人类发言（用 wolf_chat，剩余时间为超时）
                human_spoke = False
                for hw in human_wolves:
                    remaining = phase_deadline - _time.monotonic()
                    if remaining <= 0:
                        break
                    human_speech = await self._wait_for_human_action("wolf_chat", hw, timeout=max(1, int(remaining)))
                    if human_speech is None:
                        break  # 超时结束讨论
                    await _emit_wolf_speech(hw, human_speech)
                    human_spoke = True
                else:
                    if human_spoke:
                        # AI 回应一轮
                        round_num += 1
                        ai_can_speak = any(speech_counts[p.player_id] < max_ai_speeches for p in ai_wolves)
                        if ai_can_speak:
                            await _ai_wolves_speak_once(round_num)
                        continue
                break

            # 收集已提交的人类投票
            for hw in human_wolves:
                seat = hw.seat
                future = self._human_action_futures.get(seat)
                if future:
                    if future.done() and not future.cancelled():
                        try:
                            result = future.result()
                            if result is not None:
                                wolf_votes[hw.player_id] = result
                        except Exception:
                            pass
                    else:
                        future.cancel()
                self._human_action_futures.pop(seat, None)
                self._human_action_types.pop(seat, None)

        await _discussion_and_vote()

        self.state.current_speaker_seat = None

        # AI 狼人投票
        for wolf in ai_wolves:
            memory = self._get_agent_memory(wolf)
            target = await self.decision_engine.generate_wolf_decision(wolf, self.state, memory, wolf_votes)
            if target is not None and self._is_valid_target(target):
                wolf_votes[wolf.player_id] = target

        # 统计投票结果
        if wolf_votes:
            vote_counts = Counter(wolf_votes.values())
            max_count = vote_counts.most_common(1)[0][1]
            top_targets = [seat for seat, count in vote_counts.items() if count == max_count]
            wolf_target = _random.choice(top_targets)

            self.state.night_actions.wolf_votes = wolf_votes
            self.state.night_actions.wolf_target = wolf_target

            await self.emit_event("action", {
                "action": "wolf_kill",
                "target_seat": wolf_target,
                "message": f"狼人选择击杀{wolf_target + 1}号玩家",
                "visibility_type": "wolf_only"
            })
        else:
            # 全部为空，不袭击
            self.state.night_actions.wolf_target = None
            await self.emit_event("system", {"message": "狼人今晚没有袭击任何人", "visibility_type": "wolf_only"})

        await self.emit_event("system", {"message": "狼人请闭眼", "visibility_type": "wolf_only"})
        await asyncio.sleep(0.5)
        # 标记已处理，_wolf_action 跳过
        self._wolf_phase_done = True

    async def _guard_action(self):
        """守卫行动"""
        guard = next((p for p in self.state.players if p.role == "Guard" and p.alive), None)
        if not guard:
            return

        self.state = transition_phase(self.state, "NIGHT_GUARD_ACTION")
        await self.emit_event("phase_change", {"phase": "NIGHT_GUARD_ACTION"})

        # 只有守卫能看到这条消息
        if guard.is_human:
            await self.emit_event("system", {"message": "守卫请睁眼，选择要保护的玩家", "visibility_type": "guard_only"})

        if guard.is_human:
            # 等待人类玩家选择（20秒超时）
            target = await self._wait_for_human_action("guard", guard, {
                "last_guard_target": self.state.night_actions.last_guard_target,
            }, timeout=20)
            if target is None:
                # 超时，不保护任何人
                await self.emit_event("system", {"message": "操作超时，本轮不保护任何人", "visibility_type": "guard_only"})
        else:
            # AI决策（使用 Agent 系统）
            memory = self._get_agent_memory(guard)
            target = await self.decision_engine.generate_guard_decision(guard, self.state, memory)

        if target is not None and self._is_valid_target(target):
            self.state.night_actions.guard_target = target
            if not guard.is_human:
                memory = self._get_agent_memory(guard)
                self.memory_system.update_night_action(memory, "guard", target, None, self.state.day)
            if guard.is_human:
                await self.emit_event("action", {
                    "action": "guard",
                    "player_seat": guard.seat,
                    "target_seat": target,
                    "message": f"守卫保护了{target + 1}号玩家",
                    "visibility_type": "guard_only"
                })
        else:
            # 没有保护任何人，也记录到记忆
            if not guard.is_human:
                memory = self._get_agent_memory(guard)
                self.memory_system.update_night_action(memory, "guard_pass", None, None, self.state.day)

        if guard.is_human:
            await self.emit_event("system", {"message": "守卫请闭眼", "visibility_type": "guard_only"})
        await asyncio.sleep(0.5)

    async def _wolf_action(self):
        """狼人行动"""
        # 如果已在讨论阶段处理完（有人类狼人时），跳过
        if getattr(self, '_wolf_phase_done', False):
            self._wolf_phase_done = False
            return

        wolves = [p for p in self.state.players if p.role == "Werewolf" and p.alive]
        if not wolves:
            return

        self.state = transition_phase(self.state, "NIGHT_WOLF_ACTION")
        await self.emit_event("phase_change", {"phase": "NIGHT_WOLF_ACTION"})

        wolf_votes: Dict[str, int] = {}

        for wolf in wolves:
            # 纯 AI 狼人
            memory = self._get_agent_memory(wolf)
            target = await self.decision_engine.generate_wolf_decision(wolf, self.state, memory, wolf_votes)

            if target is not None and self._is_valid_target(target):
                wolf_votes[wolf.player_id] = target

        # 统计狼人投票
        if wolf_votes:
            import random as _random
            vote_counts = Counter(wolf_votes.values())
            max_count = vote_counts.most_common(1)[0][1]
            top_targets = [seat for seat, count in vote_counts.items() if count == max_count]
            wolf_target = _random.choice(top_targets)

            self.state.night_actions.wolf_votes = wolf_votes
            self.state.night_actions.wolf_target = wolf_target

        await asyncio.sleep(0.5)

    async def _witch_action(self):
        """女巫行动"""
        witch = next((p for p in self.state.players if p.role == "Witch" and p.alive), None)
        if not witch:
            return

        self.state = transition_phase(self.state, "NIGHT_WITCH_ACTION")
        await self.emit_event("phase_change", {"phase": "NIGHT_WITCH_ACTION"})

        # 只有女巫能看到这条消息
        if witch.is_human:
            await self.emit_event("system", {"message": "女巫请睁眼", "visibility_type": "witch_only"})

        wolf_target = self.state.night_actions.wolf_target
        can_save = not self.state.role_abilities.witch_heal_used and wolf_target is not None
        can_poison = not self.state.role_abilities.witch_poison_used

        if witch.is_human:
            # 等待人类玩家选择（20秒超时）
            action = await self._wait_for_human_action("witch", witch, {
                "wolf_target": wolf_target,
                "can_save": can_save,
                "can_poison": can_poison,
            }, timeout=20)
            if action is None:
                # 超时：有解药就救人，否则什么都不做
                if can_save:
                    action = {"type": "save"}
                    await self.emit_event("system", {"message": "操作超时，自动使用解药", "visibility_type": "witch_only"})
                else:
                    action = {"type": "pass"}
                    await self.emit_event("system", {"message": "操作超时，本轮不使用药水", "visibility_type": "witch_only"})
        else:
            # AI决策（使用 Agent 系统）
            memory = self._get_agent_memory(witch)
            action = await self.decision_engine.generate_witch_decision(witch, self.state, memory, wolf_target)

        if action:
            if action.get("type") == "save" and can_save:
                self.state.night_actions.witch_save = True
                self.state.role_abilities.witch_heal_used = True
                if witch.is_human:
                    await self.emit_event("action", {
                        "action": "witch_save",
                        "message": "女巫使用了解药",
                        "visibility_type": "witch_only"
                    })
                # 记录到 AI 记忆
                if not witch.is_human:
                    memory = self._get_agent_memory(witch)
                    self.memory_system.update_night_action(memory, "save", wolf_target, None, self.state.day)
            elif action.get("type") == "poison" and can_poison:
                poison_target = action.get("target")
                if poison_target is not None and self._is_valid_target(poison_target):
                    self.state.night_actions.witch_poison = poison_target
                    self.state.role_abilities.witch_poison_used = True
                    if witch.is_human:
                        await self.emit_event("action", {
                            "action": "witch_poison",
                            "target_seat": poison_target,
                            "message": f"女巫毒杀了{poison_target + 1}号玩家",
                            "visibility_type": "witch_only"
                        })
                    # 记录到 AI 记忆
                    if not witch.is_human:
                        memory = self._get_agent_memory(witch)
                        self.memory_system.update_night_action(memory, "poison", poison_target, None, self.state.day)
            else:
                # pass - 也记录到 AI 记忆
                if not witch.is_human:
                    memory = self._get_agent_memory(witch)
                    self.memory_system.update_night_action(memory, "witch_pass", None, None, self.state.day)

        if witch.is_human:
            await self.emit_event("system", {"message": "女巫请闭眼", "visibility_type": "witch_only"})
        await asyncio.sleep(0.5)

    async def _seer_action(self):
        """预言家行动"""
        seer = next((p for p in self.state.players if p.role == "Seer" and p.alive), None)
        if not seer:
            return

        self.state = transition_phase(self.state, "NIGHT_SEER_ACTION")
        await self.emit_event("phase_change", {"phase": "NIGHT_SEER_ACTION"})

        # 只有预言家能看到这条消息
        if seer.is_human:
            await self.emit_event("system", {"message": "预言家请睁眼，选择要查验的玩家", "visibility_type": "seer_only"})

        if seer.is_human:
            # 等待人类玩家选择（20秒超时）
            target = await self._wait_for_human_action("seer", seer, timeout=20)
            if target is None:
                # 超时，随机验一个没验过的存活玩家
                import random
                checked_seats = set()
                if self.state.night_actions.seer_history:
                    checked_seats = {h["targetSeat"] for h in self.state.night_actions.seer_history}
                candidates = [p for p in self.state.players if p.alive and p.seat != seer.seat and p.seat not in checked_seats]
                if not candidates:
                    candidates = [p for p in self.state.players if p.alive and p.seat != seer.seat]
                if candidates:
                    target = random.choice(candidates).seat
                await self.emit_event("system", {"message": "操作超时，系统已自动查验", "visibility_type": "seer_only"})
        else:
            # AI决策（使用 Agent 系统）
            memory = self._get_agent_memory(seer)
            target = await self.decision_engine.generate_seer_decision(seer, self.state, memory)

        if target is not None and self._is_valid_target(target, exclude_self_seat=seer.seat):
            target_player = next((p for p in self.state.players if p.seat == target), None)
            if target_player:
                is_wolf = target_player.role == "Werewolf"
                result_text = "狼人" if is_wolf else "好人"

                self.state.night_actions.seer_target = target
                self.state.night_actions.seer_result = {"targetSeat": target, "isWolf": is_wolf}

                # 更��查验历史
                seer_history = self.state.night_actions.seer_history or []
                seer_history.append({"targetSeat": target, "isWolf": is_wolf})
                self.state.night_actions.seer_history = seer_history

                # 预言家查验结果只有预言家自己知道
                if seer.is_human:
                    await self.emit_event("action", {
                        "action": "seer_check",
                        "player_seat": seer.seat,
                        "target_seat": target,
                        "is_wolf": is_wolf,
                        "message": f"预言家查验了{target + 1}号玩家，结果是{result_text}",
                        "visibility_type": "seer_only"
                    })

                # 更新预言家的 Agent 记忆
                if not seer.is_human:
                    memory = self._get_agent_memory(seer)
                    check_result = "wolf" if is_wolf else "village"
                    self.memory_system.update_night_action(memory, "check", target, check_result, self.state.day)

                    # 预言家查验后触发反思（知道结果了）
                    target_name = target_player.display_name if target_player else f"{target+1}号"
                    try:
                        llm_config = self.decision_engine._get_llm_config_dict(seer)
                        await self.memory_system.generate_reflection(
                            memory=memory,
                            event_description=f"我查验了{target_name}，结果是{result_text}。",
                            action_type="night_action",
                            day=self.state.day,
                            phase="NIGHT",
                            player=seer,
                            llm_config=llm_config,
                        )
                    except Exception as e:
                        print(f"[预言家反思失败] {seer.display_name}: {e}")

        if seer.is_human:
            await self.emit_event("system", {"message": "预言家请闭眼", "visibility_type": "seer_only"})
        await asyncio.sleep(0.5)

    async def _resolve_night(self):
        """夜晚结算"""
        deaths = []

        wolf_target = self.state.night_actions.wolf_target
        guard_target = self.state.night_actions.guard_target
        witch_save = self.state.night_actions.witch_save
        witch_poison = self.state.night_actions.witch_poison

        # 狼人击杀 (目标必须存活，且没有被守卫保护，且没有被女巫救)
        if wolf_target is not None and self._is_valid_target(wolf_target):
            if wolf_target != guard_target and not witch_save:
                deaths.append(wolf_target)

        # 女巫毒杀 (目标必须存活)
        if witch_poison is not None and self._is_valid_target(witch_poison):
            if witch_poison not in deaths:
                deaths.append(witch_poison)

        # 处理死亡
        for seat in deaths:
            self.state = kill_player(self.state, seat)
            player = next((p for p in self.state.players if p.seat == seat), None)
            if player:
                # 如果猎人被毒死，不能开枪
                if player.role == "Hunter" and witch_poison == seat:
                    self.state.role_abilities.hunter_can_shoot = False

            # 更新 AI 玩家的记忆：死亡事件
            # 不同角色知道不同的死因信息
            actual_cause = "wolf_kill" if seat == wolf_target and seat in deaths else "poison"
            for pid, mem in self.agent_memories.items():
                p = next((pl for pl in self.state.players if pl.player_id == pid), None)
                if not p:
                    continue
                if p.role == "Werewolf":
                    # 狼人知道自己杀了谁，如果还被毒了也能推断
                    if seat == wolf_target and wolf_target != guard_target and not witch_save:
                        self.memory_system.update_from_death(mem, seat, "wolf_kill", self.state.day)
                    else:
                        self.memory_system.update_from_death(mem, seat, "night_death", self.state.day)
                elif p.role == "Witch":
                    # 女巫知道自己救/毒了谁
                    if witch_poison == seat:
                        self.memory_system.update_from_death(mem, seat, "poison", self.state.day)
                    elif seat == wolf_target:
                        self.memory_system.update_from_death(mem, seat, "wolf_kill", self.state.day)
                    else:
                        self.memory_system.update_from_death(mem, seat, "night_death", self.state.day)
                elif p.role == "Guard":
                    # 守卫知道自己守了谁，如果守的人没死可以推断
                    self.memory_system.update_from_death(mem, seat, "night_death", self.state.day)
                else:
                    # 其他角色只知道有人死了
                    self.memory_system.update_from_death(mem, seat, "night_death", self.state.day)

        # 更新 last_guard_target
        self.state.night_actions.last_guard_target = guard_target

        # 发送死亡事件
        await self.emit_event("phase_change", {"phase": "DAY_START", "day": self.state.day})

        if deaths:
            death_names = [f"{seat + 1}号" for seat in deaths]
            await self.emit_event("death", {
                "seats": deaths,
                "message": f"昨晚，{'、'.join(death_names)}玩家死亡"
            })
            await self.emit_event("system", {"message": f"天亮了，昨晚{'、'.join(death_names)}玩家死亡"})

            # 天亮公告后触发 LLM 反思
            await self._trigger_observation_reflections(
                f"天亮了，昨晚{'、'.join(death_names)}玩家死亡。",
                "observation",
            )
        else:
            await self.emit_event("system", {"message": "天亮了，昨晚是平安夜"})

            # 平安夜也触发反思
            await self._trigger_observation_reflections(
                "天亮了，昨晚是平安夜。",
                "observation",
            )

        await asyncio.sleep(1)

    async def _run_day_phase(self):
        """运行白天阶段"""
        # 发言阶段
        await self._speech_phase()
        if self._stop_flag:
            return

        # 投票阶段
        await self._vote_phase()
        if self._stop_flag:
            return

    async def _speech_phase(self):
        """发言阶段"""
        self.state = transition_phase(self.state, "DAY_SPEECH")
        await self.emit_event("phase_change", {"phase": "DAY_SPEECH", "day": self.state.day})
        await self.emit_event("system", {"message": "现在是白天讨论阶段，请各位玩家依次发言"})
        await asyncio.sleep(1)

        alive_players = [p for p in self.state.players if p.alive]

        for player in alive_players:
            if self._stop_flag:
                return

            self.state.current_speaker_seat = player.seat
            await self.emit_event("speaker_change", {
                "seat": player.seat,
                "name": player.display_name,
            })

            if player.is_human:
                # 等待人类玩家发言（60秒超时）
                speech = await self._wait_for_human_action("speech", player, timeout=60)
                if speech is None:
                    speech = "过"
            else:
                # AI发言（使用 Agent 系统）
                memory = self._get_agent_memory(player)
                speech = await self.decision_engine.generate_speech(player, self.state, memory)

            if speech:
                self.state = add_player_message(self.state, player.player_id, speech)
                await self.emit_event("speech", {
                    "seat": player.seat,
                    "name": player.display_name,
                    "content": speech,
                })

                # 更新所有 AI 玩家的记忆：发言事件
                self._update_all_memories_from_speech(player.seat, speech)
                # 更新信任分数（轻量规则）
                self._update_trust_from_speech(player.seat, speech)

            await asyncio.sleep(0.5)

        self.state.current_speaker_seat = None

    async def _vote_phase(self):
        """投票阶段（含平票 PK）"""
        eliminated = await self._do_vote_round()

        if eliminated is None:
            # 第一轮平票，进入 PK
            pk_seats = self._get_tied_seats()
            if pk_seats and len(pk_seats) > 1:
                pk_names = "、".join([f"{s+1}号" for s in pk_seats])
                await self.emit_event("system", {"message": f"投票平票！{pk_names}进入 PK 发言"})

                # PK 发言：只有平票的人发言
                for seat in pk_seats:
                    player = next((p for p in self.state.players if p.seat == seat), None)
                    if not player or not player.alive:
                        continue

                    self.state.current_speaker_seat = player.seat
                    await self.emit_event("speaker_change", {"seat": player.seat, "name": player.display_name})

                    if player.is_human:
                        speech = await self._wait_for_human_action("speech", player, timeout=60)
                        if speech is None:
                            speech = "过"
                    else:
                        memory = self._get_agent_memory(player)
                        speech = await self.decision_engine.generate_speech(player, self.state, memory)

                    if speech:
                        self.state = add_player_message(self.state, player.player_id, speech)
                        await self.emit_event("speech", {
                            "seat": player.seat,
                            "name": player.display_name,
                            "content": speech,
                        })
                        self._update_all_memories_from_speech(player.seat, speech)
                        # 更新信任分数（轻量规则）
                        self._update_trust_from_speech(player.seat, speech)

                    await asyncio.sleep(0.5)

                self.state.current_speaker_seat = None

                # PK 投票：平票的人不能投票
                eliminated = await self._do_vote_round(exclude_voters=pk_seats, candidates=pk_seats)

                if eliminated is None:
                    await self.emit_event("system", {"message": "PK 投票仍然平票，本轮无人出局"})
                    return
            else:
                return

        # 处理出局
        eliminated_player = next((p for p in self.state.players if p.seat == eliminated), None)

        # 遗言阶段
        if eliminated_player:
            await self._last_words_phase(eliminated_player)

        # 处理死亡
        self.state = kill_player(self.state, eliminated)

        await self.emit_event("death", {
            "seats": [eliminated],
            "message": f"{eliminated + 1}号{eliminated_player.display_name if eliminated_player else ''}被投票出局"
        })

        self._update_all_memories_from_death(eliminated, "vote")

        # 猎人开枪
        if eliminated_player and eliminated_player.role == "Hunter" and self.state.role_abilities.hunter_can_shoot:
            await self._hunter_shoot(eliminated_player)

    def _get_tied_seats(self) -> List[int]:
        """获取最高票平票的座位列表"""
        from collections import Counter
        alive_player_ids = {p.player_id for p in self.state.players if p.alive}
        vote_counts: Dict[int, float] = {}
        sheriff_seat = self.state.badge.holder_seat
        sheriff_player = None
        if sheriff_seat is not None:
            sheriff_player = next((p for p in self.state.players if p.seat == sheriff_seat and p.alive), None)

        for voter_id, target_seat in self.state.votes.items():
            if voter_id not in alive_player_ids:
                continue
            weight = 1.5 if (sheriff_player and voter_id == sheriff_player.player_id) else 1.0
            vote_counts[target_seat] = vote_counts.get(target_seat, 0) + weight

        if not vote_counts:
            return []
        max_votes = max(vote_counts.values())
        return [seat for seat, count in vote_counts.items() if count == max_votes]

    async def _do_vote_round(self, exclude_voters: List[int] = None, candidates: List[int] = None):
        """执行一轮投票，返回出局座位或 None（平票）"""
        self.state = transition_phase(self.state, "DAY_VOTE")
        await self.emit_event("phase_change", {"phase": "DAY_VOTE"})
        await self.emit_event("system", {"message": "现在开始投票"})
        await asyncio.sleep(1)

        self.state.votes = {}
        exclude_voters = exclude_voters or []

        alive_players = [p for p in self.state.players if p.alive and p.seat not in exclude_voters]

        for player in alive_players:
            if self._stop_flag:
                return None

            if player.is_human:
                target = await self._wait_for_human_action("vote", player, timeout=30)
                if target is None:
                    pass
            else:
                memory = self._get_agent_memory(player)
                target = await self.decision_engine.generate_vote(player, self.state, memory)

            # 如果有候选人限制，只能投候选人
            if target is not None and self._is_valid_target(target):
                if candidates and target not in candidates:
                    target = None  # 无效投票，忽略

            if target is not None and self._is_valid_target(target):
                self.state.votes[player.player_id] = target
                target_player = next((p for p in self.state.players if p.seat == target), None)
                await self.emit_event("vote", {
                    "voter_seat": player.seat,
                    "voter_name": player.display_name,
                    "target_seat": target,
                    "target_name": target_player.display_name if target_player else "",
                })
                self._update_all_memories_from_vote(player.seat, target)

        # 统计投票
        result = tally_votes(self.state)

        vote_detail = self._build_vote_detail()
        if vote_detail:
            self.state = add_system_message(self.state, f"投票详情: {vote_detail}")

        if result:
            eliminated_seat = result["seat"]
            eliminated_player = next((p for p in self.state.players if p.seat == eliminated_seat), None)

            await self.emit_event("vote_result", {
                "eliminated_seat": eliminated_seat,
                "eliminated_name": eliminated_player.display_name if eliminated_player else "",
                "vote_count": result["count"],
                "vote_detail": vote_detail,
            })

            await self.emit_event("system", {
                "message": f"投票结束，{eliminated_seat + 1}号{eliminated_player.display_name if eliminated_player else ''}被投票出局"
            })

            # 投票结果出来后触发 LLM 反思
            await self._trigger_observation_reflections(
                f"投票结果：{eliminated_seat + 1}号{eliminated_player.display_name if eliminated_player else ''}被投票出局。{vote_detail}",
                "observation",
            )

            return eliminated_seat
        else:
            if vote_detail:
                await self.emit_event("vote_result", {
                    "eliminated_seat": None,
                    "eliminated_name": None,
                    "vote_count": 0,
                    "vote_detail": vote_detail,
                })
            return None

    async def _last_words_phase(self, player: Player):
        """遗言阶段"""
        self.state = transition_phase(self.state, "DAY_LAST_WORDS")
        await self.emit_event("phase_change", {"phase": "DAY_LAST_WORDS"})
        await self.emit_event("system", {"message": f"{player.seat + 1}号{player.display_name}请发表遗言"})

        if player.is_human:
            speech = await self._wait_for_human_action("last_words", player, timeout=30)
            if speech is None:
                speech = "过"
        else:
            # AI遗言（使用 Agent 系统）
            memory = self._get_agent_memory(player)
            speech = await self.decision_engine.generate_last_words(player, self.state, memory)

        if speech:
            self.state = add_player_message(self.state, player.player_id, speech, is_last_words=True)
            await self.emit_event("speech", {
                "seat": player.seat,
                "name": player.display_name,
                "content": speech,
                "is_last_words": True,
            })

            # 更新所有 AI 玩家的记忆：遗言
            self._update_all_memories_from_speech(player.seat, speech)
            # 更新信任分数（轻量规则）
            self._update_trust_from_speech(player.seat, speech)

    async def _hunter_shoot(self, hunter: Player):
        """猎人开枪"""
        self.state = transition_phase(self.state, "HUNTER_SHOOT")
        await self.emit_event("phase_change", {"phase": "HUNTER_SHOOT"})
        await self.emit_event("system", {"message": f"猎人{hunter.display_name}可以开枪带走一名玩家"})

        if hunter.is_human:
            target = await self._wait_for_human_action("hunter", hunter, timeout=20)
            if target is None:
                # 超时不开枪
                await self.emit_event("system", {"message": "操作超时，猎人放弃开枪"})
                return
        else:
            # AI猎人开枪（使用 Agent 系统）
            memory = self._get_agent_memory(hunter)
            target = await self.decision_engine.generate_hunter_decision(hunter, self.state, memory)

        if target is not None and self._is_valid_target(target, exclude_self_seat=hunter.seat):
            target_player = next((p for p in self.state.players if p.seat == target), None)
            self.state = kill_player(self.state, target)

            # 更新所有 AI 玩家的记忆：猎人带走
            self._update_all_memories_from_death(target, "hunter_shoot")

            await self.emit_event("action", {
                "action": "hunter_shoot",
                "shooter_seat": hunter.seat,
                "target_seat": target,
                "message": f"猎人开枪带走了{target + 1}号{target_player.display_name if target_player else ''}"
            })
            await self.emit_event("death", {
                "seats": [target],
                "message": f"{target + 1}号玩家被猎人带走"
            })

    async def _handle_game_end(self, winner: Alignment):
        """处理游戏结束"""
        self.state.winner = winner
        self.state = transition_phase(self.state, "GAME_END")

        winner_text = "好人阵营" if winner == "village" else "狼人阵营"

        await self.emit_event("game_end", {
            "winner": winner,
            "winner_text": winner_text,
            "players": [self._player_to_dict(p, reveal_role=True) for p in self.state.players],
        })
        await self.emit_event("system", {"message": f"游戏结束，{winner_text}获胜！"})

    # ========== 人类玩家交互 ==========

    # 按座位存储 future，支持多人类玩家
    _human_action_futures: Dict[int, asyncio.Future] = field(default_factory=dict)
    _human_action_types: Dict[int, str] = field(default_factory=dict)

    async def _wait_for_human_action(self, action_type: str, player: Player, extra_data: Dict = None, timeout: int = 300) -> Any:
        """等待人类玩家操作"""
        seat = player.seat
        self._human_action_types[seat] = action_type
        self._human_action_futures[seat] = asyncio.get_event_loop().create_future()

        # 把超时时间放进 extra 给前端显示倒计时
        if extra_data is None:
            extra_data = {}
        extra_data["timeout"] = timeout

        # 发送等待人类操作的事件
        await self.emit_event("wait_human", {
            "action_type": action_type,
            "player_seat": player.seat,
            "extra": extra_data,
        })

        try:
            result = await asyncio.wait_for(self._human_action_futures[seat], timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return None
        finally:
            self._human_action_futures.pop(seat, None)
            self._human_action_types.pop(seat, None)

    def submit_human_action(self, action_type: str, data: Any, seat: int = 0):
        """提交人类玩家操作（按座位区分）"""
        future = self._human_action_futures.get(seat)
        expected_type = self._human_action_types.get(seat)
        if future and not future.done() and expected_type == action_type:
            future.set_result(data)

    def stop_game(self):
        """停止游戏"""
        self._stop_flag = True
        for future in self._human_action_futures.values():
            if not future.done():
                future.cancel()
        self._human_action_futures.clear()
        self._human_action_types.clear()

    # ========== 工具函数 ==========

    def _is_valid_target(self, seat: Optional[int], exclude_self_seat: Optional[int] = None) -> bool:
        """校验目标座位是否合法（存活且非自身）"""
        if seat is None:
            return False
        player = next((p for p in self.state.players if p.seat == seat), None)
        if not player or not player.alive:
            return False
        if exclude_self_seat is not None and seat == exclude_self_seat:
            return False
        return True

    def _build_vote_detail(self) -> str:
        """构建详细投票信息，逐人列出，格式如: 1号投了3号, 2号投了3号, 6号弃票"""
        alive_players = [p for p in self.state.players if p.alive]
        alive_player_ids = {p.player_id for p in alive_players}
        voted_player_ids = set()

        # 按座位号排序，逐人列出投票
        vote_lines = []
        for p in sorted(alive_players, key=lambda x: x.seat):
            if p.player_id in self.state.votes:
                target_seat = self.state.votes[p.player_id]
                target_player = next((t for t in self.state.players if t.seat == target_seat), None)
                target_name = target_player.display_name if target_player else f"{target_seat+1}号"
                vote_lines.append(f"{p.seat+1}号{p.display_name}投了{target_seat+1}号{target_name}")
                voted_player_ids.add(p.player_id)
            else:
                vote_lines.append(f"{p.seat+1}号{p.display_name}弃票")

        return "；".join(vote_lines)

    def _parse_seat_number(self, text: str) -> Optional[int]:
        """从文本中解析座位号"""
        # 尝试找到数字
        match = re.search(r'(\d+)', text)
        if match:
            seat = int(match.group(1)) - 1  # 转换为0索引
            if 0 <= seat < len(self.state.players):
                return seat
        return None

    def _get_role_text(self, role: str) -> str:
        """获取角色中文名"""
        role_names = {
            "Villager": "村民",
            "Werewolf": "狼人",
            "Seer": "预言家",
            "Witch": "女巫",
            "Hunter": "猎人",
            "Guard": "守卫",
        }
        return role_names.get(role, role)

    def _get_teammates_info(self, player: Player) -> List[Dict]:
        """获取队友信息（仅狼人）"""
        if player.role != "Werewolf":
            return []

        teammates = []
        for p in self.state.players:
            if p.role == "Werewolf" and p.player_id != player.player_id:
                teammates.append({
                    "seat": p.seat,
                    "name": p.display_name,
                })
        return teammates

    def _player_to_dict(self, player: Player, reveal_role: bool = False) -> Dict:
        """将玩家转换为字典"""
        data = {
            "seat": player.seat,
            "name": player.display_name,
            "alive": player.alive,
            "is_human": player.is_human,
        }
        if reveal_role or player.is_human:
            data["role"] = player.role
            data["role_text"] = self._get_role_text(player.role)
        return data

    def get_game_state_dict(self) -> Dict:
        """获取游戏状态字典"""
        human_player = next((p for p in self.state.players if p.is_human), None)

        return {
            "game_id": self.state.game_id,
            "phase": self.state.phase,
            "day": self.state.day,
            "players": [self._player_to_dict(p) for p in self.state.players],
            "human_seat": human_player.seat if human_player else 0,
            "current_speaker": self.state.current_speaker_seat,
            "is_night": self.state.phase.startswith("NIGHT_"),
        }
