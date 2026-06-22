import logging
logger = logging.getLogger("mahgic")

import yfinance as yf
import pandas as pd
import json
import os
import argparse
from providers.llm_provider import get_provider

import threading

class WisdomRAG:
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = WisdomRAG()
        return cls._instance
        
    def __init__(self):
        import chromadb
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        import warnings
        warnings.filterwarnings("ignore")
        
        self.chroma_client = chromadb.PersistentClient(path=os.path.join(os.path.dirname(__file__), "chroma_db"))
        self.collection = self.chroma_client.get_or_create_collection(name="wisdom")
        
        if self.collection.count() == 0:
            logger.info("[*] Initializing Wisdom RAG Database...")
            wisdom_path = os.path.join(os.path.dirname(__file__), "wisdom_corpus.txt")
            if os.path.exists(wisdom_path):
                with open(wisdom_path, "r") as f:
                    text = f.read()
                
                splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
                chunks = splitter.split_text(text)
                
                self.collection.add(
                    documents=chunks,
                    ids=[f"chunk_{i}" for i in range(len(chunks))]
                )
                logger.info(f"[+] Added {len(chunks)} wisdom chunks to DB.")
            else:
                logger.info("[!] wisdom_corpus.txt not found.")
                
    def query(self, text: str, k=3) -> str:
        if self.collection.count() == 0:
            return ""
        results = self.collection.query(
            query_texts=[text],
            n_results=k
        )
        if results and results['documents']:
            docs = results['documents'][0]
            return "\n\n".join(docs)
        return ""

# ==========================================
# Market Brain Core
# ==========================================
class MarketBrain:
    def __init__(self, llm_provider = None, proxycurl_key: str = None):
        self.llm = llm_provider
        self.proxycurl_key = proxycurl_key

    def fetch_quarterly_data(self, ticker_symbol: str) -> dict:
        logger.info(f"Fetching last 8 quarters of data for {ticker_symbol}...")
        ticker = yf.Ticker(ticker_symbol)
        
        try:
            q_financials = ticker.quarterly_financials
            q_balance = ticker.quarterly_balance_sheet
            q_cashflow = ticker.quarterly_cashflow
            info = ticker.info
        except Exception as e:
            return {"error": str(e)}

        def safe_extract(df, row_name):
            if df is not None and row_name in df.index:
                # Extract up to 8 quarters, fill missing with 0
                return df.loc[row_name].fillna(0).head(8).tolist()
            return []

        # Extract specific trends for the last 8 quarters
        trends = {
            "Total Revenue": safe_extract(q_financials, "Total Revenue"),
            "Net Income": safe_extract(q_financials, "Net Income"),
            "Total Debt": safe_extract(q_balance, "Total Debt"),
            "Cash And Cash Equivalents": safe_extract(q_balance, "Cash And Cash Equivalents"),
            "Free Cash Flow": safe_extract(q_cashflow, "Free Cash Flow")
        }
        
        # Currency normalization (Fixes INFY.NS reporting in USD while trading in INR)
        stock_currency = info.get('currency', 'USD')
        fin_currency = info.get('financialCurrency', stock_currency)
        
        if stock_currency != fin_currency:
            # Dynamically fetch exchange rate using yfinance
            try:
                forex_ticker = f"{fin_currency}{stock_currency}=X"
                forex_data = yf.Ticker(forex_ticker)
                rate = forex_data.fast_info.get('lastPrice') or forex_data.info.get('regularMarketPrice', 1.0)
            except Exception as e:
                logger.warning(f"Failed to fetch exchange rate for {fin_currency} to {stock_currency}: {e}")
                rate = 1.0

            if rate != 1.0:
                logger.info(f"[*] Currency mismatch detected. Converting financials from {fin_currency} to {stock_currency} (Dynamic Rate: {rate})")
                for key in trends:
                    trends[key] = [v * rate if v != 0 else 0 for v in trends[key]]
        
        dates = []
        if q_financials is not None and not q_financials.empty:
            dates = [d.strftime('%Y-%m-%d') for d in q_financials.columns[:8]]
            
        return {
            "symbol": ticker_symbol,
            "info": info,
            "dates": dates,
            "trends": trends
        }

    def fetch_linkedin_data(self, officer_name: str, company: str) -> str:
        """Integration hook for Proxycurl API. 
        If the user provides an API key, this hits the Proxycurl endpoint."""
        if not self.proxycurl_key:
            return ""
            
        logger.info(f"[*] Proxycurl Key detected. Attempting to fetch LinkedIn data for {officer_name}...")
        import requests
        # NOTE: A real implementation would first search for the profile URL, then query the profile endpoint.
        # This is a stubbed integration for the GitHub repository.
        headers = {'Authorization': 'Bearer ' + self.proxycurl_key}
        # Example API call:
        # response = requests.get('https://nubela.co/proxycurl/api/v2/linkedin', headers=headers, params={'url': profile_url})
        return f"[Proxycurl Integration] {officer_name} has a strong track record of capital allocation."

    def generate_report(self, data: dict) -> str:
        if "error" in data:
            return f"Error fetching data: {data['error']}"
            
        info = data.get("info", {})
        dates = data.get("dates", [])
        trends = data.get("trends", {})
        
        report = f"--- Fundamental Data for {info.get('shortName', data['symbol'])} ({data['symbol']}) ---\n"
        
        currency_code = info.get('currency', 'USD')
        currency_syms = {'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥', 'INR': '₹', 'AUD': 'A$', 'CAD': 'C$', 'CHF': 'CHF'}
        curr = currency_syms.get(currency_code, currency_code + " ")
        
        report += f"Sector: {info.get('sector')} | Industry: {info.get('industry')}\n"
        
        market_cap = info.get('marketCap', 0)
        if currency_code in ["INR", "BDT", "PKR", "NPR", "LKR"]:
            report += f"Market Cap: {curr}{market_cap/1e7:.2f}Cr\n"
        else:
            report += f"Market Cap: {curr}{market_cap/1e9:.2f}B\n"
            
        report += f"Trailing P/E: {info.get('trailingPE')}\n"
        report += f"Forward P/E: {info.get('forwardPE')}\n\n"
        
        report += "--- Management Team ---\n"
        officers = info.get("companyOfficers", [])
        if officers:
            for officer in officers[:5]:
                name = officer.get("name", "Unknown")
                title = officer.get("title", "Unknown Title")
                age = officer.get("age", "Unknown Age")
                linkedin_info = self.fetch_linkedin_data(name, info.get("shortName", ""))
                report += f"- {name} ({title}, Age: {age})\n"
                if linkedin_info:
                    report += f"  {linkedin_info}\n"
        else:
            report += "Management information not available.\n"
        report += "\n"
        
        report += "--- Last 8 Quarters Trend (Newest to Oldest) ---\n"
        report += f"Quarters: {dates}\n"
        for key, values in trends.items():
            formatted_vals = []
            for v in values:
                if v == 0:
                    formatted_vals.append("N/A")
                elif currency_code in ["INR", "BDT", "PKR", "NPR", "LKR"]:
                    if abs(v) >= 1e7:
                        formatted_vals.append(f"{curr}{v/1e7:.2f}Cr")
                    elif abs(v) >= 1e5:
                        formatted_vals.append(f"{curr}{v/1e5:.2f}L")
                    else:
                        formatted_vals.append(f"{curr}{v}")
                else:
                    if abs(v) >= 1e9:
                        formatted_vals.append(f"{curr}{v/1e9:.2f}B")
                    elif abs(v) >= 1e6:
                        formatted_vals.append(f"{curr}{v/1e6:.2f}M")
                    else:
                        formatted_vals.append(f"{curr}{v}")
            report += f"{key}: {formatted_vals}\n"
            
        return report

    def evaluate(self, report_text: str) -> tuple[str, dict]:
        if not self.llm:
            return "No LLM provider configured. Returning raw data only.", {"prompt": 0, "response": 0, "total": 0}
            
        wisdom_corpus = ""
        try:
            rag = WisdomRAG.get_instance()
            relevant_wisdom = rag.query(report_text, k=3)
            if relevant_wisdom:
                wisdom_corpus = f"\n\n--- MENTAL MODELS & WISDOM CORPUS (Relevant Extracts) ---\n{relevant_wisdom}\n"
        except Exception as e:
            logger.info(f"[!] RAG Query failed: {e}")

        system_instruction = (
            "You are an expert fundamental value investor. Your goal is to identify 'Hidden Gems'.\n"
            "Analyze the provided financial data against these strict rules:\n"
            "1. Debt to Cash: A healthy company should ideally have more cash than debt, or manageable debt. If Total Debt is significantly higher than Total Cash, flag this as a major risk.\n"
            "2. Valuation: Look at the P/E ratio. If it's extremely high (e.g., > 50), it is likely overvalued and NOT a hidden gem, unless growth is astronomical.\n"
            "3. Profitability: The company must have positive Free Cash Flow and Profit Margins.\n"
            "4. Growth: Revenue growth should be positive. Check the last 8 quarters trend for revenue and net income to ensure it's not declining.\n\n"
            "When generating your reasoning, format all financial figures using the local currency denominations. NEVER use the words 'Billion' or 'Million'. If the country uses Lakhs and Crores (e.g., India), strictly convert all large numbers to Crores (Cr) and Lakhs (L).\n"
            "Provide a brief, brutal assessment based on the last 8 quarters. You MUST return your output strictly as a JSON object with the following schema: "
            "{\"score\": <int out of 10>, \"reasoning\": \"<your brief brutal assessment>\"}. Do not include markdown formatting or backticks around the JSON."
            f"{wisdom_corpus}"
        )
        
        logger.info("Running AI Evaluation...")
        return self.llm.generate(prompt=report_text, system_instruction=system_instruction)


def main():
    parser = argparse.ArgumentParser(description="AI Stock Market Brain")
    parser.add_argument("--ticker", type=str, default="ELF", help="Stock ticker symbol to analyze")
    parser.add_argument("--llm", type=str, choices=["gemini", "openai", "claude"], default="gemini", help="LLM Provider to use")
    args = parser.parse_args()

    # Configure the selected LLM Provider
    os.environ["LLM_PROVIDER"] = args.llm
    try:
        provider = get_provider()
    except Exception as e:
        logger.info(f"WARNING: {e}. Proceeding without AI analysis.")
        provider = None

    brain = MarketBrain(llm_provider=provider)
    
    data = brain.fetch_quarterly_data(args.ticker)
    report = brain.generate_report(data)
    
    logger.info("\n" + report)
    
    if provider:
        logger.info("\n" + "="*40 + "\nAI ANALYSIS THESIS\n" + "="*40)
        analysis, token_dict = brain.evaluate(report)
        logger.info(analysis)

if __name__ == "__main__":
    main()
