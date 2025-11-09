# -*- coding: utf-8 -*-
# scripts/simulate_dialogue.py
"""
Dialogue Simulation Script (CSV-driven, emotion-style aware):
- Load personas from project/data/npc.csv (no hardcoding).
- Load test turns from project/data/test_cases.csv.
- Prefer project.provider.qwen.QwenProvider; fallback to OpenAI-compatible Qwen (DashScope).
- Only use denial template when the user asks for sensitive/taboo topics.
- Enforce emotion surface style using parsed style_emotion_map + fallback cues.
- Emotion-adaptive sampling temperature.
- One-shot style rewrite to strengthen emotion while preserving facts.
- If no explicit cue is present, inject a minimal cue non-intrusively.
- Log spans via project.runtime.logger.LOGGER.

Env:
  - QWEN_API_KEY (required if fallback is used)
  - OPENAI_BASE_URL (default: https://dashscope.aliyuncs.com/compatible-mode/v1)
  - QWEN_MODEL (default: qwen2.5-7b-instruct)
  - GEN_TEMPERATURE, GEN_TOP_P, GEN_MAX_TOKENS, GEN_SEED (optional)
"""

from __future__ import annotations
import sys
import os
import time
import csv
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from pathlib import Path

# ---------------- Logger ----------------
from project.runtime.logger import LOGGER

# ---------------- Gen config from env ----------------
DEFAULT_MODEL = os.getenv("QWEN_MODEL", "qwen2.5-7b-instruct")
DEFAULT_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
API_KEY = os.getenv("QWEN_API_KEY")

GEN_TEMPERATURE = float(os.getenv("GEN_TEMPERATURE", "0.7"))
GEN_TOP_P = float(os.getenv("GEN_TOP_P", "0.9"))
GEN_MAX_TOKENS = int(os.getenv("GEN_MAX_TOKENS", "192"))
GEN_SEED = os.getenv("GEN_SEED")  # optional

# ---- Emotion cue lexicon (surface signals) ----
EMOTION_CUES = {
    "neutral":  ["even tone", "no exclamation", "short factual line"],
    "cheerful": [
        "glad", "excited", "great", "can’t wait", "looking forward",
        "nice", "fun", "awesome", "happy to", "stoked"
    ],
    "friendly": [
        "hey", "sure", "no worries", "happy to", "let’s", "you could",
        "feel free", "sounds good", "if you like"
    ],
    "serious":  [
        "note that", "it’s best to", "I’d recommend", "please be aware",
        "generally", "in practice", "to be precise"
    ],
    "sad":      [
        "I guess", "not easy", "it can be tough", "I’m afraid",
        "quietly", "sometimes it feels"
    ],
    "annoyed":  [
        "fine", "if you insist", "look", "anyway", "to be blunt"
    ],
}

def gen_params_for_emotion(emotion: str):
    e = (emotion or "neutral").lower()
    if e in ("cheerful", "friendly"):
        return {"temperature": max(0.75, float(os.getenv("GEN_TEMPERATURE", "0.7"))), "top_p": float(os.getenv("GEN_TOP_P","0.9"))}
    elif e in ("serious", "sad"):
        return {"temperature": 0.45, "top_p": 0.9}
    elif e in ("annoyed",):
        return {"temperature": 0.6, "top_p": 0.9}
    return {"temperature": float(os.getenv("GEN_TEMPERATURE", "0.7")), "top_p": float(os.getenv("GEN_TOP_P","0.9"))}

# ---------------- Paths (robust discovery) ----------------
THIS = Path(__file__).resolve()
# 支持脚本位于 <repo>/scripts 或 <repo>/project/scripts 等位置
DATA_DIR_CANDIDATES = [
    THIS.parent.parent / "project" / "data",  # <repo>/project/data  ← 常用
    THIS.parent.parent / "data",              # <repo>/data
    THIS.parent / "data",                     # <repo>/scripts/data
]

def _pick_data_file(filename: str) -> Path:
    for d in DATA_DIR_CANDIDATES:
        p = d / filename
        if p.exists():
            return p
    return DATA_DIR_CANDIDATES[0] / filename  # 返回首选路径，后续报友好错误

NPC_CSV_PATH = _pick_data_file("npc.csv")
TEST_CASES_PATH = _pick_data_file("test_cases.csv")

print(f"🗂 Using npc.csv at: {NPC_CSV_PATH}")
print(f"🗂 Using test_cases.csv at: {TEST_CASES_PATH}")

# ---------------- Provider Adapters ----------------
@dataclass
class LLMResponse:
    text: str
    emotion: str = "none"

class BaseProvider:
    def get_response(self, prompt: str, **gen_params) -> LLMResponse:
        raise NotImplementedError

class QwenOpenAICompatProvider(BaseProvider):
    """Fallback provider using openai-python against an OpenAI-compatible endpoint (e.g., DashScope)."""
    def __init__(self, api_key: str, base_url: str, model: str):
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:
            raise RuntimeError("Missing dependency: pip install openai") from e
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def get_response(self, prompt: str, **gen_params) -> LLMResponse:
        params = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an NPC dialogue engine for a Stardew-like world. Stay in-character and obey safety rules."},
                {"role": "user", "content": prompt},
            ],
            "temperature": gen_params.get("temperature", GEN_TEMPERATURE),
            "top_p": gen_params.get("top_p", GEN_TOP_P),
            "max_tokens": gen_params.get("max_tokens", GEN_MAX_TOKENS),
        }
        if GEN_SEED is not None:
            try:
                params["seed"] = int(GEN_SEED)
            except Exception:
                pass
        resp = self.client.chat.completions.create(**params)
        txt = (resp.choices[0].message.content or "").strip()
        return LLMResponse(text=txt, emotion=gen_params.get("emotion_hint", "none"))

def _resolve_provider() -> BaseProvider:
    """
    Prefer local project.provider.qwen.QwenProvider（支持 JSON & 采样参数透传）;
    fallback to OpenAI-compatible client if missing.
    """
    try:
        from project.provider.qwen import QwenProvider  # type: ignore
        class ProviderWrapper(BaseProvider):
            def __init__(self):
                self.impl = QwenProvider()
            def get_response(self, prompt: str, **gen_params) -> LLMResponse:
                out = self.impl.get_response(prompt, **gen_params)  # expects {'text','emotion'}
                if isinstance(out, dict):
                    return LLMResponse(text=(out.get("text") or "").strip(), emotion=out.get("emotion", "none"))
                return LLMResponse(text=str(out).strip(), emotion="none")
        return ProviderWrapper()
    except Exception:
        if not API_KEY:
            raise RuntimeError("QWEN_API_KEY not set. Export QWEN_API_KEY=sk-xxx for real API calls.")
        return QwenOpenAICompatProvider(api_key=API_KEY, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL)

# ---------------- CSV helpers ----------------
def _first_nonempty(d: Dict[str, str], keys: List[str]) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""

def _parse_style_map(s: str) -> dict:
    """
    'cheerful: Upbeat; friendly: Casual and relaxed; serious: Reflective'
      → {'cheerful':['upbeat'], 'friendly':['casual','relaxed'], 'serious':['reflective']}
    """
    out: Dict[str, List[str]] = {}
    if not s:
        return out
    parts = [p.strip() for p in s.split(";") if p.strip()]
    for p in parts:
        if ":" not in p:
            continue
        k, v = p.split(":", 1)
        k = k.strip().lower()
        vals = [w.strip().lower() for w in v.split(",") if w.strip()] or [v.strip().lower()]
        expanded: List[str] = []
        for item in vals:
            item = item.replace(" and ", ",")
            expanded += [w.strip() for w in item.split(",") if w.strip()]
        out[k] = expanded or vals
    return out

def load_personas_from_npc_csv() -> Dict[str, Dict[str, Any]]:
    """
    从 npc.csv 读取人设，返回：
    { key -> {
        'persona_text': str,
        'denial_template': str,
        'taboo_topics': str,
        'style_map': dict
    }}
    同时用 npc_id 和 name 两种键索引。
    """
    if not NPC_CSV_PATH.exists():
        raise FileNotFoundError(f"npc.csv not found at {NPC_CSV_PATH}")

    personas: Dict[str, Dict[str, Any]] = {}
    with NPC_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            npc_id = _first_nonempty(row, ["npc_id", "id"])
            name = _first_nonempty(row, ["name", "npc"])
            role = _first_nonempty(row, ["role", "job", "title"])
            baseline = _first_nonempty(row, ["baseline_emotion", "baseline"])
            emo_range = _first_nonempty(row, ["emotion_range"])
            style_map_str = _first_nonempty(row, ["style_emotion_map"])
            speaking = _first_nonempty(row, ["speaking_style", "style", "voice"])
            taboo = _first_nonempty(row, ["taboo_topics", "taboo"])
            allowed = _first_nonempty(row, ["allowed_tags", "tags"])
            denial = _first_nonempty(row, ["denial_template", "deny_template", "denial"])

            header_bits = [s for s in [name or npc_id, role] if s]
            header = ", ".join(header_bits) if header_bits else (name or npc_id or "NPC")
            body = []
            if baseline: body.append(f"Baseline emotion: {baseline}.")
            if emo_range: body.append(f"Emotion range: {emo_range}.")
            if speaking: body.append(f"Speaking style: {speaking}.")
            if allowed: body.append(f"Allowed tags: {allowed}.")
            # 不把 denial/taboo 写进 persona_text，避免模型预设拒绝
            persona_text = f"{header}. " + (" ".join(body) if body else "Stay in character and keep answers concise.")
            # Sam neutral 特殊规则（若未包含）
            if (name or "").lower() == "sam" and "neutral" not in persona_text.lower():
                persona_text += " IMPORTANT RULE: If requested to be 'neutral', suppress excitement and avoid exclamation marks."

            record = {
                "persona_text": persona_text.strip(),
                "denial_template": denial,
                "taboo_topics": taboo,
                "style_map": _parse_style_map(style_map_str),
            }
            if npc_id:
                personas[npc_id] = record
            if name:
                personas[name] = record
    return personas

def load_test_cases() -> List[Dict[str, str]]:
    """
    读取 test_cases.csv；兼容列名：
      - 角色键：npc_id 或 npc
      - 输入文本：player_text 或 question
    """
    if not TEST_CASES_PATH.exists():
        print(f"❌ ERROR: Test file not found: {TEST_CASES_PATH}", file=sys.stderr)
        return []
    cases: List[Dict[str, str]] = []
    try:
        with TEST_CASES_PATH.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cleaned = {(k.strip() if k else k): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                npc_key = cleaned.get("npc_id") or cleaned.get("npc")
                if not npc_key:
                    print("⚠️ WARNING: Missing 'npc_id'/'npc'. Skipping row.", file=sys.stderr)
                    continue
                if not cleaned.get("player_text"):
                    if cleaned.get("question"):
                        cleaned["player_text"] = cleaned["question"]
                    else:
                        print("⚠️ WARNING: Missing 'player_text'/'question'. Skipping row.", file=sys.stderr)
                        continue
                cleaned.setdefault("session_id", f"session-{len(cases)+1:03d}")
                cleaned.setdefault("slot", "general_test")
                cleaned.setdefault("emotion_proposed", "neutral")
                cleaned["npc_key"] = npc_key  # 保存灵活键
                cases.append(cleaned)
    except Exception as e:
        print(f"❌ ERROR: Failed to read/parse test_cases.csv: {e}", file=sys.stderr)
        return []
    return cases

# ---------------- Sensitivity quick check ----------------
def looks_sensitive(text: str, taboo: str) -> bool:
    toks = [t.strip().lower() for t in (taboo or "").split(",") if t.strip()]
    t = (text or "").lower()
    return any(tok in t for tok in toks)

# ---------------- Prompt builder (emotion-aware) ----------------
def build_prompt(npc_label: str, persona_text: str, player_text: str, emotion: str, slot: str,
                 denial_template: str = "", taboo_topics: str = "", style_map: dict | None = None) -> str:
    emo_key = (emotion or "neutral").strip().lower()
    # 从 csv 的 style_map 取提示，取不到就用全局 EMOTION_CUES
    style_cues = []
    if style_map and isinstance(style_map, dict) and emo_key in style_map:
        style_cues = style_map.get(emo_key, [])
    fallback = EMOTION_CUES.get(emo_key, EMOTION_CUES["neutral"])
    cue_list = (style_cues or fallback)

    rules = f"""
- Safety: Never reveal private addresses, secret areas, lock combinations, or staff schedules.
- Privacy: If the user requests taboo/forbidden info, refuse politely.
- Otherwise, ANSWER NORMALLY (do NOT refuse preemptively).
- Do NOT quote meta-data like "taboo topics" or "denial template" in your reply.
- If you must refuse, paraphrase in your own words with the NPC's style (do NOT print the template verbatim).
- Keep replies concise (<= 2 sentences) unless asked to elaborate.
- Style control: realize the requested emotion with surface signals (lexicon/phrases/punctuation).
- Use **at least one** of these cues in the wording: {", ".join(cue_list)}.
- Punctuation rule: {"at most one exclamation mark" if emo_key in ("cheerful",) else "no exclamation marks"}.
""".strip()

    denial_line = f"(Internal only, do NOT output verbatim) Denial template: {denial_template}" if denial_template else ""
    taboo_line  = f"(Internal only, do NOT mention) Taboo topics: {taboo_topics}" if taboo_topics else ""

    return (
        f"Act strictly as {npc_label}.\n"
        f"Persona:\n{persona_text}\n\n"
        f"{taboo_line}\n"
        f"{denial_line}\n"
        f"Requested emotion: {emotion}\n"
        f"Slot: {slot}\n"
        f"Rules:\n{rules}\n"
        f"Player: {player_text}\n"
        f"Answer as {npc_label}:"
    )

# ---------------- Retry helper ----------------
def with_retries(call_fn, retries: int = 3, backoff: float = 0.8):
    err: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            return call_fn()
        except BaseException as e:
            err = e
            sleep_s = backoff * (2 ** (attempt - 1))
            print(f"⚠️ API call failed (attempt {attempt}/{retries}): {e}. Retrying in {sleep_s:.2f}s...", file=sys.stderr)
            time.sleep(sleep_s)
    assert err is not None
    raise err

# ---------------- Style rewrite (strengthen emotion, preserve facts) ----------------
def rewrite_with_emotion(provider: BaseProvider, npc_label: str, persona_text: str, original: str, emotion: str, style_map: dict):
    emo_key = (emotion or "neutral").lower()
    style_cues = []
    if style_map and emo_key in style_map:
        style_cues = style_map.get(emo_key, [])
    fallback = EMOTION_CUES.get(emo_key, EMOTION_CUES["neutral"])
    cue_list = (style_cues or fallback)

    sys_msg = (
        "You are a style rewriter for a video game NPC. "
        "Rewrite the given line to strengthen the surface emotion while preserving facts. "
        "Do NOT add new facts. Keep it to 1–2 sentences. "
        "Respect punctuation rule (cheerful: at most one exclamation; others: no exclamation)."
    )
    user_msg = (
        f"NPC: {npc_label}\n"
        f"Persona: {persona_text}\n"
        f"Target emotion: {emotion}\n"
        f"Use at least one of these cues in wording: {', '.join(cue_list)}\n"
        f"Original line:\n{original}\n"
        f"Rewrite now (only the rewritten line):"
    )
    try:
        out = provider.get_response(
            f"{sys_msg}\n\n{user_msg}",
            temperature=0.5, top_p=0.9, max_tokens=GEN_MAX_TOKENS
        )
        return out.text if hasattr(out, "text") else (out.get("text","") if isinstance(out, dict) else str(out))
    except Exception:
        return original

# ---------------- Ensure cue injection if missing ----------------
def ensure_emotion_cue(text: str, emotion: str, style_map: dict) -> str:
    """若成品句子里没有明显情绪线索，则温和地注入一个（不新增事实）。"""
    if not isinstance(text, str) or not text.strip():
        return text
    t_low = text.lower()
    emo_key = (emotion or "neutral").lower()
    csv_cues = (style_map.get(emo_key, []) if isinstance(style_map, dict) else []) or []
    fallback = EMOTION_CUES.get(emo_key, EMOTION_CUES["neutral"])
    cues = [c for c in (csv_cues or fallback) if c]
    if any(c in t_low for c in cues):
        return text
    cue = sorted(cues, key=len)[0] if cues else None
    if not cue or emo_key in ("neutral", "none", ""):
        return text
    if emo_key == "cheerful":
        if text.endswith((".", "!", "?")):
            return text.rstrip(".!?") + f", {cue}!"
        return text + f" — {cue}!"
    else:
        if text.endswith((".", "!", "?")):
            return text.rstrip(".!?") + f", {cue}."
        return text + f" — {cue}."

# ---------------- Main ----------------
def run_dialogue_simulation():
    # 1) Personas
    try:
        personas = load_personas_from_npc_csv()
    except Exception as e:
        print(f"❌ ERROR: Failed to load NPC personas from npc.csv: {e}", file=sys.stderr)
        return

    # 2) Test cases
    cases = load_test_cases()
    if not cases:
        print("Simulation finished. No valid test cases found.", file=sys.stderr)
        LOGGER.close()
        return

    # 3) Provider
    provider = _resolve_provider()
    print(f"--- Starting Dialogue Simulation: Running {len(cases)} test turns ---")

    for idx, case in enumerate(cases, 1):
        npc_key = case.get("npc_key", "")
        session_id = case.get("session_id", f"session-{idx:03d}")
        player_text = case.get("player_text", "Empty Question")
        emotion_proposed = case.get("emotion_proposed", "neutral")
        slot = case.get("slot", "general_test")

        record = personas.get(npc_key) or personas.get(npc_key.title()) or personas.get(npc_key.capitalize())
        if not record:
            print(f"⚠️ WARNING: Persona not found for key '{npc_key}'. (Expect npc_id like SV001 or name like Sam) Skipping.", file=sys.stderr)
            continue

        persona_text   = record.get("persona_text", "")
        denial_template = record.get("denial_template", "")
        taboo_topics    = record.get("taboo_topics", "")
        style_map       = record.get("style_map", {})

        # 轻量敏感检测：只有疑似命中 taboo 才暴露拒绝模板与 taboo 列表
        sensitive = looks_sensitive(player_text, taboo_topics)
        dt = denial_template if sensitive else ""
        tt = taboo_topics if sensitive else ""

        start = time.time()

        # 4) Start log span
        ctx = {
            "npc_key": npc_key,
            "player_id": session_id,
            "raw_text": player_text,
            "slot": slot,
            "emotion_proposed": emotion_proposed,
            "sensitive_hint": sensitive,
        }
        span = LOGGER.start_span(ctx)

        print(f"\n[{idx:02d}. {npc_key} | {session_id}] Player: {player_text}")

        # 5) Emotion-adaptive sampling params — define BEFORE _call so it's in outer scope
        gp_used = gen_params_for_emotion(emotion_proposed)

        # 6) Call provider using gp_used
        def _call():
            prompt = build_prompt(
                npc_key,
                persona_text,
                player_text,
                emotion_proposed,
                slot,
                denial_template=dt,
                taboo_topics=tt,
                style_map=style_map,
            )
            return provider.get_response(
                prompt,
                temperature=gp_used["temperature"],
                top_p=gp_used["top_p"],
                max_tokens=GEN_MAX_TOKENS,
                emotion_hint=emotion_proposed,
            )

        try:
            llm = with_retries(_call, retries=3, backoff=0.6)
            final_text = llm.text or "(empty)"
            emotion_final = llm.emotion or "none"

            # 7) 非敏感 + 非 neutral 时：风格化重写 + 缺失时注入 1 个情绪线索
            if not sensitive and (emotion_proposed or "").lower() not in ("neutral", "none", ""):
                rewritten = rewrite_with_emotion(provider, npc_key, persona_text, final_text, emotion_proposed, style_map)
                if rewritten and isinstance(rewritten, str):
                    final_text = rewritten.strip()
                final_text = ensure_emotion_cue(final_text, emotion_proposed, style_map)
            else:
                # 即便 neutral/敏感，也保证文本安全的标点统一
                final_text = ensure_emotion_cue(final_text, emotion_proposed, style_map)

        except Exception as e:
            final_text = f"[ERROR] API Call Failed: {type(e).__name__}: {str(e)}"
            emotion_final = "error"
            print(f"❌ API Error: {type(e).__name__}: {e}", file=sys.stderr)

        # 8) Metrics (placeholder)
        ooc_risk = 0.1
        latency_ms = (time.time() - start) * 1000.0

        # 9) End span
        payload = {
            "event": "npc_response",
            "evidence": "memory_ref_123",
            "raw_text": player_text,
            "ooc_risk": ooc_risk,
            "final_text": final_text,
            "trigger_hits": [],
            "emotion_final": emotion_final,
            "mem_refs": "",
            "memory_write": "",
            "latency_ms": latency_ms,
            "cache_hit": False,
            "gen_params": {
                "temperature": gp_used["temperature"],
                "top_p": gp_used["top_p"],
                "max_tokens": GEN_MAX_TOKENS,
                "seed": GEN_SEED,
                "model": DEFAULT_MODEL,
            },
        }
        LOGGER.end_span(span, payload)
        print(f"  NPC({emotion_final}): {final_text}")
        print(f"  [Log Saved. Latency: {latency_ms:.2f}ms]")

    print("\n--- Dialogue Simulation Ended. Log file generated ---")
    LOGGER.close()

if __name__ == "__main__":
    # 仅在需要回退时检查 API KEY；若本地 QwenProvider 可用则不会触发
    try:
        _ = _resolve_provider()
    except Exception as e:
        print(f"Provider init check: {e}", file=sys.stderr)
        sys.exit(1)
    run_dialogue_simulation()
