import argparse
import asyncio
import subprocess
import os

def main():
    print("="*60)
    print("💎 Welcome to MA(h)GIC (Macro AI (hidden) Gem Intelligence Core) 💎")
    print("="*60)
    
    parser = argparse.ArgumentParser(description="MA(h)GIC Orchestrator Wrapper")
    parser.add_argument("--api-key", required=False, help="LLM API Key")
    parser.add_argument("--provider", required=False, choices=["gemini", "openai", "claude"], help="LLM Provider to use")
    parser.add_argument("--country", required=False, help="Target country for stock discovery")
    parser.add_argument("--limit", type=int, default=None, help="Number of companies to analyze")
    parser.add_argument("--streamlit", action="store_true", help="Launch the Streamlit interactive dashboard after completion")
    args = parser.parse_args()

    # Determine Provider
    provider = args.provider or os.environ.get("LLM_PROVIDER")
    if not provider:
        print("\n[?] Which LLM Provider would you like to use?")
        print("    1. Gemini (Google) [Default]")
        print("    2. OpenAI (GPT-4o)")
        print("    3. Claude (Anthropic)")
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

    api_key = args.api_key or os.environ.get(api_key_env_var)
    if not api_key:
        api_key = input(f"\n[?] Please enter your {api_key_env_var.split('_')[0].capitalize()} API Key: ")
        if not api_key.strip():
            print("[!] API key is required to run the pipeline.")
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
            print("Invalid input for limit. Defaulting to 50.")
            limit = 50

    run_streamlit = args.streamlit
    if not run_streamlit:
        streamlit_input = input("[?] Would you like to run the interactive Streamlit dashboard after completion? (y/n): ")
        run_streamlit = streamlit_input.lower().startswith('y')

    # Run orchestrator
    print("\n[*] Starting MA(h)GIC Pipeline...")
    import orchestrator
    
    # Run the async pipeline
    asyncio.run(orchestrator.run_pipeline(country, None, limit))
    
    print("\n[*] Injecting results into the HTML Dashboard...")
    try:
        import json
        with open('results.json', 'r') as f:
            results_data = json.load(f)
        with open('dashboard_template.html', 'r') as f:
            html_content = f.read()
        json_str = json.dumps(results_data)
        start_marker = "Promise.resolve({"
        end_marker = "}).then(data => {"
        start_idx = html_content.find(start_marker)
        end_idx = html_content.find(end_marker) + 1
        if start_idx != -1 and end_idx != -1:
            new_html = html_content[:start_idx] + "Promise.resolve(" + json_str + html_content[end_idx:]
            with open('dashboard.html', 'w') as f:
                f.write(new_html)
            print("Dashboard injected successfully.")
        else:
            print("Markers not found in template.")
    except Exception as e:
        print(f"[!] Warning: Failed to inject dashboard: {e}")
        
    print(f"\n[+] Pipeline completed successfully! The HTML dashboard has been updated: file://{os.path.abspath('dashboard.html')}")

    if run_streamlit:
        print("\n[*] Launching Streamlit dashboard...")
        subprocess.run(["streamlit", "run", "streamlit_app.py"])

if __name__ == "__main__":
    main()
