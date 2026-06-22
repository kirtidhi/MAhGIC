import logging
import yfinance as yf
import requests
import argparse
import os
from bs4 import BeautifulSoup
from providers.llm_provider import get_provider

logger = logging.getLogger("mahgic")

class RegulatoryBrain:
    def __init__(self, llm_provider=None):
        self.llm = llm_provider
        self.headers = {
            "User-Agent": "MAhGIC Analysis (mahgic-bot@example.com)"
        }

    def get_document_type(self, ticker_symbol: str) -> str:
        if ticker_symbol.endswith(".L"): return "Annual Report (FCA)"
        elif ticker_symbol.endswith(".PA") or ticker_symbol.endswith(".AS"): return "Universal Registration Document (URD)"
        elif ticker_symbol.endswith(".T"): return "Annual Securities Report (Yuho)"
        elif ticker_symbol.endswith(".NS") or ticker_symbol.endswith(".BO"): return "Annual Report"
        elif ticker_symbol.endswith(".AX"): return "Annual Report"
        elif ticker_symbol.endswith(".TO"): return "Annual Information Form (AIF)"
        elif ticker_symbol.endswith(".DE"): return "Annual Report (Jahresabschluss)"
        else: return "SEC 10-K"

    def fetch_regulatory_text(self, ticker_symbol: str) -> tuple:
        doc_type = self.get_document_type(ticker_symbol)
        logger.info(f"[*] Fetching {doc_type} for {ticker_symbol}...")
        
        if doc_type != "SEC 10-K":
            if ticker_symbol.endswith(".NS") or ticker_symbol.endswith(".BO") or ticker_symbol.endswith(".AX") or ticker_symbol.endswith(".L"):
                logger.info(f"[*] Falling back to DuckDuckGo search for {ticker_symbol} {doc_type}...")
                try:
                    import urllib.parse
                    import io
                    try:
                        import pypdf
                    except ImportError:
                        pypdf = None

                    ticker = yf.Ticker(ticker_symbol)
                    company_name = ticker.info.get("longName", ticker_symbol)
                    query = f"{company_name} {doc_type} summary analysis risks"
                    res = requests.get(f"https://html.duckduckgo.com/html/?q={query}", headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    soup = BeautifulSoup(res.text, 'html.parser')
                    
                    extracted_text = ""
                    for a in soup.find_all('a', class_='result__snippet')[:5]:
                        extracted_text += a.get_text(strip=True) + "\n"
                    
                    first_url_tag = soup.find('a', class_='result__url')
                    if first_url_tag and first_url_tag.get('href'):
                        uddg_href = first_url_tag.get('href')
                        parsed_url = urllib.parse.urlparse(uddg_href)
                        qs = urllib.parse.parse_qs(parsed_url.query)
                        if 'uddg' in qs:
                            target_url = qs['uddg'][0]
                            logger.info(f"[*] Following DuckDuckGo search result URL: {target_url}")
                            try:
                                doc_res = requests.get(target_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                                content_type = doc_res.headers.get('Content-Type', '').lower()
                                
                                if 'application/pdf' in content_type and pypdf:
                                    logger.info("[*] URL is a PDF, extracting text...")
                                    pdf_reader = pypdf.PdfReader(io.BytesIO(doc_res.content))
                                    pdf_text = ""
                                    for page in pdf_reader.pages[:20]:
                                        pdf_text += page.extract_text() + "\n"
                                    extracted_text += "\n\n--- SOURCE DOCUMENT ---\n" + pdf_text
                                elif 'text/html' in content_type:
                                    logger.info("[*] URL is HTML, extracting text...")
                                    doc_soup = BeautifulSoup(doc_res.text, 'html.parser')
                                    for script in doc_soup(["script", "style"]):
                                        script.extract()
                                    doc_text = doc_soup.get_text(separator=' ', strip=True)
                                    extracted_text += "\n\n--- SOURCE DOCUMENT ---\n" + doc_text[:50000]
                            except Exception as doc_e:
                                logger.warning(f"[!] Failed to fetch target document: {doc_e}")
                    
                    if extracted_text.strip():
                        logger.info(f"[*] Extracted {len(extracted_text)} characters from DuckDuckGo fallback.")
                        return extracted_text, doc_type
                except Exception as e:
                    logger.info(f"[!] DuckDuckGo fallback failed: {e}")

            logger.info(f"[!] Automated fetching of {doc_type} is not natively supported by yfinance for {ticker_symbol}.")
            logger.info(f"[*] Support for DuckDuckGo web search fallback is currently only available for Indian (.NS, .BO), Australian (.AX), and London (.L) markets.")
            return "", doc_type

        try:
            ticker = yf.Ticker(ticker_symbol)
            filings = ticker.get_sec_filings()
            
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
                return "", doc_type
                
            logger.info(f"[*] Found 10-K URL: {ten_k_url}")
            
            response = requests.get(ten_k_url, headers=self.headers)
            if response.status_code != 200:
                logger.info(f"[!] Failed to fetch 10-K. Status: {response.status_code}")
                return "", doc_type
                
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text(separator=' ')
            
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            clean_text = '\n'.join(lines)
            
            logger.info(f"[*] Extracted {len(clean_text)} characters. Truncating to 60k for LLM context.")
            return clean_text[:60000], doc_type
            
        except Exception as e:
            logger.info(f"[!] {doc_type} fetch error for {ticker_symbol}: {e}")
            return "", doc_type

    def evaluate_regulatory_text(self, text: str, doc_type: str) -> str:
        if not self.llm:
            return "No LLM provider configured."
        if not text:
            return f"No {doc_type} data available for automated analysis."
            
        system_instruction = (
            "You are an expert fundamental value investor. "
            f"Analyze this extract from the company's {doc_type} filing. "
            "Do not just look for keywords; deeply analyze the context, tone, and actual meaning of what management is saying. "
            "Focus on identifying:\n"
            "1. Major business risks and headwinds.\n"
            "2. Management's forward-looking guidance and strategic outlook.\n"
            "3. Any qualitative advantages (moats) that pure financial numbers wouldn't show.\n\n"
            "Provide a concise, critical qualitative assessment. Return your response in plain text."
        )
        
        logger.info(f"[*] Running AI Evaluation on {doc_type}...")
        return self.llm.generate(prompt=text, system_instruction=system_instruction)[0]

def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Regulatory Filing Brain")
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

    brain = RegulatoryBrain(llm_provider=provider)
    text, doc_type = brain.fetch_regulatory_text(args.ticker)
    
    if text and provider:
        logger.info("\n" + "="*40 + f"\n{doc_type.upper()} QUALITATIVE ANALYSIS\n" + "="*40)
        analysis = brain.evaluate_regulatory_text(text, doc_type)
        logger.info(analysis)

if __name__ == "__main__":
    main()
