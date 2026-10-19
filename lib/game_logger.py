"""游戏日志记录器 - 记录每个 AI agent 的完整决策过程"""

import json
import os
from datetime import datetime
from typing import Any, Dict, Optional


_LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")


class GameLogger:
    """每局游戏的日志记录器，每个 AI 玩家一个 JSONL 文件"""

    def __init__(self):
        self._game_dir: Optional[str] = None
        self._game_id: Optional[str] = None

    def start_game(self, game_id: str, players: list, config_data: Optional[Dict] = None):
        """开局时调用，创建日志目录并写入 game_info.json

        Args:
            game_id: 游戏 ID
            players: Player 对象列表
            config_data: LLM 配置数据
        """
        self._game_id = game_id
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_id = game_id[:6]
        self._game_dir = os.path.join(_LOGS_DIR, f"{ts}_{short_id}")
        os.makedirs(self._game_dir, exist_ok=True)

        # 写入游戏基本信息
        game_info = {
            "game_id": game_id,
            "start_time": datetime.now().isoformat(),
            "players": [
                {
                    "seat": p.seat,
                    "name": p.display_name,
                    "role": p.role,
                    "is_human": p.is_human,
                }
                for p in players
            ],
        }
        if config_data:
            # 脱敏：移除 api_key
            safe_config = {}
            for k, v in config_data.get("players", {}).items():
                if isinstance(v, dict):
                    safe_config[k] = {ck: cv for ck, cv in v.items() if ck != "api_key"}
                else:
                    safe_config[k] = v
            game_info["llm_config"] = safe_config

        info_path = os.path.join(self._game_dir, "game_info.json")
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(game_info, f, ensure_ascii=False, indent=2)

    def log_decision(
        self,
        seat: int,
        player_name: str,
        action_type: str,
        day: int = 0,
        phase: str = "",
        model: str = "",
        system_msg: str = "",
        user_msg: str = "",
        raw_response: str = "",
        parsed_result: Any = None,
        final_decision: Any = None,
        extra: Optional[Dict] = None,
    ):
        """记录一次 agent 决策

        Args:
            seat: 座位号
            player_name: 玩家名
            action_type: 决策类型 (guard/wolf/witch/seer/speech/vote/last_words/hunter/night_discussion/personality)
            day: 第几天
            phase: 阶段
            model: 模型名
            system_msg: 系统提示词
            user_msg: 用户提示词
            raw_response: LLM 原始返回文本
            parsed_result: 解析后的结果
            final_decision: 最终决策
            extra: 额外信息
        """
        if not self._game_dir:
            return

        record = {
            "timestamp": datetime.now().isoformat(),
            "action_type": action_type,
            "day": day,
            "phase": phase,
            "model": model,
            "system_msg": system_msg,
            "user_msg": user_msg,
            "raw_response": raw_response,
            "parsed_result": parsed_result,
            "final_decision": final_decision,
        }
        if extra:
            record["extra"] = extra

        filename = f"seat_{seat}_{player_name}.jsonl"
        filepath = os.path.join(self._game_dir, filename)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
