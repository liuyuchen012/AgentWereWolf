"""Memory system for tracking game state and player analysis."""

import json
import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from game_types.game_types import GameState, Player
from lib.llm import LLMMessage, generate_completion, strip_markdown_code_fences


@dataclass
class PlayerMemory:
    """单个玩家的记忆"""
    seat: int
    name: str
    is_alive: bool = True

    # 角色推断
    claimed_role: Optional[str] = None
    alignment_belief: Optional[str] = None  # "village" or "wolf"
    confidence: float = 0.5

    # 行为记录
    speech_count: int = 0
    speech_keywords: List[str] = field(default_factory=list)
    vote_history: List[int] = field(default_factory=list)
    voted_by: List[int] = field(default_factory=list)

    # 关系网络
    suspected_by: List[int] = field(default_factory=list)
    defended_by: List[int] = field(default_factory=list)

    # 备注
    notes: str = ""


@dataclass
class NightActionRecord:
    """夜间行动记录"""
    day: int
    action_type: str  # "guard", "kill", "poison", "save", "check"
    actor_seat: Optional[int] = None
    target_seat: Optional[int] = None
    result: Optional[str] = None


@dataclass
class DeathRecord:
    """死亡记录"""
    day: int
    seat: int
    name: str
    cause: str  # "wolf_kill", "poison", "vote", "hunter_shoot"
    claimed_role: Optional[str] = None


@dataclass
class Reflection:
    """结构化反思记录"""
    day: int
    phase: str
    action_type: str  # "speech", "vote", "night_action", "observation"
    content: str  # LLM 生成的反思内容
    updated_beliefs: Optional[Dict[str, Any]] = None  # 更新的信念


@dataclass
class AgentMemory:
    """Agent 完整记忆"""
    player_id: str
    role: str

    # 玩家记忆映射
    player_memories: Dict[int, PlayerMemory] = field(default_factory=dict)

    # 行动日志
    night_actions: List[NightActionRecord] = field(default_factory=list)
    deaths: List[DeathRecord] = field(default_factory=list)

    # 推理结果
    wolf_suspects: List[int] = field(default_factory=list)
    confirmed_good: List[int] = field(default_factory=list)
    key_insights: List[str] = field(default_factory=list)

    # 策略状态
    current_strategy: Optional[str] = None

    # 角色专属记忆
    role_specific: Dict[str, Any] = field(default_factory=dict)

    # === 新增：反思与信任系统 ===

    # 反思日志 - 每次行动后的结构化反思
    reflections: List[Reflection] = field(default_factory=list)

    # 当前计划 - agent 的短期策略计划
    current_plan: Optional[str] = None
    plan_reasoning: Optional[str] = None

    # 信任网络 - 对每个玩家的动态信任分数 (-1.0 到 1.0)
    trust_scores: Dict[int, float] = field(default_factory=dict)

    # 情绪状态 - 当前的情绪倾向
    emotional_state: str = "neutral"  # calm/anxious/suspicious/confident/desperate


def init_agent_memory(player: Player, state: GameState) -> AgentMemory:
    """初始化 Agent 记忆"""
    memory = AgentMemory(
        player_id=player.player_id,
        role=player.role,
    )

    # 初始化所有玩家的记忆
    for p in state.players:
        memory.player_memories[p.seat] = PlayerMemory(
            seat=p.seat,
            name=p.display_name,
            is_alive=p.alive,
        )

    # 初始化信任分数（默认 0.0 中立）
    for p in state.players:
        if p.player_id != player.player_id:
            memory.trust_scores[p.seat] = 0.0

    # 狼人知道队友
    if player.role == "Werewolf":
        for p in state.players:
            if p.role == "Werewolf" and p.player_id != player.player_id:
                mem = memory.player_memories[p.seat]
                mem.alignment_belief = "wolf"
                mem.confidence = 1.0
                mem.notes = "队友"
                # 队友信任度最高
                memory.trust_scores[p.seat] = 1.0

    return memory


class MemorySystem:
    """记忆系统 - 负责更新和维护 Agent 记忆"""

    ROLE_CHINESE = {
        "Villager": "村民",
        "Werewolf": "狼人",
        "Seer": "预言家",
        "Witch": "女巫",
        "Hunter": "猎人",
        "Guard": "守卫",
    }

    def update_from_speech(
        self,
        memory: AgentMemory,
        speaker_seat: int,
        speech: str,
        state: GameState,
    ) -> AgentMemory:
        """从发言更新记忆"""
        player_mem = memory.player_memories.get(speaker_seat)
        if not player_mem:
            return memory

        player_mem.speech_count += 1

        # 提取关键词
        keywords = self._extract_keywords(speech)
        player_mem.speech_keywords.extend(keywords)

        # 检测角色声称
        claimed = self._detect_role_claim(speech)
        if claimed:
            player_mem.claimed_role = claimed

        # 检测怀疑关系
        for target_seat in self._detect_suspicions(speech, state):
            target_mem = memory.player_memories.get(target_seat)
            if target_mem and speaker_seat not in target_mem.suspected_by:
                target_mem.suspected_by.append(speaker_seat)

        # 检测辩护关系
        for target_seat in self._detect_defenses(speech, state):
            target_mem = memory.player_memories.get(target_seat)
            if target_mem and speaker_seat not in target_mem.defended_by:
                target_mem.defended_by.append(speaker_seat)

        return memory

    def update_from_vote(
        self,
        memory: AgentMemory,
        voter_seat: int,
        target_seat: int,
    ) -> AgentMemory:
        """从投票更新记忆"""
        voter_mem = memory.player_memories.get(voter_seat)
        target_mem = memory.player_memories.get(target_seat)

        if voter_mem:
            voter_mem.vote_history.append(target_seat)
        if target_mem and voter_seat not in target_mem.voted_by:
            target_mem.voted_by.append(voter_seat)

        return memory

    def update_from_vote_result(
        self,
        memory: AgentMemory,
        eliminated_seat: Optional[int],
        vote_detail: str,
        day: int,
    ) -> AgentMemory:
        """从投票结果更新记忆"""
        insight = f"第{day}天投票: {vote_detail}"
        if eliminated_seat is not None:
            player_mem = memory.player_memories.get(eliminated_seat)
            name = player_mem.name if player_mem else f"{eliminated_seat+1}号"
            insight += f" -> {name}被投票出局"
        else:
            insight += " -> 平票无人出局"
        memory.key_insights.append(insight)
        return memory

    def update_from_night_announcement(
        self,
        memory: AgentMemory,
        death_seats: List[int],
        day: int,
    ) -> AgentMemory:
        """从天亮公告更新记忆（谁死了）"""
        if death_seats:
            names = []
            for s in death_seats:
                pm = memory.player_memories.get(s)
                names.append(f"{s+1}号{pm.name if pm else ''}")
            memory.key_insights.append(f"第{day}夜死亡: {'、'.join(names)}")
        else:
            memory.key_insights.append(f"第{day}夜平安夜")
        return memory

    def update_from_hunter_shoot(
        self,
        memory: AgentMemory,
        hunter_seat: int,
        target_seat: int,
        day: int,
    ) -> AgentMemory:
        """从猎人开枪更新记忆"""
        hunter_mem = memory.player_memories.get(hunter_seat)
        target_mem = memory.player_memories.get(target_seat)
        h_name = hunter_mem.name if hunter_mem else f"{hunter_seat+1}号"
        t_name = target_mem.name if target_mem else f"{target_seat+1}号"
        memory.key_insights.append(f"第{day}天: 猎人{h_name}开枪带走了{t_name}")
        # 猎人身份确认
        if hunter_mem:
            hunter_mem.claimed_role = "Hunter"
        return memory

    def record_own_speech(
        self,
        memory: AgentMemory,
        speech: str,
        day: int,
        phase: str,
    ) -> AgentMemory:
        """记录自己的发言到记忆"""
        phase_name = "白天" if "DAY" in phase else "夜晚"
        memory.key_insights.append(f"第{day}天{phase_name}我的发言: {speech[:80]}{'...' if len(speech) > 80 else ''}")
        return memory

    def record_own_vote(
        self,
        memory: AgentMemory,
        target_seat: int,
        day: int,
    ) -> AgentMemory:
        """记录自己的投票到记忆"""
        target_mem = memory.player_memories.get(target_seat)
        t_name = target_mem.name if target_mem else f"{target_seat+1}号"
        memory.key_insights.append(f"第{day}天我投票给了{t_name}")
        return memory

    def update_day_summary(
        self,
        memory: AgentMemory,
        day: int,
        state: GameState,
    ) -> AgentMemory:
        """每天结束时生成日总结"""
        # key_insights 全部保留，不裁剪
        return memory

    def update_from_death(
        self,
        memory: AgentMemory,
        seat: int,
        cause: str,
        day: int,
    ) -> AgentMemory:
        """从死亡事件更新记忆"""
        player_mem = memory.player_memories.get(seat)
        if not player_mem:
            return memory

        player_mem.is_alive = False

        death_record = DeathRecord(
            day=day,
            seat=seat,
            name=player_mem.name,
            cause=cause,
            claimed_role=player_mem.claimed_role,
        )
        memory.deaths.append(death_record)

        # 从嫌疑列表中移除死者
        if seat in memory.wolf_suspects:
            memory.wolf_suspects.remove(seat)
        if seat in memory.confirmed_good:
            memory.confirmed_good.remove(seat)

        return memory

    def update_night_action(
        self,
        memory: AgentMemory,
        action_type: str,
        target_seat: Optional[int],
        result: Optional[str],
        day: int,
    ) -> AgentMemory:
        """记录夜间行动"""
        action = NightActionRecord(
            day=day,
            action_type=action_type,
            target_seat=target_seat,
            result=result,
        )
        memory.night_actions.append(action)

        # 更新角色专属记忆
        if action_type == "check" and result:
            if "check_results" not in memory.role_specific:
                memory.role_specific["check_results"] = {}
            memory.role_specific["check_results"][target_seat] = result

            # 更新推理
            if result == "wolf":
                if target_seat not in memory.wolf_suspects:
                    memory.wolf_suspects.append(target_seat)
            else:
                if target_seat not in memory.confirmed_good:
                    memory.confirmed_good.append(target_seat)

        elif action_type == "guard":
            memory.role_specific["last_protected"] = target_seat

        elif action_type == "save":
            memory.role_specific["saved_player"] = target_seat

        elif action_type == "poison":
            memory.role_specific["poisoned_player"] = target_seat

        return memory

    def format_memory_for_prompt(
        self,
        memory: AgentMemory,
        max_players: int = 12,
    ) -> str:
        """格式化记忆用于 Prompt"""
        lines = []

        # 存活玩家分析
        alive_mems = [
            mem for mem in memory.player_memories.values()
            if mem.is_alive
        ]

        lines.append("【玩家分析】")
        for mem in alive_mems[:max_players]:
            info_parts = []

            if mem.claimed_role:
                info_parts.append(f"声称{self.ROLE_CHINESE.get(mem.claimed_role, mem.claimed_role)}")

            if mem.alignment_belief:
                belief = "好人" if mem.alignment_belief == "village" else "狼人"
                info_parts.append(f"推测{belief}")

            if mem.vote_history:
                last_vote = mem.vote_history[-1]
                info_parts.append(f"上次投{last_vote + 1}号")

            if len(mem.suspected_by) >= 2:
                info_parts.append(f"被{len(mem.suspected_by)}人怀疑")

            if len(mem.defended_by) >= 2:
                info_parts.append(f"被{len(mem.defended_by)}人辩护")

            if mem.notes:
                info_parts.append(mem.notes)

            info_str = ", ".join(info_parts) if info_parts else "无特殊信息"
            lines.append(f"  {mem.seat + 1}号 {mem.name}: {info_str}")

        # 已死亡玩家
        dead_mems = [
            mem for mem in memory.player_memories.values()
            if not mem.is_alive
        ]
        if dead_mems:
            lines.append("\n【已死亡玩家】")
            for mem in dead_mems:
                death_info = ""
                for d in memory.deaths:
                    if d.seat == mem.seat:
                        cause_map = {
                            "wolf_kill": "被狼人杀",
                            "poison": "被毒杀",
                            "vote": "被投票出局",
                            "hunter_shoot": "被猎人带走",
                            "night_death": "夜晚死亡",
                        }
                        death_info = cause_map.get(d.cause, d.cause)
                        break
                role_info = f"声称{self.ROLE_CHINESE.get(mem.claimed_role, mem.claimed_role)}" if mem.claimed_role else ""
                lines.append(f"  {mem.seat + 1}号 {mem.name}: {death_info} {role_info}".strip())

        # 狼人嫌疑
        if memory.wolf_suspects:
            suspects_str = ", ".join([f"{s + 1}号" for s in memory.wolf_suspects])
            lines.append(f"\n【狼人嫌疑】{suspects_str}")

        # 确认好人
        if memory.confirmed_good:
            good_str = ", ".join([f"{s + 1}号" for s in memory.confirmed_good])
            lines.append(f"【确认好人】{good_str}")

        # 关键洞察（全部保留）
        if memory.key_insights:
            lines.append("\n【关键洞察】")
            for insight in memory.key_insights:
                lines.append(f"  - {insight}")

        # 角色专属信息
        role_lines = self._format_role_specific(memory)
        if role_lines:
            lines.append(role_lines)

        # === 新增：信任网络摘要 ===
        if memory.trust_scores:
            trust_parts = []
            sorted_trust = sorted(memory.trust_scores.items(), key=lambda x: x[1])
            # 最不信任的 (负分)
            low = [(s, v) for s, v in sorted_trust if v < -0.2]
            high = [(s, v) for s, v in sorted_trust if v > 0.2]
            if low or high:
                lines.append("\n【信任评估】")
                if high:
                    lines.append("  信任: " + ", ".join([f"{s+1}号({v:+.1f})" for s, v in high[-3:]]))
                if low:
                    lines.append("  警惕: " + ", ".join([f"{s+1}号({v:+.1f})" for s, v in low[:3]]))

        # === 新增：当前计划 ===
        if memory.current_plan:
            lines.append(f"\n【当前计划】{memory.current_plan}")

        # === 新增：情绪状态 ===
        emotion_map = {
            "calm": "冷静", "anxious": "焦虑", "suspicious": "多疑",
            "confident": "自信", "desperate": "绝望", "neutral": "平静",
        }
        if memory.emotional_state != "neutral":
            lines.append(f"【情绪状态】{emotion_map.get(memory.emotional_state, memory.emotional_state)}")

        # === 新增：最近反思（最近 2-3 条）===
        if memory.reflections:
            recent_refs = memory.reflections[-3:]
            lines.append("\n【近期反思】")
            for ref in recent_refs:
                lines.append(f"  - [{ref.action_type}] {ref.content}")

        return "\n".join(lines)

    # === 新增：LLM 驱动的反思方法 ===

    async def generate_reflection(
        self,
        memory: AgentMemory,
        event_description: str,
        action_type: str,
        day: int,
        phase: str,
        player: Optional[Any] = None,
        llm_config: Optional[Dict[str, Any]] = None,
    ) -> Optional[Reflection]:
        """在 agent 行动后调用 LLM 生成反思

        Args:
            memory: 当前 agent 记忆
            event_description: 刚发生的事件描述
            action_type: 行动类型 (speech/vote/night_action/observation)
            day: 当前天数
            phase: 当前阶段
            player: 玩家对象（用于获取 LLM 配置）
            llm_config: LLM 配置覆盖 {model, api_base, api_key, temperature}
        """
        try:
            role_name = self.ROLE_CHINESE.get(memory.role, memory.role)

            # 构建简短的记忆摘要
            trust_summary = ""
            if memory.trust_scores:
                high_trust = [f"{s+1}号({v:+.1f})" for s, v in memory.trust_scores.items() if v > 0.3]
                low_trust = [f"{s+1}号({v:+.1f})" for s, v in memory.trust_scores.items() if v < -0.3]
                if high_trust:
                    trust_summary += f"信任: {', '.join(high_trust[:3])} "
                if low_trust:
                    trust_summary += f"不信任: {', '.join(low_trust[:3])}"

            plan_text = f"当前计划: {memory.current_plan}" if memory.current_plan else ""

            system_msg = f"""你是{role_name}，正在狼人杀游戏中。刚才发生了一件事，你需要在心里消化一下。

这不是分析报告，是你的内心独白——像一个真人在脑子里默默想事情。
- 可以有情绪：紧张、怀疑、庆幸、后悔、愤怒
- 要具体：不要说"我需要更加小心"，要说"我开始怀疑3号了，他刚才那句话不对劲"
- 重点想：这件事改变了我对谁的看法？我接下来该怎么办？

【严格禁止】
- 不要脑补别人没说过的话。如果某人没有在发言中提到某事，就不要假设他说了。
- 不要把"投票给某人"等同于"带队冲某人"或"带节奏"。投票是个人行为，除非某人在发言中明确号召大家投某人，否则不能说他"带队"。
- 只基于你实际听到的发言内容和看到的投票结果来判断，不要推测别人的意图超出事实范围。"""

            user_msg = f"""刚才发生了：{event_description}

你现在的心情：{memory.emotional_state}
{trust_summary}
{plan_text}

在心里想想：
- 这件事让你对谁的看法变了？变好了还是变差了？
- 你现在最担心什么？最有把握的是什么？
- 接下来你打算怎么做？

输出严格JSON（reflection用内心独白的口吻，50-100字）：
{{"reflection": "你的内心想法", "trust_changes": {{"座位号": 变化值}}, "emotion": "新情绪(calm/anxious/suspicious/confident/desperate)", "plan": "接下来的打算或null"}}"""

            messages = [
                LLMMessage(role="system", content=system_msg),
                LLMMessage(role="user", content=user_msg),
            ]

            # 使用配置或默认值
            cfg = llm_config or {}
            response = await generate_completion(
                messages,
                model=cfg.get("model"),
                temperature=cfg.get("temperature", 0.5),
                max_tokens=200,
                api_base=cfg.get("api_base"),
                api_key=cfg.get("api_key"),
            )

            content = response.choices[0]["message"]["content"].strip()
            content = strip_markdown_code_fences(content)

            # 解析 JSON
            parsed = None
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group())
                    except json.JSONDecodeError:
                        pass

            if not parsed:
                return None

            reflection_text = parsed.get("reflection", "")
            if not reflection_text:
                return None

            # 更新信任分数
            trust_changes = parsed.get("trust_changes", {})
            if isinstance(trust_changes, dict):
                for seat_str, delta in trust_changes.items():
                    try:
                        seat = int(seat_str)
                        # 兼容 1-indexed
                        if seat > 0 and seat <= len(memory.player_memories):
                            seat_0 = seat - 1 if seat not in memory.trust_scores else seat
                            if seat_0 not in memory.trust_scores and seat - 1 in memory.trust_scores:
                                seat_0 = seat - 1
                        else:
                            seat_0 = seat
                        if seat_0 in memory.trust_scores:
                            new_val = memory.trust_scores[seat_0] + float(delta)
                            memory.trust_scores[seat_0] = max(-1.0, min(1.0, new_val))
                    except (ValueError, TypeError):
                        continue

            # 更新情绪状态
            new_emotion = parsed.get("emotion", "")
            if new_emotion in ("calm", "anxious", "suspicious", "confident", "desperate"):
                memory.emotional_state = new_emotion

            # 更新计划
            new_plan = parsed.get("plan")
            if new_plan and isinstance(new_plan, str) and new_plan.lower() != "null":
                memory.current_plan = new_plan

            # 创建反思记录
            reflection = Reflection(
                day=day,
                phase=phase,
                action_type=action_type,
                content=reflection_text,
                updated_beliefs=trust_changes if trust_changes else None,
            )
            memory.reflections.append(reflection)

            # 限制反思数量，避免无限增长
            if len(memory.reflections) > 20:
                memory.reflections = memory.reflections[-15:]

            return reflection

        except Exception as e:
            # 反思失败不影响游戏流程
            print(f"[反思生成失败] {memory.player_id}: {e}")
            return None

    def update_trust_from_speech(
        self,
        memory: AgentMemory,
        speaker_seat: int,
        speech: str,
        my_seat: int,
    ) -> AgentMemory:
        """基于规则的轻量信任更新（不调 LLM）

        在听到他人发言后调用，根据发言内容调整信任分数。
        """
        my_seat_str = f"{my_seat + 1}号"
        speaker_trust = memory.trust_scores.get(speaker_seat, 0.0)

        # 如果发言者怀疑了我 → 降低对其信任
        suspect_keywords = ["狼", "怀疑", "可疑", "有问题", "不对劲", "查杀"]
        if my_seat_str in speech:
            for kw in suspect_keywords:
                if kw in speech:
                    speaker_trust -= 0.15
                    break

        # 如果发言者为我辩护 → 提高对其信任
        defense_keywords = ["好人", "相信", "清白", "没问题", "金水", "信任"]
        if my_seat_str in speech:
            for kw in defense_keywords:
                if kw in speech:
                    speaker_trust += 0.1
                    break

        # 如果发言者声称了角色 → 根据一致性调整
        claimed = self._detect_role_claim(speech)
        if claimed:
            pm = memory.player_memories.get(speaker_seat)
            if pm and pm.claimed_role and pm.claimed_role != claimed:
                # 前后声称不一致，降低信任
                speaker_trust -= 0.2
            elif claimed == "Seer":
                # 声称预言家，如果已有人声称预言家，降低信任
                other_seers = [
                    s for s, m in memory.player_memories.items()
                    if m.claimed_role == "Seer" and s != speaker_seat
                ]
                if other_seers:
                    speaker_trust -= 0.1  # 有多个预言家，可疑

        # 如果发言者被多人怀疑，降低信任
        pm = memory.player_memories.get(speaker_seat)
        if pm and len(pm.suspected_by) >= 3:
            speaker_trust -= 0.05

        # 限制范围
        memory.trust_scores[speaker_seat] = max(-1.0, min(1.0, speaker_trust))

        return memory

    def _format_role_specific(self, memory: AgentMemory) -> str:
        """格式化角色专属记忆"""
        lines = []

        if memory.role == "Seer":
            check_results = memory.role_specific.get("check_results", {})
            if check_results:
                lines.append("\n【查验记录】")
                for seat, result in check_results.items():
                    result_text = "狼人" if result == "wolf" else "好人"
                    lines.append(f"  {seat + 1}号: {result_text}")

        elif memory.role == "Guard":
            last = memory.role_specific.get("last_protected")
            if last is not None:
                lines.append(f"\n【上次保护】{last + 1}号")

        elif memory.role == "Witch":
            saved = memory.role_specific.get("saved_player")
            poisoned = memory.role_specific.get("poisoned_player")
            # 显示每晚行动记录
            witch_actions = [a for a in memory.night_actions if a.action_type in ("save", "poison", "witch_pass")]
            if witch_actions:
                lines.append("\n【女巫行动记录】")
                for a in witch_actions:
                    if a.action_type == "save":
                        lines.append(f"  第{a.day}夜：使用解药救了{a.target_seat + 1}号")
                    elif a.action_type == "poison":
                        lines.append(f"  第{a.day}夜：使用毒药毒了{a.target_seat + 1}号")
                    elif a.action_type == "witch_pass":
                        lines.append(f"  第{a.day}夜：未使用任何药水")
            else:
                lines.append("\n【女巫行动记录】")
                lines.append("  尚未使用过任何药水")
            # 药水状态总结
            if saved is not None:
                lines.append(f"【解药状态】已使用（救了{saved + 1}号）")
            else:
                lines.append("【解药状态】未使用")
            if poisoned is not None:
                lines.append(f"【毒药状态】已使用（毒了{poisoned + 1}号）")
            else:
                lines.append("【毒药状态】未使用")

        return "\n".join(lines)

    def _extract_keywords(self, speech: str) -> List[str]:
        """提取关键词"""
        keywords = []
        key_terms = [
            "预言家", "女巫", "猎人", "守卫", "狼人", "村民",
            "查验", "金水", "查杀", "银水",
            "悍跳", "深水", "警徽流",
            "解药", "毒药", "保护",
        ]
        for term in key_terms:
            if term in speech:
                keywords.append(term)
        return keywords

    def _detect_role_claim(self, speech: str) -> Optional[str]:
        """检测角色声称"""
        claim_patterns = {
            "预言家": "Seer",
            "女巫": "Witch",
            "猎人": "Hunter",
            "守卫": "Guard",
            "村民": "Villager",
        }
        for keyword, role in claim_patterns.items():
            if f"我是{keyword}" in speech or f"我的身份是{keyword}" in speech:
                return role
        return None

    def _detect_suspicions(self, speech: str, state: GameState) -> List[int]:
        """检测怀疑对象"""
        suspects = []
        suspect_keywords = ["狼", "怀疑", "可疑", "有问题", "不对劲"]
        for p in state.players:
            seat_str = f"{p.seat + 1}号"
            if seat_str in speech:
                for kw in suspect_keywords:
                    if kw in speech:
                        suspects.append(p.seat)
                        break
        return suspects

    def _detect_defenses(self, speech: str, state: GameState) -> List[int]:
        """检测辩护对象"""
        defended = []
        defense_keywords = ["好人", "相信", "清白", "没问题", "金水"]
        for p in state.players:
            seat_str = f"{p.seat + 1}号"
            if seat_str in speech:
                for kw in defense_keywords:
                    if kw in speech:
                        defended.append(p.seat)
                        break
        return defended
