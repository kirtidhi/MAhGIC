import logging
logger = logging.getLogger("mahgic")

import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import argparse
import requests
import re
from urllib.parse import urlparse, parse_qs

class JobBoardScraper:
    def __init__(self, company_name: str):
        self.company_name = company_name
        self.target_url = None

    async def scrape_jobs(self):
        logger.info(f"[*] Finding careers page for {self.company_name}...")
        try:
            res = requests.get(f"https://html.duckduckgo.com/html/?q={self.company_name}+careers+site", headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            soup = BeautifulSoup(res.text, 'html.parser')
            urls = [parse_qs(urlparse(a['href']).query).get('uddg', [''])[0] for a in soup.find_all('a', class_='result__url')]
            if urls and urls[0]:
                self.target_url = urls[0]
                logger.info(f"[*] Found careers URL: {self.target_url}")
            else:
                logger.info(f"[!] Could not find careers page for {self.company_name}")
                return []
        except Exception as e:
            logger.info(f"[!] DuckDuckGo search failed: {e}")
            return []

        logger.info(f"[*] Navigating to {self.target_url}...")
        jobs = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(self.target_url, wait_until="domcontentloaded", timeout=60000)
                
                # We extract the entire HTML to parse it simply
                html_content = await page.content()
                await browser.close()
                
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Basic heuristic: look for links or headers that look like job postings
                # Many ATS systems (Lever/Greenhouse) use div classes like 'posting', 'job', 'position'
                # Or we can just look for <a> tags with hrefs containing 'job' or 'careers'
                
                # Example: Greenhouse uses <div class="opening">
                # Lever uses <div class="posting">
                for item in soup.find_all(['div', 'li', 'a'], class_=lambda x: x and any(c in str(x).lower() for c in ['posting', 'opening', 'job', 'position'])):
                    # Get the title text
                    title_elem = item.find(['h2', 'h3', 'h4', 'h5', 'a', 'span'])
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        if title and title not in jobs:
                            jobs.append(title)
                
                # If heuristic fails, fallback to links that might be jobs
                if not jobs:
                    for a in soup.find_all('a', href=True):
                        href = a['href'].lower()
                        if 'job' in href or 'career' in href or 'role' in href:
                            title = a.get_text(strip=True)
                            if title and len(title) > 5 and title not in jobs:
                                jobs.append(title)
                                
        except Exception as e:
            logger.info(f"[!] Error scraping {self.target_url}: {e}")

        return jobs

    def analyze_strategic_intent(self, jobs: list, keywords: list) -> dict:
        """
        Check if the scraped jobs match specific strategic keywords.
        Returns a dict of matched keywords and the corresponding job titles.
        """
        results = {kw: [] for kw in keywords}
        
        for job in jobs:
            job_lower = job.lower()
            for kw in keywords:
                if re.search(r'\b' + re.escape(kw.lower()) + r'\b', job_lower):
                    results[kw].append(job)
                    
        if not any(results.values()):
            logger.info("[*] Direct scraping found no matching roles. Falling back to web search workaround...")
            try:
                for kw in keywords:
                    query = f"{self.company_name}+careers+{kw.replace(' ', '+')}"
                    res = requests.get(f"https://html.duckduckgo.com/html/?q={query}", headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    soup = BeautifulSoup(res.text, 'html.parser')
                    for a in soup.find_all('a', class_='result__snippet')[:3]:
                        title = a.get_text(strip=True)
                        if title:
                            results[kw].append(title)
            except Exception as e:
                logger.info(f"[!] Web search fallback failed: {e}")
                
        return results

async def main():
    parser = argparse.ArgumentParser(description="Job Board Scraper for Strategic Intent")
    parser.add_argument("--company", required=True, help="Name of the company")
    parser.add_argument("--keywords", nargs="+", default=["AI", "Machine Learning", "Data", "Automation", "Engineer", "Cloud"], help="Keywords to look for")
    args = parser.parse_args()

    scraper = JobBoardScraper(args.company)
    jobs = await scraper.scrape_jobs()
    
    logger.info(f"\n--- Scraped {len(jobs)} potential job postings ---")
    if jobs:
        logger.info("Sample jobs:")
        for j in jobs[:10]:
            logger.info(f" - {j}")
            
    logger.info(f"\n--- Strategic Intent Analysis (Keywords: {', '.join(args.keywords)}) ---")
    intent = scraper.analyze_strategic_intent(jobs, args.keywords)
    
    matches_found = False
    for kw, matched_jobs in intent.items():
        if matched_jobs:
            matches_found = True
            logger.info(f"\n[{kw}] roles found ({len(matched_jobs)}):")
            for j in matched_jobs[:5]:
                logger.info(f"  * {j}")
                
    if not matches_found:
        logger.info("\nNo matching strategic roles found based on the provided keywords.")

if __name__ == "__main__":
    asyncio.run(main())
