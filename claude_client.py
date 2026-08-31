"""
Claude AI 客戶端模組
處理與 Anthropic Claude API 的互動，包括建立對話、發送截圖、處理回應等
"""

import os
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
    CLAUDE_USE_GATEWAY,
    resolve_computer_config
)


class ClaudeContentBlock:
    """Claude Content Block 結構封裝"""
    def __init__(self, text: str, type: str = "text"):
        self.text = text
        self.type = type


class ClaudeStep:
    """Claude Step 步驟結構封裝"""
    def __init__(self, type: str, content: list = None, name: str = None, id: str = None, arguments: dict = None):
        self.type = type
        self.content = content or []
        self.name = name
        self.id = id
        self.arguments = arguments or {}


class ClaudeInteraction:
    """Claude Interaction 互動作為統一回應物件"""
    def __init__(self, id: str, steps: list, usage: dict = None):
        self.id = id
        self.steps = steps
        self.usage = usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

class ClaudeAgent:
    """Claude AI 代理封裝類別"""

    
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
        # 決定使用的 API Key/Token 與 Base URL（支援自訂 Base URL、Proxy 或 Gateway 代理配置）
        if CLAUDE_USE_GATEWAY or CLAUDE_BASE_URL:
            api_key = CLAUDE_AUTH_TOKEN or CLAUDE_API_KEY or "dummy-key-for-proxy"
            base_url = CLAUDE_BASE_URL or None
        else:
            api_key = CLAUDE_API_KEY
            base_url = None
        
        # 初始化 Claude 客戶端，設定自訂 Base URL、超時限制與自動重試
        self.client = anthropic.Anthropic(
            api_key=api_key if api_key else None,
            base_url=base_url,
            timeout=60.0,
            max_retries=2
        )
        
        self.role = role or "default"
        self.behavior = behavior or "careful"
        self.output_format = output_format or "natural"
        # 預設使用支援 Computer Use 的最新 Claude 5 Sonnet 模型
        self.model = model or "claude-sonnet-5"
        self.messages = []
        
    def _get_computer_config(self) -> tuple[str, str]:
        """
        根據當前模型版本 (self.model) 與環境變數設定，動態解析並回傳對應的 (tool_type, beta_header)。
        """
        return resolve_computer_config(self.model)
        
    def generate_quick_response(self, prompt: str) -> str:
        """
        快速生成一回合純文字回應 (不使用任何 Tool 或截圖)
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        parts = [block.text for block in response.content if block.type == "text"]
        return "".join(parts)
        
    def create_initial_interaction(
        self, 
        task: str, 
        screenshot_bytes: bytes,
        extra_instructions: str = "",
        skill: str = None
    ):
        """
        建立第一次 Claude 互動
        """
        screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
        
        # 整合核心技能 (SOP) 提示詞
        from prompts import build_prompt
        enhanced_task = build_prompt(
            task=task,
            role=self.role,
            behavior=self.behavior,
            output_format=self.output_format,
            extra_instructions=extra_instructions,
            skill=skill
        )

        # 建立初始對話歷史，並在包含巨大 WCAG 規範與 Focus Map 的任務文字區塊加上 cache_control
        self.messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": enhanced_task,
                        "cache_control": {"type": "ephemeral"}
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
        _, resolved_beta = self._get_computer_config()
        betas = [] if CLAUDE_DISABLE_EXPERIMENTAL_BETAS == "1" else [resolved_beta]

        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system_prompt,
            messages=self.messages,
            betas=betas
        )
        
        # 提取回應文字
        summary = "".join([block.text for block in response.content if block.type == "text"])
        
        tokens = {"input": 0, "output": 0, "total": 0}
        if hasattr(response, "usage") and response.usage:
            tokens["input"] = getattr(response.usage, "input_tokens", 0)
            tokens["output"] = getattr(response.usage, "output_tokens", 0)
            tokens["total"] = tokens["input"] + tokens["output"]
            
        return {
            "summary": summary,
            "usage": tokens
        }

    def _prune_history_images(self, keep_recent: int = 1):
        """
        修剪歷史訊息中的舊截圖，只保留最新 1 回合的截圖，以徹底消除影像 Token 累積。
        為了避免破壞 Anthropic API 的結構，將舊截圖物件替換為極簡的佔位提示文字區塊。
        """
        image_occurrences = []
        for i, msg in enumerate(self.messages):
            content = msg.get("content")
            if isinstance(content, list):
                for j, block in enumerate(content):
                    if isinstance(block, dict):
                        if block.get("type") == "image":
                            image_occurrences.append((i, j, None))
                        elif block.get("type") == "tool_result" and isinstance(block.get("content"), list):
                            for k, sub_block in enumerate(block["content"]):
                                if isinstance(sub_block, dict) and sub_block.get("type") == "image":
                                    image_occurrences.append((i, j, k))
                                
        if len(image_occurrences) > keep_recent:
            for i, j, k in image_occurrences[:-keep_recent]:
                msg = self.messages[i]
                replacement = {
                    "type": "text",
                    "text": "[Historical screenshot pruned to save tokens]"
                }
                if k is None:
                    msg["content"][j] = replacement
                else:
                    msg["content"][j]["content"][k] = replacement

    def _apply_sliding_window(self, keep_recent_turns: int = 15, max_history_turns: int = None):
        """
        結構安全之歷史內容輕量化 (Structural-Safe Token Pruning)：
        保持 Anthropic API 嚴格的 tool_use <-> tool_result ID 配對鏈完好無損，
        但將超過 keep_recent_turns 以外的舊回合龐大內容（如長文字、Focus Map 與截圖）
        精簡替換為極簡標記，完全封頂 Token 消耗，並 100% 避免 400 結構匹配錯誤。
        """
        if max_history_turns is not None:
            keep_recent_turns = max_history_turns
        protected_count = keep_recent_turns * 2
        if len(self.messages) <= 1 + protected_count:
            return

        cutoff_index = len(self.messages) - protected_count
        for idx in range(1, cutoff_index):
            msg = self.messages[idx]
            role = msg.get("role")
            if role == "user" and isinstance(msg.get("content"), list):
                for block_idx, block in enumerate(msg["content"]):
                    if isinstance(block, dict):
                        btype = block.get("type")
                        if btype == "tool_result":
                            block["content"] = [
                                {
                                    "type": "text",
                                    "text": "[Historical step completed successfully]"
                                }
                            ]
                        elif btype == "image":
                            msg["content"][block_idx] = {
                                "type": "text",
                                "text": "[Historical screenshot pruned for context optimization]"
                            }
            elif role == "assistant" and isinstance(msg.get("content"), list):
                # 精簡舊回合的 assistant text 回應，只保留 tool_use 結構
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "text":
                        if len(block.get("text", "")) > 100:
                            block["text"] = block["text"][:100] + "... [Historical reasoning truncated]"

    def _build_system_prompt(self) -> str:
        """
        整合 prompts.py 中的系統提示詞，包含角色特徵、行為原則與例外處理。
        """
        from prompts import IDENTITY_DEFINITIONS, OPERATIONAL_PROTOCOLS, OUTPUT_SPECIFICATIONS
        prompt_parts = []
        
        # 1. 系統角色
        role_prompt = IDENTITY_DEFINITIONS.get(self.role, IDENTITY_DEFINITIONS.get("default", ""))
        if role_prompt:
            prompt_parts.append(role_prompt)
        
        # 2. 行為指引 (包含死循環停損原則)
        behavior_prompt = OPERATIONAL_PROTOCOLS.get(self.behavior, OPERATIONAL_PROTOCOLS.get("careful", ""))
        if behavior_prompt:
            prompt_parts.append(behavior_prompt)
            
        # 3. 輸出格式
        output_prompt = OUTPUT_SPECIFICATIONS.get(self.output_format, OUTPUT_SPECIFICATIONS.get("natural", ""))
        if output_prompt:
            prompt_parts.append(output_prompt)
            
        return "\n\n".join(prompt_parts)

    def _create_claude_response(self):
        """呼叫 Claude Messages API 並轉換為統一互動格式"""
        # 1. 執行歷史截圖剪裁：嚴格限制上下文僅保留最新 1 張截圖（消除 90% 冗餘圖像 Token）
        self._prune_history_images(keep_recent=1)
        # 2. 歷史文字與操作記憶策略：
        # 單頁巡檢內完整保留過去所有動作、思考與 DOM 探測結果，確保 AI 具備 100% 長時記憶不重複操作，
        # 同時維持 Anthropic Prompt Cache 前綴穩定性，享受 90% 快取讀取優惠（僅在極端超過 35 回合時作為安全防線）。
        self._apply_sliding_window(keep_recent_turns=35)
        
        # 建立完整的系統提示詞 (包含行為原則與停損指南)
        system_prompt = self._build_system_prompt()
        
        # 自動根據模型或自訂配置調整 tool type 與 beta header
        tool_type, beta_header = self._get_computer_config()

        # 配置 Anthropic 預設的 Computer Use 工具
        # 為了使運作與截圖精確匹配，寬度設為 1024，高度設為 768
        if "toolset" in tool_type:
            # 對於 computer_toolset 類型的工具集（例如 computer_toolset_20260801），Anthropic API 規定不接受 name、display_width_px、display_height_px 或 display_number 等欄位，僅需傳入 type
            computer_tool = {
                "type": tool_type,
            }
        else:
            # 對於非 toolset 的獨立 computer 工具類型（例如 computer_20241022、computer_20250124），需要指定 name="computer" 並提供 display_* 參數以匹配瀏覽器視窗大小
            computer_tool = {
                "type": tool_type,
                "name": "computer",
                "display_width_px": 1024,
                "display_height_px": 768,
                "display_number": 1,
            }
            
        tools = [
            computer_tool,
            {
                "name": "navigate",
                "description": "Directly navigate to a specific URL in the browser (e.g. 'http://localhost:8000/'). Use this tool when you get lost, navigate to a wrong page, or need to return to the home page.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "intent": {
                            "type": "string",
                            "description": "【強制必填】依照 WCAG 兩段式分析：說明目前觀察到的狀態與下一步對應之 WCAG 條款（例如：WCAG 2.1.1 導航）。"
                        },
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
                    "properties": {
                        "intent": {
                            "type": "string",
                            "description": "【強制必填】依照 WCAG 兩段式分析：說明上一動觀察與返回之 WCAG 條款依據。"
                        }
                    }
                }
            },
            {
                "name": "evaluate_javascript",
                "description": "Evaluate a JavaScript expression on the current webpage and return the result. Use this to inspect the DOM, query elements, check media elements, or retrieve page state without needing DevTools.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "intent": {
                            "type": "string",
                            "description": "【強制必填】依照 WCAG 兩段式分析：說明上一動觀察與本次操作對應之當前任務 WCAG 條款依據。"
                        },
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
                    "properties": {
                        "intent": {
                            "type": "string",
                            "description": "執行 Axe 審查之意圖與 WCAG 規範範圍。"
                        }
                    }
                }
            },
            {
                "name": "scan_focus_path",
                "description": "Scan the current page to retrieve the focus map: all focusable elements, their visual coordinates, and outline styles to check keyboard accessibility.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "intent": {
                            "type": "string",
                            "description": "掃描焦點路徑之意圖與對應 WCAG 條款。"
                        }
                    }
                }
            }
        ]
        
        # 根據環境變數或配置決定是否傳送 beta 標頭（預設啟用 computer-use beta 與 prompt-caching）
        betas = []
        if CLAUDE_DISABLE_EXPERIMENTAL_BETAS != "1":
            if beta_header:
                betas.append(beta_header)
            if "prompt-caching-2024-07-25" not in betas:
                betas.append("prompt-caching-2024-07-25")
        
        # 標記系統提示詞啟用 Prompt Caching
        system_blocks = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ]
        
        # 在最後一個 Tool 上啟用 Prompt Caching 斷點
        if tools:
            tools[-1]["cache_control"] = {"type": "ephemeral"}

        # Diagnostic logging: only show summary and the last message details to prevent terminal bloat
        print(f"[*] API Call: System Prompt Length = {len(system_prompt)} chars (Prompt Caching Enabled)")
        print(f"[*] API Call: Number of messages in history = {len(self.messages)}")
        if self.messages:
            last_msg = self.messages[-1]
            last_msg_str = json.dumps(last_msg, ensure_ascii=False)
            print(f"  - Latest Message ({last_msg['role']}): {len(last_msg_str)} chars")
            
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_blocks,
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
        
        # 提取 token 使用量 (包含 Prompt Cache 讀取與寫入統計)
        usage_info = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "total_tokens": 0
        }
        if hasattr(response, "usage") and response.usage:
            usage_info["input_tokens"] = getattr(response.usage, "input_tokens", 0)
            usage_info["output_tokens"] = getattr(response.usage, "output_tokens", 0)
            usage_info["cache_creation_input_tokens"] = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            usage_info["cache_read_input_tokens"] = getattr(response.usage, "cache_read_input_tokens", 0) or 0
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
        texts = []
        for step in interaction.steps:
            if step.type == "model_output":
                for content_block in step.content:
                    if content_block.type == "text" and content_block.text:
                        texts.append(content_block.text.strip())
            elif step.type == "function_call":
                args = step.arguments
                if isinstance(args, dict) and "intent" in args and args["intent"]:
                    intent_text = args["intent"].strip()
                    if intent_text and intent_text not in texts:
                        texts.append(f"【WCAG 動作依據與分析】: {intent_text}")
        return "\n\n".join(texts)

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
                            f"請為我們進行智慧診斷，撰寫一份高嚴謹度的無障礙 Markdown 評估報告。請嚴格遵守以下結構與指示：\n"
                            f"1. **【必須包含】第 1 章：規範涵蓋與成功條款合規對照表 (WCAG 2.2 Success Criteria Compliance Matrix Table)**：\n"
                            f"   - 必須在此章節完整建立 Markdown 表格，精確列出對應的 3 位數 Success Criteria 成功條款 (如 1.1.1, 1.3.1, 1.4.3, 2.1.4, 2.4.7, 4.1.2 等)、條款名稱、合規等級 (Level A / AA / AAA) 及實測合規狀態 (PASS / FAIL / 違規件數)。\n"
                            f"2. **第 2 章：執行摘要 (Executive Summary)**：依據第 1 章表格，概括合規狀況與風險等級。\n"
                            f"3. **第 3 章：智慧診斷與深度評估 (AI Diagnosis & Evaluation)**：**後續的所有問題分析、影響評估都必須嚴格依據第 1 章表格中的 3 位數成功條款進行關聯與對應**！\n"
                            f"4. **第 4 章：修復方向建議 (Remediation Directions)**：若有違規，依據 Level A -> Level AA 優先級，針對 3 位數條款給出明確的修復指引（請給出邏輯說明，不要貼程式碼片段）。\n"
                            f"5. **❌ 絕對禁止贅字廢話**：請絕對不要撰寫任何『建議後續行動』、『結語』或『未來指引』等贅字章節！寫完主題內容後請立即結束。範例請保持嚴謹精確。"
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
        _, resolved_beta = self._get_computer_config()
        betas = []
        if CLAUDE_DISABLE_EXPERIMENTAL_BETAS != "1":
            if resolved_beta:
                betas.append(resolved_beta)
            if "prompt-caching-2024-07-25" not in betas:
                betas.append("prompt-caching-2024-07-25")

        system_blocks = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}
            }
        ]

        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_blocks,
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
        cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) if hasattr(response, "usage") else 0
        cache_read = getattr(response.usage, "cache_read_input_tokens", 0) if hasattr(response, "usage") else 0
        total_tokens = input_tokens + output_tokens
        
        return {
            "text": "".join(text_parts),
            "usage": {
                "input": input_tokens,
                "output": output_tokens,
                "cache_creation_input_tokens": cache_creation or 0,
                "cache_read_input_tokens": cache_read or 0,
                "total": total_tokens
            }
        }


def get_function_responses(
    page, 
    results: List[Tuple[str, str, dict]], 
    interaction=None
) -> List[dict]:
    """
    將執行結果轉換為 Claude/Gemini API 可接受的回應格式
    包含當前頁面截圖和執行狀態
    """
    # 擷取當前頁面截圖
    screenshot_bytes = page.screenshot(type="png")
    current_url = page.url
    
    # 檢查是否需要安全確認
    needs_safety = False
    if interaction and getattr(interaction, "steps", None):
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
    
    for idx, (name, call_id, result) in enumerate(results):
        final_result = {"url": current_url, **result}
        if needs_safety:
            final_result["safety_acknowledgement"] = True
            
        result_blocks = [
            {
                "type": "text",
                # 將結果序列化為 JSON，包含當前網址與安全認證
                "text": json.dumps(final_result)
            }
        ]
        
        # 核心優化：只在該回合的「最後一個動作」附加截圖，避免一次批次執行多個動作時送出重複的巨型 Base64 截圖
        if idx == len(results) - 1:
            result_blocks.append({
                "type": "image",
                "data": base64.b64encode(screenshot_bytes).decode("utf-8"),
                "mime_type": "image/png"
            })
            
        # 為每個執行的函數建立回應
        function_responses.append({
            "type": "function_result",
            "name": name,
            "call_id": call_id,
            "result": result_blocks
        })
    
    return function_responses


def ask_claude(prompt: str, model: str = None) -> str:
    """
    極簡的單回合對話呼叫，供快速測試或指令碼整合使用。
    """
    agent = ClaudeAgent(model=model)
    return agent.generate_quick_response(prompt)

