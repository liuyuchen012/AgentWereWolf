"""一次性冒烟测试：验证 LLM 配置解析 + 各决策接口端到端可用。"""
import asyncio
import sys

from game_controller import GameController
from lib.game_master import setup_players


async def main():
    c = GameController()
    # 8 人全 AI 局，验证纯 AI 多人模式
    players = setup_players(player_count=8, human_seat=0, human_name="测试", human_seats={})
    c.state.players = players
    c.state.day = 1
    c._init_agent_memories()

    print(f"[1/5] 生成 {len(players)} 名 AI 玩家性格...")
    await c._init_agent_personalities()

    p = players[1]  # 任意一个 AI
    mem = c._get_agent_memory(p)
    print(f"[2/5] 测试发言生成 ({p.display_name} / {p.role})...")
    speech = await c.decision_engine.generate_speech(p, c.state, mem)
    print("      发言:", (speech or "")[:150])

    print("[3/5] 测试投票生成...")
    t = await c.decision_engine.generate_vote(p, c.state, mem)
    print("      投票目标座位:", t)

    wolf = next((x for x in players if x.role == "Werewolf"), None)
    if wolf:
        wm = c._get_agent_memory(wolf)
        print(f"[4/5] 测试狼人击杀决策 ({wolf.display_name})...")
        wt = await c.decision_engine.generate_wolf_decision(wolf, c.state, wm, {})
        print("      狼人目标座位:", wt)

    seer = next((x for x in players if x.role == "Seer"), None)
    if seer:
        sm = c._get_agent_memory(seer)
        print(f"[5/5] 测试预言家查验决策 ({seer.display_name})...")
        st = await c.decision_engine.generate_seer_decision(seer, c.state, sm)
        print("      预言家查验座位:", st)

    print("\nSMOKE TEST PASSED — LLM 集成正常")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
