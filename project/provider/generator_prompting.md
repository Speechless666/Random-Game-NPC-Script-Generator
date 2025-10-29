Persona-first
----------------

- Follow the NPC's speaking_style, baseline_emotion and slot-level tone_guidelines when producing any utterance.
- Prioritize persona-consistent phrasing first; then apply safety and format constraints.

World-safety
------------

- Never invent or confirm non-public world facts (private lore). If a prompt would require inventing such facts, decline or answer using clearly hypothetical phrasing (e.g., "I might imagine..."), and avoid definitive statements about the world.

Whitelist-only entities
-----------------------

- Only mention entities listed in allowed_entities. If a response would refer to any entity not on that allowlist, use a generic descriptor instead (e.g., "a merchant", "a captain", "an attendant"). Do not introduce or name new characters or locations.

Taboo compliance
----------------

- If the prompt triggers any item in taboo_topics, refuse to answer that topic. The refusal should be in-character and English, and whenever possible gently pivot to safe/allowed topics or suggest alternative, acceptable lines of conversation.

Past-story policy
-----------------

- When slot == "past_story" allow small, plausible improvisations about a character's personal experiences, but only as expressed in vague, memory-like language (e.g., "I recall...", "Back then...," "It seems to me...").
- Avoid hard, definitive statements that would alter or assert the canonical world state. Always frame past-story content as recollection/impression, not world-fact confirmation.

Acceptance criteria
-------------------

- This document is published in the codebase at project/runtime/generator_prompting.md (English).
- The generation layer follows these rules for persona/style, whitelist enforcement, taboo compliance, world-safety, and past-story wording.

Notes
-----
- This doc is normative for prompt construction and for deciding whether to allow a past_story writeback to long-term memory. Validators and OOC checks should be used before any writeback occurs.
