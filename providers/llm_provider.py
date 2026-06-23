from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, system_instruction: str, max_tokens: int = 8192) -> tuple[str, dict]:
        pass

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
            self.genai = genai
        except ImportError:
            raise ImportError("Please install google-genai: pip install google-genai")
        
    def generate(self, prompt: str, system_instruction: str, max_tokens: int = 8192) -> tuple[str, dict]:
        try:
            response = self.client.models.generate_content(
                model='gemini-3.1-pro-preview',
                contents=prompt,
                config=self.genai.types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    max_output_tokens=max_tokens,
                ),
            )
            
            # Extract token usage
            usage = response.usage_metadata
            token_info = {"prompt": usage.prompt_token_count, "response": usage.candidates_token_count, "total": usage.total_token_count}
            
            return response.text, token_info
        except Exception as e:
            return f"Error connecting to Gemini: {e}", {}

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str):
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("Please install openai: pip install openai")
        
    def generate(self, prompt: str, system_instruction: str, max_tokens: int = 8192) -> tuple[str, dict]:
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ]
            )
            usage = response.usage
            token_info = {"prompt": usage.prompt_tokens, "response": usage.completion_tokens, "total": usage.total_tokens}
            return response.choices[0].message.content, token_info
        except Exception as e:
            return f"Error connecting to OpenAI: {e}", {}

class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str):
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("Please install anthropic: pip install anthropic")
        
    def generate(self, prompt: str, system_instruction: str, max_tokens: int = 8192) -> tuple[str, dict]:
        actual_max_tokens = min(max_tokens, 8192)
        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=actual_max_tokens,
                system=system_instruction,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            usage = response.usage
            token_info = {"prompt": usage.input_tokens, "response": usage.output_tokens, "total": usage.input_tokens + usage.output_tokens}
            return response.content[0].text, token_info
        except Exception as e:
            return f"Error connecting to Claude: {e}", {}

def get_provider() -> LLMProvider:
    import os
    provider_name = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if provider_name == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        return OpenAIProvider(api_key)
    elif provider_name in ["claude", "anthropic"]:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
        return ClaudeProvider(api_key)
    else:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        return GeminiProvider(api_key)
