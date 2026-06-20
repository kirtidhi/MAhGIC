import asyncio
import argparse
import os

from macro_brain import MacroBrain
from discovery_engine import DiscoveryEngine
from market_brain import MarketBrain
from llm_provider import get_provider
from job_scraper import JobBoardScraper

async def run_pipeline(country: str, proxycurl_key: str = None, limit: int = 30):
    print("="*60)
    print(f"STARTING AI STOCK BRAIN PIPELINE FOR COUNTRY: {country}")
    print("="*60)
    
    total_pipeline_tokens = {"prompt": 0, "response": 0, "total": 0}

    # PHASE 1: Macro Brain (Economy and Macro Trend Identification)
    print("\n>>> PHASE 1: MACRO TREND IDENTIFICATION")
    try:
        macro_brain = MacroBrain()
        macro_result = macro_brain.get_macro_trends()
        if isinstance(macro_result, dict):
            strategic_keywords = macro_result.get("trends", [])
            macro_commentary = macro_result.get("commentary", "")
            macro_sources = macro_result.get("sources", [])
        else:
            strategic_keywords = macro_result
            macro_commentary = ""
            macro_sources = []
        print(f"[+] Derived Strategic Keywords: {strategic_keywords}")
    except Exception as e:
        print(f"[!] Macro Brain failed: {e}")
        strategic_keywords = ["Generative AI", "Quantum Computing", "Space Tech"] # fallback
        macro_result = {"trends": strategic_keywords, "commentary": "Fallback", "sources": []}
    # PHASE 1.5: Discovery Engine (Generate 100 Companies)
    print("\n>>> PHASE 1.5: DISCOVERY ENGINE")
    try:
        discovery_engine = DiscoveryEngine()
        discovered_companies = discovery_engine.generate_companies(country, strategic_keywords)
        print(f"[+] Discovered {len(discovered_companies)} potential companies.")
        
        # Accumulate tokens
        for k in total_pipeline_tokens:
            total_pipeline_tokens[k] += discovery_engine.total_tokens[k]
    except Exception as e:
        print(f"[!] Discovery Engine failed: {e}")
        discovered_companies = []
    # PHASE 2 & 3: Market Brain Evaluation & Job Scraper for each ticker
    print("\n>>> PHASE 2 & 3: EVALUATION & INTENT ANALYSIS")
    
    provider = get_provider()
    market_brain = MarketBrain(llm_provider=provider, proxycurl_key=proxycurl_key)
    
    hidden_gems = []
    hidden_gems_thesis = {}
    hidden_gems_data = {}
    all_scores = {}
    
    print(f"[*] Processing up to {limit} out of {len(discovered_companies)} tickers for a full end-to-end test...")
    
    for company in discovered_companies[:limit]:
        if not isinstance(company, dict): continue
        ticker = company.get("ticker")
        if not ticker: continue
        print(f"\n--- Analyzing {ticker} ---")
        try:
            # 1. Financial Evaluation
            data = market_brain.fetch_quarterly_data(ticker)
            report = market_brain.generate_report(data)
            thesis = market_brain.evaluate(report)
            
            score = 0
            for line in thesis.split('\n'):
                if "Hidden Gem Score:" in line:
                    try:
                        score = int(line.split(":")[1].strip().split("/")[0])
                    except:
                        pass
                elif "[Token Usage]" in line:
                    try:
                        parts = line.split("|")
                        total_pipeline_tokens["prompt"] += int(parts[0].split(":")[1].strip())
                        total_pipeline_tokens["response"] += int(parts[1].split(":")[1].strip())
                        total_pipeline_tokens["total"] += int(parts[2].split(":")[1].strip())
                    except:
                        pass
            
            print(f"[+] Extracted Hidden Gem Score: {score}/10")
            all_scores[ticker] = score
            
            if score >= 6:
                print(f"[*] {ticker} qualifies as a Hidden Gem! Adding to list.")
                hidden_gems.append(ticker)
                hidden_gems_data[ticker] = data
                
                # 2. Job Board Scraper (Assume a generic URL for now)
                clean_ticker = ticker.lower().split('.')[0]
                jobs_url = f"https://careers.{clean_ticker}.com/"
                print(f"[*] Attempting to scrape job board at: {jobs_url}")
                scraper = JobBoardScraper(jobs_url)
                try:
                    jobs = await scraper.scrape_jobs()
                    intent = scraper.analyze_strategic_intent(jobs, strategic_keywords)
                except Exception as e:
                    print(f"[!] Scraper failed: {e}")
                    intent = {}
                    
                matches_found = any(intent.values())
                if not matches_found:
                    print(f"[-] No matching strategic roles found for trends: {strategic_keywords}")
                    print(f"[*] Look, the job scraper didn't return anything relevant, so we are going to build our analysis for this specific stock using the available information.")

                # Final Phase 3 Structured LLM Analysis
                structured_prompt = f"""
You are an expert fundamental value investor and strategic intent analyst.
Based on the following data for {ticker}, write a 'Hidden Gem Strategic Thesis'.
Use VERY SIMPLE language that is easy to understand. Do not use complex financial jargon.

You must structure your response with these exact sections (use bold headings or bullet points):
1. **Macro Trends:** Explain what macro trends this company satisfies (e.g., {strategic_keywords}).
2. **Job Postings / Strategic Intent:** Detail what job postings we found (if any) or other strategic moves that enforce our analysis of these macro trends. Jobs found: {intent}
3. **Wisdom Brain Application:** Explain what parts of our Wisdom Corpus are applicable. Make sure to include Ashish Chugh's balance sheet insights (Survival Over Profits, Leading vs Lagging Indicators like Capital Work in Progress, and Cash Flow > P&L).
4. **Financial Metrics Summary:** Showcase the key financial metrics studied (e.g., P/E ratio, Debt, Cash, Revenue Growth). Use the data provided below to summarize this.
5. **Leadership Assessment:** List out the C-suite leadership specifically. For each leader, use your internal knowledge and the provided raw data to explain how long they have been at the company and highlight some of their notable career achievements.

Raw Financial Data:
{report}
"""             
                final_thesis = provider.generate(structured_prompt, "You are a strategic intent analyst focusing on simple, structured reporting.")
                hidden_gems_thesis[ticker] = final_thesis
                
        except Exception as e:
            print(f"[!] Analysis for {ticker} failed: {e}")
            all_scores[ticker] = -1


    import json
    with open("results.json", "w") as f:
        json.dump({
            "country": country,
            "macro_result": macro_result,
            "discovered_companies": discovered_companies,
            "hidden_gems": hidden_gems,
            "hidden_gems_thesis": hidden_gems_thesis,
            "hidden_gems_data": hidden_gems_data,
            "all_scores": all_scores,
            "token_usage": total_pipeline_tokens['total'],
            "limit": limit
        }, f, indent=4)

    print("\n" + "="*60)
    print(f"PIPELINE COMPLETE.")
    print(f"Hidden Gems Found: {hidden_gems}")
    print(f"Total Pipeline Token Usage: {total_pipeline_tokens['total']} tokens")
    print("="*60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Stock Brain Orchestrator Wrapper")
    parser.add_argument("--country", required=False, help="Target country for stock discovery")
    parser.add_argument("--proxycurl-key", type=str, default=None, help="Optional Proxycurl API key to fetch deep LinkedIn management data")
    parser.add_argument("--limit", type=int, default=None, help="Number of companies to analyze")
    args = parser.parse_args()

    country = args.country
    if not country:
        country = input("Which country's stocks would you like to analyze? ")

    limit = args.limit
    if limit is None:
        try:
            limit_input = input("How many companies would you like to run the analysis for? (e.g. 100): ")
            limit = int(limit_input)
        except ValueError:
            print("Invalid input for limit. Defaulting to 100.")
            limit = 100

    estimated_tokens = limit * 18000
    print(f"\n[*] Estimated Token Usage for {limit} companies: ~{estimated_tokens} tokens")

    asyncio.run(run_pipeline(country, args.proxycurl_key, limit))
