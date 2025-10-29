# runtime/generator.py
import numpy as np
from typing import Dict, List, Any, Optional
import json
import re
    
class Generator:
    """封装候选生成与后验对齐的生成器。

    新的 draft/输出 结构（依据阶段3规范）：
      - draft.text: 模型生成的英文草稿文本
      - draft.meta.self_report: 模型自述的简短短语/关键词（例如："cheerful"、"tired"）
      - draft.meta.sentiment: 模型自评情感标签（positive/negative/neutral）

    在接收到外部或后验推断情感（post_infer_emotion）后，生成器会将其与 draft.meta.sentiment 比较。
    若不一致，则对草稿进行重写（保持事实内容不变，仅调整语气/情绪），并返回带审核信息的最终结构：
      - final.text
      - final.emotion（等于目标情绪 target_emotion）
      - final.audit {rewritten: bool, reason: str}
    """

    def __init__(self, provider):
        """使用实现了 generate(prompt, schema=...) 的 provider 初始化。

        provider.generate 在提供 schema 时应能返回结构化 JSON，否则返回纯文本。
        本模块保持接口简单，便于适配不同的 provider 实现。
        """
        self.provider = provider

    def safe_json_parse(self, text: str):
        """安全地解析 LLM 输出为 JSON 对象，自动清理 ```json 包裹."""
        if not text:
            return None
        try:
            # 清理 Markdown 包裹
            text = re.sub(r"^```json", "", text.strip(), flags=re.IGNORECASE)
            text = re.sub(r"```$", "", text.strip())
            text = text.strip()
            # 尝试解析为 JSON
            return json.loads(text)
        except Exception as e:
            print(f"[safe_json_parse] JSON parse failed: {e}\nRaw text:\n{text[:300]}...")
        return None
    
    def generate_candidates(self, ctx: str, persona: str, n: int = 2) -> List[Dict[str, Any]]:
        """生成候选草稿。

        对底层 provider 返回的每个候选，封装成所需的 draft 结构，并尝试获取短的自述和自评情感标签。
        当前实现对每个候选会调用 provider 两次：
          1) 主回复生成（reply + emotion）
          2) 一个简短的自述提示，要求模型输出 self_report 与 sentiment

        注意：每个候选调用两次 provider 会增加成本；若受限可从初始回复启发式推断 self_report/sentiment。
        """
        prompt = f"""
        You are an NPC. Persona: {persona}.
        Context: {ctx}.
        Please generate {n} candidate replies in JSON list format, each with fields:
        [
          {{
            "reply": "NPC's natural and emotional response (1-3 sentences)",
            "emotion": "happy/sad/neutral/angry"
          }}
        ]
        Only return valid JSON.
        """

        # 调用 provider
        raw_output = self.provider.generate(prompt, schema=["reply", "emotion"], retries=n)
        print("Raw provider output for candidates:", raw_output)
        if not raw_output:
            print("[WARN] provider returned None, retrying with relaxed prompt...")
            retry_prompt = f"Generate one fallback reply in JSON with fields reply/emotion for: {ctx}"
            raw_output = self.provider.generate(retry_prompt, schema=["reply", "emotion"])

        # 尝试解析
        raw_candidates = None
        if isinstance(raw_output, str):
            raw_candidates = self.safe_json_parse(raw_output)
        elif isinstance(raw_output, (list, dict)):
            raw_candidates = raw_output

        if raw_candidates is None:
            print("[ERROR] Failed to parse provider output into JSON. Using fallback reply.")
            raw_candidates = [{"reply": "I'm sorry, I didn’t quite catch that.", "emotion": "neutral"}]

        # 保证是 list
        if isinstance(raw_candidates, dict):
            raw_candidates = [raw_candidates]

        wrapped: List[Dict[str, Any]] = []

        for rc in raw_candidates:
            draft_text = rc.get("reply") if isinstance(rc, dict) else str(rc)
            draft_emotion = rc.get("emotion", "neutral") if isinstance(rc, dict) else "neutral"

            # 简短自述阶段
            sr_prompt = f"""
            In one short phrase, describe how you (the NPC) feel after saying: "{draft_text}"
            Return JSON: {{"self_report": "...", "sentiment": "positive/negative/neutral"}}
            """
            sr = self.provider.generate(sr_prompt, schema=["self_report", "sentiment"]) or {}

            # 防御式处理
            if isinstance(sr, str):
                sr = self.safe_json_parse(sr) or {}
            if isinstance(sr, list) and sr:
                sr = sr[0]
            if not isinstance(sr, dict):
                sr = {"self_report": "seems fine", "sentiment": draft_emotion}

            wrapped.append({
                "draft": {
                    "text": draft_text,
                    "meta": {
                        "self_report": sr.get("self_report", ""),
                        "sentiment": sr.get("sentiment", draft_emotion),
                    },
                }
            })

        return wrapped

    def _persona_score(self, text, persona):
        """简单的角色匹配评分辅助函数（保留原实现）。

        计算 persona 中出现的词在文本中的命中比例，作为匹配度得分。
        """
        words = persona.split()
        if not words:
            return 0.0
        return sum(word in text for word in words) / len(words)

    def _emotion_consistency(self, emotion, ctx):
        """简单的情绪一致性检查（保留原实现）。

        如果情绪标签出现在上下文中则返回较高分。
        """
        return 1.0 if emotion.lower() in ctx.lower() else 0.5

    def _length_penalty(self, text):
        """长度惩罚：与先前启发式类似（理想长度约25词）。"""
        return abs(len(text.split()) - 25) / 25.0

    def rank(self, candidates: List[Dict[str, Any]], persona: str, ctx: str) -> Dict[str, Any]:
        """对封装后的候选进行排序并返回最高的一项。

        每个候选预期为封装格式：{'draft': {'text', 'meta':{...}}}。
        本方法提取文本并使用前述启发式评分进行排序。
        """
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

    def align_with_post_infer(self, draft_envelope: Dict[str, Any], post_infer_emotion: str, target_emotion: Optional[str] = None) -> Dict[str, Any]:
        """将草稿自评情感与后验推断情感比较，并在需要时重写语气。

        输入：
          - draft_envelope: { 'draft': { 'text': str, 'meta': { 'sentiment': str, 'self_report': str } } }
          - post_infer_emotion: 外部从内容中推断出的情感标签
          - target_emotion: 可选的目标情感标签；若未提供则使用 post_infer_emotion 作为目标

        行为：
          - 如果 draft.meta.sentiment 与 post_infer_emotion 不一致（忽略大小写），
            则通过 provider 请求一次重写，提示为：
              "保持事实与内容不变，仅将语气/情绪调整为 {target_emotion}."
            （为确保模型按指令返回，仍以英文提示给 provider。）
          - 返回 final 结构，包含 final.text、final.emotion、final.audit。
        """
        draft = draft_envelope.get("draft", {})
        text = draft.get("text", "")
        draft_sent = (draft.get("meta", {}).get("sentiment") or "neutral").lower()
        post_infer_emotion_norm = (post_infer_emotion or "neutral").lower()
        t_emotion = (target_emotion or post_infer_emotion_norm).lower()

        audit = {"rewritten": False, "reason": None}

        # Determine inconsistency: simple inequality of normalized labels
        if draft_sent != post_infer_emotion_norm:
            # 需要重写：指示模型保持事实/内容不变，仅调整语气
            rewrite_prompt = (
                f"Please rewrite the following English text to keep facts and content unchanged, "
                f"but adjust only the tone/emotion to '{t_emotion}'. Keep the same meaning and details, "
                f"do not add or remove facts. Original: '{text}'\nReturn only the rewritten text."
            )

            try:
                # Ask provider to rewrite; expect either a plain string or JSON with 'text'
                rewritten = self.provider.generate(rewrite_prompt)
            except Exception:
                rewritten = None

            # 将 provider 返回的重写结果规范化为纯文本
            final_text = None
            if isinstance(rewritten, dict):
                final_text = rewritten.get("text") or rewritten.get("reply")
            elif isinstance(rewritten, list) and rewritten:
                # take first element if list
                first = rewritten[0]
                final_text = first.get("text") if isinstance(first, dict) else str(first)
            elif isinstance(rewritten, str):
                final_text = rewritten

            # 若 provider 失败或未返回有效文本，则回退为原始文本
            if not final_text:
                final_text = text

            audit["rewritten"] = True
            audit["reason"] = f"sentiment_mismatch: draft={draft_sent}, post_infer={post_infer_emotion_norm}"
            final_emotion = t_emotion
        else:
            # 无需重写
            final_text = text
            final_emotion = draft_sent

        # 按照规范打包最终结果
        final = {
            "final": {
                "text": final_text,
                "emotion": final_emotion,
                "audit": audit,
            }
        }

        return final

    def refusal_response(self, deny: Dict[str, Any], persona: str, tone_guidelines: Optional[str] = None) -> Dict[str, str]:
        """根据 deny.reason 生成英文的角色内拒答。

        deny: {"reason": <str>, "details": <可选的触发细节>}。
        返回：{"reply": <文本>, "emotion": <标签>}。

        - taboo: 立场化拒绝并给出话题引导（可提供安全的替代方向）
        - secret: 谨慎模糊的拒答，避免承认机密存在；提供公开可用的信息替代
        - unknown_entity: 表示不认识/不能谈论该实体，避免引入新实体

        输出必须为英文且尽量与 persona/tone_guidelines 保持一致。
        """
        reason = deny.get("reason", "unknown_entity")
        details = deny.get("details")

        # 默认情绪为 neutral；可根据具体风格调整
        if reason == "taboo":
            # Firm but in-character refusal and pivot suggestions
            reply = (
                f"I can't talk about that subject. It makes me uncomfortable to get into it. "
                f"If you'd like, we could talk about local gossip, recent market news, or an old legend instead."
            )
            emotion = "firm"

        elif reason == "secret":
            # Avoid admitting secret existence. Provide public alternatives or general info.
            alt = "I can share what is commonly known in town: the weather, who owns the inn, or general rumors."
            reply = (
                f"I'm sorry, I can't share that. I don't have anything I can responsibly say on that matter. "
                f"{alt}"
            )
            emotion = "guarded"

        elif reason == "unknown_entity":
            # Do not invent — state lack of knowledge and offer to continue on adjacent topics
            name_hint = f" about '{details}'" if details else ""
            reply = (
                f"I don't recognize{name_hint}. I can't speak for someone or something I haven't heard of. "
                f"If you mean someone from around here, try giving me more context—otherwise we can talk about familiar faces or trades."
            )
            emotion = "curious"

        else:
            reply = "I can't help with that request."
            emotion = "neutral"

        # 若提供了 tone_guidelines，则尝试进行轻度对齐：
        # - 若语气友好/开朗，则在回复前加上温和的短语
        # - 若语气粗犷/冷峻，则保持简短直接
        if tone_guidelines:
            if "cheer" in tone_guidelines.lower() or "friendly" in tone_guidelines.lower():
                reply = f"Oh, I wish I could help — but {reply[0].lower() + reply[1:]}"
            elif "gruff" in tone_guidelines.lower() or "stoic" in tone_guidelines.lower():
                reply = f"I won't say. {reply}"

        return {"reply": reply, "emotion": emotion}
