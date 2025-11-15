# test_dialogue_system.py
"""
Dialogue System Full Test - Based on Actual Data
(MODIFIED: Fully integrated with config-driven modules)
"""

import json, os, yaml
import sys
from pathlib import Path
from typing import Dict, Any, List
import argparse
import pprint 

# Add project path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from runtime.controller import run_once, load_compiled
    
    # --- MODIFIED: Import all providers ---
    from provider.base import BaseProvider
    from provider.gemini import GeminiProvider
    from provider.openai import OpenAIProvider
    from provider.qwen import QwenProvider
    
    # --- MODIFIED: Import logger ---
    from runtime.logger import LOGGER
    
    # (Assuming your generator is in provider/ as per your original file)
    from provider.generator import Generator
    from provider.oocChecker import OOCChecker
    from provider.memory_store import MemoryStore
    from provider.memory_summarizer import MemorySummarizer
except ImportError as e:
    print(f"Import Error: {e}")
    print(">>> FAILED. DID YOU CREATE THE '__init__.py' FILES in /provider and /runtime? <<<")
    sys.exit(1)


class DialogueSystemTester:
    """Dialogue System Tester - (Refactored)"""
    
    def __init__(self, use_real_provider=False):
        self.use_real_provider = use_real_provider
        self.memory_store = None
        self.memory_summarizer = None
        self.provider = None
        self.generator = None
        self.ooc_checker = None
        self.config = None
        self.api_status = {
            "config_loaded": False,
            "compiled_data_loaded": False, # <-- ADDED
            "provider_initialized": False,
            "generator_initialized": False,
            "ooc_checker_initialized": False,
            "memory_store_initialized": False,
            "memory_summarizer_initialized": False
        }
        
        # --- MODIFIED: Refactored loading sequence ---
        try:
            # 1. Load Config first
            self._load_config()
            
            # 2. Load Compiled Data
            self.compiled_data = self._load_actual_compiled_data(self.config, PROJECT_ROOT)
            self.api_status["compiled_data_loaded"] = True

            # 3. Initialize providers if requested
            if use_real_provider:
                self._initialize_providers()
            else:
                print("🔶 Running in MOCK mode (no real API calls)")
        except Exception as e:
            print(f"❌ CRITICAL: Tester initialization failed: {e}")
            import traceback
            traceback.print_exc()
            self.use_real_provider = False
        # --- END MODIFICATION ---

    # --- MODIFIED: Added config loading ---
    def _load_config(self):
        config_path = PROJECT_ROOT / "config.yaml" 
        if not config_path.exists():
            raise FileNotFoundError("config.yaml not found in project root.")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
            # Initialize Logger
            LOGGER.initialize(config=self.config, project_root=PROJECT_ROOT)
        self.api_status["config_loaded"] = True
        print(f"✅ 'config.yaml' loaded. Provider set to: {self.config.get('provider', {}).get('name')}")
    # --- END MODIFICATION ---

    # --- MODIFIED: Changed signature ---
    def _load_actual_compiled_data(self, config, project_root) -> Dict[str, Any]:
    # --- END MODIFICATION ---
        """Load the actual compiled data"""
        try:
            # --- MODIFIED: Pass config and project_root ---
            compiled_data = load_compiled(config=config, project_root=project_root)
            # --- END MODIFICATION ---
            print("✅ Successfully loaded compiled data")
            print(f"  - NPC Count: {len(compiled_data.get('npc', []))}")
            print(f"  - Public Lore Count: {len(compiled_data.get('lore_public', []))}")
            return compiled_data
        except Exception as e:
            print(f"❌ Failed to load compiled data: {e}")
            print("Running with mock data")
            return {}
    
    def _initialize_providers(self):
        """Initialize the real providers (if needed)"""
        try:
            print("🔄 Initializing real provider components...")

            # --- Provider Factory (Logic Unchanged) ---
            provider_name = self.config.get('provider', {}).get('name', 'openai')
            provider_instance: BaseProvider

            print(f"[Factory] Initializing provider: '{provider_name}'")
            if provider_name == 'gemini':
                self.provider = GeminiProvider(config=self.config)
            elif provider_name == 'openai':
                self.provider = OpenAIProvider(config=self.config)
            elif provider_name == 'qwen':
                self.provider = QwenProvider(config=self.config)
            else:
                raise ValueError(f"Unknown provider name in config: '{provider_name}'")
            # --- END FACTORY ---

            print("🔄 Testing API connection...")
            test_result = self._test_api_connection()
            
            if test_result:
                self.api_status["provider_initialized"] = True
                
                # --- MODIFIED: Pass config to all components ---
                self.generator = Generator(self.provider, self.config)
                self.api_status["generator_initialized"] = True
                
                self.ooc_checker = OOCChecker(self.provider, self.config) # <-- MODIFIED
                self.api_status["ooc_checker_initialized"] = True
                
                # --- MODIFIED: Pass config and project_root to MemoryStore ---
                self.memory_store = MemoryStore(config=self.config, project_root=PROJECT_ROOT) # <-- MODIFIED
                self.api_status["memory_store_initialized"] = True
                
                # --- MODIFIED: Pass config to MemorySummarizer ---
                self.memory_summarizer = MemorySummarizer(self.provider, self.ooc_checker, config=self.config) # <-- MODIFIED
                self.api_status["memory_summarizer_initialized"] = True
                # --- END CHANGES ---
                
                print(f"✅ Real provider ({provider_name}) and memory modules initialized")
            else:
                print("❌ API test failed, falling back to mock mode")
                self.use_real_provider = False
                
        except Exception as e:
            print(f"❌ Real provider initialization failed: {e}")
            import traceback
            traceback.print_exc()
            print("Running in MOCK mode")
            self.use_real_provider = False
    
    def _test_api_connection(self) -> bool:
        """Test if the API connection is working"""
        # (Logic Unchanged)
        try:
            test_prompt = "Please respond with just the word 'success'"
            result = self.provider.generate(test_prompt)
            if result and isinstance(result, dict) and "text" in result:
                if "success" in result["text"].lower():
                    print("✅ API connection successful.")
                    return True
            return False
        except Exception as e:
            print(f"❌ API connection test failed: {e}")
            return False
    
    def print_api_status(self):
        """Print API status information"""
        self.print_subsection("API Status")
        status_icons = { True: "✅", False: "❌" }
        
        print(f"Using Real Provider: {status_icons[self.use_real_provider]}")
        print(f"Config Loaded: {status_icons[self.api_status['config_loaded']]}")
        print(f"Compiled Data Loaded: {status_icons[self.api_status['compiled_data_loaded']]}")
        if self.use_real_provider:
            print(f"Provider Initialized: {status_icons[self.api_status['provider_initialized']]}")
            print(f"Generator Initialized: {status_icons[self.api_status['generator_initialized']]}")
            print(f"OOC Checker Initialized: {status_icons[self.api_status['ooc_checker_initialized']]}")
            print(f"MemoryStore Initialized: {status_icons[self.api_status['memory_store_initialized']]}")
            print(f"MemorySummarizer Initialized: {status_icons[self.api_status['memory_summarizer_initialized']]}")
        else:
            print("🔶 Currently running in MOCK mode")
    
    def print_section(self, title: str, width=80):
        # (Logic Unchanged)
        print("\n" + "=" * width)
        print(f" {title} ".center(width, "="))
        print("=" * width)
    
    def print_subsection(self, title: str):
        # (Logic Unchanged)
        print(f"\n--- {title} ---")

    def run_complete_test(self, user_text: str, npc_id: str = "SV001", player_id: str = "P001"):
        """(Simplified) Run the complete test flow"""
        print(f"\n🎭 Starting Dialogue Test")
        print(f"🗣️  NPC: {npc_id}")
        print(f"👤 Player: {player_id}")
        print(f"💬 User Input: '{user_text}'")
        
        self.print_api_status()
        
        if not self.use_real_provider:
            print("🔶 In mock mode, skipping controller call.")
            return
            
        if not all([self.generator, self.ooc_checker, self.compiled_data, self.memory_store, self.memory_summarizer]):
            print("❌ Core components (Generator, OOC, Memory, CompiledData) not fully initialized.")
            return

        try:
            self.print_section("Calling Controller.run_once")
            
            # --- MODIFIED: Pass 'config' and 'memory_path' to run_once ---
            controller_result = run_once(
                user_text=user_text,
                npc_id=npc_id,
                player_id=player_id,
                config=self.config, # <-- ADDED
                memory_path=self.memory_store.longterm_path, # <-- ADDED
                generator=self.generator,
                ooc_checker=self.ooc_checker,
                compiled_data=self.compiled_data,
                memory_store=self.memory_store, 
                memory_summarizer=self.memory_summarizer, 
                last_emotion=None 
            )
            # --- END MODIFICATION ---
            
            print("✅ Controller.run_once executed")
            
            self.print_section("Test Summary (Full result from Controller)")
            pprint.pprint(controller_result)
            
            # --- Memory Monitor (Logic Unchanged) ---
            self.print_subsection("Memory Monitor")
            short_term_events = self.memory_store.get_short_window()
            print(f"Events currently in short-term memory (Total {len(short_term_events)}):")
            pprint.pprint(short_term_events)
            
            memory_audit = controller_result.get('audit', {}).get('memory', {})
            if memory_audit.get("facts_written", 0) > 0:
                print(f"✅ Successfully wrote {memory_audit['facts_written']} facts to long-term memory:")
                pprint.pprint(memory_audit.get("facts", []))
            # --- End Memory Monitor ---

            print("\n--- Quick View ---")
            print(f"👤 NPC: {npc_id}")
            print(f"💬 User Input: {user_text}")
            print(f"🎯 Slot Identified: {controller_result.get('slot')}")
            print(f"🎭 Final Emotion: {controller_result.get('final_emotion')}")
            print(f"📝 Generated Text: {controller_result.get('final_text')}")
            
        except Exception as e:
            print(f"❌ Error during test: {e}")
            import traceback
            traceback.print_exc()


def main():
    """Main function - runs preset test cases"""
    # (Logic Unchanged)
    test_cases = [
        {"npc_id": "SV001", "user_text": "When the Luau will be held?", "description": "Greet Shane"},
        {"npc_id": "SV001", "user_text": "When is the Luau and where is it held?", "description": "Ask Shane about work (may trigger past_story)"},
        {"npc_id": "SV001", "user_text": "When will you write story?", "description": "Small talk"},
        {"npc_id": "SV001", "user_text": "When will you write story?", "description": "Small talk (repeat)"},
        {"npc_id": "SV002", "user_text": "When is the Luau and where is it held?", "description": "Small talk with SV002"},
        {"npc_id": "SV002", "user_text": "When is the Luau and where is it held?", "description": "Small talk with SV002 (repeat)"},
    ]
    
    print("🎮 Stardew Valley Dialogue System Test")
    print("=" * 50)
    
    use_real = input("Use real API? (y/N): ").strip().lower() == 'y'
    
    tester = DialogueSystemTester(use_real_provider=use_real)
    
    player_id = "P001_Session" 

    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'#' * 60}")
        print(f"Test Case {i}: {test_case['description']}")
        print(f"{'#' * 60}")
        
        tester.run_complete_test(test_case['user_text'], test_case['npc_id'], player_id=player_id)
        
        if i < len(test_cases):
            input("\nPress Enter to continue to the next test...")
    
    print("\n🎉 All test cases finished!")

if __name__ == "__main__":
    main()