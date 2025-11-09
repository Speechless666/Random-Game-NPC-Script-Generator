import numpy as np
from typing import Dict, List, Any, Optional
import json
import re
import random  # <-- 新增导入

class Generator:
    """封装候选生成与后验对齐的生成器。"""

    def __init__(self, provider):
        """构造函数：接收实现 generate(prompt, schema=...) 的 provider 实例。"""
        self.provider = provider

    def safe_json_parse(self, text: str) -> Optional[Any]:
        """安全地解析 LLM 输出为 JSON。"""
        if not text:
            return None

        # 去除常见的 Markdown 块标记，例如 ```json ... ``` 或 ``` ... ```
        cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

        # 直接解析尝试
        try:
            return json.loads(cleaned)
        except Exception:
            pass

        # 尝试从文本中抽取 JSON 子串（列表优先）
        try:
            m = re.search(r"(\[.*\])", cleaned, re.S)
            if not m:
                m = re.search(r"(\{.*\})", cleaned, re.S)
            if m:
                candidate = m.group(1)
                try:
                    return json.loads(candidate)
                except Exception:
                    # 如果抽取到的子串仍无法解析，则继续回退
                    pass
        except Exception:
            pass

        # 无法解析，返回 None
        return None

    def generate_candidates(self, ctx: str, persona: str, n: int = 2, evidence: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """生成候选草稿并封装为 draft 结构。"""
        
        # --- 修改：构建证据字符串，并随机选择1-2条 ---
        evidence_str = "No specific evidence provided."
        if evidence:
            # --- 新增：随机选择最多2条证据 ---
            max_evidence_to_use = 2
            if len(evidence) > max_evidence_to_use:
                selected_evidence = random.sample(evidence, max_evidence_to_use)
            else:
                selected_evidence = evidence
            # --- 结束新增 ---

            facts = []
            # 使用 selected_evidence 而不是 evidence
            for i, item in enumerate(selected_evidence):
                fact = item.get('fact', '')
                entity = item.get('entity', '')
                if entity:
                    facts.append(f"{i+1}. {entity}: {fact}")
                else:
                    facts.append(f"{i+1}. {fact}")
            evidence_str = "\n".join(facts)
        # --- 结束修改 ---

        # --- 修改：调整 Prompt，增加世界观安全规则 ---
        prompt = f"""
        You are an NPC. Persona: {persona}.
        DIALOGUE CONTEXT (This is the conversation so far):
        ---
        {ctx}
        ---

        RULES:
        1. **Worldview Safety**: You are an NPC in a specific world (e.g., fantasy, medieval). You MUST NOT recognize or discuss real-world brands (e.g., Apple, Google), modern technology (e.g., smartphones, the internet), or real-world events *unless* they are explicitly part of your persona.
        2. **Refusal**: If the context asks about something outside your worldview, your reply must show confusion or lack of knowledge, consistent with your persona. (e.g., "What is this... 'internet'... you speak of?")

        BACKGROUND FACTS (FOR INSPIRATION):
        ---
        {evidence_str}
        ---
        
        Use these facts as inspiration for your reply. 
        DO NOT just repeat the facts verbatim. 
        Weave them naturally into your persona-driven response. If no facts are provided, answer based on your persona and rules.

        Please generate {n} candidate replies in JSON list format, each with fields:
        [
        {{
            "reply": "NPC's natural and emotional response (1-3 sentences)",
            "emotion": "happy/sad/neutral/angry"
        }}
        ]
        Only return valid JSON.
        """
        # --- 结束修改 ---
        
        # 调用 provider 生成候选
        raw_output = None
        try:
            raw_output = self.provider.generate(prompt, schema=["reply", "emotion"])
        except Exception as e:
            print(f"[WARN] provider.generate raised: {e}; will try a lightweight fallback.")
            # 回退提示（尽量简单）
            try:
                raw_output = self.provider.generate(f'Generate {n} replies in JSON with keys reply and emotion for: {ctx}', schema=["reply", "emotion"])
            except Exception as e2:
                print(f"[ERROR] fallback provider.generate also failed: {e2}")
                raw_output = None

        # 解析 provider 返回：支持 dict/list/str
        raw_candidates = None
        if isinstance(raw_output, (list, dict)):
            raw_candidates = raw_output
        elif isinstance(raw_output, str):
            raw_candidates = self.safe_json_parse(raw_output)
        else:
            # 有些 provider 返回自定义对象（已在外层打印为字符串）
            try:
                raw_str = str(raw_output)
                raw_candidates = self.safe_json_parse(raw_str)
            except Exception:
                raw_candidates = None

        # 最后一道防护：若仍无法得到候选，使用单条中性回退
        if raw_candidates is None:
            print("[ERROR] Failed to parse provider output into JSON. Using fallback reply.")
            raw_candidates = [{"reply": "I'm sorry, I didn't quite catch that.", "emotion": "neutral"}]

        # 保证 raw_candidates 为 list
        if isinstance(raw_candidates, dict):
            raw_candidates = [raw_candidates]

        wrapped: List[Dict[str, Any]] = []

        for rc in raw_candidates:
            # 兼容 rc 为 dict 或原始字符串
            if isinstance(rc, dict):
                draft_text = rc.get("reply", "").strip()
                draft_emotion = rc.get("emotion", "neutral")
            else:
                draft_text = str(rc).strip()
                draft_emotion = "neutral"

            # ========== 删除 self_report 部分 ==========
            # 直接构建候选，不再请求 self_report
            
            wrapped.append({
                "draft": {
                    "text": draft_text,
                    "meta": {
                        # 不再包含 self_report 字段
                        "sentiment": draft_emotion,  # 直接使用候选的 emotion
                    },
                }
            })

        return wrapped

    def _persona_score(self, text, persona):
        """简单的角色匹配评分：persona 中词汇在文本中命中的比例。"""
        words = persona.split()
        if not words:
            return 0.0
        return sum(word in text for word in words) / len(words)

    def _emotion_consistency(self, emotion, ctx):
        """情绪一致性：若情绪词出现在上下文中则得分高些。"""
        return 1.0 if emotion and emotion.lower() in (ctx or "").lower() else 0.5

    def _length_penalty(self, text):
        """长度惩罚：偏离 25 词惩罚更高（启发式）。"""
        return abs(len((text or "").split()) - 25) / 25.0

    def rank(self, candidates: List[Dict[str, Any]], persona: str, ctx: str) -> Dict[str, Any]:
        """使用启发式打分选出最佳候选（返回整个候选条目）。"""
        def score(c):
            text = c.get("draft", {}).get("text", "")
            sentiment = c.get("draft", {}).get("meta", {}).get("sentiment", "neutral")
            return (
                0.5 * self._persona_score(text, persona)
                + 0.3 * self._emotion_consistency(sentiment, ctx)
                - 0.2 * self._length_penalty(text)
            )

        ranked = sorted(candidates, key=score, reverse=True)
        return ranked[0] if ranked else {"draft": {"text": "", "meta": {"sentiment": "neutral"}}}

    def align_with_post_infer(self, candidate: Dict, current_emotion: str, target_emotion: str) -> Dict:
        """
        将候选回复的情绪从 current_emotion 对齐到 target_emotion
        """
        # 如果情绪相同，不需要重写
        if current_emotion == target_emotion:
            return {
                "final": candidate,
                "audit": {"rewritten": False, "reason": "emotions_identical"}
            }
    
        # 获取原始文本
        original_text = candidate.get('draft', {}).get('text', '')
        if not original_text:
            return {
              "final": candidate,
                "audit": {"rewritten": False, "reason": "no_text"}
            }
    
        # 构建重写提示
        rewrite_prompt = self._build_rewrite_prompt(original_text, current_emotion, target_emotion)
    
        try:
            # 调用API进行重写
            rewritten_text = self.provider.generate(rewrite_prompt)
        
            # 检查重写是否成功
            if rewritten_text and rewritten_text != original_text:
                # 创建重写后的候选
                final_candidate = candidate.copy()
                final_candidate['final'] = {
                    'text': rewritten_text,
                    'emotion': target_emotion,
                    'meta': candidate.get('draft', {}).get('meta', {})
                }
            
                return {
                    "final": final_candidate,
                    "audit": {"rewritten": True, "reason": "emotion_aligned"}
                }
            else:
                # 重写失败，返回原始候选
                return {
                    "final": candidate,
                    "audit": {"rewritten": False, "reason": "rewrite_failed"}
                }
            
        except Exception as e:
            # 重写过程中出现错误
            return {
                "final": candidate,
                "audit": {"rewritten": False, "reason": f"error: {str(e)}"}
            }

    def _build_rewrite_prompt(self, text: str, current_emotion: str, target_emotion: str) -> str:
        """构建情绪重写提示"""
        emotion_descriptions = {
            "neutral": "neutral, matter-of-fact tone",
            "friendly": "friendly, warm tone", 
            "cheerful": "cheerful, upbeat tone",
            "serious": "serious, concerned tone",
            "annoyed": "annoyed, irritated tone",
            "sad": "sad, melancholic tone"
        }
        
        current_desc = emotion_descriptions.get(current_emotion, "neutral tone")
        target_desc = emotion_descriptions.get(target_emotion, "neutral tone")
        
        prompt = f"""
        Rewrite the following text from a {current_desc} to a {target_desc}. 
        Keep the core meaning and facts the same, but adjust the emotional tone.
        
        Original text: "{text}"
        
        Rewritten text:
        """
        
        return prompt.strip()

    def refusal_response(self, deny: Dict[str, Any], persona: str, tone_guidelines: Optional[str] = None) -> Dict[str, str]:
        """根据 deny.reason 生成英文的角色内拒答。"""
        reason = deny.get("reason", "unknown_entity")
        details = deny.get("details")

        if reason == "taboo":
            reply = (
                f"I can't talk about that subject. It makes me uncomfortable to get into it. "
                f"If you'd like, we could talk about local gossip, recent market news, or an old legend instead."
            )
            emotion = "firm"
        elif reason == "secret":
            alt = "I can share what is commonly known in town: the weather, who owns the inn, or general rumors."
            reply = (
                f"I'm sorry, I can't share that. I don't have anything I can responsibly say on that matter. "
                f"{alt}"
            )
            emotion = "guarded"
        elif reason == "unknown_entity":
            name_hint = f" about '{details}'" if details else ""
            reply = (
                f"I don't recognize{name_hint}. I can't speak for someone or something I haven't heard of. "
                f"If you mean someone from around here, try giving me more context—otherwise we can talk about familiar faces or trades."
            )
            emotion = "curious"
        else:
            reply = "I can't help with that request."
            emotion = "neutral"

        if tone_guidelines:
            if "cheer" in tone_guidelines.lower() or "friendly" in tone_guidelines.lower():
                reply = f"Oh, I wish I could help — but {reply[0].lower() + reply[1:]}"
            elif "gruff" in tone_guidelines.lower() or "stoic" in tone_guidelines.lower():
                reply = f"I won't say. {reply}"

        return {"reply": reply, "emotion": emotion}