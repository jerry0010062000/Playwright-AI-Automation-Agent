import os
import json
import time
import urllib.request

# ========================================
# 基準硬編碼定價表 (Base 7/7 Hardcoded Baseline)
# 單位: USD / 1M Tokens
# ========================================
BASE_7_7_PRICING = {
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
    # 預設基準 (Base Fallback)
    "default": {"input": 3.0, "output": 15.0}
}

MODEL_PRICING = BASE_7_7_PRICING.copy()

_LIVE_PRICING_CACHE = None
_LIVE_PRICING_LOADED = False


def fetch_live_model_pricing(cache_file: str = "records/pricing_cache.json", ttl_seconds: int = 86400, timeout: float = 2.0) -> dict:
    """
    動態即時定價抓取系統：
    1. 優先檢查本地硬碟快取 (預設有效期限 24 小時)。
    2. 若快取過期或不存在，嘗試連網向公開 Model Pricing 端點獲取最新牌價。
    3. 若連網失敗或逾時，平滑降級 (Fall back) 至 Base 7/7 硬編碼基準定價表。
    """
    global _LIVE_PRICING_CACHE, _LIVE_PRICING_LOADED
    
    if _LIVE_PRICING_LOADED and _LIVE_PRICING_CACHE:
        return _LIVE_PRICING_CACHE

    now = time.time()
    
    # 1. 檢查本地快取檔
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
                timestamp = cache_data.get("timestamp", 0)
                prices = cache_data.get("prices", {})
                if now - timestamp < ttl_seconds and prices:
                    _LIVE_PRICING_CACHE = prices
                    _LIVE_PRICING_LOADED = True
                    return _LIVE_PRICING_CACHE
        except Exception:
            pass

    # 2. 連網自動抓取最新牌價
    pricing_endpoints = [
        "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json",
        "https://cdn.jsdelivr.net/gh/BerriAI/litellm@main/model_prices_and_context_window.json"
    ]
    
    live_prices = {}
    for url in pricing_endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ASACC-Pricing-Fetcher/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    raw_json = json.loads(response.read().decode("utf-8"))
                    for m_name, meta in raw_json.items():
                        if isinstance(meta, dict):
                            in_cost = meta.get("input_cost_per_token")
                            out_cost = meta.get("output_cost_per_token")
                            if in_cost is not None and out_cost is not None:
                                live_prices[m_name.lower()] = {
                                    "input": round(float(in_cost) * 1_000_000, 4),
                                    "output": round(float(out_cost) * 1_000_000, 4)
                                }
                    if live_prices:
                        break
        except Exception:
            continue

    if live_prices:
        # 寫入本地快取檔
        try:
            cache_dir = os.path.dirname(cache_file)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"timestamp": now, "prices": live_prices}, f, indent=2)
        except Exception:
            pass
        _LIVE_PRICING_CACHE = live_prices
        _LIVE_PRICING_LOADED = True
        return _LIVE_PRICING_CACHE

    # 3. 抓取失敗，回傳空字典以觸發 Fallback
    _LIVE_PRICING_LOADED = True
    return {}


def resolve_model_rates(model_name: str) -> tuple[dict, str, str]:
    """
    動態解析模型費率，優先採用即時抓取牌價，失敗時自動 Fall back 至 Base 7/7 基準表。
    回傳: (rates_dict, matched_model_key, source_description)
    """
    model_name_norm = model_name.lower().replace("-", ".").replace("_", ".")
    
    # 嘗試從自動抓取系統獲取
    live_pricing = fetch_live_model_pricing()
    if live_pricing:
        # 精確比對
        if model_name.lower() in live_pricing:
            return live_pricing[model_name.lower()], model_name, "即時抓取牌價 (Live API)"
        # 模糊比對
        for k, rates in live_pricing.items():
            k_norm = k.replace("-", ".").replace("_", ".")
            if k_norm in model_name_norm or model_name_norm in k_norm:
                return rates, k, "即時抓取牌價 (Live API)"

    # Fall back 到 Base 7/7 硬編碼基準表
    matched_key = None
    for key in BASE_7_7_PRICING:
        if key == "default":
            continue
        key_norm = key.replace("-", ".").replace("_", ".")
        if key_norm in model_name_norm or model_name_norm in key_norm:
            matched_key = key
            break
            
    if not matched_key:
        if "opus" in model_name_norm:
            matched_key = "claude-3-opus"
        elif "haiku" in model_name_norm:
            matched_key = "claude-3-5-haiku"
        elif "fable" in model_name_norm:
            matched_key = "claude-fable-5"
        elif "mythos" in model_name_norm:
            matched_key = "claude-mythos-5"
        elif "gemini" in model_name_norm:
            if "flash" in model_name_norm:
                matched_key = "gemini-2.5-flash"
            else:
                matched_key = "gemini-2.5-pro"
        else:
            matched_key = "claude-sonnet-5"
            
    rates = BASE_7_7_PRICING.get(matched_key, BASE_7_7_PRICING["default"])
    return rates, matched_key, "基準定價表 (Base 7/7 Hardcoded Fallback)"


def get_interaction_tokens(interaction) -> dict:
    """
    統一解析 AI 互動物件中的 Token 消耗量（包含 Prompt Caching 資訊）
    """
    tokens = {
        "input": 0,
        "output": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "total": 0
    }
    if not interaction:
        return tokens
        
    # 1. 檢查 ClaudeInteraction 物件的 usage 字典
    if hasattr(interaction, "usage") and isinstance(interaction.usage, dict):
        u = interaction.usage
        tokens["input"] = u.get("input_tokens", 0)
        tokens["output"] = u.get("output_tokens", 0)
        tokens["cache_creation_input_tokens"] = u.get("cache_creation_input_tokens", 0) or 0
        tokens["cache_read_input_tokens"] = u.get("cache_read_input_tokens", 0) or 0
        tokens["total"] = u.get("total_tokens", tokens["input"] + tokens["output"])
        return tokens

    # 2. 檢查通用 usage 物件 (例如 Anthropic Message 物件)
    if hasattr(interaction, "usage"):
        u = interaction.usage
        tokens["input"] = getattr(u, "input_tokens", 0)
        tokens["output"] = getattr(u, "output_tokens", 0)
        tokens["cache_creation_input_tokens"] = getattr(u, "cache_creation_input_tokens", 0) or 0
        tokens["cache_read_input_tokens"] = getattr(u, "cache_read_input_tokens", 0) or 0
        tokens["total"] = getattr(u, "total_tokens", tokens["input"] + tokens["output"])
        return tokens
        
    return tokens


def print_token_and_cost_summary(model_name: str, input_tokens: int, output_tokens: int, report_target=None, cache_read_tokens: int = 0, cache_creation_tokens: int = 0):
    """
    計算並列印 Token 消耗與花費統計（含即時動態抓取 / Base 7/7 Fallback 與 Prompt Caching 節省統計）
    """
    total_tokens = input_tokens + output_tokens
    
    rates, model_key, pricing_source = resolve_model_rates(model_name)
    
    # 快取讀取費率通常為一般輸入的 10% (節省約 90%)
    cached_input_rate = rates["input"] * 0.1
    uncached_inputs = max(0, input_tokens - cache_read_tokens)
    
    usd_input_cost = (uncached_inputs / 1_000_000.0) * rates["input"] + (cache_read_tokens / 1_000_000.0) * cached_input_rate
    usd_output_cost = (output_tokens / 1_000_000.0) * rates["output"]
    total_usd_cost = usd_input_cost + usd_output_cost
    
    EXCHANGE_RATE_TWD = 32.5
    total_twd_cost = total_usd_cost * EXCHANGE_RATE_TWD
    
    cache_info_lines = ""
    if cache_read_tokens > 0 or cache_creation_tokens > 0:
        cache_info_lines = (
            f"  快取讀取 (Prompt Cache Read) : {cache_read_tokens:,} Tokens (節省 ~90% 費率)\n"
            f"  快取寫入 (Cache Creation)     : {cache_creation_tokens:,} Tokens\n"
        )
    
    token_summary = (
        f"\n{'='*60}\n"
        f"[Token 消耗與花費統計 (Token Usage & Cost Summary)]\n"
        f"{'='*60}\n"
        f"  輸入 Token (Input Tokens)  : {input_tokens:,}\n"
        f"  輸出 Token (Output Tokens) : {output_tokens:,}\n"
        f"{cache_info_lines}"
        f"  總計 Token (Total Tokens)  : {total_tokens:,}\n"
        f"{'-'*60}\n"
        f"  計費模型 (Pricing Model)   : {model_key} (輸入: ${rates['input']:.2f}/M, 輸出: ${rates['output']:.2f}/M)\n"
        f"  定價來源 (Pricing Source)  : {pricing_source}\n"
        f"  預估花費 (Estimated Cost)  : ${total_usd_cost:.5f} USD\n"
        f"  折合台幣 (Converted Cost)  : NT$ {total_twd_cost:.3f} TWD (匯率: {EXCHANGE_RATE_TWD})\n"
        f"{'='*60}\n"
    )
    print(token_summary)
    
    if report_target is not None:
        cache_report_md = ""
        if cache_read_tokens > 0:
            cache_report_md = f"- **快取讀取 Token (Cache Read)**: `{cache_read_tokens:,}` (節省成本與延遲)\n"
            
        report_text = (
            f"## Token 消耗與花費統計\n\n"
            f"- **輸入 Token 數 (Input Tokens)**: `{input_tokens:,}`\n"
            f"- **輸出 Token 數 (Output Tokens)**: `{output_tokens:,}`\n"
            f"{cache_report_md}"
            f"- **總計 Token 數 (Total Tokens)**: `{total_tokens:,}`\n"
            f"- **計費模型 (Pricing Model)**: `{model_key}` (輸入: ${rates['input']:.2f}/M, 輸出: ${rates['output']:.2f}/M)\n"
            f"- **定價來源 (Pricing Source)**: `{pricing_source}`\n"
            f"- **預估美金花費 (Estimated USD)**: `${total_usd_cost:.5f} USD`\n"
            f"- **預估台幣花費 (Estimated TWD)**: `NT$ {total_twd_cost:.3f} TWD` (匯率: {EXCHANGE_RATE_TWD})\n"
            f"- *註記：此費用係依官方公開牌價標準計算，僅供參考*\n\n"
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
        "【稽核與每回合思考標準指導方針 (Two-Section Reasoning & SPEC Mapping)】:\n"
        f"1. **嚴格限制檢測範圍**：本次檢測任務專注於【WCAG Guideline {wcag_ver}】。請絕對不要檢測或回報屬於其他章節的條款！\n"
        "2. **每回合思考文字必須嚴格分為兩節**：\n"
        "   - **第一節：【上一動狀態與截圖/DOM 分析】**：整理上一張截圖得到的訊息（焦點 activeElement 位於何處、標籤 ID、文字、可視狀態、畫面是否有彈窗/抽屜展開）。\n"
        f"   - **第二節：【下一步計畫與對應 WCAG SPEC 條款】**：規劃下一步動作，並**明確說明這是依照本次注入之 WCAG Guideline {wcag_ver} 中的哪一個具體條款** 進行的閱讀理解與驗證。\n"
        "3. 每當完成一個頁面的走訪與無障礙診斷後，請務必於回答中包含 `WCAG`、`合規對照表`、`Success Criteria` 關鍵字之詳細條款對照表與問題修復建議。\n"
        f"4. 對照表必須清晰寫出 Success Criteria 編號 (僅限 Guideline {wcag_ver} 條款)、等級 (Level A/AA/AAA)、合規狀態 (PASS/FAIL) 及具體受影響的 DOM 元素。"
    )
    
    return full_instructions, rules_text
