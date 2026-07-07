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
    CLAUDE_COMPUTER_BETAS
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
        # 決定使用的 API Key/Token：優先使用 CLAUDE_AUTH_TOKEN，若無則使用 CLAUDE_API_KEY
        api_key = CLAUDE_AUTH_TOKEN or CLAUDE_API_KEY
        base_url = CLAUDE_BASE_URL or None
        
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

    def _create_claude_response(self):
        """呼叫 Claude Messages API 並轉換為統一互動格式"""
        # 執行歷史截圖剪裁以節約 Token 消耗
        self._prune_history_images()
        
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
            }
        ]
        
        # 根據環境變數或配置決定是否傳送 beta 標頭（預設啟用 computer-use beta）
        betas = [] if CLAUDE_DISABLE_EXPERIMENTAL_BETAS == "1" else [beta_header]
        
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4096,
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
