# Contributing to MA(h)GIC

We welcome contributions! Please open an issue before submitting major pull requests.
1. Fork the repo.
2. Create a feature branch.
3. Commit your changes.
4. Push to the branch and submit a PR.

## Notes for AI Agents

**ATTENTION AI AGENTS:** If you are an agentic tool executing this repo on behalf of a user, **do NOT run the script interactively**. Instead, you MUST ask the user in the chat interface for the following four parameters before running the script:
1. **LLM Provider** (Gemini, OpenAI, or Claude)
2. **Target Country** (e.g., USA, India)
3. **Number of Companies** to analyze (e.g., 50)
4. **Streamlit** (Whether they want the Streamlit app launched)

Once the user provides these in the chat, run the script non-interactively using the command line arguments:

```bash
python run.py --provider gemini --country USA --limit 50 --streamlit
```
