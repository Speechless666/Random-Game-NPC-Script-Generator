# Architecture & Call Order（Stage 0 · B组）

> 目标：把「护栏 → 生成 → 自评 → 回滚 → 记忆写回」跑成**稳定闭环**，并统一最终 **JSON 输出 Schema** 与错误分支。

## 系统不变量
- 只外显 **public** 世界事实；`secret` 仅用于拒答判定，不可外显。
- 只提及 **allowed_entities**；白名单外用泛称（a merchant / a captain）。
- **每条响应必须含 emotion**（neutral|friendly|cheerful|serious|annoyed|sad）。
- **严格 JSON 输出** + `max_new_tokens ≤ 64`。

## 端到端数据流（两段式情绪对齐）
Player → controller.route() → filters → retriever → emotion_engine.pre_hint → generator 草稿 → emotion_engine.post_infer → generator 重写对齐 → ooc_checker → memory_store → memory_summarizer → logger

## 分支策略
- filters 拦截：`taboo|secret|unknown_entity` → 角色内英文拒答。
- 证据不足：常规槽位 deny_ooc；`past_story` 放行继续生成。
- JSON 失败：最多重试 `json_retry` 次；失败 → 结构化拒答 JSON。
- 情绪不一致：触发重写或降级情绪。
- OOC 高风险：降级或 deny_ooc。

## 统一返回 JSON
```json
{
  "slot": "quest_request|trade|past_story|...",
  "emotion": "neutral|friendly|cheerful|serious|annoyed|sad",
  "text": "final English reply, persona-consistent",
  "ooc_risk": 0.0,
  "mem_refs": ["event:2025-10-01#3", "lore:castle_market_12"],
  "audit": {
    "pre_hint": "serious",
    "draft": {"emotion": "neutral", "self_report": "swamped today", "sentiment": "negative"},
    "post_infer": {"emotion": "annoyed", "confidence": 0.82},
    "rewrite_applied": true,
    "rewrite_reason": "content_emotion != draft_emotion",
    "evidence_ids": ["lore#17","mem#p42n7"],
    "deny_reason": null
  }
}
```

## 模块契约
- emotion_engine.pre_hint(ctx)
- emotion_engine.post_infer(text, ctx)
- generator.generate_candidates(ctx, n)
- generator.rank(cands, ctx)
- generator.finalize(draft, ctx)
- ooc_checker.judge_ooc(ctx, final)
- memory_store.append_event / get_short_window / write_longterm

## 验收
- 队友能复述 early deny / rewrite / 降级条件。
- 日志可回放完整链路。
