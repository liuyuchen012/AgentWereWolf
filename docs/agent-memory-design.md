# AI Agent 记忆系统设计文档

## 一、设计目标

让每个 AI Agent 在游戏中的每次行动都经历完整的 **"记忆读取 → 决策 → 反思写回"** 循环，模拟人类玩家在狼人杀中的思考过程：听到信息会分析、做完决定会复盘、对其他玩家的态度会动态变化。

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    GameController                        │
│  （游戏主控，驱动阶段流转，调用各模块）                      │
│                                                         │
│  agent_memories: Dict[player_id, AgentMemory]           │
│  memory_system: MemorySystem                            │
│  decision_engine: DecisionEngine                        │
└────────┬──────────────┬──────────────┬──────────────────┘
         │              │              │
         ▼              ▼              ▼
   ┌──────────┐  ┌────────────┐  ┌──────────────┐
   │MemorySystem│  │DecisionEngine│  │InformationMgr│
   │记忆读写层  │  │决策层(LLM)   │  │信息可见性过滤 │
   └──────────┘  └────────────┘  └──────────────┘
```

### 模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| AgentMemory | `agent/memory.py` | 数据结构，存储单个 agent 的全部记忆 |
| MemorySystem | `agent/memory.py` | 记忆的读取、更新、格式化、反思生成 |
| DecisionEngine | `agent/decision.py` | 构建 prompt + 调用 LLM 生成决策 + 触发反思 |
| InformationManager | `agent/information.py` | 按角色过滤可见信息（信息屏障） |
| StrategyLibrary | `agent/strategy.py` | 从 JSON 加载角色策略，注入 prompt |
| GameController | `game_controller.py` | 游戏流程控制，协调上述模块 |

---

## 三、AgentMemory 数据结构

每个 AI 玩家持有一个独立的 `AgentMemory` 实例，包含以下层次：

### 3.1 基础记忆

```
AgentMemory
├── player_id: str              # 玩家唯一标识
├── role: str                   # 自己的角色 (Werewolf/Seer/...)
├── player_memories: Dict[seat, PlayerMemory]  # 对每个玩家的认知
├── night_actions: List[NightActionRecord]     # 自己的夜间行动日志
├── deaths: List[DeathRecord]                  # 死亡事件记录
├── wolf_suspects: List[seat]                  # 狼人嫌疑列表
├── confirmed_good: List[seat]                 # 确认好人列表
├── key_insights: List[str]                    # 关键洞察（文本）
├── current_strategy: Optional[str]            # 当前策略标签
└── role_specific: Dict                        # 角色专属数据
```

### 3.2 PlayerMemory（对单个玩家的认知）

```
PlayerMemory
├── seat / name / is_alive      # 基本信息
├── claimed_role                # 该玩家声称的角色
├── alignment_belief            # 推测阵营 ("village" / "wolf")
├── confidence                  # 推测置信度 (0~1)
├── speech_count                # 发言次数
├── speech_keywords             # 发言中的关键词
├── vote_history                # 投票历史 [target_seat, ...]
├── voted_by                    # 被谁投过票
├── suspected_by                # 被谁怀疑过
├── defended_by                 # 被谁辩护过
└── notes                       # 备注（如"队友"）
```

### 3.3 新增：反思与信任系统

```
AgentMemory（新增字段）
├── reflections: List[Reflection]       # 反思日志（结构化）
├── trust_scores: Dict[seat, float]     # 信任网络 (-1.0 ~ 1.0)
├── emotional_state: str                # 情绪状态
├── current_plan: Optional[str]         # 当前短期计划
└── plan_reasoning: Optional[str]       # 计划的推理依据
```

**Reflection 结构：**
```
Reflection
├── day: int                    # 第几天
├── phase: str                  # 阶段
├── action_type: str            # 行动类型 (speech/vote/night_action/observation)
├── content: str                # LLM 生成的反思文本 (50-100字)
└── updated_beliefs: Dict       # 本次反思更新的信念
```

**信任分数含义：**
| 分数范围 | 含义 |
|---------|------|
| 0.5 ~ 1.0 | 高度信任（队友/确认好人） |
| 0.2 ~ 0.5 | 倾向信任 |
| -0.2 ~ 0.2 | 中立 |
| -0.5 ~ -0.2 | 倾向怀疑 |
| -1.0 ~ -0.5 | 高度怀疑（确认狼人） |

**情绪状态枚举：**
`neutral` / `calm` / `anxious` / `suspicious` / `confident` / `desperate`

---

## 四、Memory 交互的完整数据流

### 4.1 总览：一次完整的行动循环

```
事件发生
    │
    ▼
┌─────────────────────────┐
│ 1. 规则更新（轻量，不调LLM）│  ← MemorySystem.update_from_xxx()
│   - 更新 PlayerMemory     │
│   - 更新 key_insights     │
│   - 更新 trust_scores     │  ← MemorySystem.update_trust_from_speech()
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 2. 读取记忆构建 Prompt    │  ← MemorySystem.format_memory_for_prompt()
│   - 玩家分析              │
│   - 信任评估              │
│   - 当前计划              │
│   - 情绪状态              │
│   - 近期反思              │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 3. LLM 决策              │  ← DecisionEngine.generate_xxx()
│   - system prompt (角色+策略+性格)
│   - user prompt (记忆+局势+选项)
│   - → LLM 返回决策结果     │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│ 4. LLM 反思（异步）       │  ← DecisionEngine._trigger_reflection()
│   - 输入：刚发生的事件描述  │     → MemorySystem.generate_reflection()
│   - 输出：                │
│     · reflection 文本     │
│     · trust_changes       │
│     · emotion 更新        │
│     · plan 更新           │
│   - 写回 AgentMemory      │
└─────────────────────────┘
```

### 4.2 两种更新机制对比

| | 规则更新 | LLM 反思 |
|---|---------|---------|
| 调用方式 | 同步，纯 Python 逻辑 | 异步，调用 LLM API |
| 触发频率 | 每次发言/投票/死亡都触发 | 仅在关键节点触发 |
| 成本 | 零 | ~200 tokens/次 |
| 更新内容 | PlayerMemory 字段、key_insights、trust_scores 微调 | 反思文本、信任大幅调整、情绪、计划 |
| 失败影响 | 不会失败 | 失败时静默跳过，不影响游戏 |

---

## 五、各阶段的 Memory 交互详情

### 5.1 游戏初始化

```
角色分配
  │
  ├→ init_agent_memory()
  │   - 初始化 player_memories（所有玩家）
  │   - 初始化 trust_scores（全部 0.0）
  │   - 狼人：队友 trust = 1.0, alignment_belief = "wolf"
  │
  └→ generate_personality()
      - LLM 生成性格描述（说话风格、游戏倾向、社交特点）
      - 缓存到 DecisionEngine._personality_cache
```

### 5.2 夜间 — 守卫行动

```
守卫行动阶段
  │
  ├→ [读] format_memory_for_prompt(memory)
  │   构建 prompt，包含玩家分析、信任评估、上次保护记录
  │
  ├→ [决策] generate_guard_decision()
  │   LLM 选择保护目标 → target_seat
  │
  ├→ [写-规则] update_night_action(memory, "guard", target, ...)
  │   记录本次保护行动到 night_actions
  │
  └→ [写-反思] _trigger_reflection()
      事件描述: "我选择保护了X号玩家，因为..."
      → 更新 trust_scores, emotional_state, current_plan
```

### 5.3 夜间 — 狼人讨论 + 投票

```
狼人讨论阶段（60s 总时限）
  │
  ├→ AI 狼人发言:
  │   ├→ [读] format_memory_for_prompt() + discussion_history
  │   ├→ [决策] generate_night_discussion_speech()
  │   ├→ [写-规则] update_from_speech() → 更新所有狼人的 PlayerMemory
  │   ├→ [写-规则] _update_wolf_memories_from_speech()
  │   └→ [写-反思] _trigger_reflection("night_discussion")
  │
  ├→ 人类狼人发言:
  │   └→ [写-规则] update_from_speech() → 更新所有狼人的 PlayerMemory
  │
  └→ AI 狼人投票:
      ├→ [读] format_memory_for_prompt() + existing_votes
      ├→ [决策] generate_wolf_decision()
      └→ [写-反思] _trigger_reflection("wolf_kill")
          事件描述: "我们决定击杀X号，因为..."
```

### 5.4 夜间 — 女巫行动

```
女巫行动阶段
  │
  ├→ [读] format_memory_for_prompt()
  │   包含：药水状态、女巫行动记录、被杀目标信息
  │
  ├→ [决策] generate_witch_decision()
  │   LLM 选择 save / poison / pass
  │
  ├→ [写-规则] update_night_action(memory, "save"/"poison"/"witch_pass", ...)
  │
  └→ [写-反思] _trigger_reflection()
      - save: "我救了X号，因为..."
      - poison: "我毒了X号，因为..."
      - pass: "我选择不用药，因为..."
```

### 5.5 夜间 — 预言家查验

```
预言家查验阶段
  │
  ├→ [读] format_memory_for_prompt()
  │   包含：查验记录、已查过的玩家
  │
  ├→ [决策] generate_seer_decision()
  │   LLM 选择查验目标
  │
  ├→ [写-规则] update_night_action(memory, "check", target, result, ...)
  │   记录查验结果，更新 wolf_suspects / confirmed_good
  │
  └→ [写-反思] _trigger_reflection()  ← 在 game_controller 中查验结果出来后触发
      事件描述: "我查验了X号，结果是好人/狼人"
      → 大幅更新对该玩家的 trust_score
```

### 5.6 天亮公告

```
天亮 → 公布昨晚死亡信息
  │
  ├→ [写-规则] update_from_death() → 所有 AI 玩家
  │   - 标记死者 is_alive = False
  │   - 添加 DeathRecord
  │   - 从 wolf_suspects / confirmed_good 移除死者
  │
  ├→ [写-规则] update_from_night_announcement() → 所有 AI 玩家
  │   - 添加 key_insight: "第X夜死亡: ..."
  │
  └→ [写-反思] _trigger_observation_reflections() → 所有存活 AI 玩家
      事件描述: "天亮了，昨晚X号死亡（被狼人杀）"
      每个 AI 独立反思：
      - 狼人："我们的计划成功了" / "被守卫挡了"
      - 预言家："死者是我验过的好人，损失很大"
      - 村民："根据死亡信息，我怀疑..."
```

### 5.7 白天发言

```
玩家发言阶段（按座位顺序）
  │
  ├→ AI 玩家发言:
  │   ├→ [读] format_memory_for_prompt() + today_transcript
  │   ├→ [决策] generate_speech()
  │   │   prompt 包含：记忆、信任评估、计划、情绪、近期反思
  │   ├→ [写-规则] update_from_speech() → 所有 AI 玩家更新 PlayerMemory
  │   ├→ [写-规则] _update_trust_from_speech() → 所有 AI 玩家更新信任分数
  │   └→ [写-反思] _trigger_reflection("speech")
  │       事件描述: "我刚才发言说了...，别人可能怎么看我"
  │
  └→ 人类/其他 AI 发言:
      ├→ [写-规则] update_from_speech() → 所有 AI 玩家
      └→ [写-规则] _update_trust_from_speech() → 所有 AI 玩家
          规则逻辑：
          - 发言者怀疑我 → trust -0.15
          - 发言者为我辩护 → trust +0.1
          - 发言者角色声称前后不一致 → trust -0.2
          - 多个人声称预言家 → 后声称者 trust -0.1
          - 发言者被 ≥3 人怀疑 → trust -0.05
```

### 5.8 投票阶段

```
投票阶段
  │
  ├→ AI 玩家投票:
  │   ├→ [读] format_memory_for_prompt() + today_transcript
  │   ├→ [决策] generate_vote()
  │   ├→ [写-规则] update_from_vote() → 所有 AI 玩家
  │   └→ [写-反思] _trigger_reflection("vote")
  │       事件描述: "我投了X号，因为..."
  │
  └→ 投票结果出来:
      ├→ [写-规则] update_from_vote_result() → 所有 AI 玩家
      ├→ [写-规则] update_from_death() → 如果有人出局
      └→ [写-反思] _trigger_observation_reflections() → 所有存活 AI
          事件描述: "投票结果：X号被投出局 / 平票无人出局"
```

### 5.9 遗言 & 猎人开枪

```
遗言阶段:
  ├→ [读] format_memory_for_prompt()
  ├→ [决策] generate_last_words()
  └→ 不触发反思（人已经要死了）

猎人开枪:
  ├→ [读] format_memory_for_prompt()
  ├→ [决策] generate_hunter_decision()
  └→ 不触发反思（人已经死了）
  但其他 AI 会收到死亡事件 → 触发 _update_all_memories_from_death()
```

---

## 六、Prompt 中的 Memory 呈现

`format_memory_for_prompt()` 输出示例：

```
【玩家分析】
  1号 小明: 声称预言家, 上次投3号
  2号 小红: 无特殊信息
  3号 小刚: 推测狼人, 被3人怀疑
  ...

【已死亡玩家】
  5号 小李: 被狼人杀 声称村民

【狼人嫌疑】3号, 7号

【确认好人】2号

【关键洞察】
  - 第1夜死亡: 5号小李
  - 第1天投票: 3号被投出局
  - 第2天我的发言: 我怀疑7号...

【查验记录】（预言家专属）
  2号: 好人
  7号: 狼人

【信任评估】
  信任: 2号(+0.6), 4号(+0.3)
  警惕: 7号(-0.8), 3号(-0.4)

【当前计划】今天投票集中火力投7号，引导其他人跟票

【情绪状态】自信

【近期反思】
  - [observation] 天亮了，5号死了，我昨晚查验的7号是狼人，今天必须公布
  - [speech] 我公布了查验结果，大部分人似乎相信我，但3号在质疑
  - [vote] 投票成功把3号投出去了，场上局势对好人有利
```

---

## 七、反思机制详解

### 7.1 反思的 LLM 调用

**System Prompt：**
```
你是{角色名}，正在进行狼人杀游戏的内心反思。
请根据刚发生的事件，简短反思（50-100字），并输出JSON。
```

**User Prompt：**
```
【事件】我选择保护了3号玩家
【情绪】calm
信任: 2号(+0.6) 不信任: 7号(-0.5)
当前计划: 保护声称预言家的3号

请输出严格JSON：
{"reflection": "...", "trust_changes": {"座位号": 变化值}, "emotion": "...", "plan": "..."}
```

**LLM 返回示例：**
```json
{
  "reflection": "3号声称预言家且逻辑自洽，保护他是正确选择。如果今晚平安夜，说明我保对了。",
  "trust_changes": {"3": 0.1},
  "emotion": "confident",
  "plan": "明天继续观察3号的查验结果是否合理"
}
```

### 7.2 反思触发点汇总

| 触发点 | 触发方式 | 谁被触发 | action_type |
|--------|---------|---------|-------------|
| 守卫保护后 | DecisionEngine | 守卫自己 | night_action |
| 狼人讨论发言后 | DecisionEngine | 发言的狼人 | night_discussion |
| 狼人投票击杀后 | DecisionEngine | 投票的狼人 | wolf_kill |
| 女巫用药后 | DecisionEngine | 女巫自己 | night_action |
| 预言家查验结果后 | GameController | 预言家自己 | night_action |
| 天亮公告后 | GameController | 所有存活 AI | observation |
| AI 发言后 | DecisionEngine | 发言者自己 | speech |
| 投票后 | DecisionEngine | 投票者自己 | vote |
| 投票结果出来后 | GameController | 所有存活 AI | observation |

### 7.3 反思的容错

- `generate_reflection()` 整体包在 try/except 中
- LLM 调用失败 → 打印日志，返回 None，游戏继续
- JSON 解析失败 → 尝试正则提取，仍失败则跳过
- 信任分数更新时自动 clamp 到 [-1.0, 1.0]
- 反思列表超过 20 条时自动裁剪到最近 15 条

---

## 八、信任网络更新机制

### 8.1 规则更新（每次发言后，不调 LLM）

`update_trust_from_speech()` 在 `_update_trust_from_speech()` 中被调用，对所有存活 AI 执行：

| 条件 | 信任变化 |
|------|---------|
| 发言者在发言中怀疑了我 | -0.15 |
| 发言者在发言中为我辩护 | +0.10 |
| 发言者角色声称前后不一致 | -0.20 |
| 已有人声称预言家，又有人声称 | 后者 -0.10 |
| 发言者被 ≥3 人怀疑 | -0.05 |

### 8.2 LLM 更新（反思时）

反思 JSON 中的 `trust_changes` 字段可以对任意玩家做任意幅度的信任调整，由 LLM 自主判断。例如：
- 查验出狼人 → `{"7": -1.0}`（直接拉满不信任）
- 有人为我辩护且逻辑合理 → `{"2": 0.2}`

---

## 九、情绪系统

情绪影响 agent 的决策风格（通过注入 prompt）：

| 情绪 | 中文 | 对决策的影响 |
|------|------|------------|
| neutral | 平静 | 默认状态 |
| calm | 冷静 | 理性分析 |
| anxious | 焦虑 | 倾向保守，可能犯错 |
| suspicious | 多疑 | 更容易怀疑别人 |
| confident | 自信 | 更果断，敢于跳身份 |
| desperate | 绝望 | 孤注一掷，可能做出极端决策 |

情绪由 LLM 在反思时自主更新，不需要规则干预。

---

## 十、数据流总结图

```
                    ┌──────────────┐
                    │  游戏事件     │
                    │ (发言/投票/   │
                    │  死亡/天亮)   │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │规则更新   │ │规则更新   │ │规则更新   │
        │Agent A   │ │Agent B   │ │Agent C   │
        │的Memory  │ │的Memory  │ │的Memory  │
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │            │            │
             ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │读取Memory│ │读取Memory│ │读取Memory│
        │构建Prompt│ │构建Prompt│ │构建Prompt│
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │            │            │
             ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │LLM 决策  │ │LLM 决策  │ │LLM 决策  │
        └────┬─────┘ └────┬─────┘ └────┬─────┘
             │            │            │
             ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │LLM 反思  │ │LLM 反思  │ │LLM 反思  │
        │写回Memory│ │写回Memory│ │写回Memory│
        │·信任更新 │ │·信任更新 │ │·信任更新 │
        │·情绪更新 │ │·情绪更新 │ │·情绪更新 │
        │·计划更新 │ │·计划更新 │ │·计划更新 │
        └──────────┘ └──────────┘ └──────────┘
```

每个 Agent 的 Memory 是完全独立的，互不可见。Agent 只能通过公开信息（发言、投票、死亡公告）间接了解其他 Agent 的状态，就像真实玩家一样。
