# runtime/memory_store.py
"""
本模块实现一个简单的记忆存储管理器（MemoryStore）。
(基于 fixmemory_store.py 的简洁设计)
"""

from collections import deque
import csv, os
from typing import List, Optional, Dict, Any # <-- 导入 Dict, Any
import datetime

class MemoryStore:
    """记忆存储管理类。"""

    def __init__(self, short_window=5, longterm_path="data/memory_longterm.csv"):
        self.short_memory = deque(maxlen=short_window)
        self.longterm_path = longterm_path

        if not os.path.exists(longterm_path):
            with open(longterm_path, "w", newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["player_id", "npc_id", "fact", "emotion", "timestamp"])

    def append_event(self, event: dict):
        """将一个交互事件追加到短期记忆队列。"""
        self.short_memory.append(event)

    def get_short_window(self, k: Optional[int] = None) -> List[dict]:
        """返回短期记忆的切片。"""
        return list(self.short_memory)[-k:] if k else list(self.short_memory)

    def retrieve_longterm(self, player_id: str, npc_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """检索长期记忆"""
        try:
            if not os.path.exists(self.longterm_path): # <-- 修复：使用 self.longterm_path
                return []
            
            with open(self.longterm_path, 'r', encoding='utf-8') as f: # <-- 修复：使用 self.longterm_path
                reader = csv.DictReader(f)
                
                if not reader.fieldnames or 'player_id' not in reader.fieldnames:
                    print(f"警告: 长期记忆文件缺少必要的列，字段名: {reader.fieldnames}")
                    return []
                
                facts = []
                for row in reader:
                    try:
                        if (row.get("player_id") == player_id and 
                            row.get("npc_id") == npc_id):
                            facts.append(row)
                    except KeyError as e:
                        print(f"警告: 跳过记忆文件中的无效行，缺失字段: {e}")
                        continue
                    
                    if len(facts) >= top_k:
                        break
                
                return facts
                
        except Exception as e:
            print(f"检索长期记忆失败: {e}")
            return []
    
    def write_longterm(self, player_id: str, npc_id: str, facts: List[dict], timestamp: Optional[str] = None):
        """将候选 facts 追加写入长期记忆 CSV。"""
        with open(self.longterm_path, "a", newline='') as f:
            writer = csv.writer(f)
            for fact in facts:
                # 确保只写入合规的字典
                if isinstance(fact, dict):
                    writer.writerow([
                        player_id, 
                        npc_id, 
                        fact.get("fact", "MISSING_FACT"), 
                        fact.get("emotion", "neutral"),
                        timestamp or datetime.datetime.now()
                    ])

    # ... (evict_by_policy 和 policy_fn 保持不变) ...
    def evict_by_policy(self, policy_fn):
        """根据外部策略函数 policy_fn 清理长期记忆。"""
        with open(self.longterm_path, "r", newline='') as f:
            reader = list(csv.DictReader(f))
        retained = [row for row in reader if not policy_fn(row)]
        with open(self.longterm_path, "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["player_id", "npc_id", "fact", "emotion", "timestamp"])
            for row in retained:
                writer.writerow([row["player_id"], row["npc_id"], row["fact"], row["emotion"], row["timestamp"]])

    def policy_fn(self, memory_record: dict) -> bool:
        """示例策略函数：淘汰情绪为 'neutral' 的记忆。"""
        return memory_record["emotion"] == "neutral"