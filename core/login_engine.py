import time
from config import MAX_LOGIN_TURNS
from core.prompt_builder import get_interaction_tokens


def handle_auto_login(page, username: str, password: str) -> bool:
    """
    透過 DOM 選擇器快速嘗試在登入頁面填入帳號密碼並點擊登入
    """
    print("[*] 偵測到已提供登入資訊，嘗試自動填表登入...")
    try:
        # 1. 尋找密碼欄位
        password_input = page.query_selector("input[type='password']")
        if not password_input:
            print("[WARNING] 未找到密碼欄位，跳過自動填表登入。")
            return False
            
        # 2. 尋找帳號欄位
        username_input = page.query_selector("input[type='text']:not([style*='display: none']):not([style*='visibility: hidden'])")
        if not username_input:
            username_input = page.query_selector("#username, #login-username, input[name='username'], input[name='user']")
            
        if username_input and username:
            print(f"[*] 輸入帳號: {username}")
            username_input.fill(username)
            
        print("[*] 輸入密碼...")
        password_input.fill(password)
        
        # 3. 尋找並點擊登入按鈕
        login_btn = page.query_selector("button[type='submit'], input[type='submit'], #login-btn, #login_btn, button:has-text('Login'), button:has-text('登入')")
        if not login_btn:
            login_btn = page.query_selector("button, input[type='button']")
            
        if login_btn:
            print("[*] 點擊登入按鈕...")
            login_btn.click()
        else:
            print("[*] 未找到登入按鈕，嘗試在密碼欄位發送 Enter 鍵...")
            password_input.press("Enter")
            
        page.wait_for_timeout(3000)
        print("[✓] 自動填表登入步驟完成。")
        return True
    except Exception as e:
        print(f"[WARNING] 自動登入失敗: {e}")
        return False


def perform_ai_login_phase(page, model_name: str, username: str, password: str) -> dict:
    """
    自訂預登入階段：引導 AI 自動識別登入頁面、填寫憑證並發送表單，實現無人值守後台無障礙巡檢
    傳回格式: {
        "input": int, 
        "output": int, 
        "cache_read_input_tokens": int,
        "cache_creation_input_tokens": int,
        "total": int, 
        "success": bool
    }
    """
    print("\n" + "="*60)
    print(f"[AI 預登入] 啟動 AI 預先登入程序...")
    print(f"  - 使用模型: {model_name}")
    print(f"  - 帳號: {username if username else '(未指定)'}")
    print("="*60)

    # 根據模型類型實體化 AI 代理
    is_claude = model_name.lower().startswith("claude-")
    try:
        from claude_client import ClaudeAgent
        if is_claude:
            agent = ClaudeAgent(model=model_name)
        else:
            print(f"[AI 預登入] [WARNING] 偵測到非 Claude 模型 '{model_name}'，已自動轉為使用預設 Claude 代理。")
            agent = ClaudeAgent(model="claude-3-5-sonnet-20241022")
    except Exception as e:
        print(f"[AI 預登入] [WARNING] 無法實體化 AI 模型 ({model_name}): {e}，跳過預登入階段。")
        return {
            "input": 0, "output": 0, 
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, 
            "total": 0, "success": False
        }

    # 組裝 AI 預登入專用提示詞
    login_prompt = (
        f"請登入此網站（備用帳號為 '{username}'，密碼為 '{password}'）。\n"
        "【語言與思考格式規範】：所有思考過程 (Thoughts) 與操作描述必須一律使用「繁體中文（台灣）」，清楚說明當前頁面元素與預計動作。\n"
        "1. 首先判斷當前畫面是否為登入頁面。如果已經在登入狀態（或非登入頁面），請立刻使用文字說明並結束任務。\n"
        "2. 【單一密碼欄位與雙欄位判定關鍵原則】：\n"
        f"   - **單一欄位頁面**：若頁面只有一個輸入框（例如路由器、網管裝置僅有一個密碼輸入框），請『直接在該唯一輸入框點擊並輸入密碼 \"{password}\"』，不要嘗試尋找帳號欄位或輸入帳號！\n"
        f"   - **雙欄位頁面**：若頁面同時包含帳號與密碼兩個輸入框，才分別點擊並輸入帳號 \"{username}\" 與密碼 \"{password}\"。\n"
        "3. 為了避免現代前端框架（如 React/Vue）的狀態綁定 (state binding) 失效，請『務必使用滑鼠點擊輸入框』並『使用鍵盤打字 (type/key)』，『絕對不要』使用 Javascript (evaluate_javascript) 直接修改欄位的 value。\n"
        "4. 點擊登入/送出按鈕 (Submit/Login/OK)，並等待登入跳轉完成。\n"
        "5. 登入成功進入後台儀表板或首頁後，請立刻結束任務（不要進行任何無障礙檢測，直接完成任務）。"
    )
    
    viewport_width = 1024 if is_claude else 1440
    viewport_height = 768 if is_claude else 900
    
    try:
        login_input_tokens = 0
        login_output_tokens = 0
        login_cache_read_tokens = 0
        login_cache_creation_tokens = 0
        login_total_tokens = 0
        
        # DOM 探測：檢測頁面上可見輸入框數量
        single_field_hint = ""
        try:
            input_detect_script = """
            (() => {
                const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"])'))
                    .filter(i => i.offsetWidth > 0 && i.offsetHeight > 0);
                return {
                    count: inputs.length,
                    types: inputs.map(i => i.type || 'text'),
                    ids: inputs.map(i => i.id || i.name || '')
                };
            })()
            """
            det_res = page.evaluate(input_detect_script)
            if det_res and det_res.get("count") == 1:
                print(f"[AI 預登入] [DOM 探測] 發現當前頁面為「單一密碼欄位」登入頁！將指示 AI 直接填入密碼。")
                single_field_hint = f"\n\n**【系統 DOM 偵測提醒】**：當前頁面只有 1 個可見輸入框！這是一個單一欄位登入頁，請直接點擊該欄位並輸入密碼 '{password}' 進行登入，切勿輸入帳號名稱。"
        except Exception:
            pass

        screenshot_bytes = page.screenshot(type="png")
        from browser_actions import scan_focus_path, execute_function_calls
        from claude_client import get_function_responses
        
        focus_map = scan_focus_path(page)
        
        focus_map_text = ""
        if focus_map:
            table_lines = [
                "\n\n### 本地自動化焦點順序地圖 (Focus Map)",
                "| 順序 | 標籤 (Tag) | 識別碼 (ID) | 文字內容 |",
                "| :--- | :--- | :--- | :--- |"
            ]
            for item in focus_map[:20]:
                idx = item.get("idx", item.get("index", 1))
                tag = item.get("tag", item.get("tagName", "element"))
                table_lines.append(f"| {idx} | {tag} | `{item.get('id', '')}` | {item.get('text', '')} |")
            focus_map_text = "\n".join(table_lines)
            
        extra_instructions = f"\n\n{focus_map_text}{single_field_hint}\n\n請以最快、最有效率的步驟完成登入，一旦登入完成看到主頁/後台，請不要做任何其他操作，直接停止呼叫工具以結束任務。"
        
        interaction = agent.create_initial_interaction(login_prompt, screenshot_bytes, extra_instructions)
        
        init_tokens = get_interaction_tokens(interaction)
        login_input_tokens += init_tokens["input"]
        login_output_tokens += init_tokens["output"]
        login_cache_read_tokens += init_tokens.get("cache_read_input_tokens", 0)
        login_cache_creation_tokens += init_tokens.get("cache_creation_input_tokens", 0)
        login_total_tokens += init_tokens["total"]
        
        max_login_turns = MAX_LOGIN_TURNS
        for turn in range(max_login_turns):
            print(f"\n[AI 預登入 | 回合 {turn + 1}/{max_login_turns}]")
            
            text_response = agent.extract_text_response(interaction)
            if text_response.strip():
                print(f"[AI 預登入思考輸出]:\n{text_response}\n")
                
            if not agent.has_function_calls(interaction):
                print("[AI 預登入] [OK] AI 判定已進入目標頁面，結束預登入動作。")
                break
                
            results = execute_function_calls(interaction, page, viewport_width, viewport_height)
            function_responses = get_function_responses(page, results, interaction)
            
            interaction = agent.continue_interaction(interaction.id, function_responses)
            
            turn_tokens = get_interaction_tokens(interaction)
            login_input_tokens += turn_tokens["input"]
            login_output_tokens += turn_tokens["output"]
            login_cache_read_tokens += turn_tokens.get("cache_read_input_tokens", 0)
            login_cache_creation_tokens += turn_tokens.get("cache_creation_input_tokens", 0)
            login_total_tokens += turn_tokens["total"]
            
        print("[AI 預登入] 正在等待登入跳轉並驗證狀態...")
        try:
            page.wait_for_timeout(2000)
            page.wait_for_load_state("load", timeout=3000)
        except Exception:
            pass

        is_still_login_page = False
        try:
            pw_field = page.query_selector("input[type='password']")
            if pw_field and pw_field.is_visible():
                is_still_login_page = True
        except Exception:
            pass

        if is_still_login_page:
            print("[AI 預登入] [WARNING] 認證失敗：密碼輸入欄位依然存在！登入未能成功切換頁面。")
            return {
                "input": login_input_tokens,
                "output": login_output_tokens,
                "cache_read_input_tokens": login_cache_read_tokens,
                "cache_creation_input_tokens": login_cache_creation_tokens,
                "total": login_total_tokens,
                "success": False
            }
        else:
            print("[AI 預登入] [OK] 登入驗證成功！密碼欄位已消失，瀏覽器已成功切換至登入後頁面。")
            
        print(f"[AI 預登入] [OK] 預登入程序結束 (登入消耗 Tokens - 輸入: {login_input_tokens}, 輸出: {login_output_tokens})，回傳控制權給主流程。\n")
        return {
            "input": login_input_tokens,
            "output": login_output_tokens,
            "cache_read_input_tokens": login_cache_read_tokens,
            "cache_creation_input_tokens": login_cache_creation_tokens,
            "total": login_total_tokens,
            "success": True
        }
    except Exception as e:
        print(f"[AI 預登入] [WARNING] AI 預登入出錯: {e}")
        return {
            "input": 0,
            "output": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "total": 0,
            "success": False
        }
