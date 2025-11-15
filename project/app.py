# app.py
"""
The project's main Web Server (HTTP interface).
(MODIFIED: Fully integrated with config-driven modules)
"""

import sys
import yaml 
from pathlib import Path
from typing import Dict, Any

# --- 1. Set sys.path (Same as before) ---
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- 2. Import FastAPI and project core components ---
try:
    import uvicorn
    from fastapi import FastAPI
except ImportError:
    print("Error: FastAPI or Uvicorn not found.")
    print("Please run: pip install fastapi uvicorn[standard]")
    sys.exit(1)

try:
    from runtime.controller import run_once, load_compiled
    
    # --- Imports (Unchanged) ---
    from provider.base import BaseProvider
    from provider.gemini import GeminiProvider
    from provider.openai import OpenAIProvider
    from provider.qwen import QwenProvider
    
    # (Assuming your generator is in provider/ as per test.py)
    from provider.generator import Generator 
    from provider.oocChecker import OOCChecker
    from provider.memory_store import MemoryStore
    from provider.memory_summarizer import MemorySummarizer
    
    # --- MODIFIED: Import the logger ---
    from runtime.logger import LOGGER 

except ImportError as e:
    print(f"Project internal import failed: {e}")
    print(">>> FAILED. DID YOU CREATE THE '__init__.py' FILES in /provider and /runtime? <<<")
    sys.exit(1)

# --- 3. FastAPI App Instance ---
app = FastAPI(
    title="NPC AI Project API",
    description="HTTP interface connecting the Pygame Demo to the AI Controller"
)

# --- 4. Global State ---
CORE_COMPONENTS: Dict[str, Any] = {}


@app.on_event("startup")
def load_core_components():
    """
    Runs once on server startup: Loads config, data, and all components.
    """
    print("Server starting up... Loading core components...")
    
    try:
        # 1. --- Load Configuration ---
        # --- MODIFIED: Corrected config path (assumes config.yaml is IN project/) ---
        config_path = PROJECT_ROOT / "config.yaml" 
        if not config_path.exists():
            raise FileNotFoundError(f"config.yaml not found at {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            # --- MODIFIED: Initialize Logger ---
            LOGGER.initialize(config=config, project_root=PROJECT_ROOT)
            
        CORE_COMPONENTS["config"] = config
        print(f"✅ 'config.yaml' loaded. Provider set to: {config.get('provider', {}).get('name')}")

        # 2. Load Compiled Data
        # --- MODIFIED: Pass config and project_root to load_compiled ---
        compiled_data = load_compiled(config=config, project_root=PROJECT_ROOT) 
        CORE_COMPONENTS["compiled_data"] = compiled_data
        print(f"✅ 'compiled.json' (incl. {len(compiled_data.get('npc',[]))} NPCs) loaded.")

        # 3. --- Provider Factory (Logic Unchanged) ---
        provider_name = config.get('provider', {}).get('name', 'openai')
        provider_instance: BaseProvider

        print(f"[Factory] Initializing provider: '{provider_name}'")
        if provider_name == 'gemini':
            provider_instance = GeminiProvider(config=config)
        elif provider_name == 'openai':
            provider_instance = OpenAIProvider(config=config)
        elif provider_name == 'qwen':
            provider_instance = QwenProvider(config=config)
        else:
            raise ValueError(f"Unknown provider name in config: '{provider_name}'")
        
        CORE_COMPONENTS["provider"] = provider_instance
        print(f"✅ Provider ({provider_name}) initialized.")
        # --- End Factory ---

        # 4. Initialize Generator and OOCChecker
        # --- MODIFIED: Pass config to all component constructors ---
        generator = Generator(provider_instance, config=config)
        CORE_COMPONENTS["generator"] = generator
        
        ooc_checker = OOCChecker(provider_instance, config=config)
        CORE_COMPONENTS["ooc_checker"] = ooc_checker
        print("✅ Generator and OOCChecker initialized.")

        # 5. Initialize Memory modules
        # --- MODIFIED: Pass config and project_root to MemoryStore ---
        memory_store = MemoryStore(config=config, project_root=PROJECT_ROOT)
        CORE_COMPONENTS["memory_store"] = memory_store
        
        # --- MODIFIED: Pass config to MemorySummarizer ---
        memory_summarizer = MemorySummarizer(provider_instance, ooc_checker, config=config)
        CORE_COMPONENTS["memory_summarizer"] = memory_summarizer
        print(f"✅ MemoryStore and MemorySummarizer initialized.")
        # --- END ALL MODIFICATIONS ---
        
        print("\n🎉 All core components loaded. Server is ready.\n")
        
    except Exception as e:
        print(f"❌ CRITICAL: Server startup failed while loading components: {e}")
        import traceback
        traceback.print_exc()
        raise e


@app.get("/npc_reply")
def get_npc_reply_endpoint(
    npc_id: str, 
    player: str, 
    player_id: str = "P001_Demo"
):
    """
    This is the main API endpoint that the Demo (main.py) will call.
    """
    
    # 1. Get initialized components from global state
    # --- MODIFIED: Get config from global state ---
    config = CORE_COMPONENTS.get("config")
    generator = CORE_COMPONENTS.get("generator")
    ooc_checker = CORE_COMPONENTS.get("ooc_checker")
    compiled_data = CORE_COMPONENTS.get("compiled_data")
    memory_store = CORE_COMPONENTS.get("memory_store")
    memory_summarizer = CORE_COMPONENTS.get("memory_summarizer")
    
    if not all([config, generator, ooc_checker, compiled_data, memory_store, memory_summarizer]):
        return {"text": "(Error: Server core components not loaded correctly)", "emotion": "sad"}

    print(f"Request received: NPC={npc_id}, Player={player}")

    # 2. Call the core logic
    try:
        # --- MODIFIED: Pass 'config' and 'memory_path' to run_once ---
        result = run_once(
            user_text=player,
            npc_id=npc_id,
            player_id=player_id,
            config=config, # <-- ADDED
            memory_path=memory_store.longterm_path, # <-- ADDED
            generator=generator,
            ooc_checker=ooc_checker,
            compiled_data=compiled_data,
            memory_store=memory_store,
            memory_summarizer=memory_summarizer,
            last_emotion=None
        )
        # --- END MODIFICATION ---
        
        # 3. Return the format (Logic Unchanged)
        final_text = result.get("final_text", "(No text)")
        final_emotion = result.get("final_emotion", "unknown")
        display_text = f"{final_text}  ({final_emotion})"

        return {
            "text": display_text,
            "emotion": final_emotion,
            "slot": result.get("slot")
        }

    except Exception as e:
        print(f"❌ Error during controller.run_once execution: {e}")
        import traceback
        traceback.print_exc()
        return {"text": f"(Controller Error: {e})", "emotion": "sad"}


if __name__ == "__main__":
    """
    Allows you to run this server directly with 'python project/app.py'
    """
    print("Starting Uvicorn server, listening on http://127.0.0.1:8000")
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)