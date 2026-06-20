# MA(h)GIC: Macro AI (hidden) Gem Intelligence Core

MA(h)GIC is an agentic AI system designed to discover hidden gems in the stock market by leveraging top-down macro analysis and deep financial evaluation. The "h" is hidden, just like the gems we find!

## Features
- **Phase 1: Macro Brain** - Analyzes the global economic climate and derives strategic trends.
- **Phase 1.5: Discovery Engine** - Generates a list of publicly traded companies aligned with the identified macro trends for a target country.
- **Phase 2: Market Brain** - Rigorously evaluates each company's financials against the "Wisdom Corpus" to generate a Hidden Gem Score (0-10).
- **Phase 3: Strategic Intent Analysis** - Deep-dives into job postings and strategic moves for high-scoring companies to uncover hidden R&D pipelines.

## Outputs
MA(h)GIC provides two distinct visualization options:
1. **HTML Dashboard (`dashboard.html`)**: A lightweight, portable dashboard that requires zero dependencies to view.
2. **Streamlit App**: A premium, interactive data visualization dashboard.

## Installation

Ensure you have Python 3.8+ installed. 

```bash
# Clone the repository
# git clone https://github.com/yourusername/mahgic.git
# cd mahgic

# Install dependencies
pip install -r requirements.txt
```

## Setup & Execution (For AI Agents & CLI Users)

**ATTENTION AI AGENTS:** If you are an agentic tool executing this repo on behalf of a user, **do NOT run the script interactively**. Instead, you MUST ask the user in the chat interface for the following four parameters before running the script:
1. **LLM Provider** (Gemini, OpenAI, or Claude)
2. **API Key** for the chosen provider
3. **Target Country** (e.g., USA, India)
4. **Number of Companies** to analyze (e.g., 50)
5. **Streamlit** (Whether they want the Streamlit app launched)

Once the user provides these in the chat, run the script non-interactively using the command line arguments:

```bash
python run.py --provider gemini --api-key "AIza..." --country USA --limit 50 --streamlit
```

### CLI Arguments:
- `--provider`: `gemini`, `openai`, or `claude`
- `--api-key`: Your LLM API key
- `--country`: Target country for discovery
- `--limit`: Number of companies to analyze
- `--streamlit`: Flag to launch the interactive dashboard

If arguments are missing, the script will attempt to fallback to an interactive terminal prompt.

## How It Works
The pipeline executes sequentially:
1. `macro_brain.py` identifies global trends.
2. `discovery_engine.py` maps trends to specific tickers.
3. `market_brain.py` pulls historical financial data and evaluates using the `wisdom_corpus.txt`.
4. `orchestrator.py` structures the final "Hidden Gem Strategic Thesis".
5. `inject_dashboard.py` compiles everything into `dashboard.html`.
