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

    def get_final_summary(self, previous_interaction_id: str) -> str:
        """
        當達到最大回合數時，向 AI 要求對當前狀態與歷史檢測進行總結結論
        """
        interaction = self.client.interactions.create(
            model=self.model,
            previous_interaction_id=previous_interaction_id,
            input=[
                {
                    "type": "text",
                    "text": "目前已達到最大執行回合數 (Max Turns)。請就您目前所觀察到的網頁狀態、已執行的檢測步驟與發現的無障礙問題，進行一次最終的總結評估，並寫出結論與改善建議項目。"
                }
            ]
        )
        tokens = {"input": 0, "output": 0, "total": 0}
        if hasattr(interaction, "usage_metadata") and interaction.usage_metadata:
            tokens["input"] = interaction.usage_metadata.prompt_token_count or 0
            tokens["output"] = interaction.usage_metadata.candidates_token_count or 0
            tokens["total"] = tokens["input"] + tokens["output"]
            
        return {
            "summary": self.extract_text_response(interaction),
            "usage": tokens
        }
    
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

    def diagnose_static_audit(self, target_url: str, audit_data_text: str, screenshot_bytes: bytes, wcag_guideline: str = None) -> dict:
        """
        對靜態掃描結果進行一回合的智慧診斷，不帶任何 Tool，防止模型因擁有 Tool 宣告而只做初步回應
        """
        from google.genai import types
        import base64
        
        system_prompt = (
            "你是一個資深的網頁無障礙 (Accessibility) 檢測專家與開發顧問。\n"
            "你的任務是根據所提供的網頁截圖與 Axe-core 檢測出的靜態違規數據，撰寫專業的無障礙評估報告與修復方向建議。\n"
            "**請絕對不要嘗試使用或提及任何瀏覽器操作工具**，你只需要作為一個分析器，直接產出最終的 Markdown 診斷報告。\n"
            "報告請採用繁體中文（Traditional Chinese）。"
        )
        
        wcag_instruction = ""
        if wcag_guideline:
            wcag_instruction = (
                f"\n⚠️ **重要限制指示**：使用者目前僅針對無障礙指南 **WCAG {wcag_guideline}** 進行檢測，"
                f"因此你的診斷、分析與優化方向**必須完全限制並聚焦於與 WCAG {wcag_guideline} 相關的要素**（例如若檢測 1.1，則僅分析非文字內容/圖片替代文字；若為 2.1，則僅聚焦鍵盤存取等）。"
                f"請絕對不要提及或列出任何屬於其他無障礙章節（如鍵盤、焦點、對比度、動態更新等）的評估或修復方向建議！\n"
            )
            
        contents = [
            f"目標網址: {target_url}\n{wcag_instruction}\n"
            f"以下是本地 Axe-core 掃描出的違規數據：\n\n{audit_data_text}\n\n"
            f"請為我們進行智慧診斷，撰寫一份高嚴謹度的無障礙 Markdown 評估報告。請嚴格遵守以下結構與指示：\n"
            f"1. **【必須包含】第 1 章：規範涵蓋與成功條款合規對照表 (WCAG 2.2 Success Criteria Compliance Matrix Table)**：\n"
            f"   - 必須在此章節完整建立 Markdown 表格，精確列出對應的 3 位數 Success Criteria 成功條款 (如 1.1.1, 1.3.1, 1.4.3, 2.1.4, 2.4.7, 4.1.2 等)、條款名稱、合規等級 (Level A / AA / AAA) 及實測合規狀態 (PASS / FAIL / 違規件數)。\n"
            f"2. **第 2 章：執行摘要 (Executive Summary)**：依據第 1 章表格，概括合規狀況與風險等級。\n"
            f"3. **第 3 章：智慧診斷與深度評估 (AI Diagnosis & Evaluation)**：**後續的所有問題分析、影響評估都必須嚴格依據第 1 章表格中的 3 位數成功條款進行關聯與對應**！\n"
            f"4. **第 4 章：修復方向建議 (Remediation Directions)**：若有違規，依據 Level A -> Level AA 優先級，針對 3 位數條款給出明確的修復指引（請給出邏輯說明，不要貼程式碼片段）。\n"
            f"5. **❌ 絕對禁止贅字廢話**：請絕對不要撰寫任何『建議後續行動』、『結語』或『未來指引』等贅字章節！寫完主題內容後請立即結束。範例請保持嚴謹精確。"
        ]
        
        if screenshot_bytes:
            contents.append(
                types.Part.from_bytes(
                    data=screenshot_bytes,
                    mime_type="image/png"
                )
            )
            
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=4096
        )
        
        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config
        )
        
        # 提取 Token 使用量
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0
        total_tokens = input_tokens + output_tokens
        
        return {
            "text": response.text or "",
            "usage": {
                "input": input_tokens,
                "output": output_tokens,
                "total": total_tokens
            }
        }


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
