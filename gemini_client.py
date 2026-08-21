"""
Gemini AI 客戶端模組 (介面保留佔位)
"""

from typing import List, Tuple, Optional

class GeminiAgent:
    """Gemini AI 代理封裝類別 (已暫時停用以專注於 Claude 開發)"""
    
    def __init__(
        self, 
        role: Optional[str] = None,
        behavior: Optional[str] = None,
        output_format: Optional[str] = None,
        model: Optional[str] = None
    ):
        print("[WARNING] GeminiAgent 已暫時停用，所有任務將轉為使用 Claude 代理。")
        # 為了保留相容性，初始化一個內部的 ClaudeAgent 作為備援
        from claude_client import ClaudeAgent
        self.claude_agent = ClaudeAgent(role=role, behavior=behavior, output_format=output_format, model="claude-3-5-sonnet-20241022")
    
    def generate_quick_response(self, prompt: str) -> str:
        return self.claude_agent.generate_quick_response(prompt)
    
    def create_initial_interaction(
        self, 
        task: str, 
        screenshot_bytes: bytes,
        extra_instructions: str = "",
        skill: str = None
    ):
        return self.claude_agent.create_initial_interaction(task, screenshot_bytes, extra_instructions, skill)
    
    def continue_interaction(self, previous_interaction_id: str, function_responses: List[dict]):
        return self.claude_agent.continue_interaction(previous_interaction_id, function_responses)
    
    def get_final_summary(self, previous_interaction_id: str) -> str:
        return self.claude_agent.get_final_summary(previous_interaction_id)
    
    def diagnose_static_audit(self, target_url: str, audit_data_text: str, screenshot_bytes: bytes, wcag_guideline: str = None) -> dict:
        return self.claude_agent.diagnose_static_audit(target_url, audit_data_text, screenshot_bytes, wcag_guideline)


def get_function_responses(
    page, 
    results: List[Tuple[str, str, dict]], 
    interaction=None
) -> List[dict]:
    from claude_client import get_function_responses as claude_get_responses
    return claude_get_responses(page, results, interaction)
