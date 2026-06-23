import logging
logger = logging.getLogger("mahgic")

import os
import json
from providers.llm_provider import get_provider

class DiscoveryEngine:
    def __init__(self):
        self.llm = get_provider()



    def generate_companies(self, country: str, macro_trends: list) -> tuple[list, dict]:
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
        
        response_text, token_dict = self.llm.generate(prompt, system_instruction)
        
        json_str = ""
        for line in response_text.split('\n'):
            if line.startswith("```"):
                continue
            json_str += line + "\n"
            
        try:
            tickers = json.loads(json_str.strip())
        except Exception as e:
            logger.info(f"[!] Error parsing Discovery Engine output: {e}. Retrying with smaller batch (50)...")
            retry_prompt = prompt.replace("EXACTLY 100", "EXACTLY 50").replace("hit 100", "hit 50")
            retry_response, retry_tokens = self.llm.generate(retry_prompt, system_instruction)
            
            for k in token_dict:
                token_dict[k] += retry_tokens.get(k, 0)
                
            json_str = ""
            for line in retry_response.split('\n'):
                if line.startswith("```"):
                    continue
                json_str += line + "\n"
                
            try:
                tickers = json.loads(json_str.strip())
            except Exception as e2:
                logger.info(f"[!] Error parsing Discovery Engine retry output: {e2}. Attempting partial recovery...")
                last_brace = json_str.rfind('}')
                if last_brace != -1:
                    partial_json = json_str[:last_brace+1] + "\n]"
                    try:
                        tickers = json.loads(partial_json)
                        logger.info(f"[*] Recovered {len(tickers)} companies from partial JSON.")
                    except Exception as e3:
                        logger.info(f"[!] Partial recovery failed: {e3}")
                        return [], token_dict
                else:
                    return [], token_dict

        if isinstance(tickers, list):
            import yfinance as yf
            from concurrent.futures import ThreadPoolExecutor
            
            def is_valid(company):
                ticker = company.get("ticker")
                if not ticker: return None
                try:
                    info = yf.Ticker(ticker).fast_info
                    if info.get("lastPrice") is not None:
                        return company
                except:
                    pass
                return None

            with ThreadPoolExecutor(max_workers=10) as ex:
                results = list(ex.map(is_valid, tickers))
            
            valid_tickers = [r for r in results if r]
            return valid_tickers, token_dict
        else:
            return [], token_dict
