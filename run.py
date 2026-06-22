import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("mahgic")

import argparse
import asyncio
import subprocess
import os
from dotenv import load_dotenv

def main():
    load_dotenv()
    logger.info("="*60)
    logger.info("💎 Welcome to MA(h)GIC (Macro AI (hidden) Gem Intelligence Core) 💎")
    logger.info("="*60)
    
    parser = argparse.ArgumentParser(description="MA(h)GIC Orchestrator Wrapper")
    parser.add_argument("--provider", required=False, choices=["gemini", "openai", "claude"], help="LLM Provider to use")
    parser.add_argument("--country", required=False, help="Target country for stock discovery")
    parser.add_argument("--limit", type=int, default=None, help="Number of companies to analyze")
    parser.add_argument("--streamlit", action="store_true", help="Launch the Streamlit interactive dashboard after completion")
    args = parser.parse_args()

    # Determine Provider
    provider = args.provider or os.environ.get("LLM_PROVIDER")
    if not provider:
        logger.info("\n[?] Which LLM Provider would you like to use?")
        logger.info("    1. Gemini (Google) [Default]")
        logger.info("    2. OpenAI (GPT-4o)")
        logger.info("    3. Claude (Anthropic)")
        choice = input("    Enter choice (1/2/3): ").strip()
        if choice == "2":
            provider = "openai"
        elif choice == "3":
            provider = "claude"
        else:
            provider = "gemini"
    
    os.environ["LLM_PROVIDER"] = provider.lower()

    # Determine API Key based on provider
    api_key_env_var = "GEMINI_API_KEY"
    if provider == "openai":
        api_key_env_var = "OPENAI_API_KEY"
    elif provider == "claude":
        api_key_env_var = "ANTHROPIC_API_KEY"

    api_key = os.environ.get(api_key_env_var)
    if not api_key:
        api_key = input(f"\n[?] Please enter your {api_key_env_var.split('_')[0].capitalize()} API Key (or add to .env): ")
        if not api_key.strip():
            logger.info("[!] API key is required to run the pipeline.")
            return
    
    # Set the environment variable for the rest of the pipeline to use
    os.environ[api_key_env_var] = api_key.strip()

    country = args.country
    if not country:
        country = input("[?] Which country's stocks would you like to analyze? (e.g. USA, India): ")

    limit = args.limit
    if limit is None:
        try:
            limit_input = input("[?] How many companies would you like to run the analysis for? (e.g. 50): ")
            limit = int(limit_input)
        except ValueError:
            logger.info("Invalid input for limit. Defaulting to 50.")
            limit = 50

    run_streamlit = args.streamlit
    if not run_streamlit:
        streamlit_input = input("[?] Would you like to run the interactive Streamlit dashboard after completion? (y/n): ")
        run_streamlit = streamlit_input.lower().startswith('y')

    # Run orchestrator
    logger.info("\n[*] Starting MA(h)GIC Pipeline...")
    from engines import orchestrator
    
    # Run the async pipeline
    proxycurl_key = os.environ.get("PROXYCURL_API_KEY")
    asyncio.run(orchestrator.run_pipeline(country, proxycurl_key, limit))
    
    logger.info("\n[*] Injecting results into the HTML Dashboard...")
    try:
        import json
        with open('results.json', 'r') as f:
            results_data = json.load(f)
        with open('ui/dashboard_template.html', 'r') as f:
            html_content = f.read()
        json_str = json.dumps(results_data)
        # Inject the JSON into the placeholder
        new_html = html_content.replace("const DATA_PLACEHOLDER = null;", f"const DATA_PLACEHOLDER = {json_str};")
        with open('ui/dashboard.html', 'w') as f:
            f.write(new_html)
        logger.info("Dashboard injected successfully.")
    except Exception as e:
        logger.info(f"[!] Warning: Failed to inject dashboard: {e}")
        
    logger.info(f"\n[+] Pipeline completed successfully! The HTML dashboard has been updated: file://{os.path.abspath('ui/dashboard.html')}")

    if run_streamlit:
        logger.info("\n[*] Launching Streamlit dashboard...")
        subprocess.run(["streamlit", "run", "ui/streamlit_app.py"])

if __name__ == "__main__":
    main()
