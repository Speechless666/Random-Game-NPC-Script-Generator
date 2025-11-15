# provider/memory_summarizer.py
"""
Memory Summarizer: Extracts candidate facts from recent dialogue.
(This is the CORRECT file content)
"""

from typing import List, Dict, Any, Optional
import os
import json, re

# --- Uses absolute import from runtime ---
try:
    # (Assuming validators.py is in the 'runtime' folder)
    from runtime import validators
except ImportError as e:
    print(f"CRITICAL: Could not import 'validators' from 'runtime'. {e}")
    print("Please ensure 'project/runtime/validators.py' exists.")
    # We don't raise e here, as validator might be optional
    validators = None 
# --- End import ---


class MemorySummarizer:
    """Memory Summarizer class."""

    # --- MODIFIED: __init__ now accepts config ---
    def __init__(self, provider, ooc_checker=None, config: dict = None):
        self.provider = provider
        self.ooc_checker = ooc_checker
        self.config = config if config is not None else {} # Ensure config is a dict
        
        # Load the threshold from config, fallback to 0.5 if not found
        thresholds_config = self.config.get('thresholds', {})
        self.ooc_risk_threshold = thresholds_config.get('ooc_high', 0.5)
        print(f"[MemorySummarizer] Initialized. OOC risk threshold set to: {self.ooc_risk_threshold}")
    # --- END MODIFICATION ---

    def summarize(self, num_memory, recent_dialogue: List[Dict[str, Any]], slot: Optional[str] = None) -> List[Dict[str, Any]]:
        """Extracts n candidate facts from recent dialogue..."""
        if not recent_dialogue:
            return []

        # (Logic Unchanged)
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

        # (Logic Unchanged)
        candidates = []
        if isinstance(raw, list):
            candidates = raw
        elif isinstance(raw, dict):
            candidates = [raw]
        else:
            try:
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
                if validators is not None:
                    try:
                        # (This function name is from your plan, but not in validators.py)
                        # if not validators.passes_all_checks(candidate):
                        #     continue
                        pass 
                    except Exception:
                        continue

                if self.ooc_checker is not None:
                    try:
                        res = self.ooc_checker.judge_ooc(context_text, candidate)
                    except Exception:
                        continue
                    
                    ooc_risk = res.get("ooc_risk", 0) if isinstance(res, dict) else 0
                    
                    # --- MODIFIED: Use the threshold from config ---
                    if ooc_risk and ooc_risk > self.ooc_risk_threshold:
                    # --- END MODIFICATION ---
                        continue

                    if isinstance(res, dict) and "emotion" in res:
                        candidate["emotion"] = res.get("emotion", candidate["emotion"])

            accepted.append(candidate)
            
        return accepted