"""
Claude AI 客戶端模組
處理與 Anthropic Claude API 的互動，包括建立對話、發送截圖、處理回應等
"""

import json
import base64
from typing import List, Tuple, Optional
import anthropic
from config import (
    CLAUDE_API_KEY,
    CLAUDE_BASE_URL,
    CLAUDE_AUTH_TOKEN,
    CLAUDE_DISABLE_EXPERIMENTAL_BETAS,
    CLAUDE_COMPUTER_TOOL_TYPE,
    CLAUDE_COMPUTER_BETAS,
    CLAUDE_USE_GATEWAY
)


class ClaudeContentBlock:
    """模擬 Gemini Content Block 結構"""
    def __init__(self, text: str, type: str = "text"):
        self.text = text
        self.type = type


class ClaudeStep:
    """模擬 Gemini Step 結構"""
    def __init__(self, type: str, content: list = None, name: str = None, id: str = None, arguments: dict = None):
        self.type = type
        self.content = content or []
        self.name = name
        self.id = id
        self.arguments = arguments or {}


class ClaudeInteraction:
    """模擬 Gemini Interaction 回應物件"""
    def __init__(self, id: str, steps: list, usage: dict = None):
        self.id = id
        self.steps = steps
        self.usage = usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


class ClaudeAgent:
    """Claude AI 代理封裝類別，對齊 GeminiAgent 介面"""
    
    def __init__(
        self, 
        role: Optional[str] = None,
        behavior: Optional[str] = None,
        output_format: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        初始化 Claude 客戶端
        """
        # 決定使用的 API Key/Token與 Base URL（基於是否啟用閘道代理配置）
        if CLAUDE_USE_GATEWAY:
            api_key = CLAUDE_AUTH_TOKEN or CLAUDE_API_KEY
            base_url = CLAUDE_BASE_URL or None
        else:
            api_key = CLAUDE_API_KEY
            base_url = None
        
        # 初始化 Claude 客戶端，設定自訂 Base URL
        self.client = anthropic.Anthropic(
            api_key=api_key if api_key else None,
            base_url=base_url
        )
        
        self.role = role or "default"
        self.behavior = behavior or "careful"
        self.output_format = output_format or "natural"
        # 預設使用支援 Computer Use 的最新 Claude 3.5 Sonnet 模型
        self.model = model or "claude-3-5-sonnet-20241022"
        self.messages = []
        
    def create_initial_interaction(
        self, 
        task: str, 
        screenshot_bytes: bytes,
        extra_instructions: str = ""
    ):
        """
        建立第一次 Claude 互動
        """
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        
        # 建立初始對話歷史
        self.messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Task: {task}\n\nExtra instructions (if any): {extra_instructions}"
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_base64
                        }
                    }
                ]
            }
        ]
        
        return self._create_claude_response()
        
    def continue_interaction(self, previous_interaction_id: str, function_responses: List[dict]):
        """
        延續對話，將操作結果與新截圖回傳給 Claude
        """
        tool_result_content = []
        for resp in function_responses:
            tool_use_id = resp["call_id"]
            text_result = ""
            image_data = None
            
            # 從結果中尋找文字和截圖
            for block in resp["result"]:
                if block["type"] == "text":
                    text_result = block["text"]
                elif block["type"] == "image":
                    image_data = block["data"]
            
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": []
            }
            if text_result:
                tool_result_block["content"].append({
                    "type": "text",
                    "text": text_result
                })
            if image_data:
                tool_result_block["content"].append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_data
                    }
                })
            tool_result_content.append(tool_result_block)
            
        self.messages.append({
            "role": "user",
            "content": tool_result_content
        })
        
        return self._create_claude_response()

    def get_final_summary(self, previous_interaction_id: str) -> str:
        """
        當達到最大回合數時，向 AI 要求對當前狀態與歷史檢測進行總結結論
        """
        summary_text = "目前已達到最大執行回合數 (Max Turns)。請就您目前所觀察到的網頁狀態、已執行的檢測步驟與發現的無障礙問題，進行一次最終的總結評估，並寫出結論與改善建議項目。"
        
        user_content = []
        
        # 檢查最後一條 assistant 訊息是否有未處理的 tool_use
        if self.messages and self.messages[-1]["role"] == "assistant":
            last_content = self.messages[-1]["content"]
            if isinstance(last_content, list):
                # 尋找所有 tool_use 區塊
                tool_uses = []
                for block in last_content:
                    b_type = getattr(block, "type", "") or (block.get("type") if isinstance(block, dict) else "")
                    if b_type == "tool_use":
                        tool_uses.append(block)
                        
                for block in tool_uses:
                    tool_use_id = getattr(block, "id", None) or (block.get("id") if isinstance(block, dict) else None)
                    if tool_use_id:
                        user_content.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": "Task stopped due to max turns. Summary requested."
                        })
                        
        # 加上總結請求文字
        user_content.append({
            "type": "text",
            "text": summary_text
        })
        
        self.messages.append({
            "role": "user",
            "content": user_content
        })
        
        system_prompt = self._build_system_prompt()
        betas = [] if CLAUDE_DISABLE_EXPERIMENTAL_BETAS == "1" else [CLAUDE_COMPUTER_BETAS]
        if "4-5" in self.model and CLAUDE_COMPUTER_TOOL_TYPE == "computer_20251124":
            betas = ["computer-use-2025-01-24"]

        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=self.messages,
            betas=betas
        )
        
        tokens = {"input": 0, "output": 0, "total": 0}
        if hasattr(response, "usage") and response.usage:
            tokens["input"] = getattr(response.usage, "input_tokens", 0)
            tokens["output"] = getattr(response.usage, "output_tokens", 0)
            tokens["total"] = tokens["input"] + tokens["output"]
            
        return {
            "summary": summary,
            "usage": tokens
        }

    def _prune_history_images(self):
        """
        修剪歷史訊息中的舊截圖，只保留最後一回合（最新）的截圖，以節省 Token。
        為了避免破壞 JSON 結構，我們將舊截圖物件改為一個簡短的提示文字區塊。
        """
        image_occurrences = []
        for i, msg in enumerate(self.messages):
            content = msg.get("content")
            if isinstance(content, list):
                for j, block in enumerate(content):
                    if block.get("type") == "image":
                        image_occurrences.append((i, j, None))
                    elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                        for k, sub_block in enumerate(block["content"]):
                            if sub_block.get("type") == "image":
                                image_occurrences.append((i, j, k))
                                
        if len(image_occurrences) > 1:
            # 除了最後一個圖片，其餘圖片通通更換為提示文字
            for i, j, k in image_occurrences[:-1]:
                msg = self.messages[i]
                replacement = {
                    "type": "text",
                    "text": "[Screenshot of this historical step removed to save tokens]"
                }
                if k is None:
                    msg["content"][j] = replacement
                else:
                    msg["content"][j]["content"][k] = replacement

    def _build_system_prompt(self) -> str:
        """
        整合 prompts.py 中的系統提示詞，包含角色特徵、行為原則與例外處理。
        """
        from prompts import SYSTEM_PROMPTS, BEHAVIOR_GUIDELINES, SITUATION_HANDLERS, OUTPUT_FORMATS
        prompt_parts = []
        
        # 1. 系統角色
        if self.role in SYSTEM_PROMPTS:
            prompt_parts.append(SYSTEM_PROMPTS[self.role])
        
        # 2. 行為指引 (包含死循環停損原則)
        if self.behavior in BEHAVIOR_GUIDELINES:
            prompt_parts.append(BEHAVIOR_GUIDELINES[self.behavior])
            
        # 3. 特殊情境處理
        prompt_parts.append("\n【特殊情境處理】")
        for handler in SITUATION_HANDLERS.values():
            prompt_parts.append(handler)
            
        # 4. 輸出格式
        if self.output_format in OUTPUT_FORMATS:
            prompt_parts.append(f"\n【回報格式】{OUTPUT_FORMATS[self.output_format]}")
            
        return "\n\n".join(prompt_parts)

    def _create_claude_response(self):
        """呼叫 Claude Messages API 並轉換為統一互動格式"""
        # 執行歷史截圖剪裁以節約 Token 消耗
        self._prune_history_images()
        
        # 建立完整的系統提示詞 (包含行為原則與停損指南)
        system_prompt = self._build_system_prompt()
        
        # 自動根據模型或自訂配置調整 tool type 與 beta header
        tool_type = CLAUDE_COMPUTER_TOOL_TYPE
        beta_header = CLAUDE_COMPUTER_BETAS
        
        # 如果模型為 claude-sonnet-4-5 且未使用自訂設定，自動 fallback 到官方支援的 20250124 版本
        if "4-5" in self.model and CLAUDE_COMPUTER_TOOL_TYPE == "computer_20251124":
            tool_type = "computer_20250124"
            beta_header = "computer-use-2025-01-24"

        # 配置 Anthropic 預設的 Computer Use 工具
        # 為了使運作與截圖精確匹配，寬度設為 1024，高度設為 768
        tools = [
            {
                "type": tool_type,
                "name": "computer",
                "display_width_px": 1024,
                "display_height_px": 768,
                "display_number": 1,
            },
            {
                "name": "navigate",
                "description": "Directly navigate to a specific URL in the browser (e.g. 'http://localhost:8000/'). Use this tool when you get lost, navigate to a wrong page, or need to return to the home page.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The target URL to load (e.g. 'http://localhost:8000/')."
                        }
                    },
                    "required": ["url"]
                }
            },
            {
                "name": "go_back",
                "description": "Go back to the previous page in the browser history.",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "evaluate_javascript",
                "description": "Evaluate a JavaScript expression on the current webpage and return the result. Use this to inspect the DOM, query elements, check media elements, or retrieve page state without needing DevTools.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "script": {
                            "type": "string",
                            "description": "The JavaScript expression or function body to evaluate (e.g. 'document.querySelectorAll(\"video, audio\").length')."
                        }
                    },
                    "required": ["script"]
                }
            },
            {
                "name": "run_axe_audit",
                "description": "Run the local Axe-core accessibility auditing engine on the current webpage and return a JSON report of all WCAG violations.",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            },
            {
                "name": "scan_focus_path",
                "description": "Scan the current page to retrieve the focus map: all focusable elements, their visual coordinates, and outline styles to check keyboard accessibility (WCAG 2.1.1, 2.4.7).",
                "input_schema": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
        
        # 根據環境變數或配置決定是否傳送 beta 標頭（預設啟用 computer-use beta）
        betas = [] if CLAUDE_DISABLE_EXPERIMENTAL_BETAS == "1" else [beta_header]
        
        # Diagnostic logging: only show summary and the last message details to prevent terminal bloat
        print(f"[*] API Call: System Prompt Length = {len(system_prompt)} chars")
        print(f"[*] API Call: Number of messages in history = {len(self.messages)}")
        if self.messages:
            last_msg = self.messages[-1]
            last_msg_str = json.dumps(last_msg, ensure_ascii=False)
            print(f"  - Latest Message ({last_msg['role']}): {len(last_msg_str)} chars")
            
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=self.messages,
            tools=tools,
            betas=betas
        )
        
        # 將 Claude 的回應儲存到歷史紀錄中
        assistant_content = []
        steps = []
        
        for block in response.content:
            if block.type == "text":
                assistant_content.append({
                    "type": "text",
                    "text": block.text
                })
                steps.append(ClaudeStep(
                    type="model_output",
                    content=[ClaudeContentBlock(text=block.text, type="text")]
                ))
            elif block.type == "tool_use":
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
                })
                steps.append(ClaudeStep(
                    type="function_call",
                    name=block.name,
                    id=block.id,
                    arguments=block.input
                ))
                
        self.messages.append({
            "role": "assistant",
            "content": assistant_content
        })
        
        # 提取 token 使用量
        usage_info = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }
        if hasattr(response, "usage") and response.usage:
            usage_info["input_tokens"] = getattr(response.usage, "input_tokens", 0)
            usage_info["output_tokens"] = getattr(response.usage, "output_tokens", 0)
            usage_info["total_tokens"] = usage_info["input_tokens"] + usage_info["output_tokens"]
            
        # 互動 ID 使用歷史紀錄長度字串表示
        interaction_id = str(len(self.messages))
        return ClaudeInteraction(id=interaction_id, steps=steps, usage=usage_info)

    def set_role(self, role: str):
        self.role = role
        print(f"✓ AI 角色已切換為: {role}")
    
    def set_behavior(self, behavior: str):
        self.behavior = behavior
        print(f"✓ AI 行為模式已切換為: {behavior}")
        
    def set_output_format(self, output_format: str):
        self.output_format = output_format
        print(f"✓ 輸出格式已切換為: {output_format}")
    
    def get_current_config(self) -> dict:
        return {
            "role": self.role,
            "behavior": self.behavior,
            "output_format": self.output_format,
            "model": self.model
        }
    
    def print_config(self):
        print("\n" + "="*50)
        print("🤖 Claude AI 代理配置")
        print("="*50)
        print(f"角色 (Role):       {self.role}")
        print(f"行為 (Behavior):   {self.behavior}")
        print(f"輸出格式 (Output): {self.output_format}")
        print(f"模型 (Model):      {self.model}")
        print("="*50 + "\n")
        
    @staticmethod
    def has_function_calls(interaction) -> bool:
        return any(
            step.type == "function_call"
            for step in interaction.steps
        )
    
    @staticmethod
    def extract_text_response(interaction) -> str:
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
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        
        system_prompt = (
            "你是一個資深的網頁無障礙 (Accessibility) 檢測專家與開發顧問。\n"
            "你的任務是根據所提供的網頁截圖與 Axe-core 檢測出的靜態違規數據，撰寫專業的無障礙評估報告與修復方向建議。\n"
            "**請絕對不要嘗試使用或提及 any 瀏覽器操作工具**，你只需要作為一個分析器，直接產出最終的 Markdown 診斷報告。\n"
            "報告請採用繁體中文（Traditional Chinese）。"
        )
        
        wcag_instruction = ""
        if wcag_guideline:
            wcag_instruction = (
                f"\n⚠️ **重要限制指示**：使用者目前僅針對無障礙指南 **WCAG {wcag_guideline}** 進行檢測，"
                f"因此你的診斷、分析與優化方向**必須完全限制並聚焦於與 WCAG {wcag_guideline} 相關的要素**（例如若檢測 1.1，則僅分析非文字內容/圖片替代文字；若為 2.1，則僅聚焦鍵盤存取等）。"
                f"請絕對不要提及或列出任何屬於其他無障礙章節（如鍵盤、焦點、對比度、動態更新等）的評估或修復方向建議！\n"
            )
            
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"目標網址: {target_url}\n{wcag_instruction}\n"
                            f"以下是本地 Axe-core 掃描出的違規數據：\n\n{audit_data_text}\n\n"
                            f"請為我們進行智慧診斷，撰寫一份 Markdown 報告。為了保持報告精簡，請嚴格遵守以下格式與限制：\n"
                            f"1. **報告結構**：僅限包含『1. 執行摘要 (Executive Summary)』與『2. 智慧診斷與評估 (AI Diagnosis & Evaluation)』，僅在有實際違規項目時才包含『3. 修復方向建議 (Remediation Directions)』。\n"
                            f"2. **❌ 絕對禁止贅字廢話**：請絕對不要撰寫任何『建議後續行動』、『結論/總結』、『結語』或『未來指引』等贅字廢話章節！寫完主體內容後請立即結束回答。\n"
                            f"3. **無違規時省略修復建議**：若本次檢測無任何違規項目（0 違規），請完全省略『3. 修復方向建議』章節，僅撰寫前兩個章節即可。\n"
                            f"4. **禁止代碼範例**：請給出清晰好理解的具體修復邏輯或屬性指引，**請絕對不要提供任何 HTML/CSS/JS 程式碼/代碼修改範例**。"
                        )
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": screenshot_base64
                        }
                    }
                ]
            }
        ]
        
        # 取得與主對話相同的 beta header 配置，確保自訂閘道代理能成功進行路由分發
        beta_header = CLAUDE_COMPUTER_BETAS
        if "-20241022" in self.model or "sonnet" in self.model.lower():
            beta_header = "computer-use-2025-01-24"
        betas = [] if CLAUDE_DISABLE_EXPERIMENTAL_BETAS == "1" else [beta_header]

        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            betas=betas
        )
        
        # 尋找其中的 text 區塊並串接
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
                
        # 提取 Token 使用量
        input_tokens = response.usage.input_tokens if hasattr(response, "usage") else 0
        output_tokens = response.usage.output_tokens if hasattr(response, "usage") else 0
        total_tokens = input_tokens + output_tokens
        
        return {
            "text": "".join(text_parts),
            "usage": {
                "input": input_tokens,
                "output": output_tokens,
                "total": total_tokens
            }
        }
