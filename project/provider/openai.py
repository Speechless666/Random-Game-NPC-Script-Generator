# provider/openai.py
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

# --- This file uses the OpenAI API ---
try:
    from openai import OpenAI
except ImportError:
    raise ImportError("Please run: pip install -U openai")


class OpenAIProvider(BaseProvider):
    def __init__(self, config: dict, apikey=os.getenv("OPENAI_API_KEY")):
        """
        Initialize the OpenAI provider, reading settings from the config dict.
        """
        if os.getenv("OPENAI_API_KEY"):
            print("API key loaded from environment variable (OPENAI_API_KEY).")
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        else:
            print("API key not in env, using provided 'apikey' parameter.")
            self.client = OpenAI(api_key=apikey)
        
        self.config = config
        
        # Read model name from config
        self._model_name = self.config.get('provider', {}).get('model', 'gpt-4o-mini')

        # Read sampling parameters from config
        self.sampling_config = self.config.get('sampling', {})
        
        print(f"[OpenAIProvider] Initialized. Model: {self._model_name}, Temp: {self.sampling_config.get('temperature')}")

    def generate(self, prompt: str, schema=None, retries=None):
        if retries is None:
            retries = self.config.get('app', {}).get('json_retry', 2)
            
        last_error = None
        
        for attempt in range(retries):
            try:
                print(f"\n[OpenAIProvider] Generate attempt {attempt + 1}/{retries}")

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
                
                messages = [{"role": "user", "content": actual_prompt}]
                
                # Handle JSON mode
                json_mode_param = {}
                if schema and self.config.get('provider', {}).get('json_mode', True):
                     json_mode_param = {"response_format": {"type": "json_object"}}

                # === [API Call for OpenAI] ===
                resp = self.client.chat.completions.create(
                    model=self._model_name,
                    messages=messages,
                    temperature=self.sampling_config.get('temperature', 0.8),
                    top_p=self.sampling_config.get('top_p', 0.95),
                    presence_penalty=self.sampling_config.get('presence_penalty', 0.0),
                    frequency_penalty=self.sampling_config.get('frequency_penalty', 0.1),
                    max_tokens=self.config.get('app', {}).get('max_new_tokens', 64),
                    **json_mode_param
                )
                
                text = resp.choices[0].message.content
                # === [End of API Call for OpenAI] ===

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

        raise APIError(f"OpenAI API failed after {retries} retries: {str(last_error)}")

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