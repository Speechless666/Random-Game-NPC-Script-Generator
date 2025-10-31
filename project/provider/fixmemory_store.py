# runtime/memory_store.py
"""本模块实现一个简单的记忆存储管理器（MemoryStore），包含短期记忆与长期记忆的基础操作。

设计要点与假设：
- 短期记忆使用内存双端队列（deque）作为滑动窗口保存最近若干对话事件。
- 长期记忆使用 CSV 文件持久化（默认路径为 memory_longterm.csv），CSV 表头为
  [player_id, npc_id, fact, emotion]。每一行表示一条公开可检索的记忆事实。
- 该实现以可读性与移植性为主，未处理并发写入、事务或数据库优化；若需生产级别请替换为数据库或持久化服务。
"""

from collections import deque
import csv, os
from typing import List, Optional


class MemoryStore:
    """记忆存储管理类。

    参数：
      - short_window: 短期记忆窗口大小（默认保存最近 short_window 条事件）
      - longterm_path: 长期记忆 CSV 文件路径（相对或绝对路径）
    """

    def __init__(self, short_window=5, longterm_path="memory_longterm.csv"):
        # 短期记忆（队列），用于在会话中缓存最近的若干事件
        self.short_memory = deque(maxlen=short_window)
        # 长期记忆 CSV 文件路径
        self.longterm_path = longterm_path

        # 如果长期记忆文件不存在，创建并写入表头（CSV）
        if not os.path.exists(longterm_path):
            with open(longterm_path, "w", newline='') as f:
                writer = csv.writer(f)
                # header 顺序必须与 read/write 逻辑一致
                writer.writerow(["player_id", "npc_id", "fact", "emotion"])

    def append_event(self, event: dict):
        """将一个交互事件追加到短期记忆队列。

        event 期望为 dict，结构由上层 pipeline 统一（例如 {"speaker": "NPC", "text": ..., "emotion": ...}）。
        该方法仅负责入队，不进行持久化。
        """
        self.short_memory.append(event)

    # 短期记忆接口
    def get_short_window(self, k: Optional[int] = None) -> List[dict]:
        """返回短期记忆的切片。

        - 若 k 提供，返回最近 k 条事件；否则返回整个短期窗口内的事件（按时间升序）。
        """
        return list(self.short_memory)[-k:] if k else list(self.short_memory)

    def retrieve_longterm(self, player_id: str, npc_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """检索长期记忆"""
        try:
            if not self.longterm_file.exists():
                return []
            
            with open(self.longterm_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                # 检查CSV文件是否有正确的列
                if not reader.fieldnames or 'player_id' not in reader.fieldnames:
                    print(f"警告: 长期记忆文件缺少必要的列，字段名: {reader.fieldnames}")
                    return []
                
                # 安全地过滤行，处理可能缺失的字段
                facts = []
                for row in reader:
                    try:
                        # 检查必要的字段是否存在
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
    
    # 长期记忆写入
    def write_longterm(self, player_id: str, npc_id: str, facts: List[dict]):
        """将候选 facts 追加写入长期记忆 CSV。

        facts 应为可迭代对象，每项为 dict，至少包含键 'fact'，可选 'emotion'（默认 'neutral'）。
        该方法以追加模式打开 CSV，因此不会覆盖已有内容。
        """
        with open(self.longterm_path, "a", newline='') as f:
            writer = csv.writer(f)
            for fact in facts:
                # 以防缺失 emotion 字段，使用默认值 'neutral'
                writer.writerow([player_id, npc_id, fact["fact"], fact.get("emotion", "neutral")])

    # 清理低权记忆
    def evict_by_policy(self, policy_fn):
        """根据外部策略函数 policy_fn 清理长期记忆。

        policy_fn 接受一个 memory_record（dict，来自 csv.DictReader）并返回 True 表示该记录应被淘汰。
        本函数的实现流程：读取全部记录 -> 过滤 -> 覆盖写回（包含 header）。
        注意：此操作不是原子性的；在并发场景下可能产生竞态，生产环境请改用数据库事务。
        """
        with open(self.longterm_path, "r", newline='') as f:
            reader = list(csv.DictReader(f))
        retained = [row for row in reader if not policy_fn(row)]
        with open(self.longterm_path, "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["player_id", "npc_id", "fact", "emotion"])
            for row in retained:
                writer.writerow([row["player_id"], row["npc_id"], row["fact"], row["emotion"]])

    def policy_fn(self, memory_record: dict) -> bool:
        """示例策略函数：淘汰情绪为 'neutral' 的记忆。

        这是一个示例/占位实现，用于演示如何向 evict_by_policy 提供策略函数。实际策略可更复杂，
        例如基于时间（age）、重要度评分或任务相关度等。
        """
        return memory_record["emotion"] == "neutral"

    
