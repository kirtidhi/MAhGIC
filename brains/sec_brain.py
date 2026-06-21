import logging
import yfinance as yf
import requests
import argparse
import os
from bs4 import BeautifulSoup
from providers.llm_provider import get_provider

logger = logging.getLogger("mahgic")

class SECBrain:
    def __init__(self, llm_provider=None):
        self.llm = llm_provider
        # SEC EDGAR requires a custom User-Agent
        self.headers = {
            "User-Agent": "MAhGIC Analysis (mahgic@example.com)"
        }

    def fetch_10k_text(self, ticker_symbol: str) -> str:
        logger.info(f"[*] Fetching SEC 10-K for {ticker_symbol}...")
        try:
            ticker = yf.Ticker(ticker_symbol)
            filings = ticker.get_sec_filings()
            
            # Find the latest 10-K
            ten_k_url = None
            if filings:
                for filing in filings:
                    if filing.get("type") == "10-K":
                        exhibits = filing.get("exhibits", {})
                        if "10-K" in exhibits:
                            ten_k_url = exhibits["10-K"]
                            break
            
            if not ten_k_url:
                logger.info(f"[!] No 10-K found for {ticker_symbol}")
                return ""
                
            logger.info(f"[*] Found 10-K URL: {ten_k_url}")
            
            # Request the 10-K HTML
            response = requests.get(ten_k_url, headers=self.headers)
            if response.status_code != 200:
                logger.info(f"[!] Failed to fetch 10-K. Status: {response.status_code}")
                return ""
                
            # Parse HTML to text
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text(separator=' ')
            
            # Clean up excessive newlines and whitespace
            lines = [line.strip() for line in text.split(' ') if line.strip()]
            clean_text = ' '.join(lines)
            
            # We take a reasonable chunk to fit in standard context windows.
            # In a full RAG pipeline, we would chunk this and store in ChromaDB.
            # For now, we take the first 60,000 characters which often covers Business and Risk Factors.
            logger.info(f"[*] Extracted {len(clean_text)} characters. Truncating to 60k for LLM context.")
            return clean_text[:60000]
            
        except Exception as e:
            logger.info(f"[!] SEC 10-K fetch error for {ticker_symbol}: {e}")
            return ""

    def evaluate_10k(self, ten_k_text: str) -> str:
        if not self.llm:
            return "No LLM provider configured."
        if not ten_k_text:
            return "No 10-K data available."
            
        system_instruction = (
            "You are an expert fundamental value investor. "
            "Analyze this extract from the company's SEC 10-K filing. "
            "Do not just look for keywords; deeply analyze the context, tone, and actual meaning of what management is saying. "
            "Focus on identifying:\n"
            "1. Major business risks and headwinds.\n"
            "2. Management's forward-looking guidance and strategic outlook.\n"
            "3. Any qualitative advantages (moats) that pure financial numbers wouldn't show.\n\n"
            "Provide a concise, critical qualitative assessment. Return your response in plain text."
        )
        
        logger.info("[*] Running AI Evaluation on 10-K...")
        return self.llm.generate(prompt=ten_k_text, system_instruction=system_instruction)


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="SEC 10-K Brain")
    parser.add_argument("--ticker", type=str, default="AAPL", help="Stock ticker symbol to analyze")
    parser.add_argument("--llm", type=str, choices=["gemini", "openai", "claude"], default="gemini", help="LLM Provider to use")
    args = parser.parse_args()

    os.environ["LLM_PROVIDER"] = args.llm
    from dotenv import load_dotenv
    load_dotenv()
    
    try:
        provider = get_provider()
    except Exception as e:
        logger.info(f"WARNING: {e}. Proceeding without AI analysis.")
        provider = None

    brain = SECBrain(llm_provider=provider)
    text = brain.fetch_10k_text(args.ticker)
    
    if text and provider:
        logger.info("\n" + "="*40 + "\n10-K QUALITATIVE ANALYSIS\n" + "="*40)
        analysis = brain.evaluate_10k(text)
        logger.info(analysis)

if __name__ == "__main__":
    main()
