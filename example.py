"""示例：如何使用 AgentWereWolf 游戏引擎"""

import asyncio
from lib.game_master import (
    create_initial_game_state,
    setup_players,
    transition_phase,
    add_system_message,
)
from game.core.phase_manager import PhaseManager
from game.core.types import GameContext


async def main():
    """运行一个简单的游戏示例"""
    print("=== AgentWereWolf 狼人杀游戏引擎示例 ===\n")

    # 1. 创建初始游戏状态
    print("1. 创建游戏...")
    state = create_initial_game_state()
    state.difficulty = "normal"
    print(f"   游戏ID: {state.game_id}")

    # 2. 设置玩家
    print("\n2. 设置玩家...")
    players = setup_players(
        player_count=10,
        human_seat=0,
        human_name="人类玩家"
    )
    state.players = players

    print(f"   总玩家数: {len(players)}")
    print("   玩家列表:")
    for player in players:
        player_type = "人类" if player.is_human else "AI"
        print(f"     {player.seat + 1}号 {player.display_name} - {player.role} ({player_type})")

    # 3. 开始游戏
    print("\n3. 开始游戏...")
    state = transition_phase(state, "NIGHT_START")
    state.day = 1
    print(f"   当前阶段: {state.phase}")
    print(f"   当前天数: {state.day}")

    # 4. 进入守卫阶段
    print("\n4. 夜晚 - 守卫行动...")
    state = transition_phase(state, "NIGHT_GUARD_ACTION")

    # 找到守卫玩家
    guard = next((p for p in state.players if p.role == "Guard"), None)
    if guard:
        print(f"   守卫是: {guard.seat + 1}号 {guard.display_name}")

        # 获取守卫的提示词
        phase_manager = PhaseManager()
        context = GameContext(state=state)
        prompt = phase_manager.get_prompt("NIGHT_GUARD_ACTION", context, guard)

        if prompt:
            print("\n   守卫提示词示例:")
            print(f"   System: {prompt.system[:200]}...")
            print(f"   User: {prompt.user[:200]}...")
    else:
        print("   本局没有守卫")

    # 5. 狼人阶段
    print("\n5. 夜晚 - 狼人行动...")
    state = transition_phase(state, "NIGHT_WOLF_ACTION")

    wolves = [p for p in state.players if p.role == "Werewolf"]
    print(f"   狼人数量: {len(wolves)}")
    for wolf in wolves:
        print(f"     {wolf.seat + 1}号 {wolf.display_name}")

    # 获取狼人的提示词
    if wolves:
        phase_manager = PhaseManager()
        context = GameContext(state=state, extras={"existing_votes": {}})
        prompt = phase_manager.get_prompt("NIGHT_WOLF_ACTION", context, wolves[0])

        if prompt:
            print("\n   狼人提示词示例:")
            print(f"   System: {prompt.system[:200]}...")

    # 6. 检查其他特殊角色
    print("\n6. 其他角色信息:")
    seer = next((p for p in state.players if p.role == "Seer"), None)
    if seer:
        print(f"   预言家: {seer.seat + 1}号 {seer.display_name}")

    witch = next((p for p in state.players if p.role == "Witch"), None)
    if witch:
        print(f"   女巫: {witch.seat + 1}号 {witch.display_name}")

    hunter = next((p for p in state.players if p.role == "Hunter"), None)
    if hunter:
        print(f"   猎人: {hunter.seat + 1}号 {hunter.display_name}")

    print("\n=== 示例完成 ===")
    print("\n说明:")
    print("- 这只是一个简单示例，展示了如何创建游戏和访问游戏状态")
    print("- 完整的游戏流程需要实现游戏控制器来协调各个阶段")
    print("- AI玩家的决策需要调用LLM API（lib/llm.py）")
    print("- 可以基于此构建Web API或命令行界面")


if __name__ == "__main__":
    asyncio.run(main())
