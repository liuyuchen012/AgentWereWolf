#!/bin/bash
# WolfCha 启动脚本 - 游戏服务 + 公网隧道

cd "$(dirname "$0")"

echo "🐺 AgentWereWolf 启动中..."
echo ""

# 启动游戏服务
python3 main.py &
GAME_PID=$!
echo "✅ 游戏服务已启动 (PID: $GAME_PID)"
echo "   本地访问: http://localhost:8080"
echo ""

# 等服务就绪
sleep 2

# 启动公网隧道
echo "🌐 正在建立公网隧道..."
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=60 -R 80:localhost:8080 serveo.net &
TUNNEL_PID=$!

echo ""
echo "📋 隧道输出中会显示公网地址 (https://xxx.serveousercontent.com)"
echo "   复制该地址分享给朋友即可加入游戏"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号
trap "echo ''; echo '正在停止...'; kill $GAME_PID $TUNNEL_PID 2>/dev/null; exit 0" INT TERM

# 等待
wait
