# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path

# 路径常量（保持原有约定）
ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = ROOT
DATA_DIR = ROOT.parent / "data"
CACHE_DIR = RUNTIME_DIR / ".cache"
CACHE_FILE = CACHE_DIR / "compiled.json"

# 数据文件（保持原有命名/位置）
NPC_CSV = DATA_DIR / "npc.csv"
LORE_CSV = DATA_DIR / "lore.csv"
SLOTS_YAML = DATA_DIR / "slots.yaml"
EMOTION_YAML = DATA_DIR / "emotion_schema.yaml"

# 运行期设置：仅补全，保证 controller/test 可导入使用
class SETTINGS:
    # 生产/严格模式（若 True 则要求 CACHE_FILE 必存在）
    PRODUCTION: bool = False
    STRICT_COMPILED: bool = False
    # 是否允许在未编译数据时使用开发 DEMO（控制器可用）
    ALLOW_DEMO: bool = True
