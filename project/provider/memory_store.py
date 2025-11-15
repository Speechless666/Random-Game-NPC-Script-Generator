# provider/memory_store.py
"""
This module implements a simple memory storage manager (MemoryStore).
(MODIFIED: Reads all paths and limits from config)
"""

from collections import deque
import csv, os
from typing import List, Optional, Dict, Any 
import datetime
from pathlib import Path # <-- ADDED

class MemoryStore:
    """Memory storage management class."""

    # --- MODIFIED: __init__ now accepts config and project_root ---
    def __init__(self, config: dict, project_root: Path):
        self.config = config
        
        # 1. Get short_window size from config
        memory_policy = config.get('memory_policy', {})
        short_window_k = memory_policy.get('short_window_k', 8)
        self.short_memory = deque(maxlen=short_window_k)
        
        # 2. Construct longterm_path from config
        data_files = config.get('data_files', {})
        longterm_path_str = data_files.get('memory_longterm', 'data/memory_longterm.csv')
        # (Builds path like .../project/data/memory_longterm.csv)
        self.longterm_path = str(project_root / longterm_path_str) 
        
        print(f"[MemoryStore] Initialized. Short-term window: {short_window_k}, Long-term path: {self.longterm_path}")

        # 3. Create file if it doesn't exist (Logic Unchanged)
        if not os.path.exists(self.longterm_path):
            try:
                # Ensure directory exists
                os.makedirs(os.path.dirname(self.longterm_path), exist_ok=True)
                with open(self.longterm_path, "w", newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["player_id", "npc_id", "fact", "emotion", "timestamp"])
            except Exception as e:
                print(f"FATAL [MemoryStore] Could not create log file at {self.longterm_path}: {e}")
    # --- END MODIFICATION ---

    def append_event(self, event: dict):
        """Appends an interaction event to the short-term memory queue."""
        self.short_memory.append(event)

    def get_short_window(self, k: Optional[int] = None) -> List[dict]:
        """Returns a slice of short-term memory."""
        # --- MODIFIED: Read 'k' from config if not provided ---
        if k is None:
            # Reads from memory_policy.short_window_k
            k = self.config.get('memory_policy', {}).get('short_window_k', 8)
        # --- END MODIFICATION ---
        return list(self.short_memory)[-k:]

    # --- MODIFIED: retrieve_longterm now reads top_k from config ---
    def retrieve_longterm(self, player_id: str, npc_id: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieves long-term memories"""
        
        if top_k is None:
            # (You should add 'retrieval_top_k: 5' to your config.yaml 'memory_policy')
            top_k = self.config.get('memory_policy', {}).get('retrieval_top_k', 5)
            
        try:
            if not os.path.exists(self.longterm_path):
                return []
            
            with open(self.longterm_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                if not reader.fieldnames or 'player_id' not in reader.fieldnames:
                    print(f"Warning: Long-term memory file is missing required columns. Fields: {reader.fieldnames}")
                    return []
                
                facts = []
                for row in reader:
                    try:
                        if (row.get("player_id") == player_id and 
                            row.get("npc_id") == npc_id):
                            facts.append(row)
                    except KeyError as e:
                        print(f"Warning: Skipping invalid row in memory file, missing field: {e}")
                        continue
                    
                    if len(facts) >= top_k:
                        break
                
                return facts
                
        except Exception as e:
            print(f"Failed to retrieve long-term memory: {e}")
            return []
    # --- END MODIFICATION ---
    
    def write_longterm(self, player_id: str, npc_id: str, facts: List[dict], timestamp: Optional[str] = None):
        """Appends candidate facts to the long-term memory CSV."""
        # (Logic Unchanged)
        with open(self.longterm_path, "a", newline='') as f:
            writer = csv.writer(f)
            for fact in facts:
                if isinstance(fact, dict):
                    writer.writerow([
                        player_id, 
                        npc_id, 
                        fact.get("fact", "MISSING_FACT"), 
                        fact.get("emotion", "neutral"),
                        timestamp or datetime.datetime.now()
                    ])

    def evict_by_policy(self, policy_fn):
        """Evicts long-term memories based on an external policy function."""
        # (Logic Unchanged)
        with open(self.longterm_path, "r", newline='') as f:
            reader = list(csv.DictReader(f))
        retained = [row for row in reader if not policy_fn(row)]
        with open(self.longterm_path, "w", newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["player_id", "npc_id", "fact", "emotion", "timestamp"])
            for row in retained:
                writer.writerow([row["player_id"], row["npc_id"], row["fact"], row["emotion"], row["timestamp"]])

    def policy_fn(self, memory_record: dict) -> bool:
        """Example policy: evict 'neutral' emotions."""
        # (Logic Unchanged)
        return memory_record["emotion"] == "neutral"