import os

MODEL_PRICING = {
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-3-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-3-5": {"input": 0.80, "output": 4.00},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "default": {"input": 3.00, "output": 15.00}
}

def print_token_and_cost_summary(model_name: str, input_tokens: int, output_tokens: int, report_file=None):
    """
    計算並於控制台與報告中格式化印出 Token 消耗與預估 API 花費 (美金 & 折合台幣)
    """
    total_tokens = input_tokens + output_tokens
    
    # 尋找匹配的計費模型
    pricing = MODEL_PRICING.get("default")
    model_lower = model_name.lower()
    for key, price_info in MODEL_PRICING.items():
        if key in model_lower:
            pricing = price_info
            break
            
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    total_cost_usd = input_cost + output_cost
    twd_exchange_rate = 32.5
    total_cost_twd = total_cost_usd * twd_exchange_rate
    
    summary_text = (
        f"\n============================================================\n"
        f"💰 Token 消耗與花費統計 (Token Usage & Cost Summary)\n"
        f"============================================================\n"
        f"  輸入 Token (Input Tokens)  : {input_tokens:,}\n"
        f"  輸出 Token (Output Tokens) : {output_tokens:,}\n"
        f"  總計 Token (Total Tokens)  : {total_tokens:,}\n"
        f"------------------------------------------------------------\n"
        f"  計費模型 (Pricing Model)   : {model_name} (輸入: ${pricing['input']:.2f}/M, 輸出: ${pricing['output']:.2f}/M)\n"
        f"  預估花費 (Estimated Cost)  : ${total_cost_usd:.5f} USD\n"
        f"  折合台幣 (Converted Cost)  : NT$ {total_cost_twd:.3f} TWD (匯率: {twd_exchange_rate})\n"
        f"============================================================\n"
    )
    
    print(summary_text)
    if report_file and not report_file.closed:
        try:
            report_file.write("\n" + summary_text + "\n")
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
