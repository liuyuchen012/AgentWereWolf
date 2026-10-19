"""Decision engine - builds prompts and calls LLM for all decision types."""

import json
import re
import random
from typing import List, Dict, Any, Optional

from game_types.game_types import GameState, Player
from lib.llm import LLMMessage, generate_completion, strip_markdown_code_fences
from lib.game_constants import GAME_TEMPERATURE
from lib.prompt_utils import build_game_context, build_today_transcript
from lib.game_logger import GameLogger
from llms_config import load_llms_config, get_player_llm_config, PlayerLLMConfig

from .memory import AgentMemory, MemorySystem, Reflection
from .information import InformationManager
from .strategy import StrategyLibrary


ROLE_CHINESE = {
    "Villager": "村民",
    "Werewolf": "狼人",
    "Seer": "预言家",
    "Witch": "女巫",
    "Hunter": "猎人",
    "Guard": "守卫",
}


class DecisionEngine:
    """决策引擎 - 基于 LLM 生成各类决策"""

    def __init__(
        self,
        info_manager: InformationManager,
        memory_system: MemorySystem,
        strategy_lib: StrategyLibrary,
        llm_config_path: Optional[str] = None,
        logger: Optional[GameLogger] = None,
    ):
        self.info_manager = info_manager
        self.memory_system = memory_system
        self.strategy_lib = strategy_lib
        self.logger = logger
        # 加载 LLM 配置
        self._llm_config_data = load_llms_config(llm_config_path)
        # 玩家性格缓存: player_id -> personality_text
        self._personality_cache: Dict[str, str] = {}

    def get_player_llm_config(self, player: Player) -> PlayerLLMConfig:
        """获取玩家的 LLM 配置"""
        return get_player_llm_config(player.seat, self._llm_config_data)

    def get_personality_text(self, player: Player) -> str:
        """获取玩家的性格描述文本，用于注入 prompt"""
        text = self._personality_cache.get(player.player_id, "")
        if text:
            return f"\n【你的性格】\n{text}\n"
        return ""

    def set_personality(self, player_id: str, personality_text: str):
        """设置玩家的性格描述"""
        self._personality_cache[player_id] = personality_text

    # ========== 夜间决策 ==========

    def _get_llm_config_dict(self, player: Player) -> Dict[str, Any]:
        """获取玩家的 LLM 配置字典，用于反思调用"""
        cfg = self.get_player_llm_config(player)
        return {
            "model": cfg.model,
            "api_base": cfg.api_base,
            "api_key": cfg.api_key,
            "temperature": 0.5,
        }

    async def _trigger_reflection(
        self,
        player: Player,
        memory: AgentMemory,
        event_description: str,
        action_type: str,
        day: int,
        phase: str,
    ):
        """触发反思（异步，失败不影响流程）"""
        try:
            llm_config = self._get_llm_config_dict(player)
            await self.memory_system.generate_reflection(
                memory=memory,
                event_description=event_description,
                action_type=action_type,
                day=day,
                phase=phase,
                player=player,
                llm_config=llm_config,
            )
        except Exception as e:
            print(f"[反思触发失败] {player.display_name}: {e}")

    # ========== 夜间决策（原有） ==========

    async def generate_guard_decision(
        self,
        player: Player,
        state: GameState,
        memory: AgentMemory,
    ) -> Optional[int]:
        """生成守卫保护决策"""
        role_info = self.info_manager.get_role_specific_info(player, state)
        last_protected = role_info.get("last_protected_seat")

        alive_players = [p for p in state.players if p.alive]
        valid_targets = [p for p in alive_players if p.seat != last_protected]

        if not valid_targets:
            valid_targets = alive_players

        options = ", ".join([f"{p.seat + 1}号 {p.display_name}" for p in valid_targets])

        strategies = self.strategy_lib.get_strategies_for_role(player.role, state.difficulty)
        strategy_text = self.strategy_lib.format_strategies_for_prompt(strategies)

        personality = self.get_personality_text(player)
        system_msg = f"""你是{player.display_name}，{player.seat + 1}号位，身份是守卫。你是一个真实的人类玩家，不是AI。
{personality}
你肩负着保护关键人物的重任。每到夜晚，你都在焦虑地猜测——狼人今晚会对谁下手？你必须在有限的信息中做出判断，一旦守错，可能就是一条人命。

【能力与限制】
- 每晚选择一名玩家保护，使其免受狼人击杀
- 不能连续两晚保护同一人（上次保护：{f"{last_protected + 1}号" if last_protected is not None else "无"}）
- 守护成功则当晚平安夜

【思考方式】
先想：狼人最想杀谁？（神职？发言强势的人？昨晚没守的高价值目标？）
再想：我守谁的收益最大？有没有可能被狼人读到我的守护模式？
最后决定：在不确定中做出你认为最优的选择。

{strategy_text}"""

        memory_text = self.memory_system.format_memory_for_prompt(memory)

        user_msg = f"""第{state.day}天夜晚，你睁眼了。

{memory_text}

【存活玩家】
{options}

现在闭上眼想一想：
1. 今晚谁最危险？狼人会盯上谁？（发言强势的？疑似神职的？）
2. 有没有人昨天的表现让你觉得他是关键角色，必须活着？
3. 狼人会不会猜到你的守护思路，故意绕开？

做出你的选择。

严格输出JSON：
{{"reasoning": "你的内心想法（50-100字，像人说话）", "target_seat": 座位号数字}}"""

        result = await self._call_llm_json(system_msg, user_msg, player, action_type="guard", day=state.day, phase="NIGHT")
        target = self._extract_seat(result, valid_targets)
        if target is not None:
            # 反思：守卫行动后
            target_name = next((p.display_name for p in valid_targets if p.seat == target), f"{target+1}号")
            await self._trigger_reflection(
                player, memory,
                f"我今晚保护了{target_name}。",
                "night_action", state.day, "NIGHT",
            )
            return target

        # fallback
        fallback_target = random.choice(valid_targets).seat if valid_targets else None
        if fallback_target is not None:
            target_name = next((p.display_name for p in valid_targets if p.seat == fallback_target), f"{fallback_target+1}号")
            await self._trigger_reflection(
                player, memory,
                f"我今晚保护了{target_name}。",
                "night_action", state.day, "NIGHT",
            )
        return fallback_target

    async def generate_wolf_decision(
        self,
        player: Player,
        state: GameState,
        memory: AgentMemory,
        existing_votes: Dict[str, int],
    ) -> Optional[int]:
        """生成狼人击杀决策"""
        role_info = self.info_manager.get_role_specific_info(player, state)
        teammates = role_info.get("teammates", [])

        alive_players = [p for p in state.players if p.alive]
        options = ", ".join([f"{p.seat + 1}号 {p.display_name}" for p in alive_players])

        teammate_info = ""
        if teammates:
            teammate_list = ", ".join([f"{t['seat'] + 1}号 {t['name']}" for t in teammates])
            teammate_info = f"你的狼队友: {teammate_list}"
        else:
            teammate_info = "你是唯一存活的狼人"

        vote_info = ""
        if existing_votes:
            vote_lines = []
            for t in teammates:
                pid = next((p.player_id for p in state.players if p.seat == t["seat"]), None)
                if pid and pid in existing_votes:
                    target_seat = existing_votes[pid]
                    vote_lines.append(f"  {t['name']} 选择了 {target_seat + 1}号")
            if vote_lines:
                vote_info = "【队友投票】\n" + "\n".join(vote_lines)

        strategies = self.strategy_lib.get_strategies_for_role(player.role, state.difficulty)
        strategy_text = self.strategy_lib.format_strategies_for_prompt(strategies)

        personality = self.get_personality_text(player)
        system_msg = f"""你是{player.display_name}，{player.seat + 1}号位，身份是狼人。你是一个真实的人类玩家，不是AI。
{personality}
{teammate_info}

夜晚是你的主场。你和队友要在暗中猎杀，同时不能让白天的自己露出马脚。每一刀都是一个信号——杀谁、不杀谁，都会被场上的聪明人分析。

【博弈意识】
- 击杀不只是消灭威胁，也是在制造信息迷雾
- 杀太有规律会被读出模式（比如总杀发言强的人）
- 有时候杀一个"意料之外"的人，反而能打乱好人的推理节奏
- 要考虑守卫可能守谁，女巫可能救谁

{strategy_text}"""

        memory_text = self.memory_system.format_memory_for_prompt(memory)

        user_msg = f"""第{state.day}天夜晚，狼人睁眼。

{memory_text}

{vote_info}

【场上存活】
{options}

想清楚再动手：
1. 谁对我们威胁最大？（疑似预言家？发言带节奏的？）
2. 杀这个人之后，明天白天的局面会怎样？会不会直接指向我们？
3. 守卫今晚可能守谁？有没有办法避开？
4. 队友的意见是什么？要不要统一？

选一个目标。

严格输出JSON：
{{"reasoning": "你的内心盘算（50-150字，像狼人密谋时的口吻）", "target_seat": 座位号数字}}"""

        result = await self._call_llm_json(system_msg, user_msg, player, action_type="wolf", day=state.day, phase="NIGHT")
        # 狼人不应该杀自己的队友（除非自刀策略），优先排除队友
        teammate_seats = {t["seat"] for t in teammates}
        non_teammate_alive = [p for p in alive_players if p.seat not in teammate_seats and p.seat != player.seat]

        target = self._extract_seat(result, alive_players)
        if target is not None:
            # 反思：狼人击杀后
            target_name = next((p.display_name for p in alive_players if p.seat == target), f"{target+1}号")
            await self._trigger_reflection(
                player, memory,
                f"我们决定今晚击杀{target_name}。",
                "night_action", state.day, "NIGHT",
            )
            return target

        # fallback: 随机选一个非队友
        if non_teammate_alive:
            fb = random.choice(non_teammate_alive).seat
        else:
            fb = random.choice(alive_players).seat if alive_players else None
        if fb is not None:
            target_name = next((p.display_name for p in alive_players if p.seat == fb), f"{fb+1}号")
            await self._trigger_reflection(
                player, memory,
                f"我们决定今晚击杀{target_name}。",
                "night_action", state.day, "NIGHT",
            )
        return fb

    async def generate_witch_decision(
        self,
        player: Player,
        state: GameState,
        memory: AgentMemory,
        wolf_target: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        """生成女巫用药决策"""
        role_info = self.info_manager.get_role_specific_info(player, state)
        has_antidote = role_info.get("has_antidote", False)
        has_poison = role_info.get("has_poison", False)

        if not has_antidote and not has_poison:
            return {"type": "pass"}

        alive_players = [p for p in state.players if p.alive and p.player_id != player.player_id]
        poison_targets = ", ".join([f"{p.seat + 1}号 {p.display_name}" for p in alive_players])

        victim_info = ""
        if wolf_target is not None and has_antidote:
            victim = next((p for p in state.players if p.seat == wolf_target), None)
            if victim:
                victim_info = f"今晚狼人击杀了 {wolf_target + 1}号 {victim.display_name}。"
        elif not has_antidote:
            victim_info = "你已经使用过解药，无法感知今晚的死亡信息。"
        else:
            victim_info = "今晚没有人被狼人击杀。"

        strategies = self.strategy_lib.get_strategies_for_role(player.role, state.difficulty)
        strategy_text = self.strategy_lib.format_strategies_for_prompt(strategies)

        personality = self.get_personality_text(player)
        system_msg = f"""你是{player.display_name}，{player.seat + 1}号位，身份是女巫。你是一个真实的人类玩家，不是AI。
{personality}
你手中的药水是整局游戏最珍贵的资源——用对了能翻盘，用错了万劫不复。每次用药都是一次豪赌，你必须在不完全信息下做出可能改变全局的决定。

【药水状态】
- 解药：{'可用 — 可以救活今晚被杀的人' if has_antidote else '已用完'}
- 毒药：{'可用 — 可以毒杀一名你认为是狼人的玩家' if has_poison else '已用完'}
- 每晚最多用一种药，用了就没了

【今晚情况】
{victim_info}

【用药哲学】
- 解药：这个人值得救吗？他活着对好人阵营有多大价值？如果留着解药，后面可能救到更关键的人吗？第一晚通常值得救，后期要慎重。
- 毒药：你有多大把握他是狼？毒错一个好人等于帮狼人杀人。没有八成以上把握，宁可不毒。
- 不用药也是一种选择，有时候按兵不动才是最优解。

{strategy_text}"""

        memory_text = self.memory_system.format_memory_for_prompt(memory)

        user_msg = f"""第{state.day}天夜晚，你感受到了今晚的情况。

{memory_text}

【可毒杀目标】
{poison_targets}

现在做决定：
1. 如果有人被杀——这个人重要吗？救他能改变局势吗？还是留着解药以后用更划算？
2. 如果想毒人——你对谁的狼人身份最有把握？把握不够就别动手。
3. 什么都不做也行——药水留着本身就是一种威慑。

做出你的选择。

严格输出JSON：
{{"reasoning": "你的纠结和判断（50-150字，体现权衡过程）", "action": "save"或"poison"或"pass", "target_seat": 目标座位号或null}}"""

        result = await self._call_llm_json(system_msg, user_msg, player, action_type="witch", day=state.day, phase="NIGHT")

        if result:
            action = result.get("action", "pass").lower()
            if action == "save" and has_antidote and wolf_target is not None:
                # 反思：女巫救人后
                victim_name = next((p.display_name for p in state.players if p.seat == wolf_target), f"{wolf_target+1}号")
                await self._trigger_reflection(
                    player, memory,
                    f"我使用解药救了{victim_name}。",
                    "night_action", state.day, "NIGHT",
                )
                return {"type": "save"}
            elif action == "poison" and has_poison:
                target_seat = result.get("target_seat")
                if target_seat is not None:
                    seat = int(target_seat) - 1 if int(target_seat) > 0 else int(target_seat)
                    # 验证目标合法
                    if any(p.seat == seat and p.alive for p in state.players):
                        # 反思：女巫毒人后
                        poison_name = next((p.display_name for p in state.players if p.seat == seat), f"{seat+1}号")
                        await self._trigger_reflection(
                            player, memory,
                            f"我使用毒药毒了{poison_name}。",
                            "night_action", state.day, "NIGHT",
                        )
                        return {"type": "poison", "target": seat}

        # 反思：女巫选择不用药
        await self._trigger_reflection(
            player, memory,
            "我今晚选择不使用任何药水。",
            "night_action", state.day, "NIGHT",
        )
        return {"type": "pass"}

    async def generate_seer_decision(
        self,
        player: Player,
        state: GameState,
        memory: AgentMemory,
    ) -> Optional[int]:
        """生成预言家查验决策"""
        alive_players = [p for p in state.players if p.alive and p.player_id != player.player_id]

        seer_history = state.night_actions.seer_history or []
        checked_seats = {h.get("targetSeat") for h in seer_history}
        unchecked = [p for p in alive_players if p.seat not in checked_seats]
        target_players = unchecked if unchecked else alive_players

        options = ", ".join([f"{p.seat + 1}号 {p.display_name}" for p in target_players])

        history_info = ""
        if seer_history:
            history_lines = []
            for record in seer_history:
                seat = record.get("targetSeat")
                is_wolf = record.get("isWolf")
                result_text = "狼人" if is_wolf else "好人"
                history_lines.append(f"  {seat + 1}号: {result_text}")
            history_info = "【查验记录】\n" + "\n".join(history_lines)

        strategies = self.strategy_lib.get_strategies_for_role(player.role, state.difficulty)
        strategy_text = self.strategy_lib.format_strategies_for_prompt(strategies)

        personality = self.get_personality_text(player)
        system_msg = f"""你是{player.display_name}，{player.seat + 1}号位，身份是预言家。你是一个真实的人类玩家，不是AI。
{personality}
你是好人阵营的眼睛，每晚一次查验机会，查对了能锁狼，查错了浪费一晚。你背负着巨大的信息优势，但也因此成为狼人的头号猎杀目标——你可能活不了太久，所以每一次查验都要用在刀刃上。

【能力】
- 每晚查验一名玩家：好人 or 狼人
- 结果只有你知道，白天可以选择公开

【查验思路】
- 查谁能获得最大信息增量？优先查"身份最模糊"的人，而不是已经被大家怀疑的人
- 场上谁的发言最让你拿不准？谁可能在演戏？
- 如果有人跳了预言家对抗你，优先验证他的"金水"或"查杀"对象

{strategy_text}

{history_info}"""

        memory_text = self.memory_system.format_memory_for_prompt(memory)

        user_msg = f"""第{state.day}天夜晚，你睁眼准备查验。

{memory_text}

【可查验目标】
{options}

想想今晚查谁收益最大：
1. 谁的身份最模糊？白天发言让你最拿不准的是谁？
2. 查出来的结果能不能帮你明天带好节奏？
3. 有没有人声称了身份但你无法确认真假？验一下？
4. 如果你明天可能被狼人杀掉，今晚查谁留下的信息最有价值？

选一个目标。

严格输出JSON：
{{"reasoning": "你的判断过程（50-100字）", "target_seat": 座位号数字}}"""

        result = await self._call_llm_json(system_msg, user_msg, player, action_type="seer", day=state.day, phase="NIGHT")
        target = self._extract_seat(result, target_players)
        if target is not None:
            # 反思在 game_controller 中查验结果出来后触发（因为此时还不知道结果）
            return target

        # fallback
        fb = random.choice(target_players).seat if target_players else None
        return fb

    # ========== 白天决策 ==========

    async def generate_speech(
        self,
        player: Player,
        state: GameState,
        memory: AgentMemory,
    ) -> str:
        """生成AI发言"""
        role_info = self.info_manager.get_role_specific_info(player, state)
        strategies = self.strategy_lib.get_strategies_for_role(player.role, state.difficulty)
        strategy_text = self.strategy_lib.format_strategies_for_prompt(strategies)

        role_name = ROLE_CHINESE.get(player.role, player.role)

        # 构建角色专属系统消息（含性格）
        system_msg = self._build_speech_system_msg(player, role_info, strategy_text)

        memory_text = self.memory_system.format_memory_for_prompt(memory)
        today_transcript = build_today_transcript(state, max_chars=6000, player=player)

        user_msg = f"""第{state.day}天白天，轮到你发言了。

{memory_text}

【今日已有发言】
{today_transcript if today_transcript else "（你是第一个发言的）"}

现在该你说了。想想：
- 今天场上的气氛怎么样？大家在聊什么？
- 你对谁有想法？为什么？
- 有没有人的发言让你觉得不对劲？或者让你觉得可以信任？
- 你想表达什么立场？

像真人一样说话，100-200字，直接输出你的发言："""

        # 使用玩家专属 LLM 配置
        cfg = self.get_player_llm_config(player)
        messages = [
            LLMMessage(role="system", content=system_msg),
            LLMMessage(role="user", content=user_msg),
        ]

        try:
            response = await generate_completion(
                messages,
                model=cfg.model,
                temperature=cfg.temperature,
                max_tokens=min(cfg.max_tokens, 500),
                api_base=cfg.api_base,
                api_key=cfg.api_key,
            )
            content = response.choices[0]["message"]["content"].strip()
            raw_content = content
            # 清理可能的JSON包装
            if content.startswith("{") and "content" in content:
                try:
                    parsed = json.loads(content)
                    content = parsed.get("content", parsed.get("speech", content))
                except json.JSONDecodeError:
                    pass
            if self.logger:
                self.logger.log_decision(
                    seat=player.seat, player_name=player.display_name,
                    action_type="speech", day=state.day, phase="DAY",
                    model=cfg.model, system_msg=system_msg, user_msg=user_msg,
                    raw_response=raw_content, final_decision=content,
                )
            # 反思：发言后
            await self._trigger_reflection(
                player, memory,
                f"我刚才发言说：{content[:60]}{'...' if len(content) > 60 else ''}",
                "speech", state.day, "DAY",
            )
            return content
        except Exception as e:
            print(f"Agent speech error for {player.display_name}: {e}")
            return f"我是{player.seat + 1}号，暂时没有什么想说的。"

    async def generate_vote(
        self,
        player: Player,
        state: GameState,
        memory: AgentMemory,
    ) -> Optional[int]:
        """生成AI投票"""
        role_info = self.info_manager.get_role_specific_info(player, state)
        strategies = self.strategy_lib.get_strategies_for_role(player.role, state.difficulty)
        strategy_text = self.strategy_lib.format_strategies_for_prompt(strategies)

        role_name = ROLE_CHINESE.get(player.role, player.role)

        alive_players = [p for p in state.players if p.alive]
        options = ", ".join([f"{p.seat + 1}号 {p.display_name}" for p in alive_players])

        today_transcript = build_today_transcript(state, max_chars=8000, player=player)

        # 狼人投票特殊处理
        extra_info = ""
        if player.role == "Werewolf":
            teammates = role_info.get("teammates", [])
            if teammates:
                teammate_seats = [f"{t['seat'] + 1}号" for t in teammates]
                extra_info = f"\n【注意】你的队友是 {', '.join(teammate_seats)}，不要投票给队友（除非需要伪装）。"

        personality = self.get_personality_text(player)
        system_msg = f"""你是{player.display_name}，{player.seat + 1}号位，身份是{role_name}。你是一个真实的人类玩家，不是AI。
{personality}
{strategy_text}
{extra_info}

投票是狼人杀中最关键的博弈环节。你的每一票都是公开信息，所有人都会分析你投了谁。

【投票心理】
- 跟票（随大流）：安全但没有信息量，可能被认为是"划水"
- 独立投票：有主见但可能被孤立，如果投对了会加分，投错了会被怀疑
- 你要权衡：大势指向谁？你内心真正怀疑谁？这两者一致吗？
- 如果你是狼人：要跟随好人的投票趋势，但不要总是最后一个跟票，太明显了"""

        memory_text = self.memory_system.format_memory_for_prompt(memory)

        user_msg = f"""第{state.day}天，投票环节。

{memory_text}

【今日完整发言回顾】
{today_transcript if today_transcript else "（无发言记录）"}

【可投票目标】
{options}

投票前想清楚：
1. 今天的发言里，谁最可疑？谁的逻辑有漏洞？
2. 场上大多数人想投谁？你要跟还是不跟？
3. 你投这个人，别人会怎么看你？会不会暴露你的立场或身份？
4. 有没有人今天的表现让你改变了之前的判断？

【严格禁止】
- 不要编造别人没说过的话。只能基于上面的发言记录来判断。
- "投票给某人"不等于"带队冲某人"。除非某人在发言中明确号召投票，否则不能说他"带队"或"带节奏"。

做出你的选择。

严格输出JSON：
{{"reasoning": "你的投票理由（50-150字，像真人在心里盘算）", "target_seat": 座位号数字}}"""

        result = await self._call_llm_json(system_msg, user_msg, player, action_type="vote", day=state.day, phase="DAY")
        target = self._extract_seat(result, alive_players)
        if target is not None:
            # 反思：投票后
            target_name = next((p.display_name for p in alive_players if p.seat == target), f"{target+1}号")
            await self._trigger_reflection(
                player, memory,
                f"我投票给了{target_name}。",
                "vote", state.day, "DAY",
            )
            return target

        # fallback
        fb = random.choice(alive_players).seat if alive_players else None
        if fb is not None:
            target_name = next((p.display_name for p in alive_players if p.seat == fb), f"{fb+1}号")
            await self._trigger_reflection(
                player, memory,
                f"我投票给了{target_name}。",
                "vote", state.day, "DAY",
            )
        return fb

    async def generate_last_words(
        self,
        player: Player,
        state: GameState,
        memory: AgentMemory,
    ) -> str:
        """生成AI遗言"""
        role_name = ROLE_CHINESE.get(player.role, player.role)

        personality = self.get_personality_text(player)
        system_msg = f"""你是{player.display_name}，{player.seat + 1}号位，身份是{role_name}。你是一个真实的人类玩家，不是AI。
{personality}
你要被淘汰了。这是你最后的发言机会。

【遗言的意义】
这是你留给场上所有人的最后一段话。不管你是什么身份，这段话都应该有分量。

- 如果你是好人/神职：把你知道的关键信息留下来，帮活着的人继续战斗。可以愤怒，可以不甘，但信息要清晰。
- 如果你是预言家：这是你最后的机会公布查验结果和警徽流，务必说清楚。
- 如果你是狼人：你可以继续演戏到最后一刻，混淆视听，给队友争取空间。也可以选择沉默。

【情感】
你即将离开这局游戏。你可以表达你的情绪——愤怒、不甘、释然、最后的挣扎，甚至调侃。遗言不是冷冰冰的信息传递，是一个人最后的表达。"""

        memory_text = self.memory_system.format_memory_for_prompt(memory)

        user_msg = f"""{memory_text}

这是你最后的机会了。你想对大家说什么？
有什么信息必须留下？有什么话不吐不快？

50-150字，直接说出你的遗言："""

        # 使用玩家专属 LLM 配置
        cfg = self.get_player_llm_config(player)
        messages = [
            LLMMessage(role="system", content=system_msg),
            LLMMessage(role="user", content=user_msg),
        ]

        try:
            response = await generate_completion(
                messages,
                model=cfg.model,
                temperature=cfg.temperature,
                max_tokens=300,
                api_base=cfg.api_base,
                api_key=cfg.api_key,
            )
            content = response.choices[0]["message"]["content"].strip()
            raw_content = content
            if content.startswith("{"):
                try:
                    parsed = json.loads(content)
                    content = parsed.get("content", parsed.get("speech", content))
                except json.JSONDecodeError:
                    pass
            if self.logger:
                self.logger.log_decision(
                    seat=player.seat, player_name=player.display_name,
                    action_type="last_words", day=state.day, phase="DAY",
                    model=cfg.model, system_msg=system_msg, user_msg=user_msg,
                    raw_response=raw_content, final_decision=content,
                )
            return content
        except Exception as e:
            print(f"Agent last words error: {e}")
            return f"我是{role_name}，请相信我。"

    async def generate_hunter_decision(
        self,
        player: Player,
        state: GameState,
        memory: AgentMemory,
    ) -> Optional[int]:
        """生成猎人开枪决策"""
        alive_players = [p for p in state.players if p.alive and p.player_id != player.player_id]
        options = ", ".join([f"{p.seat + 1}号 {p.display_name}" for p in alive_players])

        strategies = self.strategy_lib.get_strategies_for_role(player.role, state.difficulty)
        strategy_text = self.strategy_lib.format_strategies_for_prompt(strategies)

        personality = self.get_personality_text(player)
        system_msg = f"""你是{player.display_name}，{player.seat + 1}号位，身份是猎人。你是一个真实的人类玩家，不是AI。
{personality}
你倒下了，但你还有最后一颗子弹。这一枪的分量比你之前所有的发言和投票加起来都重——打对了可能直接翻盘，打错了就是帮狼人送人头。

{strategy_text}

【开枪原则】
- 如果你确认了谁是狼人，毫不犹豫地带走他
- 如果没有确认目标，选你最怀疑的那个人
- 绝对不要带走你认为是好人的玩家
- 这是你对这局游戏最后的贡献，慎重但果断"""

        memory_text = self.memory_system.format_memory_for_prompt(memory)

        user_msg = f"""{memory_text}

【可射击目标】
{options}

最后一枪，打谁？
1. 你心里最确定的狼人是谁？
2. 如果没有确定目标，谁的嫌疑最大？
3. 这一枪打出去，对好人阵营帮助最大的选择是什么？

严格输出JSON：
{{"reasoning": "你的最后判断（30-80字）", "target_seat": 座位号数字}}"""

        result = await self._call_llm_json(system_msg, user_msg, player, action_type="hunter", day=state.day, phase="DAY")
        target = self._extract_seat(result, alive_players)
        if target is not None:
            return target

        # fallback: 选择嫌疑最大的
        if memory.wolf_suspects:
            for suspect in memory.wolf_suspects:
                if any(p.seat == suspect and p.alive for p in state.players):
                    return suspect

        return random.choice(alive_players).seat if alive_players else None

    # ========== 内部方法 ==========

    def _build_speech_system_msg(
        self,
        player: Player,
        role_info: Dict[str, Any],
        strategy_text: str,
    ) -> str:
        """构建发言系统消息（含性格）"""
        role_name = ROLE_CHINESE.get(player.role, player.role)
        personality = self.get_personality_text(player)

        parts = [f"你是{player.display_name}，{player.seat + 1}号位。你是一个真实的人类玩家，正在玩狼人杀。"]

        if personality:
            parts.append(personality)

        parts.append("""【说话风格——极其重要，必须遵守】
你说话要像一个真人在桌游局上聊天，不是在写分析报告。具体要求：
- 可以用语气词开头："emmm"、"我觉得吧"、"说实话"、"怎么说呢"
- 可以中途改口、犹豫："等等，不对"、"我本来想说...算了"
- 不要用"综上所述"、"根据分析"、"首先...其次...最后"这种结构
- 不要每句话都有因果逻辑连接词
- 可以有情绪：生气、怀疑、调侃、无奈
- 可以直接怼人，也可以帮人说话
- 不要做总结性发言，说完就完了，像聊天一样自然收尾""")

        if player.role == "Werewolf":
            teammates = role_info.get("teammates", [])
            if teammates:
                teammate_list = ", ".join([f"{t['seat'] + 1}号 {t['name']}" for t in teammates])
                parts.append(f"\n【秘密身份】你是狼人。你的队友: {teammate_list}")
            parts.append("""
【狼人发言策略】
- 你要伪装成好人，但不要伪装得太完美——真人不会每句话都逻辑自洽
- 适度留一点"不确定"和"犹豫"，这才像真人
- 可以主动怀疑别人来转移注意力，但不要每次都带节奏，会被看穿
- 不要暴露队友，不要说出只有狼人才知道的夜晚信息
- 偶尔可以"站错边"或"分析错误"，真人经常判断失误
- 如果被怀疑了，不要过度辩解，适度回应就好""")

        elif player.role == "Seer":
            check_history = role_info.get("check_history", [])
            if check_history:
                parts.append("\n【你的查验结果——只有你知道】")
                for record in check_history:
                    seat = record.get("targetSeat")
                    is_wolf = record.get("isWolf")
                    result_text = "狼人" if is_wolf else "好人"
                    parts.append(f"  {seat + 1}号: {result_text}")
            parts.append("""
【预言家发言策略】
- 你手握真相，但要选择合适的时机和方式公开
- 跳预言家要有气势，但不要像在念报告，要像真人在据理力争
- 如果有人悍跳对抗你，要用具体的逻辑和细节反驳，带点情绪更真实
- 可以建立警徽流，告诉大家如果你死了下一个查谁
- 记住：你越像真人，别人越信你""")

        elif player.role == "Witch":
            parts.append("""
【女巫发言策略】
- 一般不主动暴露身份，伪装成普通村民
- 如果你用过药，心里有数但嘴上别说
- 可以根据你知道的夜晚信息（谁死了、你救没救）来引导讨论方向
- 如果局势危急需要跳身份自保，要果断""")

        elif player.role == "Hunter":
            parts.append("""
【猎人发言策略】
- 猎人的枪是你的底牌，不到万不得已别亮出来
- 正常发言像村民一样分析局势
- 如果被强烈怀疑或即将被投出，可以跳身份："你们投我试试，我有枪的"
- 这种威慑力本身就是一种保护""")

        elif player.role == "Guard":
            parts.append("""
【守卫发言策略】
- 绝对不要暴露守卫身份，你一旦暴露就失去了守护的意义
- 像普通村民一样发言，分析局势、表达观点
- 心里记着谁可能是预言家，你要暗中保护他
- 如果出现平安夜，不要表现得太得意""")

        else:  # Villager
            parts.append("""
【村民发言策略】
- 你没有特殊能力，但你的投票和发言同样重要
- 仔细听别人说了什么，找矛盾、找破绽
- 选一个你相信的预言家站边
- 大胆表达你的怀疑，村民就是要靠逻辑和直觉找狼""")

        if strategy_text:
            parts.append(f"\n{strategy_text}")

        parts.append("""
【严格禁止】
- 不要编造或脑补别人没说过的话。只能引用你实际听到的发言内容。
- 不要把"投票给某人"说成"带队冲某人"，除非那个人在发言中明确号召大家投票。
- 投票是个人行为，不等于"带节奏"。""")

        parts.append("\n【输出要求】\n- 100-200字，像真人说话\n- 直接输出发言内容，不要JSON\n- 不要加引号包裹")

        return "\n".join(parts)

    async def _call_llm_json(self, system_msg: str, user_msg: str, player: Optional[Player] = None, action_type: str = "", day: int = 0, phase: str = "") -> Optional[Dict]:
        """调用 LLM 并解析 JSON 响应（支持per-player配置）"""
        messages = [
            LLMMessage(role="system", content=system_msg),
            LLMMessage(role="user", content=user_msg),
        ]

        # 获取玩家专属 LLM 配置
        temperature = GAME_TEMPERATURE
        max_tokens = 500
        model = None
        api_base = None
        api_key = None
        if player is not None:
            cfg = self.get_player_llm_config(player)
            temperature = cfg.temperature
            max_tokens = cfg.max_tokens if cfg.max_tokens <= 500 else 500
            model = cfg.model
            api_base = cfg.api_base
            api_key = cfg.api_key

        try:
            response = await generate_completion(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                api_base=api_base,
                api_key=api_key,
            )
            content = response.choices[0]["message"]["content"].strip()
            raw_content = content
            content = strip_markdown_code_fences(content)

            parsed = None
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                # 尝试提取 JSON
                match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group())
                    except json.JSONDecodeError:
                        pass

                # 尝试直接提取数字
                if parsed is None:
                    num_match = re.search(r'(\d+)', content)
                    if num_match:
                        parsed = {"target_seat": int(num_match.group(1))}

            # 记录日志
            if self.logger and player is not None:
                self.logger.log_decision(
                    seat=player.seat,
                    player_name=player.display_name,
                    action_type=action_type,
                    day=day,
                    phase=phase,
                    model=model or "",
                    system_msg=system_msg,
                    user_msg=user_msg,
                    raw_response=raw_content,
                    parsed_result=parsed,
                )

            return parsed
        except Exception as e:
            print(f"LLM call error: {e}")
            return None

    def _extract_seat(
        self,
        result: Optional[Dict],
        valid_players: List[Player],
    ) -> Optional[int]:
        """从 LLM 结果中提取合法座位号"""
        if not result:
            return None

        target_seat = result.get("target_seat")
        if target_seat is None:
            return None

        # LLM 可能返回 1-indexed 或 0-indexed
        seat = int(target_seat)

        # 如果是 1-indexed（大于0且在玩家范围内）
        if seat > 0:
            seat_0 = seat - 1
            if any(p.seat == seat_0 for p in valid_players):
                return seat_0

        # 如果是 0-indexed
        if any(p.seat == seat for p in valid_players):
            return seat

        return None

    # ========== 夜晚讨论 ==========

    async def generate_night_discussion_speech(
        self,
        player: Player,
        state: GameState,
        memory: AgentMemory,
        discussion_history: List[Dict[str, str]],
        round_num: int,
    ) -> str:
        """生成夜晚讨论发言

        Args:
            player: 当前发言玩家
            state: 游戏状态
            memory: 玩家记忆
            discussion_history: 已有的讨论记录 [{"name": ..., "content": ...}, ...]
            round_num: 当前是第几轮发言（1-3）
        """
        role_name = ROLE_CHINESE.get(player.role, player.role)
        personality = self.get_personality_text(player)

        history_text = ""
        if discussion_history:
            lines = [f"  {d['name']}: {d['content']}" for d in discussion_history]
            history_text = "【已有讨论】\n" + "\n".join(lines)

        memory_text = self.memory_system.format_memory_for_prompt(memory)

        system_msg = f"""你是{player.display_name}，{player.seat + 1}号位，身份是狼人。你是一个真实的人类玩家，不是AI。
{personality}
现在是第{state.day}天夜晚，你和狼队友在密谋。这是第{round_num}轮讨论（最多3轮）。

【讨论氛围】
你们是一伙的，但不代表没有分歧。好的狼队会讨论、争论、最终达成一致。
- 像真人密谋一样说话，简短、直接、有主见
- 可以同意队友，也可以反驳："我觉得不行，杀他太明显了"
- 如果已经达成一致，直接说 [达成共识] 结束讨论
- 不要写分析报告，就像两个人在小声商量"""

        user_msg = f"""【场上局势】
{memory_text}

{history_text}

跟队友商量一下：
- 今晚杀谁？为什么？
- 队友说的有没有道理？你同意还是有别的想法？
- 明天白天怎么应对？

30-80字，像密谋一样说话。
如果已经和队友想法一致，直接回复 [达成共识]。
不要输出JSON："""

        cfg = self.get_player_llm_config(player)
        messages = [
            LLMMessage(role="system", content=system_msg),
            LLMMessage(role="user", content=user_msg),
        ]

        try:
            response = await generate_completion(
                messages,
                model=cfg.model,
                temperature=cfg.temperature,
                max_tokens=200,
                api_base=cfg.api_base,
                api_key=cfg.api_key,
            )
            content = response.choices[0]["message"]["content"].strip()
            raw_content = content
            if content.startswith("{"):
                try:
                    parsed = json.loads(content)
                    content = parsed.get("content", parsed.get("speech", content))
                except json.JSONDecodeError:
                    pass
            if self.logger:
                self.logger.log_decision(
                    seat=player.seat, player_name=player.display_name,
                    action_type="night_discussion", day=state.day, phase="NIGHT",
                    model=cfg.model, system_msg=system_msg, user_msg=user_msg,
                    raw_response=raw_content, final_decision=content,
                    extra={"round": round_num},
                )
            # 反思：狼人讨论后（仅最后一轮触发，避免过多 LLM 调用）
            if round_num >= 2 or "[达成共识]" in content or "达成共识" in content:
                await self._trigger_reflection(
                    player, memory,
                    f"狼人讨论中我说：{content[:50]}{'...' if len(content) > 50 else ''}",
                    "night_action", state.day, "NIGHT",
                )
            return content
        except Exception as e:
            print(f"Night discussion speech error for {player.display_name}: {e}")
            return "我暂时没什么想说的。"

    # ========== 性格生成 ==========

    async def generate_personality(self, player: Player) -> str:
        """使用 LLM 为玩家生成游戏性格描述

        Returns:
            性格描述文本
        """
        role_name = ROLE_CHINESE.get(player.role, player.role)

        system_msg = """你是一个狼人杀玩家性格生成器。为每个玩家创造一个独特的、有辨识度的人格。

生成的性格要包含以下维度（50-100字，紧凑有力）：
1. 说话风格：语速快慢、用词习惯、是否爱用反问句、是否喜欢打比方
2. 口头禅或标志性表达：给一个让人记住的语言习惯（比如爱说"你品你细品"、"这波啊这波是..."、"我直说了啊"）
3. 性格底色：冲动型/沉稳型/阴阳怪气型/老好人型/刺头型/话少但狠型
4. 情绪触发点：什么情况下会激动？什么情况下会沉默？被怀疑时是反击还是冷处理？
5. 游戏风格：激进找狼/保守观望/喜欢站边/独立思考/容易被带节奏

不要面面俱到，突出2-3个最鲜明的特点就好。要让每个玩家"不一样"。
直接输出性格描述文本，不要JSON。"""

        user_msg = f"给{player.seat + 1}号玩家 {player.display_name} 创造一个独特的性格。要求有辨识度，让人一听发言就知道'这是他的风格'。直接输出性格描述："

        cfg = self.get_player_llm_config(player)
        messages = [
            LLMMessage(role="system", content=system_msg),
            LLMMessage(role="user", content=user_msg),
        ]

        try:
            response = await generate_completion(
                messages,
                model=cfg.model,
                temperature=0.9,
                max_tokens=200,
                api_base=cfg.api_base,
                api_key=cfg.api_key,
            )
            content = response.choices[0]["message"]["content"].strip()
            self.set_personality(player.player_id, content)
            if self.logger:
                self.logger.log_decision(
                    seat=player.seat, player_name=player.display_name,
                    action_type="personality", day=0, phase="INIT",
                    model=cfg.model, system_msg=system_msg, user_msg=user_msg,
                    raw_response=content, final_decision=content,
                )
            return content
        except Exception as e:
            print(f"Personality generation error for {player.display_name}: {e}")
            fallback = "性格沉稳，善于观察，发言简洁有力。"
            self.set_personality(player.player_id, fallback)
            return fallback
