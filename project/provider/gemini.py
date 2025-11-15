# provider/gemini.py
import json, time, random, os
try:
    # prefer absolute import when package root is available
    from provider.base import BaseProvider, APIError
except Exception:
    # fallback to relative/ local import for simpler execution contexts
    try:
        from .base import BaseProvider, APIError
    except Exception:
        from base import BaseProvider, APIError  # type: ignore

# --- This file now uses the Google Gemini API ---
try:
    from google import genai
    from google.genai import types as gtypes
except ImportError:
    raise ImportError("Please run: pip install -U google-genai")


class GeminiProvider(BaseProvider):
    def __init__(self, config: dict, apikey=os.getenv("GEMINI_API_KEY")):
        """
        Initialize the Gemini provider, reading settings from the config dict.
        """
        # --- Client setup (Your original logic) ---
        if os.getenv("GEMINI_API_KEY"):
            print("API key loaded from environment variable (GEMINI_API_KEY).")
            self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        else:
            print("API key not in env, using provided 'apikey' parameter.")
            self.client = genai.Client(api_key=apikey)

        # --- Config setup ---
        self.config = config 
        
        # Read model name from config, with fallback to env, then hardcoded default
        default_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash") # Updated default
        self._model_name = self.config.get('provider', {}).get('model', default_model)

        # Read sampling parameters from config
        sampling_config = self.config.get('sampling', {})
        self._gen_config = gtypes.GenerateContentConfig(
            temperature=sampling_config.get('temperature', 0.8),
            top_p=sampling_config.get('top_p', 0.95)
        )
        
        print(f"[GeminiProvider] Initialized. Model: {self._model_name}, Temp: {self._gen_config.temperature}")

    def generate(self, prompt: str, schema=None, retries=None):
        # Load default retries from config if not specified
        if retries is None:
            retries = self.config.get('app', {}).get('json_retry', 2)
            
        last_error = None
        
        for attempt in range(retries):
            try:
                print(f"\n[GeminiProvider] Generate attempt {attempt + 1}/{retries}")

                # --- Your Original Prompting Logic ---
                actual_prompt = prompt
                if schema:
                    schema_desc = ", ".join([f'"{key}": ...' for key in schema])
                    actual_prompt = f"""{prompt}

IMPORTANT: You MUST return valid JSON format with these exact keys: {schema_desc}
Return ONLY the JSON object, no other text or explanations.
Example format: {json.dumps({key: "example_value" for key in schema}, ensure_ascii=False)}
"""
                # --- End of Original Prompting Logic ---

                # === [API Call for Gemini] ===
                resp = self.client.models.generate_content(
                    model=self._model_name,
                    contents=actual_prompt,
                    config=self._gen_config
                )
                
                text = getattr(resp, "text", "")
                if not text:
                    try:
                        text = "".join(
                            p.text for c in getattr(resp, "candidates", []) 
                            for p in getattr(c, "content", {}).get("parts", [])
                            if hasattr(p, "text")
                        ).strip()
                    except Exception:
                        text = ""
                # === [End of API Call for Gemini] ===

                print(f"Raw response: {text}") # Debug info

                # --- Your Original Cleanup & Validation Logic ---
                cleaned_text = text.strip()
                if cleaned_text.startswith("```json"):
                    cleaned_text = cleaned_text[7:]
                if cleaned_text.startswith("```"):
                    cleaned_text = cleaned_text[3:]
                if cleaned_text.endswith("```"):
                    cleaned_text = cleaned_text[:-3]
                cleaned_text = cleaned_text.strip()

                if schema:
                    try:
                        parsed = json.loads(cleaned_text)
                        
                        if isinstance(parsed, list):
                            for i, item in enumerate(parsed):
                                if not isinstance(item, dict):
                                    raise ValueError(f"Item {i} is not a dictionary")
                                for key in schema:
                                    if key not in item:
                                        raise ValueError(f"Missing key '{key}' in item {i}: {item}")
                        elif isinstance(parsed, dict):
                            for key in schema:
                                if key not in parsed:
                                    raise ValueError(f"Missing key: {key}")
                        else:
                            raise ValueError(f"Expected list or dict, got {type(parsed)}")
                            
                        return parsed
                    except Exception as e:
                        print(f"[ERROR] JSON parse failed: {e}")
                        print(f"[ERROR] Raw text was: {text}")
                        print(f"[ERROR] Cleaned text was: {cleaned_text}")
                        last_error = e
                        if attempt < retries - 1:
                            time.sleep(1)
                            continue
                        else:
                            raise
                # --- End of Original Cleanup & Validation Logic ---

                return {"text": text}

            except Exception as e:
                print(f"[ERROR] API call failed: {e}")
                last_error = e
                time.sleep(1)

        raise APIError(f"Gemini API failed after {retries} retries: {str(last_error)}")

    def judge(self, context: str, output: str):
        """Simple OOC risk assessment"""
        # --- This logic is identical to your original ---
        prompt = f"""
        Judge if the NPC reply stays in character.
        Context: {context}
        NPC reply: {output}
        Output JSON: {{"ooc_risk": 0.0, "reasons": []}}
        """
        return self.generate(prompt, schema=["ooc_risk", "reasons"], retries=1)