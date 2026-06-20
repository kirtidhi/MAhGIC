import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import argparse

class JobBoardScraper:
    def __init__(self, target_url: str):
        self.target_url = target_url

    async def scrape_jobs(self):
        print(f"[*] Navigating to {self.target_url}...")
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
            print(f"[!] Error scraping {self.target_url}: {e}")

        return jobs

    def analyze_strategic_intent(self, jobs: list, keywords: list) -> dict:
        """
        Check if the scraped jobs match specific strategic keywords.
        Returns a dict of matched keywords and the corresponding job titles.
        """
        results = {kw: [] for kw in keywords}
        
        import re
        for job in jobs:
            job_lower = job.lower()
            for kw in keywords:
                if re.search(r'\b' + re.escape(kw.lower()) + r'\b', job_lower):
                    results[kw].append(job)
                    
        if not any(results.values()):
            print("[*] Direct scraping found no matching roles. Falling back to web search workaround...")
            try:
                from ddgs import DDGS
                from urllib.parse import urlparse
                domain = urlparse(self.target_url).netloc
                domain = domain.replace("careers.", "") # broaden search
                
                for kw in keywords:
                    query = f"site:{domain} careers {kw}"
                    search_results = DDGS().text(query, max_results=3)
                    if search_results:
                        for res in search_results:
                            title = res.get('title', '')
                            # Add the search result if it seems relevant
                            if title:
                                results[kw].append(title)
            except Exception as e:
                print(f"[!] Web search fallback failed: {e}")
                
        return results

async def main():
    parser = argparse.ArgumentParser(description="Job Board Scraper for Strategic Intent")
    parser.add_argument("--url", required=True, help="URL of the company's job board")
    parser.add_argument("--keywords", nargs="+", default=["AI", "Machine Learning", "Data", "Automation", "Engineer", "Cloud"], help="Keywords to look for")
    args = parser.parse_args()

    scraper = JobBoardScraper(args.url)
    jobs = await scraper.scrape_jobs()
    
    print(f"\n--- Scraped {len(jobs)} potential job postings ---")
    if jobs:
        print("Sample jobs:")
        for j in jobs[:10]:
            print(f" - {j}")
            
    print(f"\n--- Strategic Intent Analysis (Keywords: {', '.join(args.keywords)}) ---")
    intent = scraper.analyze_strategic_intent(jobs, args.keywords)
    
    matches_found = False
    for kw, matched_jobs in intent.items():
        if matched_jobs:
            matches_found = True
            print(f"\n[{kw}] roles found ({len(matched_jobs)}):")
            for j in matched_jobs[:5]:
                print(f"  * {j}")
                
    if not matches_found:
        print("\nNo matching strategic roles found based on the provided keywords.")

if __name__ == "__main__":
    asyncio.run(main())
