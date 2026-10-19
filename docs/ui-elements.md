# WolfCha 前端 UI 元素统计

## 一、页面/屏幕（5个）

| 屏幕 | ID | 说明 |
|------|-----|------|
| 欢迎界面 | `welcome-screen` | 创建房间入口，选择人数/难度/名字 |
| 房间大厅 | `lobby-screen` | 座位选择、房间链接分享、等待开始 |
| 角色展示 | `role-reveal-screen` | 展示分配到的角色，狼人显示队友 |
| 游戏主界面 | `game-screen` | 核心游戏界面：玩家列表+对话区+操作面板 |
| 游戏结束 | `game-end-screen` | 显示胜负、所有玩家角色揭示 |

## 二、全局覆盖层（2个）

| 元素 | ID | 说明 |
|------|-----|------|
| 加载遮罩 | `loading-overlay` | 半透明黑底 + 旋转 spinner + "AI思考中..." |
| 日夜过渡 | `day-night-overlay` | 全屏黑底 + 过渡文字（"夜幕降临"/"天亮了"），2s 淡入淡出动画 |

## 三、欢迎界面元素

| 元素 | 类型 | 说明 |
|------|------|------|
| 标题 | h1 `🐺 WolfCha` | 金色渐变文字 |
| 副标题 | h2 `AI 狼人杀游戏` | |
| 玩家人数选择 | select `#player-count` | 8/9/10/11/12人局 |
| 难度选择 | select `#difficulty` | 简单/普通/困难 |
| 名字输入 | input `#human-name` | 默认"玩家" |
| 创建房间按钮 | button `#create-room-btn` | 金色主按钮 |
| 角色说明卡片 | `.roles-grid` | 6个角色卡片（预言家/女巫/猎人/守卫/村民/狼人），3列网格，好人蓝色左边框，狼人红色左边框 |

## 四、房间大厅元素

| 元素 | 类型 | 说明 |
|------|------|------|
| 房间链接 | input `#room-link` + 复制按钮 | 分享给朋友的 URL |
| 局信息标签 | 3个 badge | X人局 / 难度 / 已入座人数 |
| 座位网格 | `.seats-grid` | 动态生成，每个座位是 `.seat-card`，显示座位号/图标/玩家名/房主标记 |
| 座位卡片状态 | CSS class | `occupied`(已入座蓝边框) / `mine`(自己绿边框) / `owner-seat`(房主金色阴影) |
| 名字输入 | input `#lobby-name-input` | 入座前显示 |
| 开始游戏按钮 | button `#start-game-btn` | 仅房主可见 |
| 等待提示 | div `#lobby-wait-msg` | 非房主显示"等待房主开始游戏..." |

## 五、角色展示界面元素

| 元素 | 类型 | 说明 |
|------|------|------|
| 角色图标 | div `#reveal-role-icon` | 大号 emoji（👤🐺👁️🧪🔫🛡️） |
| 角色名称 | div `#reveal-role-name` | 金色文字，狼人为红色 |
| 角色卡片 | div `#role-card` | 圆角卡片，狼人有红色阴影 |
| 队友信息 | div `#teammates-info` | 仅狼人显示，红色背景，列出队友 badge |
| 确认按钮 | button `#continue-btn` | "确认，开始游戏" |

## 六、游戏主界面元素

### 顶部信息栏 `.top-bar`

| 元素 | 说明 |
|------|------|
| `#day-display` | 天数标签（金色圆角 badge） |
| `#phase-display` | 阶段标签（夜晚深色/白天橙色） |
| `#alive-count` | 存活人数（绿色 badge） |
| `#my-role-display` | 我的身份（金色文字） |

### 左右玩家列表 `.players-left` / `.players-right`

| 元素 | 说明 |
|------|------|
| `.player-card` | 玩家卡片：头像 + 名字 + 座位号 + 存活状态 |
| `.player-card.speaking` | 正在发言：金色边框 + 脉冲动画 |
| `.player-card.dead` | 已死亡：40%透明度 + 灰度滤镜 |
| `.player-card.is-human` | 人类玩家：蓝色边框 |
| `.player-card.selectable` | 可选择：hover 时高亮+右移 |
| `.player-card.selected` | 已选中：绿色边框 |

### 中间对话区 `.dialog-area`

| 元素 | 说明 |
|------|------|
| `.messages-container` | 消息滚动容器 |
| `.message.system` | 系统消息：居中圆角标签 |
| `.message.system.important` | 重要系统消息：金色背景黑字 |
| `.message.system.death` | 死亡消息：红色背景白字 |
| `.message.speech` | 发言消息：深色卡片，含头像+名字+内容 |
| `.message.speech.wolf` | 狼人发言：红色左边框（仅狼人可见） |
| `.message.speech.last-words` | 遗言：红色左边框 + 红色半透明背景 |

### 操作面板 `#action-panel`

| 元素 | 说明 |
|------|------|
| `#action-prompt` | 操作提示文字（金色） |
| `.countdown` | 倒计时显示（红色加粗） |
| `#action-options` | 操作按钮容器（flex wrap） |
| `.action-btn` | 普通操作按钮（深色底+边框） |
| `.action-btn.danger` | 危险操作按钮（红色边框，用于毒药/狼人击杀） |
| `.action-btn.selected` | 已选中按钮（绿色） |
| `#speech-input` | 发言输入框（textarea） |
| `#submit-speech-btn` | 发送按钮 |

### 狼人投票浮条 `#wolf-vote-bar`

动态插入的操作面板，红色边框，与讨论面板并存。选择后显示"✓ 已选择目标"后 2s 消失。

## 七、游戏结束界面元素

| 元素 | 说明 |
|------|------|
| `#winner-text` | 胜利文字（好人蓝色/狼人红色） |
| `.final-players-list` | 玩家网格，每人一张卡片 |
| `.final-player-card` | 显示名字+角色+存活状态，狼人红边框/好人蓝边框 |
| `#restart-btn` | "再来一局"按钮 |

## 八、操作面板的 8 种模式

| action_type | 提示文字 | 交互方式 |
|-------------|---------|---------|
| `guard` | "请选择要保护的玩家" | 玩家按钮 + "不保护任何人" |
| `wolf` | "狼人请选择要击杀的玩家" | 玩家按钮 + 队友投票信息 |
| `witch` | "女巫请选择行动" | 救人按钮 + 毒药目标列表 + "不使用药水" |
| `seer` | "预言家请选择要查验的玩家" | 玩家按钮 |
| `wolf_chat` | "狼人讨论：请发言" | 文本输入框 + 发送按钮 |
| `speech` | "请发表你的观点" | 文本输入框 + 发送按钮 |
| `last_words` | "请发表遗言" | 文本输入框 + 发送按钮 |
| `vote` | "请投票选出要处决的玩家" | 玩家按钮（含自己） |
| `hunter` | "猎人请选择要带走的玩家" | 玩家按钮 |

## 九、WebSocket 消息类型（前端处理）

| 消息类型 | 说明 |
|---------|------|
| `connected` | 连接成功，返回房间状态 |
| `room_update` | 房间状态更新（座位变化等） |
| `join_result` | 入座/换座结果 |
| `game_start` | 游戏开始，返回玩家列表 |
| `role_reveal` | 角色分配通知 |
| `phase_change` | 阶段切换（夜晚/白天/投票等） |
| `system` | 系统消息（带 visibility_type 过滤） |
| `speech` | 玩家发言（带 visibility 过滤） |
| `speaker_change` | 当前发言者变更（触发高亮动画） |
| `action` | 行动结果通知（查验/用药/保护等） |
| `vote` | 单次投票通知 |
| `vote_result` | 投票结果汇总 |
| `death` | 死亡事件 |
| `wait_human` | 等待人类操作（弹出操作面板） |
| `game_end` | 游戏结束 |
| `back_to_room` | 返回房间大厅 |
| `ping` | 心跳 |
| `error` | 错误提示 |

## 十、视觉设计体系

- **配色**：深蓝黑底（`#1a1a2e`）、金色强调（`#e6b422`）、好人蓝（`#2980b9`）、狼人红（`#c0392b`）、绿色确认（`#2ecc71`）
- **字体**：Microsoft YaHei / PingFang SC
- **动画**：
  - `fadeIn` — 角色展示卡片出现
  - `pulse` — 正在发言的玩家卡片脉冲
  - `spin` — 加载 spinner 旋转
  - `fadeInOut` — 日夜过渡 2s
  - `slideIn` — 消息出现上滑
- **响应式**：768px 以下玩家列表改为横向滚动，角色网格改为 2 列
