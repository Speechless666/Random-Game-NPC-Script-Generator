# -*- coding: utf-8 -*-
# project/runtime/logger.py
"""
SpanLogger 模块：已修改为将所有日志追加写入到固定文件 'npc-test-suite.jsonl'。
"""
from __future__ import annotations
import json
import time
import uuid
import datetime
import os
import sys
import atexit
from typing import Dict, Any, Optional
from collections import defaultdict

# ❗❗❗ 固定日志文件名 ❗❗❗
FIXED_LOG_FILENAME = "npc-test-suite.jsonl"
PROJECT_ROOT_PATH = "/Users/cheryl/PycharmProjects/DSA4213---Random-Game-NPC-Script-Generator"


# ----------------- 单例模式 -----------------
class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


# ----------------- 核心 Logger 类 -----------------

class SpanLogger(metaclass=Singleton):
    REQUIRED_FIELDS = [
        "raw_text", "ooc_risk", "final_text", "emotion_proposed",
        "emotion_final", "latency_ms", "cache_hit"
    ]

    def __init__(self, log_dir: str = "project/logs"):
        """
        初始化 Logger，将日志追加写入到固定文件。
        """
        # 1. 强制使用硬编码的根目录
        root_dir = PROJECT_ROOT_PATH

        # 2. 最终日志目录路径
        self._log_dir = os.path.join(root_dir, log_dir)

        try:
            os.makedirs(self._log_dir, exist_ok=True)
            print(f"✅ LOGGER DEBUG: Log directory FINAL path set to: {self._log_dir}", file=sys.stderr)
        except OSError as e:
            print(f"❌ LOGGER FATAL ERROR: Cannot create log directory '{self._log_dir}'. Check permissions. Error: {e}",
                  file=sys.stderr)
            self._log_dir = None
            return

            # 3. ❗ 使用固定的日志文件名 ❗
        self._log_filename = FIXED_LOG_FILENAME
        self._log_path = os.path.join(self._log_dir, self._log_filename)

        print(f"✅ LOGGER DEBUG: Log file path set to: {self._log_path}", file=sys.stderr)

        # 4. 初始化文件句柄 (使用 'a' 模式追加写入)
        self._jl: Optional[object] = None
        self._ensure_log_file()

        if self._jl:
            print("✅ LOGGER DEBUG: File handler successfully initialized (Append Mode).", file=sys.stderr)
        else:
            print("❌ LOGGER ERROR: Could not open file handler. Logging disabled.", file=sys.stderr)

        self._current_span: Dict[str, Any] = {}
        self._turn_counter = defaultdict(int)

    def _ensure_log_file(self):
        """确保日志文件句柄已打开，并在退出时自动关闭。"""
        if self._log_path and self._jl is None:
            try:
                abs_path = os.path.abspath(self._log_path)
                # 使用 'a' (append) 模式追加写入
                self._jl = open(abs_path, 'a', encoding='utf-8', buffering=1)

                atexit.register(self.close)
            except Exception as e:
                print(f"❌ LOGGER ERROR: Failed to open log file at {abs_path}. Error: {e}", file=sys.stderr)
                self._jl = None

    def start_span(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """开始一个新的交互回合（Span）。"""
        if self._jl is None:
            print("⚠️ LOGGER WARNING: Logger not initialized. Skipping start_span.", file=sys.stderr)
            return {}

        session_id = ctx.get("session_id", ctx.get("player_id", "default_session"))
        self._turn_counter[session_id] += 1
        turn_id = f"turn-{self._turn_counter[session_id]:06d}"

        span_ctx = {
            "timestamp": datetime.datetime.now().isoformat(timespec='milliseconds') + 'Z',
            "run_id": str(uuid.uuid4()),
            "session_id": session_id,
            "turn_id": turn_id,
            "event": "processing_start",
            "start_time": time.time(),
        }
        span_ctx.update(ctx)

        self._current_span = span_ctx
        return span_ctx

    def end_span(self, span_ctx: Dict[str, Any], payload: Dict[str, Any]):
        """结束当前的交互回合（Span），将完整数据写入日志。"""
        if self._jl is None:
            print("⚠️ LOGGER WARNING: Logger not initialized. Skipping end_span.", file=sys.stderr)
            return

        latency_sec = time.time() - span_ctx.get("start_time", time.time())
        payload["latency_ms"] = latency_sec * 1000

        for field in self.REQUIRED_FIELDS:
            if field not in payload and field not in span_ctx:
                print(f"❌ LOGGER ERROR: Missing required field '{field}' in log payload. Log will be incomplete.",
                      file=sys.stderr)

        final_record = {
            **span_ctx,
            **payload
        }

        final_record.pop("start_time", None)
        final_record["event"] = "postprocess"

        try:
            self._jl.write(json.dumps(final_record, ensure_ascii=False) + '\n')

        except Exception as e:
            print(f"❌ LOGGER ERROR: Failed to write record to file. Error: {e}", file=sys.stderr)

    def close(self):
        """手动关闭日志文件句柄。"""
        if self._jl:
            try:
                self._jl.close()
                print(f"✅ LOGGER DEBUG: Log file handler closed successfully.", file=sys.stderr)
            except Exception as e:
                print(f"❌ LOGGER ERROR: Failed to close log file handler. Error: {e}", file=sys.stderr)
            self._jl = None


LOGGER = SpanLogger()