# provider/memory_summarizer.py
"""记忆摘要器：从最近对话中抽取候选事实..."""

from typing import List, Dict, Any, Optional
import os

# --- 修复：使用绝对路径从 runtime 导入 ---
try:
    # 因为 test.py/app.py 会把 project/ 加入 sys.path
    from runtime import validators
except ImportError as e:
    print(f"CRITICAL: 无法从 'runtime' 导入 'validators'。{e}")
    print("请确保 'project/runtime/validators.py' 文件存在。")
    raise e
# --- 结束修复 ---

# OOC 风险阈值...
OOC_RISK_THRESHOLD = 0.5


class MemorySummarizer:
    """记忆摘要器类。"""

    def __init__(self, provider, ooc_checker=None):
        self.provider = provider
        self.ooc_checker = ooc_checker

    def summarize(self, num_memory, recent_dialogue: List[Dict[str, Any]], slot: Optional[str] = None) -> List[Dict[str, Any]]:
        """从最近对话中抽取 n 条候选事实..."""
        if not recent_dialogue:
            return []

        formatted_lines: List[str] = []
        for item in recent_dialogue:
            if isinstance(item, str):
                formatted_lines.append(item.strip())
            elif isinstance(item, dict):
                speaker = item.get("speaker", "").strip()
                text_part = item.get("text", "").strip()
                if speaker:
                    formatted_lines.append(f"{speaker}: {text_part}")
                else:
                    formatted_lines.append(text_part)
            else:
                try:
                    formatted_lines.append(str(item))
                except Exception:
                    continue

        context_text = "\n".join(formatted_lines)
        
        prompt = f"""
        From the following dialogue, extract strictly {num_memory} persistent facts about NPC(NPC's id) or player(player's id) relations.
        Output a JSON list; each item must contain: fact, emotion, slot.
        Dialogue: {context_text}
        """

        try:
            raw = self.provider.generate(prompt, schema=["fact", "emotion", "slot"])
        except Exception:
            return []

        candidates = []
        if isinstance(raw, list):
            candidates = raw
        elif isinstance(raw, dict):
            candidates = [raw]
        else:
            try:
                import json, re
                text_raw = str(raw)
                m = re.search(r"(\[.*\])", text_raw, re.S) or re.search(r"(\{.*\})", text_raw, re.S)
                if m:
                    parsed = json.loads(m.group(1))
                    if isinstance(parsed, list):
                        candidates = parsed
                    elif isinstance(parsed, dict):
                        candidates = [parsed]
                else:
                    return []
            except Exception:
                return []

        accepted: List[Dict[str, Any]] = []

        for c in candidates:
            fact_text = (c.get("fact", "") if isinstance(c, dict) else str(c)).strip()
            emotion = (c.get("emotion", "neutral") if isinstance(c, dict) else "neutral")
            cslot = c.get("slot", slot) if isinstance(c, dict) else slot
            
            if not fact_text:
                continue

            candidate = {"fact": fact_text, "emotion": emotion, "slot": cslot}

            if cslot == "past_story":
                try:
                    # (现在这个导入可以正常工作了)
                    if not validators.passes_all_checks(candidate):
                        continue
                except Exception:
                    continue

                if self.ooc_checker is not None:
                    try:
                        res = self.ooc_checker.judge_ooc(context_text, candidate)
                    except Exception:
                        continue
                    
                    ooc_risk = res.get("ooc_risk", 0) if isinstance(res, dict) else 0
                    if ooc_risk and ooc_risk > OOC_RISK_THRESHOLD:
                        continue

                    if isinstance(res, dict) and "emotion" in res:
                        candidate["emotion"] = res.get("emotion", candidate["emotion"])

            accepted.append(candidate)
            
        return accepted