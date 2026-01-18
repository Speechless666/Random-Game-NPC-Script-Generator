# Random-Game-NPC-Script-Generator
A controllable, memory-augmented, emotionally coherent NPC dialogue engine powered by large language models.  
This project transforms traditional static NPCs into dynamic, AI-driven characters capable of grounding their responses in world lore, maintaining emotional consistency, applying guardrails, and remembering past interactions. The system aims to bring game NPCs closer to believable agents with personalities, memories, and coherent social behavior.

---

## 🌍 Project Overview

This repository implements a controllable NPC dialogue engine. Each NPC:

- Has a lightweight persona defined in **npc.csv**.
- Grounds its replies in **lore.csv** world knowledge.
- Routes messages using **slot-based TF-IDF routing**.
- Passes through **filter guardrails** (taboo, secret entities, tag constraints).
- Retrieves **public lore** + **long-term memory**.
- Uses an **emotion engine** combining schema, triggers, slot tone, and persona.
- Generates **multiple candidates**, ranks them, and checks for OOC violations.
- Updates **short-term** & **long-term memory** after each turn.

## 📄 Written Report

A detailed written report explaining the system design, methodology, and implementation decisions is available here:

👉 [Written Report (PDF)](https://github.com/Speechless666/Random-Game-NPC-Script-Generator/blob/main/Report.pdf)

---

# 🚀 Getting Started

## 1. Clone Repository
```
git clone https://github.com/Speechless666/Random-Game-NPC-Script-Generator
cd Random-Game-NPC-Script-Generator/project
```

## 2. Create Virtual Environment
```
python -m venv venv
venv\Scripts\activate           # Windows
source venv/bin/activate        # macOS/Linux
```

## 3. Install Dependencies
```
pip install -r requirements.txt
```

## 4. Config Settings

Go to project/config.yaml
```
provider:
  # The provider to load. MUST match the class name in app.py
  # Options: 'gemini', 'openai', 'qwen'
  name: gemini
  
  # The specific model ID to call (e.g., "gemini-1.5-flash", "gpt-4o-mini", "qwen-turbo")
  model: gemini-2.5-flash
```
Choose the api you want to use, remember to set keys as system environment variable

The api key name for each models are : GEMINI_API_KEY, OPENAI_API_KEY, QWEN_API_KEY

You can also adjust other config settings such as threshold acoording to the citations

## 4. Filling NPC and Lore information

Fill up npc.csv and lore.csv under project/data

run compile_data.py manually to compile the dataset

## 5. Try testing or implement using app.py

You can try project/test.py for testing all functions 

Or you can make use of app.py to setup servers so as to connect to your own applications. 

---
# 🌐 Demo
- Try with Demo using StarstewValley as example dataset!

![Demo](https://github.com/Speechless666/Random-Game-NPC-Script-Generator/blob/main/doc/demofront.png)

Do run /runtime/compile_data.py manually after you eidted npc and lore.csv

Run start.bat for windows and start.sh for Mac

---

# 🧠 Core Components

![Pipeline](https://github.com/Speechless666/Random-Game-NPC-Script-Generator/blob/main/doc/pipeline.jpg)


## 1. Slot Routing (`qrouter.py`)
- TF-IDF scoring  
- cosine similarity  
- must/forbid rules  
- entity & tag matching  

## 2. Guardrails (`filters.py`)
Rejects queries based on:
- taboo topics  
- secret entities  
- unallowed tags  
If triggered → generate in-character refusal template.

## 3. Retriever (`retriever.py`)
Lore scoring uses:
- token overlap
- entity bonus
- user coverage
- memory coverage
- slot must/forbid enforcement  

Merges with top long-term memory items.

## 4. Emotion Engine (`emotion_engine.py`)
Weighted voting system:

```
Score(e) =
  baseline_weight * BaselineVote(e)
+ slot_weight * SlotToneVote(e)
+ trigger_weight * TriggerVote(e)
+ last_turn_weight * LastEmotionVote(e)
+ model_weight * APIVote(e)
```

Highest score = selected emotion.  
Also assigns style hooks.

## 5. Generator (`generator.py`)
- Multi-candidate JSON  
- Heuristic ranking:
  - persona match
  - emotion match
  - length penalty  

## 6. OOC Checking (`oocChecker.py`)
- LLM-as-judge scoring  
- Enforces persona safety  

## 7. Memory System
**Short-term memory:** last 5 turns  
**Long-term memory:** LLM summaries every 5 turns

---

# 🔬 Evaluation Summary
- **Near-zero leak rate**  
- **Very low OOC rate**  
- **Stronger persona consistency**  
- **More accurate and stable emotion control**  
- **Lower variance in latency**  
- **Baseline shows rambling and long delays**  

---

# 📈 Future Work
- NPC-to-NPC conversation / multi-agent simulation  
- Memory compression & forgetting  
- Dynamic world state propagation  
- Advanced personality modelling  

---

# 📜 License
TODO

# ✨ Acknowledgements
Qwen3-Plus used as backbone model.
