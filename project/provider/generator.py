import numpy as np
from typing import Dict, List, Any, Optional
import json
import re

class Generator:
    """封装候选生成与后验对齐的生成器。

    输出/草稿结构（阶段3规范）：
      - draft.text: 模型生成的英文草稿文本
      - draft.meta.self_report: 模型自述的简短短语/关键词（例如："cheerful"）
      - draft.meta.sentiment: 模型自评情感标签（positive/negative/neutral）

    对齐行为：
      - 接收 post_infer_emotion，与 draft.meta.sentiment 比较；
      - 若不一致，调用 provider 重写文本（仅调整语气/情绪，不改变事实），输出 final 包含 audit 信息。
    """

    def __init__(self, provider):
        """构造函数：接收实现 generate(prompt, schema=...) 的 provider 实例。"""
        self.provider = provider

    def safe_json_parse(self, text: str) -> Optional[Any]:
        """安全地解析 LLM 输出为 JSON。

        功能与容错策略（从严格到宽松）：
        1) 处理空值 -> 返回 None
        2) 去除常见的 Markdown ```json ``` 包裹
        3) 直接尝试 json.loads
        4) 若直接解析失败，使用正则提取最外层 JSON 子串（优先 [] 再 {}），再解析
        5) 若仍解析失败，返回 None（调用方负责回退）
        """
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

    def generate_candidates(self, ctx: str, persona: str, n: int = 2) -> List[Dict[str, Any]]:
        """生成候选草稿并封装为 draft 结构。

        实现说明：
          - 调用 provider.generate(prompt, schema=["reply","emotion"]) 期望结构化输出；
          - 兼容 provider 返回字符串（需要解析为 JSON）或直接返回 list/dict 对象；
          - 为每条候选再调用 provider 生成 self_report & sentiment（若 provider 返回失败则有回退策略）。
        返回值示例：
          [
            {
              "draft": {"text": "...", "meta": {"self_report":"...", "sentiment":"positive"}}
            },
            ...
          ]
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

            # 请求短自述（self_report）与情感标签：防御式处理 provider 输出
            sr_prompt = f"""
            In one short phrase, describe how you (the NPC) feel after saying: "{draft_text}"
            Return JSON: {{"self_report": "...", "sentiment": "positive/negative/neutral"}}
            """

            sr_raw = None
            try:
                sr_raw = self.provider.generate(sr_prompt, schema=["self_report", "sentiment"])
            except Exception as e:
                # 记录警告但不要中断整个流程
                print(f"[WARN] self_report generate failed for draft (will fallback): {e}")
                sr_raw = None

            # 解析 self_report 返回（支持 dict/list/str）
            sr = {}
            if isinstance(sr_raw, dict):
                sr = sr_raw
            elif isinstance(sr_raw, list) and sr_raw:
                # 取第一项为自述
                first = sr_raw[0]
                sr = first if isinstance(first, dict) else {}
            elif isinstance(sr_raw, str):
                parsed = self.safe_json_parse(sr_raw)
                if isinstance(parsed, dict):
                    sr = parsed
            # 如果仍为空则使用防御性默认
            if not isinstance(sr, dict) or not sr:
                sr = {"self_report": "seems fine", "sentiment": draft_emotion}

            wrapped.append({
                "draft": {
                    "text": draft_text,
                    "meta": {
                        "self_report": sr.get("self_report", "").strip(),
                        "sentiment": sr.get("sentiment", draft_emotion),
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

    def align_with_post_infer(self, draft_envelope: Dict[str, Any], post_infer_emotion: str, target_emotion: Optional[str] = None) -> Dict[str, Any]:
        """对齐草稿情感：当 draft.meta.sentiment 与 post_infer_emotion 不一致时请求重写并返回 final 结构（含 audit）。"""
        draft = draft_envelope.get("draft", {})
        text = draft.get("text", "")
        draft_sent = (draft.get("meta", {}).get("sentiment") or "neutral").lower()
        post_infer = (post_infer_emotion or "neutral").lower()
        tgt = (target_emotion or post_infer).lower()

        audit = {"rewritten": False, "reason": None}

        if draft_sent != post_infer:
            rewrite_prompt = (
                f"Please rewrite the following English text to keep facts and content unchanged, "
                f"but adjust only the tone/emotion to '{tgt}'. Keep the same meaning and details, "
                f"do not add or remove facts. Original: '{text}'\nReturn only the rewritten text."
            )
            try:
                rewritten = self.provider.generate(rewrite_prompt)
            except Exception as e:
                print(f"[WARN] rewrite request failed: {e}")
                rewritten = None

            # 规范化重写结果为纯文本
            final_text = None
            if isinstance(rewritten, dict):
                final_text = rewritten.get("text") or rewritten.get("reply")
            elif isinstance(rewritten, list) and rewritten:
                first = rewritten[0]
                final_text = first.get("text") if isinstance(first, dict) else str(first)
            elif isinstance(rewritten, str):
                # 有时返回是 JSON 字符串或纯文本，先尝试解析 JSON 再回退为原始字符串
                parsed = self.safe_json_parse(rewritten)
                if isinstance(parsed, dict):
                    final_text = parsed.get("text") or parsed.get("reply") or str(parsed)
                else:
                    final_text = rewritten

            if not final_text:
                final_text = text

            audit["rewritten"] = True
            audit["reason"] = f"sentiment_mismatch: draft={draft_sent}, post_infer={post_infer}"
            final_emotion = tgt
        else:
            final_text = text
            final_emotion = draft_sent

        return {"final": {"text": final_text, "emotion": final_emotion, "audit": audit}}

    def refusal_response(self, deny: Dict[str, Any], persona: str, tone_guidelines: Optional[str] = None) -> Dict[str, str]:
        """根据 deny.reason 生成英文的角色内拒答（已实现，细节保持不变）。"""
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