import os

# ========================================
# 模型定價表 (USD / 1M Tokens)
# ========================================
MODEL_PRICING = {
    # Fable & Mythos
    "claude-fable-5": {"input": 10.0, "output": 50.0},
    "claude-mythos-5": {"input": 10.0, "output": 50.0},
    # Opus 系列
    "claude-opus-4.8": {"input": 5.0, "output": 25.0},
    "claude-opus-4.7": {"input": 5.0, "output": 25.0},
    "claude-opus-4.6": {"input": 5.0, "output": 25.0},
    "claude-opus-4.5": {"input": 5.0, "output": 25.0},
    "claude-opus-4.1": {"input": 15.0, "output": 75.0},
    "claude-opus-4": {"input": 15.0, "output": 75.0},
    "claude-3-opus": {"input": 15.0, "output": 75.0},
    # Sonnet 系列
    "claude-sonnet-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4.6": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4.5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    # Haiku 系列
    "claude-haiku-4.5": {"input": 1.0, "output": 5.0},
    "claude-haiku-3.5": {"input": 0.8, "output": 4.0},
    "claude-3-5-haiku": {"input": 0.8, "output": 4.0},
    # Gemini 系列
    "gemini-2.5-computer-use": {"input": 1.25, "output": 5.0},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.0},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.3},
    # 預設
    "default": {"input": 3.0, "output": 15.0}
}


def get_interaction_tokens(interaction) -> dict:
    """
    統一解析 AI 互動物件中的 Token 消耗量
    """
    tokens = {"input": 0, "output": 0, "total": 0}
    if not interaction:
        return tokens
        
    # 1. 檢查 ClaudeInteraction 物件的 usage 字典
    if hasattr(interaction, "usage") and isinstance(interaction.usage, dict):
        u = interaction.usage
        tokens["input"] = u.get("input_tokens", 0)
        tokens["output"] = u.get("output_tokens", 0)
        tokens["total"] = u.get("total_tokens", tokens["input"] + tokens["output"])
        return tokens

    # 2. 檢查通用 usage 物件 (例如 Anthropic Message 物件)
    if hasattr(interaction, "usage"):
        u = interaction.usage
        tokens["input"] = getattr(u, "input_tokens", 0)
        tokens["output"] = getattr(u, "output_tokens", 0)
        tokens["total"] = getattr(u, "total_tokens", tokens["input"] + tokens["output"])
        return tokens
        
    return tokens


def print_token_and_cost_summary(model_name: str, input_tokens: int, output_tokens: int, report_target=None):
    """
    計算並列印 Token 消耗與花費統計，支援寫入檔案物件或附加至報告列表
    """
    total_tokens = input_tokens + output_tokens
    
    model_name_norm = model_name.lower().replace("-", ".").replace("_", ".")
    model_key = None
    
    # 進行標準化模糊比對
    for key in MODEL_PRICING:
        if key == "default":
            continue
        key_norm = key.replace("-", ".").replace("_", ".")
        if key_norm in model_name_norm or model_name_norm in key_norm:
            model_key = key
            break
            
    # 概略 fallback 比對
    if not model_key:
        if "opus" in model_name_norm:
            model_key = "claude-3-opus"
        elif "haiku" in model_name_norm:
            model_key = "claude-3-5-haiku"
        elif "fable" in model_name_norm:
            model_key = "claude-fable-5"
        elif "mythos" in model_name_norm:
            model_key = "claude-mythos-5"
        elif "gemini" in model_name_norm:
            if "flash" in model_name_norm:
                model_key = "gemini-2.5-flash"
            else:
                model_key = "gemini-2.5-pro"
        else:
            model_key = "claude-sonnet-5"
            
    rates = MODEL_PRICING.get(model_key, MODEL_PRICING["default"])
    usd_input_cost = (input_tokens / 1_000_000.0) * rates["input"]
    usd_output_cost = (output_tokens / 1_000_000.0) * rates["output"]
    total_usd_cost = usd_input_cost + usd_output_cost
    
    EXCHANGE_RATE_TWD = 32.5
    total_twd_cost = total_usd_cost * EXCHANGE_RATE_TWD
    
    token_summary = (
        f"\n{'='*60}\n"
        f"💰 Token 消耗與花費統計 (Token Usage & Cost Summary)\n"
        f"{'='*60}\n"
        f"  輸入 Token (Input Tokens)  : {input_tokens:,}\n"
        f"  輸出 Token (Output Tokens) : {output_tokens:,}\n"
        f"  總計 Token (Total Tokens)  : {total_tokens:,}\n"
        f"{'-'*60}\n"
        f"  計費模型 (Pricing Model)   : {model_key} (輸入: ${rates['input']:.2f}/M, 輸出: ${rates['output']:.2f}/M)\n"
        f"  預估花費 (Estimated Cost)  : ${total_usd_cost:.5f} USD\n"
        f"  折合台幣 (Converted Cost)  : NT$ {total_twd_cost:.3f} TWD (匯率: {EXCHANGE_RATE_TWD})\n"
        f"{'='*60}\n"
    )
    print(token_summary)
    
    if report_target is not None:
        report_text = (
            f"## 💰 Token 消耗與花費統計\n\n"
            f"- **輸入 Token 數 (Input Tokens)**: `{input_tokens:,}`\n"
            f"- **輸出 Token 數 (Output Tokens)**: `{output_tokens:,}`\n"
            f"- **總計 Token 數 (Total Tokens)**: `{total_tokens:,}`\n"
            f"- **計費模型 (Pricing Model)**: `{model_key}` (輸入: ${rates['input']:.2f}/M, 輸出: ${rates['output']:.2f}/M)\n"
            f"- **預估美金花費 (Estimated USD)**: `${total_usd_cost:.5f} USD`\n"
            f"- **預估台幣花費 (Estimated TWD)**: `NT$ {total_twd_cost:.3f} TWD` (匯率: {EXCHANGE_RATE_TWD})\n"
            f"- *註記：此費用係依公開官方定價計算，僅供參考*\n\n"
        )
        if isinstance(report_target, list):
            report_target.append("\n" + "---" + "\n")
            report_target.append(report_text)
        elif hasattr(report_target, "write") and not getattr(report_target, "closed", False):
            try:
                report_target.write("\n" + "---" + "\n\n")
                report_target.write(report_text)
                report_target.flush()
            except Exception:
                pass


def build_wcag_prompt(user_task: str, wcag_ver: str, rules_dir: str = "documentation/wcag_rules") -> tuple:
    """
    組裝並注入特定的 WCAG 指南規範文檔至任務提示詞中
    """
    rule_filename = f"guideline_{wcag_ver}.md"
    rule_path = os.path.join(rules_dir, rule_filename)
    
    rules_text = ""
    if os.path.exists(rule_path):
        try:
            with open(rule_path, "r", encoding="utf-8") as f:
                rules_text = f.read()
            print(f"[✓] 成功注入 WCAG {wcag_ver} 規範指引文檔: {rule_path}")
        except Exception as e:
            print(f"[WARNING] 讀取 WCAG 規範檔案失敗 ({rule_path}): {e}")
    else:
        print(f"[WARNING] WCAG rules file {rule_path} not found. Running without injected rules.")

    full_instructions = (
        f"【任務標的與要求】:\n{user_task}\n\n"
        f"【注入之 WCAG 2.2 / 無障礙對照與稽核規範 (Guideline {wcag_ver})】:\n"
        f"{rules_text if rules_text else '請依據 WCAG 2.2 通用規範進行評估。'}\n\n"
        "【稽核與報告產出指導方針】:\n"
        "1. 請依照網站地圖進行全站巡檢。\n"
        "2. 每當完成一個頁面的走訪與無障礙診斷後，請務必於回答中包含包含 `WCAG`、`合規對照表`、`Success Criteria` 關鍵字之詳細條款對照表與問題修復建議。\n"
        "3. 對照表必須清晰寫出 Success Criteria 編號 (例如 2.1.1, 2.4.7)、等級 (Level A/AA/AAA)、合規狀態 (PASS/FAIL) 及具體受影響的 DOM 元素。"
    )
    
    return full_instructions, rules_text
