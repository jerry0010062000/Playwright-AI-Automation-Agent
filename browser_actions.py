"""
瀏覽器操作模組
執行各種瀏覽器操作指令（點擊、輸入、導航等）
"""

import time
from typing import List, Tuple
from coordinate_utils import denormalize_x, denormalize_y
from config import ACTION_DELAY, PAGE_LOAD_TIMEOUT, INPUT_FOCUS_DELAY


def execute_function_calls(interaction, page, screen_width: int, screen_height: int) -> List[Tuple[str, str, dict]]:
    """
    執行 Gemini AI 回傳的函數呼叫（瀏覽器操作指令）
    
    Args:
        interaction: Gemini API 的互動回應物件
        page: Playwright 的頁面物件
        screen_width: 螢幕寬度
        screen_height: 螢幕高度
    
    Returns:
        操作結果列表，格式為 [(函數名稱, 呼叫ID, 結果字典), ...]
    """
    results = []
    
    # 從互動回應中過濾出所有的函數呼叫
    function_calls = [
        step for step in interaction.steps 
        if step.type == "function_call"
    ]

    # 逐一執行每個函數呼叫
    for function_call in function_calls:
        action_result = {}
        fname = function_call.name  # 函數名稱（如 click, type, navigate 等）
        args = function_call.arguments  # 函數參數
        
        print(f"  → 執行動作: {fname}")
        if "intent" in args:
            print(f"    意圖: {args['intent']}")

        try:
            # 根據函數名稱執行對應的操作
            if fname in ("open_web_browser", "open_app"):
                _handle_open_browser(page, args)
            
            elif fname in ("click", "click_at", "double_click", "triple_click", 
                          "middle_click", "right_click", "move", "long_press"):
                _handle_mouse_actions(page, fname, args, screen_width, screen_height)
            
            elif fname in ("type", "type_text_at"):
                _handle_keyboard_input(page, fname, args, screen_width, screen_height)
            
            elif fname in ("navigate", "go_back", "go_forward"):
                _handle_navigation(page, fname, args)
            
            elif fname == "wait":
                _handle_wait(args)
            
            elif fname == "scroll":
                _handle_scroll(page, args, screen_width, screen_height)
            
            elif fname == "computer":
                _handle_claude_computer_action(page, args, screen_width, screen_height)
            
            else:
                print(f"⚠️  警告: 未處理的函數 {fname}")

            # 等待頁面載入完成
            page.wait_for_load_state(timeout=PAGE_LOAD_TIMEOUT)
            time.sleep(ACTION_DELAY)

        except Exception as e:
            # 捕捉執行錯誤
            print(f"❌ 執行 {fname} 時發生錯誤: {e}")
            action_result = {"error": str(e)}

        # 記錄執行結果
        results.append((fname, function_call.id, action_result))

    return results


# ========================================
# 私有輔助函數：處理各類操作
# ========================================

def _handle_open_browser(page, args):
    """處理瀏覽器開啟操作（通常不需要額外處理）"""
    pass


def _handle_mouse_actions(page, fname: str, args: dict, screen_width: int, screen_height: int):
    """
    處理滑鼠相關操作
    
    支援的操作：
    - click, click_at: 單次點擊
    - double_click: 雙擊
    - right_click: 右鍵點擊
    - middle_click: 中鍵點擊
    - move: 移動滑鼠
    - long_press: 長按
    """
    # 將標準化座標轉換為實際像素座標
    actual_x = denormalize_x(args["x"], screen_width)
    actual_y = denormalize_y(args["y"], screen_height)

    if fname in ("click", "click_at"):
        page.mouse.click(actual_x, actual_y)
    
    elif fname == "double_click":
        page.mouse.dblclick(actual_x, actual_y)
    
    elif fname == "right_click":
        page.mouse.click(actual_x, actual_y, button="right")
    
    elif fname == "middle_click":
        page.mouse.click(actual_x, actual_y, button="middle")
    
    elif fname == "move":
        page.mouse.move(actual_x, actual_y)
    
    elif fname == "long_press":
        page.mouse.move(actual_x, actual_y)
        page.mouse.down()
        time.sleep(1)
        page.mouse.up()


def _handle_keyboard_input(page, fname: str, args: dict, screen_width: int, screen_height: int):
    """
    處理鍵盤輸入操作
    
    支援的操作：
    - type: 在當前焦點位置輸入
    - type_text_at: 在指定座標位置輸入
    """
    text = args["text"]
    press_enter = args.get("press_enter", False)
    
    # 如果有指定座標，先點擊該位置
    if "x" in args and "y" in args:
        actual_x = denormalize_x(args["x"], screen_width)
        actual_y = denormalize_y(args["y"], screen_height)
        page.mouse.click(actual_x, actual_y)
        time.sleep(INPUT_FOCUS_DELAY)  # 等待輸入框獲得焦點
    
    # 清空輸入框內容（選取全部 + 刪除）
    page.keyboard.press("Control+A")  # Windows 使用 Control，Mac 使用 Meta
    page.keyboard.press("Backspace")
    
    # 輸入文字
    page.keyboard.type(text)
    
    # 如果需要，按下 Enter 鍵
    if press_enter:
        page.keyboard.press("Enter")


def _handle_navigation(page, fname: str, args: dict):
    """
    處理頁面導航操作
    
    支援的操作：
    - navigate: 前往指定網址
    - go_back: 返回上一頁
    - go_forward: 前往下一頁
    """
    if fname == "navigate":
        url = args["url"]
        page.goto(url, wait_until="domcontentloaded")
    
    elif fname == "go_back":
        page.go_back()
    
    elif fname == "go_forward":
        page.go_forward()


def _handle_wait(args: dict):
    """
    處理等待操作
    """
    seconds = args.get("seconds", 1)
    time.sleep(seconds)


def _handle_scroll(page, args: dict, screen_width: int, screen_height: int):
    """
    處理滾動操作
    
    參數：
    - x, y: 滾動的參考座標（標準化座標，選填）
    - direction: 滾動方向（'up', 'down', 'left', 'right'，選填，預設為 'down'）
    - pixels: 滾動像素量（選填，預設為 500）
    """
    # 如果有指定座標，先移動滑鼠到該位置，以便在特定容器內滾動
    if "x" in args and "y" in args:
        actual_x = denormalize_x(args["x"], screen_width)
        actual_y = denormalize_y(args["y"], screen_height)
        page.mouse.move(actual_x, actual_y)
        
    direction = args.get("direction", "down").lower()
    pixels = args.get("pixels", 500)
    
    delta_x = 0
    delta_y = 0
    
    if direction == "down":
        delta_y = pixels
    elif direction == "up":
        delta_y = -pixels
    elif direction == "right":
        delta_x = pixels
    elif direction == "left":
        delta_x = -pixels
        
    page.mouse.wheel(delta_x, delta_y)


def _handle_claude_computer_action(page, args: dict, screen_width: int, screen_height: int):
    """
    處理 Claude Anthropic 的 Computer Use 動作
    動作類型支援：left_click, double_click, right_click, middle_click, mouse_hover, type, key, left_click_drag, screenshot
    註：Claude 座標基於 1024x768 進行定位
    """
    action = args.get("action")
    coord = args.get("coordinate")
    actual_x = 0
    actual_y = 0
    if coord:
        # 將 1024x768 的座標比例縮放到實際螢幕尺寸
        actual_x = int(coord[0] * screen_width / 1024)
        actual_y = int(coord[1] * screen_height / 768)
        
    if action == "left_click":
        page.mouse.click(actual_x, actual_y)
    elif action == "double_click":
        page.mouse.dblclick(actual_x, actual_y)
    elif action == "right_click":
        page.mouse.click(actual_x, actual_y, button="right")
    elif action == "middle_click":
        page.mouse.click(actual_x, actual_y, button="middle")
    elif action == "mouse_hover":
        page.mouse.move(actual_x, actual_y)
    elif action == "type":
        text = args.get("text", "")
        page.keyboard.type(text)
    elif action == "key":
        raw_key = args.get("text", "") or args.get("key", "")
        if raw_key:
            # 支援以空格分隔的多個按鍵（例如 "Tab Tab Tab"），讓 AI 可以一回合按多次鍵
            keys_to_press = [k.strip() for k in raw_key.split(" ") if k.strip()]
            for k in keys_to_press:
                # 支援組合鍵轉換，將 Anthropic 格式（如 ctrl+s, alt+tab）翻譯為 Playwright 格式
                parts = k.split("+")
                translated_parts = []
                for part in parts:
                    p = part.strip().lower()
                    if p == "ctrl":
                        translated_parts.append("Control")
                    elif p == "alt":
                        translated_parts.append("Alt")
                    elif p == "shift":
                        translated_parts.append("Shift")
                    elif p in ("meta", "win", "command", "cmd"):
                        translated_parts.append("Meta")
                    elif p in ("return", "enter"):
                        translated_parts.append("Enter")
                    else:
                        if len(p) > 1:
                            # 針對 Playwright 的特定按鍵進行首字母大寫轉換（如 ArrowRight）
                            translated_parts.append(part.strip().capitalize())
                        else:
                            translated_parts.append(part.strip())
                
                final_key = "+".join(translated_parts)
                page.keyboard.press(final_key)
    elif action == "left_click_drag":
        page.mouse.down()
        page.mouse.move(actual_x, actual_y)
        page.mouse.up()
    elif action == "screenshot":
        pass


def run_axe_audit(page) -> dict:
    """
    載入並執行本地 Axe-core 審查，獲取 WCAG 違規資料
    """
    import os
    axe_path = os.path.join(os.path.dirname(__file__), "lib", "axe.min.js")
    if not os.path.exists(axe_path):
        axe_path = os.path.join("lib", "axe.min.js")
        
    if not os.path.exists(axe_path):
        raise FileNotFoundError(f"本地 Axe-core 庫未找到: {axe_path}")
        
    # 注入 Axe-core
    page.add_script_tag(path=axe_path)
    
    # 執行 axe.run()
    try:
        result = page.evaluate("async () => { return await axe.run(); }")
        return result
    except Exception as e:
        print(f"[ERROR] Axe-core evaluation failed: {e}")
        return {"violations": []}


def scan_focus_path(page) -> list:
    """
    透過 JavaScript 遍歷頁面上所有可聚焦的元素，收集焦點地圖與樣式
    """
    js_code = """
    () => {
        const focusableSelector = 'a, button, input, select, textarea, [tabindex], [contenteditable]';
        const allElements = Array.from(document.querySelectorAll(focusableSelector));
        
        const visibleElements = allElements.filter(el => {
            if (el.tabIndex < 0) return false;
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return false;
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            return true;
        });

        const focusMap = [];
        const activeElBefore = document.activeElement;

        for (let i = 0; i < visibleElements.length; i++) {
            const el = visibleElements[i];
            try {
                el.focus();
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                
                const outlineStyle = style.outlineStyle;
                const outlineWidth = style.outlineWidth;
                const outlineColor = style.outlineColor;
                const hasOutline = outlineStyle !== 'none' && parseFloat(outlineWidth) > 0;
                
                focusMap.push({
                    index: i + 1,
                    tagName: el.tagName,
                    id: el.id || '',
                    className: el.className || '',
                    text: (el.innerText || el.value || '').trim().substring(0, 40),
                    x: Math.round(rect.left + rect.width / 2),
                    y: Math.round(rect.top + rect.height / 2),
                    outline: `${outlineStyle} ${outlineWidth} ${outlineColor}`,
                    hasOutline: hasOutline
                });
            } catch (e) {
                // Ignore element focus error
            }
        }

        if (activeElBefore && typeof activeElBefore.focus === 'function') {
            activeElBefore.focus();
        }

        return focusMap;
    }
    """
    try:
        return page.evaluate(js_code)
    except Exception as e:
        print(f"[WARNING] scan_focus_path failed: {e}")
        return []

