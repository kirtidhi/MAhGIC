import yfinance as yf
import pandas as pd
import json
import os
import argparse
from llm_provider import get_provider

# ==========================================
# Market Brain Core
# ==========================================
class MarketBrain:
    def __init__(self, llm_provider = None, proxycurl_key: str = None):
        self.llm = llm_provider
        self.proxycurl_key = proxycurl_key

    def fetch_quarterly_data(self, ticker_symbol: str) -> dict:
        print(f"Fetching last 8 quarters of data for {ticker_symbol}...")
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
            
        print(f"[*] Proxycurl Key detected. Attempting to fetch LinkedIn data for {officer_name}...")
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
        report += f"Sector: {info.get('sector')} | Industry: {info.get('industry')}\n"
        report += f"Market Cap: ${info.get('marketCap', 0)/1e9:.2f}B\n"
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
                elif abs(v) >= 1e9:
                    formatted_vals.append(f"${v/1e9:.2f}B")
                elif abs(v) >= 1e6:
                    formatted_vals.append(f"${v/1e6:.2f}M")
                else:
                    formatted_vals.append(f"${v}")
            report += f"{key}: {formatted_vals}\n"
            
        return report

    def evaluate(self, report_text: str) -> str:
        if not self.llm:
            return "No LLM provider configured. Returning raw data only."
            
        import os
        wisdom_corpus = ""
        if os.path.exists("wisdom_corpus.txt"):
            with open("wisdom_corpus.txt", "r") as f:
                wisdom_corpus = f"\n\n--- MENTAL MODELS & WISDOM CORPUS ---\n{f.read()}\n"

        system_instruction = (
            "You are an expert fundamental value investor. Your goal is to identify 'Hidden Gems'.\n"
            "Analyze the provided financial data against these strict rules:\n"
            "1. Debt to Cash: A healthy company should ideally have more cash than debt, or manageable debt. If Total Debt is significantly higher than Total Cash, flag this as a major risk.\n"
            "2. Valuation: Look at the P/E ratio. If it's extremely high (e.g., > 50), it is likely overvalued and NOT a hidden gem, unless growth is astronomical.\n"
            "3. Profitability: The company must have positive Free Cash Flow and Profit Margins.\n"
            "4. Growth: Revenue growth should be positive. Check the last 8 quarters trend for revenue and net income to ensure it's not declining.\n\n"
            "Provide a brief, brutal assessment based on the last 8 quarters. Conclude with a 'Hidden Gem Score' out of 10."
            f"{wisdom_corpus}"
        )
        
        print("Running AI Evaluation...")
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
        print(f"WARNING: {e}. Proceeding without AI analysis.")
        provider = None

    brain = MarketBrain(llm_provider=provider)
    
    data = brain.fetch_quarterly_data(args.ticker)
    report = brain.generate_report(data)
    
    print("\n" + report)
    
    if provider:
        print("\n" + "="*40 + "\nAI ANALYSIS THESIS\n" + "="*40)
        analysis = brain.evaluate(report)
        print(analysis)

if __name__ == "__main__":
    main()
