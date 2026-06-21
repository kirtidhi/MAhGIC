import logging
logger = logging.getLogger("mahgic")

import os
import json
from providers.llm_provider import get_provider

class MacroBrain:
    def __init__(self):
        self.llm = get_provider()

    def get_macro_trends(self) -> dict:
        logger.info("[*] Macro Brain: Analyzing current macro environment and identifying top trends...")
        
        system_instruction = """
        You are an expert macro-economic and technology trend analyst operating in the year 2026.
        Identify the top 3 to 5 most significant current and near-future macro trends that are driving investment and hiring across all sectors (e.g., Technology, Health, Finance, Energy, Manufacturing).

        CRITICAL INSTRUCTION: You MUST ONLY use data, reports, and perspectives from the year 2026. DO NOT use or reference anything from 2025 or earlier.
        Please explicitly consider sources such as the Harvard Business Review (HBR) and the 2026 Mary Meeker State of the Internet report (if it exists).
        
        Return the result as a raw JSON object with the following structure:
        {
            "trends": ["trend1", "trend2", ...],
            "commentary": "A detailed explanation (2-3 sentences) of why these trends are currently dominating the macro environment.",
            "sources": ["Name of Source 1", "Name of Source 2"]
        }
        The 'trends' array should contain concise, specific keywords (1-3 words).
        DO NOT include any markdown formatting or code blocks. Just output the JSON object.
        """
        
        prompt = "What are the top technological and economic macro trends right now? Output the JSON object."
        
        response_text = self.llm.generate(prompt, system_instruction)
        
        # Clean up the response to extract just the JSON
        lines = response_text.split('\n')
        json_str = ""
        for line in lines:
            if "[Token Usage]" in line:
                logger.info(f"[Macro Brain] {line.strip()}")
                continue
            # Strip markdown if the LLM hallucinated it
            if line.startswith("```"):
                continue
            json_str += line + "\n"
            
        try:
            result = json.loads(json_str.strip())
            if isinstance(result, dict) and "trends" in result:
                return result
            else:
                logger.info("[!] Macro Brain returned unexpected format. Using fallback.")
                return {"trends": ["Generative AI", "Energy Transition"], "commentary": "Fallback commentary.", "sources": ["Fallback Source"]}
        except Exception as e:
            logger.info(f"[!] Error parsing Macro Brain output: {e}")
            logger.info(f"Raw output: {response_text}")
            return {"trends": ["Generative AI", "Energy Transition"], "commentary": "Error parsing output.", "sources": ["None"]}

if __name__ == "__main__":
    brain = MacroBrain()
    trends = brain.get_macro_trends()
    logger.info("Identified Macro Trends:", trends)
