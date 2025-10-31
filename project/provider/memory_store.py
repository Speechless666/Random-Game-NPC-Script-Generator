# runtime/memory_store.py
"""本模块实现一个简单的记忆存储管理器（MemoryStore），包含短期记忆与长期记忆的基础操作。

设计要点与假设：
- 短期记忆使用内存双端队列（deque）作为滑动窗口保存最近若干对话事件。
- 长期记忆使用 CSV 文件持久化（默认路径为 memory_longterm.csv），CSV 表头为
  [player_id, npc_id, fact, emotion]。每一行表示一条公开可检索的记忆事实。
- 该实现以可读性与移植性为主，未处理并发写入、事务或数据库优化；若需生产级别请替换为数据库或持久化服务。
"""

from collections import deque
import csv, os, time
from typing import List, Optional, Dict, Any
from pathlib import Path


class MemoryStore:
    """记忆存储管理类。

    参数：
      - short_window: 短期记忆窗口大小（默认保存最近 short_window 条事件）
      - longterm_path: 长期记忆 CSV 文件路径（相对或绝对路径）
    """

    def __init__(self, short_window=5, longterm_path="longterm_memory.csv"):
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
        # 添加NPC名称映射
        self.npc_names = {}
    
    def set_npc_names(self, npc_names: Dict[str, str]):
        """设置NPC名称映射"""
        self.npc_names = npc_names

    def append_event(self, event: Dict[str, Any]):
        """添加短期事件 - 使用实际名称"""
        try:
            if not hasattr(self, 'shortterm_file'):
                self.shortterm_file = Path("shortterm_memory.csv")
                
            # 确保文件存在
            if not self.shortterm_file.exists():
                with open(self.shortterm_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['speaker', 'text', 'emotion', 'timestamp'])
            
            # 获取说话者名称
            speaker = event.get('speaker', '')
            text = event.get('text', '')
            emotion = event.get('emotion', '')
            
            # 将"player"和"NPC"替换为实际名称
            actual_speaker = self._get_actual_speaker_name(speaker, event)
            
            with open(self.shortterm_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    actual_speaker,
                    text,
                    emotion,
                    time.strftime("%Y-%m-%d %H:%M:%S")
                ])
        except Exception as e:
            print(f"添加事件失败: {e}")

    def _get_actual_speaker_name(self, speaker: str, event: Dict[str, Any]) -> str:
        """获取实际的说话者名称"""
        # 如果是NPC，使用NPC名称
        if speaker == "NPC":
            npc_id = event.get('npc_id', '')
            if npc_id and npc_id in self.npc_names:
                return self.npc_names[npc_id]
            return "Unknown NPC"
        
        # 如果是玩家，检查是否是NPC扮演的玩家
        elif speaker == "player":
            player_id = event.get('player_id', '')
            # 如果player_id以"npc_"开头，说明是NPC在扮演玩家
            if player_id and player_id.startswith("npc_"):
                npc_id = player_id[4:]  # 去掉"npc_"前缀
                if npc_id in self.npc_names:
                    return self.npc_names[npc_id]
            return "Player"
        
        return speaker
    
    # ... 其他方法保持不变 ...
    def retrieve_longterm(self, player_id: str, npc_id: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """安全地检索长期记忆"""
        try:
            # 确保 longterm_file 属性存在
            if not hasattr(self, 'longterm_file'):
                self.longterm_file = Path("longterm_memory.csv")
                return []
            
            if not self.longterm_file.exists():
                return []
            
            with open(self.longterm_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                # 检查文件是否有正确的列
                if reader.fieldnames is None:
                    return []
                
                # 检查是否包含必要的列
                if 'player_id' not in reader.fieldnames:
                    print(f"警告: 长期记忆文件缺少player_id列，字段名: {reader.fieldnames}")
                    return []
                
                facts = []
                for row in reader:
                    try:
                        # 安全地访问字段
                        row_player_id = row.get('player_id', '')
                        row_npc_id = row.get('npc_id', '')
                        
                        if row_player_id == player_id and row_npc_id == npc_id:
                            facts.append(row)
                            
                        if len(facts) >= top_k:
                            break
                    except (KeyError, AttributeError) as e:
                        print(f"跳过无效的记忆行: {e}")
                        continue
                
                return facts
                
        except Exception as e:
            print(f"检索长期记忆失败: {e}")
            return []
    
    def get_short_window(self, k: int = 5) -> List[Dict[str, Any]]:
        """获取最近k个事件 - 修复版本"""
        events = []
        try:
            if self.shortterm_file.exists():
                with open(self.shortterm_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    # 取最后k行
                    for row in rows[-k:]:
                        events.append({
                            'speaker': row.get('speaker', ''),
                            'text': row.get('text', ''),
                            'emotion': row.get('emotion', ''),
                            'timestamp': row.get('timestamp', '')
                        })
                print(f"从短期记忆文件读取了 {len(events)} 个事件")
            else:
                print("短期记忆文件不存在")
        except Exception as e:
            print(f"读取短期记忆失败: {e}")
        return events

    def write_longterm(self, player_id: str, npc_id: str, facts: List[str]):
        """安全地写入长期记忆"""
        try:
            # 确保 longterm_file 属性存在
            if not hasattr(self, 'longterm_file'):
                self.longterm_file = Path("longterm_memory.csv")
            
            # 确保文件存在并有正确的header
            if not self.longterm_file.exists():
                with open(self.longterm_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=['player_id', 'npc_id', 'fact', 'timestamp'])
                    writer.writeheader()
            
            with open(self.longterm_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['player_id', 'npc_id', 'fact', 'timestamp'])
                for fact in facts:
                    writer.writerow({
                        'player_id': player_id,
                        'npc_id': npc_id,
                        'fact': fact,
                        'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")  # 使用 time 模块
                    })
                    
        except Exception as e:
            print(f"写入长期记忆失败: {e}")

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

    
