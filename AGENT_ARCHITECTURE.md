# AI Agent 架构文档

## 项目概览

py_wolfcha 是一个基于 FastAPI + WebSocket 的 AI 狼人杀游戏。支持多人类玩家 + 多 AI 玩家混合对局，AI 玩家通过 LLM 驱动决策，具备独立的记忆、反思、信任评估和策略系统。

---

## 整体架构

```
main.py (FastAPI + WebSocket 服务)
  └── GameController (游戏流程控制器)
        ├── DecisionEngine (决策引擎)
        │     ├── InformationManager (信息过滤)
        │     ├── MemorySystem (记忆系统)
        │     └── StrategyLibrary (策略库)
        ├── agent_memories: Dict[player_id, AgentMemory] (每个AI的记忆实例)
        └── PhaseManager (阶段管理器)
```

---

## 核心模块

### 1. `agent/memory.py` — 记忆系统

#### 数据结构

| 类 | 用途 |
|---|---|
| `PlayerMemory` | 对单个玩家的认知：声称角色、阵营推测、发言次数、投票历史、怀疑/辩护关系 |
| `NightActionRecord` | 夜间行动记录（守护/击杀/毒杀/救人/查验） |
| `DeathRecord` | 死亡记录（天数、座位、死因、声称角色） |
| `Reflection` | LLM 生成的结构化反思（天数、阶段、行动类型、内容、更新的信念） |
| `AgentMemory` | 单个 Agent 的完整记忆容器，包含以上所有 + 信任网络 + 情绪状态 + 当前计划 |

#### AgentMemory 关键字段

```python
player_memories: Dict[int, PlayerMemory]  # 对每个玩家的认知
night_actions: List[NightActionRecord]     # 自己的夜间行动日志
deaths: List[DeathRecord]                  # 死亡事件记录
wolf_suspects: List[int]                   # 狼人嫌疑列表
confirmed_good: List[int]                  # 确认好人列表
key_insights: List[str]                    # 关键事件描述（全部保留，不裁剪）
reflections: List[Reflection]              # 反思记录（超过20条裁剪到15条）
trust_scores: Dict[int, float]            # 信任网络（-1.0 到 1.0）
emotional_state: str                       # 情绪状态（calm/anxious/suspicious/confident/desperate）
current_plan: Optional[str]                # 当前策略计划
role_specific: Dict[str, Any]             # 角色专属记忆（查验结果、上次保护、药水使用等）
```

#### MemorySystem 方法分类

**规则驱动（不调 LLM）：**
- `update_from_speech()` — 从发言提取关键词、角色声称、怀疑/辩护关系
- `update_from_vote()` — 记录投票行为
- `update_from_vote_result()` — 记录投票结果到 key_insights
- `update_from_night_announcement()` — 记录天亮公告（谁死了/平安夜）
- `update_from_hunter_shoot()` — 记录猎人开枪
- `update_from_death()` — 更新死亡状态，从嫌疑列表移除死者
- `update_night_action()` — 记录自己的夜间行动，更新角色专属记忆
- `record_own_speech()` / `record_own_vote()` — 记录自己的发言和投票
- `update_trust_from_speech()` — 基于规则的轻量信任更新（被怀疑→降信任，被辩护→升信任，角色声称不一致→降信任）

**LLM 驱动：**
- `generate_reflection()` — 行动后调用 LLM 生成内心独白式反思，同时更新信任分数、情绪状态、当前计划

#### 记忆生命周期

```
init_agent_memory()  →  游戏开始时创建，初始化所有玩家认知 + 信任分数
                        狼人额外知道队友身份（confidence=1.0, trust=1.0）
     ↓
每个事件  →  通过 MemorySystem 的 update_* 方法持续更新
     ↓
format_memory_for_prompt()  →  决策时序列化为文本注入 prompt
```

#### 记忆保留策略

- **key_insights**：全部保留，不裁剪
- **reflections**：超过 20 条裁剪到最近 15 条
- **其他字段**（player_memories、night_actions、deaths、trust_scores 等）：全部累积，不清理
- **format_memory_for_prompt** 输出时：key_insights 全部展示，reflections 只展示最近 3 条

---

### 2. `agent/decision.py` — 决策引擎

DecisionEngine 是所有 AI 决策的入口，负责构建 prompt、调用 LLM、解析结果、触发反思。

#### 决策类型

| 方法 | 阶段 | 输出 | 反思触发 |
|---|---|---|---|
| `generate_guard_decision()` | 夜晚 | 保护目标座位 | ✅ |
| `generate_wolf_decision()` | 夜晚 | 击杀目标座位 | ✅ |
| `generate_witch_decision()` | 夜晚 | save/poison/pass | ✅ |
| `generate_seer_decision()` | 夜晚 | 查验目标座位 | ❌（结果出来后在 controller 中触发） |
| `generate_speech()` | 白天 | 发言文本 | ✅ |
| `generate_vote()` | 白天 | 投票目标座位 | ✅ |
| `generate_last_words()` | 白天 | 遗言文本 | ❌ |
| `generate_hunter_decision()` | 白天 | 射击目标座位 | ❌ |
| `generate_night_discussion_speech()` | 夜晚 | 狼人讨论发言 | ✅（第2轮起或达成共识时） |
| `generate_personality()` | 初始化 | 性格描述文本 | ❌ |

#### Prompt 构建模式

每个决策方法的 prompt 结构：

```
System Message:
  - 角色身份 + 座位号
  - 性格描述（LLM 生成的个性化文本）
  - 角色专属策略和约束
  - 说话风格要求（拟人化、禁止总结式表达）

User Message:
  - 当前天数 + 阶段
  - format_memory_for_prompt() 输出的完整记忆
  - 今日发言记录（build_today_transcript）
  - 可选目标列表
  - 思考引导问题
  - 输出格式要求（JSON 或纯文本）
```

#### 容错机制

- JSON 解析失败时尝试正则提取 `{...}` 或纯数字
- 座位号兼容 0-indexed 和 1-indexed
- 所有决策方法都有 fallback（随机选择），确保游戏不会卡住

#### 性格系统

游戏开始时为每个 AI 玩家调用 `generate_personality()` 生成独特性格描述（说话风格、口头禅、性格底色、情绪触发点、游戏风格），缓存在 `_personality_cache` 中，后续所有 prompt 都会注入。

---

### 3. `agent/information.py` — 信息管理器

负责按角色过滤可见信息，实现信息不对称：

- **消息可见性**：通过 `visibility_type` 和 `visible_to_roles` 机制控制
  - `public` — 所有人可见
  - `seer_only` / `witch_only` / `guard_only` / `wolf_only` — 角色专属
  - `night_discussion` — 按 visible_to_roles 列表判断
- **角色专属信息** (`get_role_specific_info`)：
  - 狼人 → 队友列表
  - 预言家 → 查验历史
  - 女巫 → 解药/毒药状态 + 今晚被杀目标
  - 守卫 → 上次保护目标
  - 猎人 → 是否可以开枪

---

### 4. `agent/strategy.py` — 策略库

从 `roles/*.json` 加载角色策略，按难度分级：

- `basic`（priority=10）— easy/normal 可用
- `advanced`（priority=15）— normal 可用
- `expert`（priority=20）— hard 可用

每个角色最多注入 4 条策略到 prompt。

---

### 5. `game_controller.py` — 游戏流程控制器

GameController 是整个游戏的中枢，协调游戏流程并驱动 Agent 系统。

#### 游戏循环

```
start_game()
  ├── setup_players()          # 分配角色
  ├── _init_agent_memories()   # 初始化所有 AI 记忆
  ├── _init_agent_personalities()  # LLM 生成性格
  └── game_loop()
        └── 循环:
              ├── _run_night_phase()
              │     ├── _night_discussion_phase()  # 狼人讨论（纯AI / 人机混合）
              │     ├── _guard_action()
              │     ├── _wolf_action()
              │     ├── _witch_action()
              │     ├── _seer_action()
              │     └── _resolve_night()           # 结算 + 天亮公告
              ├── check_win_condition()
              ├── _run_day_phase()
              │     ├── _speech_phase()            # 依次发言
              │     └── _vote_phase()              # 投票 + 平票PK
              │           ├── _do_vote_round()
              │           ├── _last_words_phase()  # 遗言
              │           └── _hunter_shoot()      # 猎人开枪
              └── check_win_condition()
```

#### 记忆更新时机

| 事件 | 更新方法 | 更新范围 |
|---|---|---|
| 玩家发言 | `update_from_speech` + `update_trust_from_speech` | 所有 AI |
| 狼人夜间讨论 | `update_from_speech`（wolf only） | 仅狼人 AI |
| 投票 | `update_from_vote` | 所有 AI |
| 死亡 | `update_from_death`（按角色区分死因信息） | 所有 AI |
| 夜间行动 | `update_night_action` | 行动者自己 |
| 天亮公告 | `update_from_night_announcement` + LLM 反思 | 所有 AI |
| 投票结果 | `update_from_vote_result` + LLM 反思 | 所有 AI |
| 预言家查验 | `update_night_action` + LLM 反思 | 预言家自己 |

#### 死因信息不对称

夜晚结算时，不同角色获得不同的死因信息：
- **狼人**：知道自己杀了谁，其他死亡标记为 `night_death`
- **女巫**：知道自己毒了谁、被狼杀的是谁
- **守卫**：只知道有人死了（`night_death`）
- **其他**：只知道有人死了（`night_death`）

---

### 6. `llms_config/` — LLM 配置系统

支持每个座位独立配置不同的 LLM 模型和参数：

```json
{
  "default": "qwen-plus",
  "players": {
    "seat_0": {"is_human": true},
    "seat_1": "deepseek-v3.2",
    "seat_2": {"config": "qwen-plus", "temperature": 0.9}
  }
}
```

- 每个模型一个独立 JSON 配置文件（model、provider、api_base、api_key、temperature、max_tokens）
- `.env` 中的 `DEEPSEEK_API_KEY` / `DEEPSEEK_API_BASE` 作为默认值
- 人类座位标记为 `is_human`，跳过 LLM 配置

---

### 7. `lib/game_logger.py` — 决策日志

每局游戏创建独立目录（`logs/YYYYMMDD_HHMMSS_gameId/`），每个 AI 玩家一个 JSONL 文件，记录：
- 完整的 system_msg 和 user_msg（prompt）
- LLM 原始返回
- 解析结果和最终决策
- 时间戳、天数、阶段、模型名

---

### 8. 前端通信

- FastAPI + WebSocket，每个玩家一个连接
- 房间制：创建房间 → 选座 → 房主开始游戏
- 事件推送按角色过滤（私密事件只推给对应角色，观战者看不到）
- 人类玩家操作通过 `submit_human_action()` 提交，内部用 `asyncio.Future` 等待
- 所有人类操作都有超时机制，超时后自动处理（不操作/随机/默认行为）

---

## 数据流总结

```
游戏事件发生
  → GameController 调用 MemorySystem.update_*() 更新所有相关 AI 的记忆（规则驱动）
  → GameController 调用 _trigger_observation_reflections() 触发 LLM 反思（异步，失败不阻塞）
  → 轮到 AI 行动时：
      → DecisionEngine 调用 MemorySystem.format_memory_for_prompt() 序列化记忆
      → 构建 prompt（角色身份 + 性格 + 策略 + 记忆 + 今日发言 + 引导问题）
      → 调用 LLM 获取决策
      → 解析结果 + fallback
      → 触发行动后反思
      → 返回决策结果
```

---

## 关键设计决策

1. **记忆全量累积**：key_insights 和结构化数据（投票、死亡、查验等）全部保留，只有反思会裁剪，确保 AI 不会"遗忘"早期关键事件
2. **双层信任更新**：轻量规则（每次发言后立即更新）+ LLM 反思（关键事件后深度更新），平衡性能和质量
3. **信息不对称**：严格按角色过滤可见信息和死因信息，模拟真实游戏的信息差
4. **性格系统**：每局随机生成独特性格，注入所有 prompt，让同一模型的不同 AI 表现出差异化风格
5. **拟人化约束**：prompt 中大量约束禁止 AI 写分析报告式发言，要求使用语气词、犹豫、情绪表达
6. **容错优先**：所有决策都有 fallback，LLM 调用失败或解析失败不会导致游戏卡死
