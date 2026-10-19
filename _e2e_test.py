"""端到端 WebSocket 测试：创建一个纯 AI 房间并跑通游戏流程。"""
import asyncio
import json
import httpx
import websockets


async def main():
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "http://127.0.0.1:8081/api/create_room",
            json={"player_count": 8, "difficulty": "normal"},
            timeout=20,
        )
        print("create_room status:", r.status_code, "body:", r.text[:200])
        r.raise_for_status()
        room = r.json()
    room_id = room["room_id"]
    owner = room["owner_id"]
    print(f"ROOM {room_id} owner={owner[:8]}...")

    uri = f"ws://127.0.0.1:8081/ws/{room_id}/{owner}"
    seen = []
    speech_count = 0
    vote_count = 0

    async with websockets.connect(uri, open_timeout=20) as ws:
        first = json.loads(await ws.recv())
        print("first:", first.get("type"))

        await ws.send(json.dumps({"type": "start_game"}))

        async def drain():
            nonlocal speech_count, vote_count
            deadline = asyncio.get_event_loop().time() + 150
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    print("HARD TIMEOUT reached")
                    return
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    print("recv timeout")
                    return
                m = json.loads(raw)
                t = m.get("type")
                d = m.get("data") or {}
                seen.append(t)
                if t == "phase_change":
                    print(f"  [phase] {d.get('phase')} day={d.get('day')}")
                elif t == "game_start":
                    print(f"  [game_start] {len(d.get('players', []))} players")
                elif t == "speech":
                    speech_count += 1
                    print(f"  [speech#{speech_count}] {d.get('seat')}号 {d.get('name')}: {(d.get('content') or '')[:50]}")
                elif t == "vote":
                    vote_count += 1
                    print(f"  [vote] {d.get('voter_seat')}号 -> {d.get('target_seat')}号")
                elif t == "death":
                    print(f"  [death] seats={d.get('seats')} msg={(d.get('message') or '')[:40]}")
                elif t == "vote_result":
                    print(f"  [vote_result] eliminated={d.get('eliminated_seat')} detail={(d.get('vote_detail') or '')[:80]}")
                    print("REACHED DAY-1 VOTE RESULT — flow OK")
                    return
                elif t == "game_end":
                    print(f"  [game_end] winner={d.get('winner')} ({d.get('winner_text')})")
                    return
                elif t == "error":
                    print(f"  [error] {d.get('message')}")
                    return

        await drain()

    print(f"\nTOTAL events={len(seen)} speech={speech_count} vote={vote_count}")
    print("E2E TEST DONE")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
