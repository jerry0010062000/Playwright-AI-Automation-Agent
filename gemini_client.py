"""
Gemini AI 客戶端模組
處理與 Gemini API 的互動，包括建立對話、發送截圖、處理回應等
"""

import json
import base64
from typing import List, Tuple, Optional
from google import genai
from config import (
    GEMINI_API_KEY,
    MODEL_NAME, 
    ENABLE_PROMPT_INJECTION_DETECTION,
    TOOL_TYPE,
    TOOL_ENVIRONMENT,
    AI_ROLE,
    AI_BEHAVIOR,
    OUTPUT_FORMAT,
    INCLUDE_SITUATION_HANDLERS,
    USE_FULL_PROMPT,
    EXCLUDED_PREDEFINED_FUNCTIONS
)
from prompts import build_prompt, build_simple_prompt


class GeminiAgent:
    """Gemini AI 代理封裝類別"""
    
    def __init__(
        self, 
        role: Optional[str] = None,
        behavior: Optional[str] = None,
        output_format: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        初始化 Gemini 客戶端
        
        Args:
            role: AI 角色（覆蓋 config.py 的設定）
            behavior: AI 行為模式（覆蓋 config.py 的設定）
            output_format: 輸出格式（覆蓋 config.py 的設定）
            model: AI 模型名稱（覆蓋 config.py 的設定）
        """
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else genai.Client()
        
        # 使用傳入的參數或預設值
        self.role = role or AI_ROLE
        self.behavior = behavior or AI_BEHAVIOR
        self.output_format = output_format or OUTPUT_FORMAT
        self.model = model or MODEL_NAME
    
    def create_initial_interaction(
        self, 
        task: str, 
        screenshot_bytes: bytes,
        extra_instructions: str = ""
    ):
        """
        建立第一次 AI 互動
        
        Args:
            task: 使用者任務描述
            screenshot_bytes: 初始頁面截圖（PNG 格式）
            extra_instructions: 額外的自訂指示
        
        Returns:
            Gemini API 的互動回應物件
        """
        # 根據配置建立提示詞
        if USE_FULL_PROMPT:
            enhanced_task = build_prompt(
                task=task,
                role=self.role,
                behavior=self.behavior,
                output_format=self.output_format,
                extra_instructions=extra_instructions,
                include_situation_handlers=INCLUDE_SITUATION_HANDLERS
            )
        else:
            enhanced_task = build_simple_prompt(task, self.role)
        
        return self.client.interactions.create(
            model=self.model,  # 使用實例的模型設定
            input=[
                {"type": "text", "text": enhanced_task},
                {
                    "type": "image", 
                    "data": base64.b64encode(screenshot_bytes).decode("utf-8"), 
                    "mime_type": "image/png"
                }
            ],
            tools=[self._get_computer_use_tool()]
        )
    
    def continue_interaction(self, previous_interaction_id: str, function_responses: List[dict]):
        """
        延續對話，將操作結果回傳給 AI
        
        Args:
            previous_interaction_id: 上一次互動的 ID
            function_responses: 函數執行結果列表
        
        Returns:
            Gemini API 的互動回應物件
        """
        return self.client.interactions.create(
            model=self.model,  # 使用實例的模型設定
            previous_interaction_id=previous_interaction_id,
            input=function_responses,
            tools=[self._get_computer_use_tool()]
        )
    
    @staticmethod
    def _get_computer_use_tool() -> dict:
        """
        取得 Computer Use 工具配置
        
        Returns:
            工具配置字典
        """
        tool_config = {
            "type": TOOL_TYPE,
            "environment": TOOL_ENVIRONMENT,
        }
        if ENABLE_PROMPT_INJECTION_DETECTION:
            tool_config["enable_prompt_injection_detection"] = ENABLE_PROMPT_INJECTION_DETECTION
        if EXCLUDED_PREDEFINED_FUNCTIONS:
            tool_config["excluded_predefined_functions"] = EXCLUDED_PREDEFINED_FUNCTIONS
        return tool_config
    
    def set_role(self, role: str):
        """
        動態更改 AI 角色
        
        Args:
            role: 新的角色類型（default, tester, scraper, shopper, researcher）
        
        Example:
            agent.set_role("tester")  # 切換為測試工程師角色
        """
        self.role = role
        print(f"✓ AI 角色已切換為: {role}")
    
    def set_behavior(self, behavior: str):
        """
        動態更改 AI 行為模式
        
        Args:
            behavior: 新的行為模式（careful, fast, verbose, silent）
        
        Example:
            agent.set_behavior("fast")  # 切換為快速模式
        """
        self.behavior = behavior
        print(f"✓ AI 行為模式已切換為: {behavior}")
        
    def set_output_format(self, output_format: str):
        """
        動態更改輸出格式
        
        Args:
            output_format: 新的輸出格式（natural, json, list, table）
        
        Example:
            agent.set_output_format("json")  # 切換為 JSON 格式輸出
        """
        self.output_format = output_format
        print(f"✓ 輸出格式已切換為: {output_format}")
    
    def get_current_config(self) -> dict:
        """取得當前 AI 配置"""
        return {
            "role": self.role,
            "behavior": self.behavior,
            "output_format": self.output_format,
            "model": self.model
        }
    
    def print_config(self):
        """印出當前 AI 配置"""
        print("\n" + "="*50)
        print("🤖 AI 代理配置")
        print("="*50)
        print(f"角色 (Role):       {self.role}")
        print(f"行為 (Behavior):   {self.behavior}")
        print(f"輸出格式 (Output): {self.output_format}")
        print(f"模型 (Model):      {self.model}")
        print("="*50 + "\n")
        
    @staticmethod
    def has_function_calls(interaction) -> bool:
        """
        檢查互動回應中是否包含函數呼叫
        
        Args:
            interaction: Gemini API 的互動回應物件
        
        Returns:
            是否有函數呼叫
        """
        return any(
            step.type == "function_call"
            for step in interaction.steps
        )
    
    @staticmethod
    def extract_text_response(interaction) -> str:
        """
        從互動回應中提取文字內容
        
        Args:
            interaction: Gemini API 的互動回應物件
        
        Returns:
            AI 的文字回應
        """
        return " ".join([
            content_block.text 
            for step in interaction.steps 
            if step.type == "model_output"
            for content_block in step.content 
            if content_block.type == "text"
        ])


def get_function_responses(
    page, 
    results: List[Tuple[str, str, dict]], 
    interaction=None
) -> List[dict]:
    """
    將執行結果轉換為 Gemini API 可接受的回應格式
    包含當前頁面截圖和執行狀態
    
    Args:
        page: Playwright 的頁面物件
        results: 函數執行結果列表
        interaction: 用於檢查是否需要安全確認的互動物件
    
    Returns:
        格式化的函數回應列表
    """
    # 擷取當前頁面截圖
    screenshot_bytes = page.screenshot(type="png")
    current_url = page.url
    
    # 檢查是否需要安全確認
    needs_safety = False
    if interaction and interaction.steps:
        # 遍歷步驟，檢查是否有 function_call 包含 safety_decision
        for step in reversed(interaction.steps):
            if step.type == "function_call":
                # 1. 檢查 step 屬性是否包含 safety_decision
                if getattr(step, "safety_decision", None) is not None:
                    needs_safety = True
                    break
                # 2. 檢查 arguments 中是否包含 safety_decision
                args = getattr(step, "arguments", None)
                if args:
                    if isinstance(args, dict):
                        if "safety_decision" in args:
                            needs_safety = True
                            break
                    else:
                        if getattr(args, "safety_decision", None) is not None:
                            needs_safety = True
                            break
    
    function_responses = []
    
    for name, call_id, result in results:
        final_result = {"url": current_url, **result}
        if needs_safety:
            final_result["safety_acknowledgement"] = True
            
        result_blocks = [
            {
                "type": "text",
                # 將結果序列化為 JSON，包含當前網址與安全認證
                "text": json.dumps(final_result)
            },
            {
                "type": "image",
                # 將截圖編碼為 base64 字串
                "data": base64.b64encode(screenshot_bytes).decode("utf-8"),
                "mime_type": "image/png"
            }
        ]
            
        # 為每個執行的函數建立回應
        function_responses.append({
            "type": "function_result",
            "name": name,
            "call_id": call_id,
            "result": result_blocks
        })
    
    return function_responses
