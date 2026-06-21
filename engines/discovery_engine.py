import logging
logger = logging.getLogger("mahgic")

import os
import json
from providers.llm_provider import get_provider

class DiscoveryEngine:
    def __init__(self):
        self.llm = get_provider()
        self.total_tokens = {"prompt": 0, "response": 0, "total": 0}

    def _parse_token_usage(self, response_text: str):
        lines = response_text.split('\n')
        clean_text = ""
        for line in lines:
            if "[Token Usage]" in line:
                try:
                    parts = line.split("|")
                    prompt_tokens = int(parts[0].split(":")[1].strip())
                    response_tokens = int(parts[1].split(":")[1].strip())
                    total_tokens = int(parts[2].split(":")[1].strip())
                    self.total_tokens["prompt"] += prompt_tokens
                    self.total_tokens["response"] += response_tokens
                    self.total_tokens["total"] += total_tokens
                except:
                    pass
                continue
            clean_text += line + "\n"
        return clean_text

    def generate_companies(self, country: str, macro_trends: list) -> list:
        logger.info(f"\n[*] Discovery Engine: Finding up to 100 companies in {country} aligned with {macro_trends}...")
        
        system_instruction = """
        You are an expert financial analyst and stock screener. 
        Your task is to generate a comprehensive list of publicly traded companies (across all market caps: large, mid, and small) that are well-positioned to benefit from specific macro trends.
        
        CRITICAL: You must append the correct Yahoo Finance exchange suffix to the ticker symbols for international stocks based on the requested country. For example:
        - Australia: Append .AX (e.g., BHP.AX)
        - London: Append .L
        - Canada (Toronto): Append .TO
        - Germany: Append .DE
        - India (NSE): Append .NS
        - India (BSE): Append .BO
        If it is a US stock, do not append a suffix.
        
        Return the result as a raw JSON array of objects, where each object has:
        {
            "company_name": "Full Name",
            "ticker": "TICKER.SUFFIX",
            "description": "A brief 1-sentence description of what the company does.",
            "trends_matched": ["Trend 1"]
        }
        DO NOT include any markdown formatting or code blocks. Just output the JSON array.
        """
        
        prompt = f"""
        You are an expert equity screener.
        The current top macro trends are: {', '.join(macro_trends)}

        Return EXACTLY 100 publicly traded companies in {country} that are aligned with these trends.
        Do not return 50. Do not return 99. You MUST return exactly 100 companies.
        If you run out of obvious choices, include tangential or smaller-cap companies until you hit 100.
        Provide the output as a clean JSON array of objects.
        No markdown formatting. Do not wrap in ```json ... ```.

        The JSON array should look exactly like this:
        [
            {{
                "company_name": "Company Name",
                "ticker": "TICKER_SYMBOL",
                "description": "Brief 1-sentence description of what the company actually does.",
                "trends_matched": ["Trend 1", "Trend 2"]
            }}
        ]
        """
        
        response_text = self.llm.generate(prompt, system_instruction)
        clean_text = self._parse_token_usage(response_text)
        
        json_str = ""
        for line in clean_text.split('\n'):
            if line.startswith("```"):
                continue
            json_str += line + "\n"
            
        try:
            tickers = json.loads(json_str.strip())
            if isinstance(tickers, list):
                return tickers
            else:
                return []
        except Exception as e:
            logger.info(f"[!] Error parsing Discovery Engine output: {e}")
            return []
