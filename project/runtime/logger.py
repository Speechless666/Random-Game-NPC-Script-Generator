# -*- coding: utf-8 -*-
# project/runtime/logger.py
"""
SpanLogger module: Modified to be initialized at runtime with config.
"""
# --- MODIFIED: Fixed typo from __init__ to __future__ ---
from __future__ import annotations 
# --- END MODIFICATION ---
import json
import time
import uuid
import datetime
import os
import sys
import atexit
from typing import Dict, Any, Optional
from collections import defaultdict

# (The rest of your logger.py file is unchanged)

# ----------------- Singleton (Unchanged) -----------------
class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


# ----------------- Core Logger Class -----------------

class SpanLogger(metaclass=Singleton):
    REQUIRED_FIELDS = [
        "raw_text", "ooc_risk", "final_text", "emotion_proposed",
        "emotion_final", "latency_ms", "cache_hit"
    ]

    # --- MODIFIED __init__ ---
    def __init__(self):
        """
        Initialization is deferred until initialize() is called with the config.
        """
        self._log_path: Optional[str] = None
        self._jl: Optional[object] = None
        self._current_span: Dict[str, Any] = {}
        self._turn_counter = defaultdict(int)
        print("✅ LOGGER DEBUG: Logger instantiated. Waiting for initialize().", file=sys.stderr)

    # --- NEW METHOD ---
    def initialize(self, config: Dict[str, Any], project_root: Any): # 'Any' for pathlib.Path
        """
        Initializes the logger with paths from the loaded config.
        This MUST be called once at startup (from app.py or test.py).
        """
        if self._jl is not None:
            print("⚠️ LOGGER WARNING: Logger already initialized. Skipping.", file=sys.stderr)
            return

        try:
            # 1. Get log path from config
            # Default to 'logs/runtime.jsonl' if not specified
            log_path_str = config.get('logging', {}).get('path', 'logs/runtime.jsonl')

            # 2. Construct absolute path from the provided project_root
            # (project_root is the 'project/' folder)
            self._log_path = os.path.join(str(project_root), log_path_str)
            log_dir = os.path.dirname(self._log_path)
            
            os.makedirs(log_dir, exist_ok=True)
            print(f"✅ LOGGER DEBUG: Log directory FINAL path set to: {log_dir}", file=sys.stderr)

            # 3. Set log file path
            print(f"✅ LOGGER DEBUG: Log file path set to: {self._log_path}", file=sys.stderr)

            # 4. Initialize file handler
            self._ensure_log_file()
            if self._jl:
                print("✅ LOGGER DEBUG: File handler successfully initialized (Append Mode).", file=sys.stderr)
            else:
                raise IOError("Could not open file handler.")

        except Exception as e:
            print(f"❌ LOGGER FATAL ERROR: Cannot create log directory/file. Check config and permissions. Error: {e}",
                  file=sys.stderr)
            self._log_path = None # Disable logger
            return

    # --- ensure_log_file logic is unchanged, just moved ---
    def _ensure_log_file(self):
        """Ensures the log file handle is open and registers atexit."""
        if self._log_path and self._jl is None:
            try:
                abs_path = os.path.abspath(self._log_path)
                # Use 'a' (append) mode
                self._jl = open(abs_path, 'a', encoding='utf-8', buffering=1)

                atexit.register(self.close)
            except Exception as e:
                print(f"❌ LOGGER ERROR: Failed to open log file at {abs_path}. Error: {e}", file=sys.stderr)
                self._jl = None

    # --- start_span logic is unchanged ---
    def start_span(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Starts a new interaction span."""
        if self._jl is None:
            # Check if initialization was missed
            if self._log_path is None:
                print("❌ LOGGER FATAL: start_span() called before initialize(). Logging is disabled.", file=sys.stderr)
            else:
                print("⚠️ LOGGER WARNING: Logger not initialized (file handle is None). Skipping start_span.", file=sys.stderr)
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

    # --- end_span logic is unchanged ---
    def end_span(self, span_ctx: Dict[str, Any], payload: Dict[str, Any]):
        """Ends the current span and writes the full record."""
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

    # --- close logic is unchanged ---
    def close(self):
        """Manually closes the log file handler."""
        if self._jl:
            try:
                self._jl.close()
                print(f"✅ LOGGER DEBUG: Log file handler closed successfully.", file=sys.stderr)
            except Exception as e:
                print(f"❌ LOGGER ERROR: Failed to close log file handler. Error: {e}", file=sys.stderr)
            self._jl = None


# --- This singleton instance is created (but uninitialized) on import ---
LOGGER = SpanLogger()