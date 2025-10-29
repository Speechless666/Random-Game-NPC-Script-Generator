# main.py
from typing import List, Dict, Any, Optional
import os

# 尝试以包的绝对路径导入 validators（当项目作为包运行时更稳定）
try:
    import project.runtime.validators as validators
    from provider.qwen import QwenProvider
    from runtime.generator import Generator
    from runtime.oocChecker import OOCChecker
    from runtime.memory_store import MemoryStore
    from runtime.memory_summarizer import MemorySummarizer
except Exception:
    # 回退到相对导入或本地 import，便于在不同执行上下文下运行
    try:
        from . import validators, QwenProvider, Generator, OOCChecker, MemoryStore, MemorySummarizer
    except Exception:
        import validators
        from qwen import QwenProvider
        from generator import Generator
        from oocChecker import OOCChecker
        from memory_store import MemoryStore
        from memory_summarizer import MemorySummarizer

api_key = "Ysk-043c5acb5a5b4e59988256474c37a9be"
provider = QwenProvider(api_key)
gen = Generator(provider)
ooc = OOCChecker(provider)
mem = MemoryStore()
summ = MemorySummarizer(provider)

persona = "Elira, a cheerful tavern keeper who knows the town’s secrets."
context = "Player enters the tavern and asks for rumors."

# 生成候选
candidates = gen.generate_candidates(ctx=context, persona=persona, n=2)

# 重排选优
best = gen.rank(candidates, persona, context)

# OOC检测
checked = ooc.judge_ooc(context, best)

# 写入记忆
mem.append_event({"speaker": "NPC", "text": checked["reply"], "emotion": checked["emotion"]})

# 摘要记忆
facts = summ.summarize(mem.get_short_window())
mem.write_longterm("player1", "npc_elira", facts)

print("NPC:", checked["reply"], "| Emotion:", checked["emotion"])
