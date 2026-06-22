import logging
logger = logging.getLogger("mahgic")

import os
import json
from providers.llm_provider import get_provider

class MacroBrain:
    def __init__(self):
        self.llm = get_provider()

    def get_macro_trends(self) -> tuple[dict, dict]:
        logger.info("[*] Macro Brain: Analyzing current macro environment and identifying top trends...")
        
        system_instruction = """
        You are an expert macro-economic and technology trend analyst.
        Identify the top 3 to 5 most significant current and near-future macro trends that are driving investment and hiring across all sectors (e.g., Technology, Health, Finance, Energy, Manufacturing).

        Use the most current information available to you. If you are uncertain about recent data, state that.
        
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
        
        response_text, token_dict = self.llm.generate(prompt, system_instruction)
        
        # Clean up the response to extract just the JSON
        lines = response_text.split('\n')
        json_str = ""
        for line in lines:
            # Strip markdown if the LLM hallucinated it
            if line.startswith("```"):
                continue
            json_str += line + "\n"
            
        try:
            result = json.loads(json_str.strip())
            if isinstance(result, dict) and "trends" in result:
                return result, token_dict
            else:
                logger.info("[!] Macro Brain returned unexpected format. Using fallback.")
                return {"trends": ["Generative AI", "Energy Transition"], "commentary": "Fallback commentary.", "sources": ["Fallback Source"]}, token_dict
        except Exception as e:
            logger.info(f"[!] Error parsing Macro Brain output: {e}")
            logger.info(f"Raw output: {response_text}")
            return {"trends": ["Generative AI", "Energy Transition"], "commentary": "Error parsing output.", "sources": ["None"]}, token_dict

if __name__ == "__main__":
    brain = MacroBrain()
    trends = brain.get_macro_trends()
    logger.info(f"Identified Macro Trends: {trends}")
