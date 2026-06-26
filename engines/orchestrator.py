import logging
logger = logging.getLogger("mahgic")

import asyncio
import argparse
import os
import json
import re

from dotenv import load_dotenv
load_dotenv()

from brains.macro_brain import MacroBrain
from engines.discovery_engine import DiscoveryEngine
from brains.market_brain import MarketBrain
from brains.regulatory_brain import RegulatoryBrain
from providers.llm_provider import get_provider
from scrapers.job_scraper import JobBoardScraper

async def run_pipeline(country: str, proxycurl_key: str = None, limit: int = 30, domain: str = None, budget: int = None):
    from providers.llm_provider import reset_provider
    reset_provider()
    
    if budget:
        os.environ["TOKEN_BUDGET"] = str(budget)
    
    logger.info("="*60)
    logger.info(f"STARTING AI STOCK BRAIN PIPELINE FOR COUNTRY: {country}")
    logger.info("="*60)
    
    total_pipeline_tokens = {"prompt": 0, "response": 0, "total": 0}

    # PHASE 1: Macro Brain (Economy and Macro Trend Identification)
    logger.info("\n>>> PHASE 1: MACRO TREND IDENTIFICATION")
    if domain:
        strategic_keywords = [domain]
        macro_result = {"trends": strategic_keywords, "commentary": "Pre-supplied by user", "sources": []}
        logger.info(f"[+] User-supplied domain/trend: {strategic_keywords}")
    else:
        try:
            macro_brain = MacroBrain()
            macro_result, mb_tokens = macro_brain.get_macro_trends()
            strategic_keywords = macro_result.get("trends", ["Generative AI"])
            for k in total_pipeline_tokens:
                total_pipeline_tokens[k] += mb_tokens.get(k, 0)
            logger.info(f"[+] Macro Brain identified trends: {strategic_keywords}")
        except Exception as e:
            logger.warning(f"[!] Macro Brain failed: {e}. Using fallback trends.")
            strategic_keywords = ["Generative AI", "Quantum Computing", "Space Tech"]
            macro_result = {"trends": strategic_keywords, "commentary": "Fallback", "sources": []}
        
    logger.info(f"[+] Derived Strategic Keywords: {strategic_keywords}")
    # PHASE 1.5: Discovery Engine (Generate 100 Companies)
    logger.info("\n>>> PHASE 1.5: DISCOVERY ENGINE")
    try:
        discovery_engine = DiscoveryEngine()
        discovered_companies, disc_tokens = discovery_engine.generate_companies(country, strategic_keywords)
        logger.info(f"[+] Discovered {len(discovered_companies)} potential companies.")
        
        # Accumulate tokens
        for k in total_pipeline_tokens:
            total_pipeline_tokens[k] += disc_tokens.get(k, 0)
    except Exception as e:
        logger.info(f"[!] Discovery Engine failed: {e}")
        discovered_companies = []
    # PHASE 2 & 3: Market Brain Evaluation & Job Scraper for each ticker
    logger.info("\n>>> PHASE 2 & 3: EVALUATION & INTENT ANALYSIS")
    
    provider = get_provider()
    market_brain = MarketBrain(llm_provider=provider, proxycurl_key=proxycurl_key)
    regulatory_brain = RegulatoryBrain(llm_provider=provider)
    
    hidden_gems = []
    hidden_gems_thesis = {}
    hidden_gems_data = {}
    all_scores = {}
    
    logger.info(f"[*] Processing up to {limit} out of {len(discovered_companies)} tickers for a full end-to-end test...")
    
    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    os.makedirs(os.path.join(BASE_DIR, "results_cache"), exist_ok=True)
    
    for company in discovered_companies[:limit]:
        if not isinstance(company, dict): continue
        ticker = company.get("ticker")
        company_name = company.get("company_name", ticker)
        if not ticker: continue
        logger.info(f"\n--- Analyzing {ticker} ---")
        
        cache_file = os.path.join(BASE_DIR, f"results_cache/{ticker}.json")
        if os.path.exists(cache_file):
            logger.info(f"[*] Found cached results for {ticker}, skipping analysis.")
            with open(cache_file, "r") as f:
                cached = json.load(f)
            score = cached.get("score", 0)
            all_scores[ticker] = score
            if score >= 7:
                hidden_gems.append(ticker)
                hidden_gems_data[ticker] = cached.get("data")
                hidden_gems_thesis[ticker] = cached.get("thesis")
            continue

        try:
            # 1. Financial and Qualitative SEC Evaluation
            data = market_brain.fetch_quarterly_data(ticker)
            report = market_brain.generate_report(data)
            
            # Fetch Regulatory Qualitative Insights
            reg_text, doc_type = regulatory_brain.fetch_regulatory_text(ticker)
            if reg_text:
                reg_eval, reg_tokens = regulatory_brain.evaluate_regulatory_text(reg_text, doc_type)
                for k in total_pipeline_tokens:
                    total_pipeline_tokens[k] += reg_tokens.get(k, 0)
            else:
                reg_eval = f"No {doc_type} data available for automated analysis."
            
            full_report = report + f"\n--- {doc_type} Qualitative Assessment ---\n" + reg_eval
            
            # evaluate queries the Wisdom Corpus and returns score/reasoning
            thesis, mb_tokens = market_brain.evaluate(full_report)
            
            for k in total_pipeline_tokens:
                total_pipeline_tokens[k] += mb_tokens.get(k, 0)
            
            score = 0
            try:
                # Extract JSON using regex in case there's text around it
                json_match = re.search(r'\{.*\}', thesis.replace('\n', ' '))
                if json_match:
                    thesis_json = json.loads(json_match.group(0))
                    score = int(thesis_json.get("score", 0))
                    thesis = thesis_json.get("reasoning", thesis)
            except Exception as e:
                logger.info(f"[!] Failed to parse JSON score: {e}")
            
            logger.info(f"[+] Extracted Hidden Gem Score: {score}/10")
            all_scores[ticker] = score
            
            if score >= 7:
                logger.info(f"[*] {ticker} qualifies as a Hidden Gem! Adding to list.")
                hidden_gems.append(ticker)
                hidden_gems_data[ticker] = data
                
                # 2. Job Board Scraper
                scraper = JobBoardScraper(company_name)
                try:
                    jobs = await scraper.scrape_jobs()
                    intent = scraper.analyze_strategic_intent(jobs, strategic_keywords)
                except Exception as e:
                    logger.info(f"[!] Scraper failed: {e}")
                    intent = {}
                    
                matches_found = any(intent.values())
                if not matches_found:
                    logger.info(f"[-] No matching strategic roles found for trends: {strategic_keywords}")
                    logger.info(f"[*] Look, the job scraper didn't return anything relevant, so we are going to build our analysis for this specific stock using the available information.")

                structured_prompt = f"""
You are an expert fundamental value investor and strategic intent analyst.
Based on the following data for {ticker}, write a 'Hidden Gem Strategic Thesis'.
Use VERY SIMPLE language that is easy to understand. Do not use complex financial jargon.
Format all financial figures using the local currency denominations (e.g., Millions/Billions). For South Asian companies (e.g., India, Pakistan, Bangladesh, Nepal, Sri Lanka), strictly convert and format all large numbers using Crores (Cr) and Lakhs (L).

You must structure your response with these exact sections (use bold headings or bullet points):
1. **Macro Trends:** Explain what macro trends this company satisfies (e.g., {strategic_keywords}).
2. **Job Postings / Strategic Intent:** Detail what job postings we found (if any) or other strategic moves that enforce our analysis of these macro trends. Jobs found: {json.dumps(intent, indent=2)}
3. **Wisdom Brain Application:** Explain what parts of our Wisdom Corpus are applicable. Make sure to include Ashish Chugh's balance sheet insights (Survival Over Profits, Leading vs Lagging Indicators like Capital Work in Progress, and Cash Flow > P&L).
4. **Financial Metrics Summary:** Showcase the key financial metrics studied (e.g., P/E ratio, Debt, Cash, Revenue Growth). Use the data provided below to summarize this.
5. **Leadership Assessment:** List out the C-suite leadership specifically. For each leader, use your internal knowledge and the provided raw data to explain how long they have been at the company and highlight some of their notable career achievements.
6. **Regulatory Qualitative Assessment:** Summarize the major risks, headwinds, and management guidance extracted from the {doc_type} filing (if available).

Raw Financial Data:
{report}

Regulatory Qualitative Assessment:
{reg_eval}
"""             
                final_thesis, ft_tokens = provider.generate(structured_prompt, "You are a strategic intent analyst focusing on simple, structured reporting.")
                
                for k in total_pipeline_tokens:
                    total_pipeline_tokens[k] += ft_tokens.get(k, 0)
                    
                hidden_gems_thesis[ticker] = final_thesis
                
            with open(cache_file, "w") as f:
                json.dump({
                    "score": score,
                    "data": hidden_gems_data.get(ticker),
                    "thesis": hidden_gems_thesis.get(ticker)
                }, f)
                
        except Exception as e:
            logger.info(f"[!] Analysis for {ticker} failed: {e}")
            all_scores[ticker] = -1
            
        await asyncio.sleep(0.5)


    with open(os.path.join(BASE_DIR, "results.json"), "w") as f:
        json.dump({
            "country": country,
            "macro_result": macro_result,
            "discovered_companies": discovered_companies[:limit],
            "hidden_gems": hidden_gems,
            "hidden_gems_thesis": hidden_gems_thesis,
            "hidden_gems_data": hidden_gems_data,
            "all_scores": all_scores,
            "token_usage": total_pipeline_tokens['total'],
            "limit": limit
        }, f, indent=4)

    logger.info("\n" + "="*60)
    logger.info(f"PIPELINE COMPLETE.")
    logger.info(f"Hidden Gems Found: {hidden_gems}")
    logger.info(f"Total Pipeline Token Usage: {total_pipeline_tokens['total']} tokens")
    logger.info("="*60)

# For standalone testing only. Please use run.py to drive the pipeline.
if __name__ == "__main__":
    logger.warning("You are running orchestrator.py directly. This is for testing. Prefer running run.py instead.")
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
            logger.info("Invalid input for limit. Defaulting to 100.")
            limit = 100

    estimated_tokens = limit * 18000
    logger.info(f"\n[*] Estimated Token Usage for {limit} companies: ~{estimated_tokens} tokens")

    asyncio.run(run_pipeline(country, args.proxycurl_key, limit))
