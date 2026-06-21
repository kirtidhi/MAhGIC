from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, system_instruction: str) -> str:
        pass

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
            self.genai = genai
        except ImportError:
            raise ImportError("Please install google-genai: pip install google-genai")
        
    def generate(self, prompt: str, system_instruction: str) -> str:
        try:
            response = self.client.models.generate_content(
                model='gemini-3.1-pro-preview',
                contents=prompt,
                config=self.genai.types.GenerateContentConfig(
                    system_instruction=system_instruction,
                ),
            )
            
            # Extract token usage
            usage = response.usage_metadata
            token_info = f"\n[Token Usage] Prompt: {usage.prompt_token_count} | Response: {usage.candidates_token_count} | Total: {usage.total_token_count}"
            
            return response.text + "\n" + token_info
        except Exception as e:
            return f"Error connecting to Gemini: {e}"

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str):
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            raise ImportError("Please install openai: pip install openai")
        
    def generate(self, prompt: str, system_instruction: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ]
            )
            usage = response.usage
            token_info = f"\n[Token Usage] Prompt: {usage.prompt_tokens} | Response: {usage.completion_tokens} | Total: {usage.total_tokens}"
            return response.choices[0].message.content + token_info
        except Exception as e:
            return f"Error connecting to OpenAI: {e}"

class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str):
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key)
        except ImportError:
            raise ImportError("Please install anthropic: pip install anthropic")
        
    def generate(self, prompt: str, system_instruction: str) -> str:
        try:
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4096,
                system=system_instruction,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            usage = response.usage
            token_info = f"\n[Token Usage] Prompt: {usage.input_tokens} | Response: {usage.output_tokens} | Total: {usage.input_tokens + usage.output_tokens}"
            return response.content[0].text + token_info
        except Exception as e:
            return f"Error connecting to Claude: {e}"

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
