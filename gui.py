import sys
import os
import subprocess
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
import glob

# ==========================================
# 視覺主題與配色風格
# ==========================================
BG_COLOR = "#1e1e1e"        # VS Code 經典深灰背景
PANEL_BG = "#252526"        # 面板卡片背景色
BORDER_COLOR = "#3e3e42"    # 邊框灰色
TEXT_COLOR = "#d4d4d4"      # 文字淺灰
HEADING_COLOR = "#ffffff"   # 標題純白
ACCENT_COLOR = "#007acc"    # 亮藍色（按鈕、高亮區）
ACCENT_HOVER = "#1c97ea"    # 亮藍色懸停
BTN_BG = "#2d2d30"          # 次要按鈕背景
BTN_HOVER = "#3e3e42"       # 次要按鈕懸停
TERM_BG = "#0c0c0c"         # 終端機純黑背景
TERM_FG = "#cccccc"         # 終端機預設文字灰色

class LoadingSpinner(tk.Canvas):
    """自訂畫布圓形加載旋轉動畫，不需外部 GIF/圖片資源，解析度無損"""
    def __init__(self, parent, size=32, color=ACCENT_COLOR, bg=PANEL_BG, **kwargs):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0, **kwargs)
        self.size = size
        self.color = color
        self.angle = 0
        self.running = False
        
    def start(self):
        if not self.running:
            self.running = True
            self.animate()
            
    def stop(self):
        self.running = False
        self.delete("all")
        
    def animate(self):
        if not self.running:
            return
        self.delete("all")
        # 動態取得畫布在 High-DPI 縮放下的實際寬高，防止動畫被壓縮至角落
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1 or h <= 1:
            w = self.size
            h = self.size
            
        padding = 4
        bbox = (padding, padding, w - padding, h - padding)
        # 繪製旋轉的圓弧 (120度)
        self.create_arc(bbox, start=self.angle, extent=120, outline=self.color, width=3, style=tk.ARC)
        self.angle = (self.angle + 12) % 360
        self.after(30, self.animate)  # 約 33 FPS，旋轉流暢度極佳


class WCAGAgentGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🛡️ Playwright WCAG Accessibility Agent Controller")
        self.root.geometry("1100x720")
        self.root.configure(bg=BG_COLOR)
        
        # 子進程管理與隊列
        self.process = None
        self.log_queue = queue.Queue()
        self.is_running = False
        
        # AI 思考與操作狀態的動態提示文字
        self.loader_texts = [
            "AI 正在啟動安全沙盒瀏覽器",
            "AI 正在加載目標網頁並執行預檢",
            "AI 正在對照無障礙 Success Criteria 指南",
            "AI 正在分析 DOM Tree 結構節點",
            "AI 正在檢查鍵盤焦點與 Focus-Path",
            "AI 正在執行本地 Axe-core 審查引擎",
            "AI 正在規劃下一個最佳瀏覽操作",
            "AI 正在為您撰寫無障礙評估建議",
        ]
        self.loader_text_index = 0
        self.dot_count = 0
        
        self.setup_styles()
        self.create_widgets()
        
        # 啟動 Tkinter 定時排程檢查 Log 隊列
        self.root.after(100, self.poll_log_queue)

    def setup_styles(self):
        """設定元件外觀樣式"""
        style = ttk.Style()
        style.theme_use("clam")
        
        # 定義 Combobox, Entry, Checkbutton 等外觀
        style.configure("TFrame", background=BG_COLOR)
        style.configure("Card.TFrame", background=PANEL_BG, borderwidth=1, relief="solid")
        
        style.configure("TLabel", background=PANEL_BG, foreground=TEXT_COLOR, font=("Segoe UI", 10))
        style.configure("Heading.TLabel", background=PANEL_BG, foreground=HEADING_COLOR, font=("Segoe UI", 13, "bold"))
        style.configure("Title.TLabel", background=BG_COLOR, foreground=HEADING_COLOR, font=("Segoe UI", 18, "bold"))
        
        # Combobox 樣式設定：增強內距(padding)，使其高大且具現代感
        style.configure("TCombobox", fieldbackground=BG_COLOR, background=BTN_BG, foreground=TEXT_COLOR, 
                        arrowcolor=TEXT_COLOR, padding=5, arrowsize=13)
        style.map("TCombobox", 
                  fieldbackground=[("readonly", BG_COLOR)],
                  foreground=[("readonly", TEXT_COLOR)])
        
        # Checkbutton 樣式
        style.configure("TCheckbutton", background=PANEL_BG, foreground=TEXT_COLOR, font=("Segoe UI", 10))
        style.map("TCheckbutton",
                  background=[("active", PANEL_BG)],
                  foreground=[("active", TEXT_COLOR)])

    def create_widgets(self):
        """建立 GUI 面板配置"""
        # 頂部標題區
        header_frame = tk.Frame(self.root, bg=BG_COLOR, height=50)
        header_frame.pack(fill=tk.X, padx=20, pady=10)
        
        title_label = ttk.Label(header_frame, text="🛡️ Playwright WCAG Accessibility Agent", style="Title.TLabel")
        title_label.pack(side=tk.LEFT)
        
        subtitle_label = tk.Label(header_frame, text="本地無障礙全站巡檢 & AI 互動檢測控制台", bg=BG_COLOR, fg="#858585", font=("Segoe UI", 10))
        subtitle_label.pack(side=tk.LEFT, padx=15, pady=5)
        
        # 本地配置設定按鈕 (敏感憑證)
        config_btn = tk.Button(header_frame, text="⚙️ 本地配置設定 (Local Config)", bg=BTN_BG, fg=TEXT_COLOR, 
                               activebackground=BTN_HOVER, activeforeground=TEXT_COLOR, 
                               font=("Segoe UI", 10, "bold"), relief="flat", bd=0, command=self.open_local_config_window)
        config_btn.pack(side=tk.RIGHT, padx=5, ipady=4, ipadx=10)

        # 進階參數設定按鈕 (行為參數)
        adv_config_btn = tk.Button(header_frame, text="🔧 進階參數設定 (Advanced Config)", bg=BTN_BG, fg=TEXT_COLOR, 
                                   activebackground=BTN_HOVER, activeforeground=TEXT_COLOR, 
                                   font=("Segoe UI", 10, "bold"), relief="flat", bd=0, command=self.open_advanced_config_window)
        adv_config_btn.pack(side=tk.RIGHT, padx=5, ipady=4, ipadx=10)

        # 主要網格配置（左邊設定區，右邊終端區）
        main_container = tk.Frame(self.root, bg=BG_COLOR)
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)
        
        main_container.columnconfigure(0, weight=4)  # 左側寬度比重
        main_container.columnconfigure(1, weight=6)  # 右側寬度比重
        main_container.rowconfigure(0, weight=1)

        # ----------------------------------------------------
        # 左側面板：參數設定區域 (加入捲軸以支援小螢幕與擴充性)
        # ----------------------------------------------------
        left_panel = tk.Frame(main_container, bg=PANEL_BG, highlightbackground=BORDER_COLOR, highlightthickness=1)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=10)
        
        # 建立畫布與捲軸
        canvas = tk.Canvas(left_panel, bg=PANEL_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(left_panel, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 內邊距容器 (作為 Canvas 的子視窗，設定 (15, 15) 作為邊距防重疊)
        left_content = tk.Frame(canvas, bg=PANEL_BG)
        canvas_window = canvas.create_window((15, 15), window=left_content, anchor="nw")
        
        # 更新畫布滾動範圍 (增加一些底部邊距以防被底部截斷)
        left_content.bind("<Configure>", lambda e: canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), left_content.winfo_height() + 30)))
        # 自動適應畫布寬度，並扣除左右間距與捲軸寬度以防元件重疊
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=max(10, e.width - 30)))
        
        # 綁定滑鼠滾輪，僅在滑鼠移入左側區域時生效，不干擾右側日誌捲軸
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        def _bind_mousewheel(event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _unbind_mousewheel(event):
            canvas.unbind_all("<MouseWheel>")
            
        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)
        
        tk.Label(left_content, text="⚙️ 檢測設定面板", bg=PANEL_BG, fg=HEADING_COLOR, font=("Segoe UI", 13, "bold")).pack(anchor=tk.W, pady=(0, 15))

        # 1. 任務指令輸入
        tk.Label(left_content, text="任務指令 (Task Instruction):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(5, 3))
        self.task_entry = tk.Text(left_content, height=4, width=30, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, 
                                  highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR, 
                                  font=("Segoe UI", 10), bd=0)
        self.task_entry.pack(fill=tk.X, pady=(0, 12))
        self.task_entry.insert(tk.END, "我要求你對網頁進行wcag檢查")

        # 2. 初始 URL
        tk.Label(left_content, text="檢測目標網址 (Initial URL):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(5, 3))
        self.url_entry = tk.Entry(left_content, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, 
                                  highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR, 
                                  font=("Segoe UI", 10), bd=0)
        self.url_entry.pack(fill=tk.X, pady=(0, 12), ipady=3)
        self.url_entry.insert(0, "http://localhost:8000")

        # 3. WCAG 指南章節選擇
        tk.Label(left_content, text="WCAG 2.2 檢測章節 (Guideline):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(5, 3))
        wcag_options = [
            "None (一般網頁自動化任務)",
            "1.1 (靜態 - 替代文字 alternatives)",
            "1.2 (靜態 - 時基媒體 audio/video pre-check)",
            "1.3 (靜態 - 易讀與結構 adaptability)",
            "1.4 (靜態 - 可辨識/對比度 distinguishable)",
            "2.1 (動態 - 鍵盤鍵路徑 focus scan)",
            "2.2 (動態 - 足夠時間 timeouts checking)",
            "2.3 (動態 - 預防閃爍 seizures checking)",
            "2.4 (動態 - 導覽尋找 page layout check)",
            "2.5 (動態 - 輸入裝置 input modalities)",
            "3.1 (靜態 - 可讀性 language audit)",
            "3.2 (靜態 - 可預測性 predictability)",
            "3.3 (靜態 - 輸入協助 form errors)",
            "4.1 (靜態 - 相容性 compatibility check)",
            "🗺️ 繪製全站地圖 (AI Map)"
        ]
        self.wcag_combo = ttk.Combobox(left_content, values=wcag_options, state="readonly", style="TCombobox")
        self.wcag_combo.pack(fill=tk.X, pady=(0, 12))
        self.wcag_combo.current(0)  # 預設選 None

        # 3.5. 選擇網站地圖 (Sitemap)
        tk.Label(left_content, text="採用網站地圖 (Sitemap):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(5, 3))
        self.sitemap_combo = ttk.Combobox(left_content, state="readonly", style="TCombobox")
        self.sitemap_combo.pack(fill=tk.X, pady=(0, 12))
        self.refresh_sitemaps_list()

        # 4. AI 模型選擇 (不同公司用不可選標籤隔開)
        tk.Label(left_content, text="計費與決策 AI 模型 (Model):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(5, 3))
        model_options = [
            "--- Anthropic (Claude) ---",
            "claude-sonnet-4-5 (預設)",
            "claude-opus-4-8",
            "claude-haiku-4-5",
            "--- Google (Gemini) ---",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite"
        ]
        self.model_combo = ttk.Combobox(left_content, values=model_options, state="readonly", style="TCombobox")
        self.model_combo.pack(fill=tk.X, pady=(0, 5))
        self.model_combo.current(1)  # 預設指向 claude-sonnet-4-5 (預設)
        self.last_valid_model_index = 1
        
        # 監聽選擇，如果是分隔欄位則自動恢復上次選擇
        self.model_combo.bind("<<ComboboxSelected>>", self.on_model_selected)
        
        # 自定義模型切換 Checkbox (預設不選取以保持摺疊)
        self.use_custom_model_var = tk.BooleanVar(value=False)
        self.custom_model_cb = tk.Checkbutton(left_content, text="➕ 使用自定義模型名稱 (進階)", 
                                              variable=self.use_custom_model_var, command=self.toggle_custom_model,
                                              bg=PANEL_BG, fg="#858585", selectcolor=BG_COLOR,
                                              activebackground=PANEL_BG, activeforeground="#858585",
                                              font=("Segoe UI", 9, "italic"), highlightthickness=0, bd=0)
        self.custom_model_cb.pack(anchor=tk.W, pady=(0, 10))
        
        # 自定義模型輸入框容器 (預設不 pack，即摺疊)
        self.custom_model_frame = tk.Frame(left_content, bg=PANEL_BG)
        
        tk.Label(self.custom_model_frame, text="自定義模型名稱 (Custom Model):", bg=PANEL_BG, fg=TEXT_COLOR, 
                 font=("Segoe UI", 10, "italic")).pack(anchor=tk.W, pady=(0, 3))
        
        self.custom_model_entry = tk.Entry(self.custom_model_frame, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, 
                                           highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                                           font=("Segoe UI", 10), bd=0)
        self.custom_model_entry.pack(fill=tk.X, ipady=3, pady=(0, 10))
        self.custom_model_entry.insert(0, "claude-3-5-sonnet-20241022")

        # 5. 模擬裝置型態
        tk.Label(left_content, text="瀏覽器視窗模擬 (Device Viewport):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(5, 3))
        device_options = ["desktop", "mobile", "tablet"]
        self.device_combo = ttk.Combobox(left_content, values=device_options, state="readonly", style="TCombobox")
        self.device_combo.pack(fill=tk.X, pady=(0, 12))
        self.device_combo.current(0)

        # 6. 最大回合數與數值控制
        row_settings = tk.Frame(left_content, bg=PANEL_BG)
        row_settings.pack(fill=tk.X, pady=(5, 12))
        
        tk.Label(row_settings, text="最大回合 (Max Turns):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.turns_spin = tk.Spinbox(row_settings, from_=5, to=100, width=5, bg=BG_COLOR, fg=TEXT_COLOR, 
                                     buttonbackground=BTN_BG, insertbackground=TEXT_COLOR, font=("Segoe UI", 10),
                                     highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR, bd=0)
        self.turns_spin.pack(side=tk.LEFT, padx=10, ipady=1)
        self.turns_spin.delete(0, "end")
        self.turns_spin.insert(0, "30")

        # 7. Checkboxes: 無頭模式 與 紀錄運行
        self.headless_var = tk.BooleanVar(value=False)  # 預設顯示瀏覽器，方便使用者看畫面
        self.record_var = tk.BooleanVar(value=True)    # 預設儲存記錄與產生報告
        
        cb_frame = tk.Frame(left_content, bg=PANEL_BG)
        cb_frame.pack(fill=tk.X, pady=10)
        
        tk.Checkbutton(cb_frame, text="無頭模式 (Headless)", variable=self.headless_var,
                       bg=PANEL_BG, fg=TEXT_COLOR, selectcolor=BG_COLOR,
                       activebackground=PANEL_BG, activeforeground=TEXT_COLOR,
                       font=("Segoe UI", 10), highlightthickness=0, bd=0).pack(anchor=tk.W, pady=3)
        tk.Checkbutton(cb_frame, text="啟用報告與日誌記錄 (Record)", variable=self.record_var,
                       bg=PANEL_BG, fg=TEXT_COLOR, selectcolor=BG_COLOR,
                       activebackground=PANEL_BG, activeforeground=TEXT_COLOR,
                       font=("Segoe UI", 10), highlightthickness=0, bd=0).pack(anchor=tk.W, pady=3)

        # 隔離線
        separator = tk.Frame(left_content, bg=BORDER_COLOR, height=1)
        separator.pack(fill=tk.X, pady=15)

        # 控制按鈕區 (排版在最下方)
        self.start_btn = tk.Button(left_content, text="🚀 啟動檢測任務", bg=ACCENT_COLOR, fg=HEADING_COLOR, 
                                   activebackground=ACCENT_HOVER, activeforeground=HEADING_COLOR, 
                                   font=("Segoe UI", 11, "bold"), relief="flat", bd=0, command=self.start_audit)
        self.start_btn.pack(fill=tk.X, pady=5, ipady=5)
        
        self.stop_btn = tk.Button(left_content, text="🛑 停止目前任務", bg=BTN_BG, fg=TEXT_COLOR, 
                                  activebackground=BTN_HOVER, activeforeground=TEXT_COLOR, 
                                  font=("Segoe UI", 11), relief="flat", bd=0, command=self.stop_audit, state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X, pady=5, ipady=5)

        # 8. 動態加載動畫與狀態提示區 (AI 思考中動畫) - 始終固定於介面最底端，避免抖動
        self.loader_frame = tk.Frame(left_content, bg=PANEL_BG)
        self.loader_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.spinner = LoadingSpinner(self.loader_frame, size=28, color=ACCENT_COLOR, bg=PANEL_BG)
        self.spinner.pack(side=tk.LEFT, padx=(10, 10), pady=12)
        
        self.loader_label = tk.Label(self.loader_frame, text="🤖 系統就緒，等待任務...", bg=PANEL_BG, fg="#858585", 
                                     font=("Segoe UI", 10, "italic"), width=35, anchor=tk.W)
        self.loader_label.pack(side=tk.LEFT, pady=12)

        # ----------------------------------------------------
        # 右側面板：實時終端輸出與報表連結
        # ----------------------------------------------------
        right_panel = tk.Frame(main_container, bg=PANEL_BG, highlightbackground=BORDER_COLOR, highlightthickness=1)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)
        
        right_content = tk.Frame(right_panel, bg=PANEL_BG)
        right_content.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # 終端頂部工具列
        term_header = tk.Frame(right_content, bg=PANEL_BG)
        term_header.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(term_header, text="💻 實時執行輸出 (Real-time CMD Terminal)", style="Heading.TLabel").pack(side=tk.LEFT)
        
        # 快速操作按鈕
        self.report_btn = tk.Button(term_header, text="📁 打開紀錄目錄資料夾", bg=BTN_BG, fg=TEXT_COLOR, 
                                    activebackground=BTN_HOVER, activeforeground=TEXT_COLOR, 
                                    font=("Segoe UI", 9), relief="flat", bd=0, command=self.open_records_directory)
        self.report_btn.pack(side=tk.RIGHT, padx=5, ipady=3)
        
        self.clear_btn = tk.Button(term_header, text="🧹 清除視窗", bg=BTN_BG, fg=TEXT_COLOR, 
                                   activebackground=BTN_HOVER, activeforeground=TEXT_COLOR, 
                                   font=("Segoe UI", 9), relief="flat", bd=0, command=self.clear_terminal)
        self.clear_btn.pack(side=tk.RIGHT, padx=5, ipady=3)

        # 終端機日誌顯示元件 (Scrollable Text)
        term_container = tk.Frame(right_content, bg=TERM_BG)
        term_container.pack(fill=tk.BOTH, expand=True)
        
        self.terminal_text = tk.Text(term_container, bg=TERM_BG, fg=TERM_FG, insertbackground=TERM_FG, 
                                     font=("Consolas", 11), wrap=tk.WORD, bd=0, highlightthickness=0)
        self.terminal_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(term_container, orient=tk.VERTICAL, command=self.terminal_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.terminal_text.config(yscrollcommand=scrollbar.set)
        
        # 配置字體色彩樣式 Tags
        self.terminal_text.tag_config("error", foreground="#f44336")      # 紅色
        self.terminal_text.tag_config("warning", foreground="#ce9178")    # 橘色/黃色
        self.terminal_text.tag_config("success", foreground="#4ec9b0")    # 翠綠色
        self.terminal_text.tag_config("highlight", foreground="#9cdcfe")  # 淺藍/青色
        self.terminal_text.tag_config("ai", foreground="#ebadff")         # 亮粉紫色 (高對比度)
        
        # 鍵盤與滑鼠複製選取綁定 (實作唯讀選取與複製)
        self.terminal_text.bind("<Key>", self.block_keyboard_input)
        self.terminal_text.bind("<Control-c>", lambda e: self.copy_selection() or "break")
        self.terminal_text.bind("<Control-a>", lambda e: self.select_all_text() or "break")
        
        # 右鍵快顯選單
        self.context_menu = tk.Menu(self.root, tearoff=0, bg=PANEL_BG, fg=TEXT_COLOR, 
                                    activebackground=ACCENT_COLOR, activeforeground=HEADING_COLOR, bd=1, relief="solid")
        self.context_menu.add_command(label="複製 (Copy)", command=self.copy_selection)
        self.context_menu.add_command(label="全選 (Select All)", command=self.select_all_text)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="清除視窗 (Clear Log)", command=self.clear_terminal)
        
        self.terminal_text.bind("<Button-3>", self.show_context_menu)
        
        # 初始化終端狀態
        self.append_log("[GUI] 歡迎使用 Playwright WCAG Accessibility Agent 設定主控台！\n[GUI] 請於左側調整參數後點選「啟動檢測任務」開始檢測。\n\n")

    def open_local_config_window(self):
        """開啟獨立的本地配置編輯視窗 (Modal Toplevel Window)"""
        config_win = tk.Toplevel(self.root)
        config_win.title("⚙️ 本地配置設定 (config_local.py)")
        config_win.geometry("540x520")
        config_win.configure(bg=PANEL_BG)
        config_win.transient(self.root)  # 設為父視窗的子視窗
        config_win.grab_set()           # 阻斷父視窗互動
        
        # 居中定位於父視窗上方
        parent_x = self.root.winfo_x()
        parent_y = self.root.winfo_y()
        config_win.geometry(f"+{parent_x + 280}+{parent_y + 110}")
        
        # 頂部文字標題
        tk.Label(config_win, text="⚙️ 編輯本地私密配置 (Local Config)", bg=PANEL_BG, fg=HEADING_COLOR, 
                 font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, padx=25, pady=(20, 5))
        tk.Label(config_win, text="以下設定將儲存至 config_local.py。此檔案已列入 .gitignore，不會上傳公開庫。", 
                 bg=PANEL_BG, fg="#858585", font=("Segoe UI", 9)).pack(anchor=tk.W, padx=25, pady=(0, 15))
        
        # 欄位內容容器
        form_frame = tk.Frame(config_win, bg=PANEL_BG)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=25)
        
        # 動態載入 config 模組屬性值
        import config
        curr_gemini = getattr(config, "GEMINI_API_KEY", "")
        curr_claude = getattr(config, "CLAUDE_API_KEY", "")
        curr_url = getattr(config, "CLAUDE_BASE_URL", "")
        curr_token = getattr(config, "CLAUDE_AUTH_TOKEN", "")
        curr_enable_betas = "0" if getattr(config, "CLAUDE_DISABLE_EXPERIMENTAL_BETAS", "0") == "1" else "1"
        curr_use_gateway = "1" if getattr(config, "CLAUDE_USE_GATEWAY", False) else "0"
        curr_login_user = getattr(config, "AUTO_LOGIN_USERNAME", "")
        curr_login_pass = getattr(config, "AUTO_LOGIN_PASSWORD", "")
        
        def toggle_visibility(entry, btn):
            if entry.cget("show") == "*":
                entry.config(show="")
                btn.config(text="🙈")
            else:
                entry.config(show="*")
                btn.config(text="👁")

        fields = {}
        
        def add_field(label_text, var_name, default_val, is_checkbox=False, is_password=False):
            row = tk.Frame(form_frame, bg=PANEL_BG)
            row.pack(fill=tk.X, pady=6)
            
            lbl = tk.Label(row, text=label_text, bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10), width=25, anchor=tk.W)
            lbl.pack(side=tk.LEFT)
            
            if is_checkbox:
                var = tk.StringVar(value=default_val)
                cb = tk.Checkbutton(row, variable=var, onvalue="1", offvalue="0",
                                    bg=PANEL_BG, fg=TEXT_COLOR, selectcolor=BG_COLOR,
                                    activebackground=PANEL_BG, activeforeground=TEXT_COLOR,
                                    font=("Segoe UI", 10), highlightthickness=0, bd=0)
                cb.pack(side=tk.LEFT)
                fields[var_name] = var
            else:
                eye_btn = None
                if is_password:
                    eye_btn = tk.Button(row, text="👁", bg=BTN_BG, fg=TEXT_COLOR, 
                                        activebackground=BTN_HOVER, activeforeground=TEXT_COLOR,
                                        font=("Segoe UI", 9), relief="flat", bd=0, width=3)
                    eye_btn.pack(side=tk.RIGHT, padx=(5, 0), ipady=1)
                    
                entry = tk.Entry(row, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, 
                                 highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                                 font=("Segoe UI", 10), bd=0)
                entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
                entry.insert(0, default_val)
                fields[var_name] = entry
                
                if is_password and eye_btn:
                    entry.config(show="*")
                    eye_btn.config(command=lambda e=entry, b=eye_btn: toggle_visibility(e, b))
                
        add_field("Gemini API Key:", "GEMINI_API_KEY", curr_gemini, is_password=True)
        add_field("Claude API Key:", "CLAUDE_API_KEY", curr_claude, is_password=True)
        add_field("啟用 Claude 代理閘道 (Proxy):", "CLAUDE_USE_GATEWAY", curr_use_gateway, is_checkbox=True)
        add_field("Claude Base URL (Proxy):", "CLAUDE_BASE_URL", curr_url)
        add_field("Claude Auth Token:", "CLAUDE_AUTH_TOKEN", curr_token, is_password=True)
        add_field("啟用 Claude 實驗性功能 (Beta):", "CLAUDE_ENABLE_EXPERIMENTAL_BETAS", curr_enable_betas, is_checkbox=True)
        add_field("自動登入帳號 (Username):", "AUTO_LOGIN_USERNAME", curr_login_user)
        add_field("自動登入密碼 (Password):", "AUTO_LOGIN_PASSWORD", curr_login_pass, is_password=True)
        
        # 下方控制按鈕區
        btn_frame = tk.Frame(config_win, bg=PANEL_BG)
        btn_frame.pack(fill=tk.X, pady=(15, 20), padx=25)
        
        def save_config():
            gemini_key = fields["GEMINI_API_KEY"].get().strip()
            claude_key = fields["CLAUDE_API_KEY"].get().strip()
            claude_url = fields["CLAUDE_BASE_URL"].get().strip()
            claude_token = fields["CLAUDE_AUTH_TOKEN"].get().strip()
            claude_enable = fields["CLAUDE_ENABLE_EXPERIMENTAL_BETAS"].get().strip()
            claude_use_gateway = fields["CLAUDE_USE_GATEWAY"].get().strip()
            login_user = fields["AUTO_LOGIN_USERNAME"].get().strip()
            login_pass = fields["AUTO_LOGIN_PASSWORD"].get().strip()
            
            # 將正向的「啟用啟用」值轉譯為後台的否定型「禁止禁止」值
            claude_disable = "0" if claude_enable == "1" else "1"
            
            try:
                # 寫入 config_local.py 存檔
                with open("config_local.py", "w", encoding="utf-8") as f:
                    f.write(f'GEMINI_API_KEY = "{gemini_key}"\n')
                    f.write(f'CLAUDE_API_KEY = "{claude_key}"\n')
                    f.write(f'CLAUDE_USE_GATEWAY = {claude_use_gateway == "1"}\n')
                    f.write(f'CLAUDE_BASE_URL = "{claude_url}"\n')
                    f.write(f'CLAUDE_AUTH_TOKEN = "{claude_token}"\n')
                    f.write(f'CLAUDE_DISABLE_EXPERIMENTAL_BETAS = "{claude_disable}"\n')
                    f.write(f'AUTO_LOGIN_USERNAME = "{login_user}"\n')
                    f.write(f'AUTO_LOGIN_PASSWORD = "{login_pass}"\n')
                
                # 重新載入 config 與 AI 代理模組，確保本次運作中立即生效
                import importlib
                import config
                import claude_client
                import gemini_client
                
                importlib.reload(config)
                importlib.reload(claude_client)
                importlib.reload(gemini_client)
                
                messagebox.showinfo("成功", "配置已寫入 config_local.py，並且已在當前運行環境中即時生效！", parent=config_win)
                config_win.destroy()
            except Exception as e:
                messagebox.showerror("錯誤", f"儲存配置文件失敗: {e}", parent=config_win)
                
        save_btn = tk.Button(btn_frame, text="💾 儲存並套用", bg=ACCENT_COLOR, fg=HEADING_COLOR, 
                            activebackground=ACCENT_HOVER, activeforeground=HEADING_COLOR, 
                            font=("Segoe UI", 10, "bold"), relief="flat", bd=0, command=save_config)
        save_btn.pack(side=tk.RIGHT, padx=5, ipady=4, ipadx=15)
        
        cancel_btn = tk.Button(btn_frame, text="❌ 取消", bg=BTN_BG, fg=TEXT_COLOR, 
                              activebackground=BTN_HOVER, activeforeground=TEXT_COLOR, 
                              font=("Segoe UI", 10), relief="flat", bd=0, command=config_win.destroy)
        cancel_btn.pack(side=tk.RIGHT, padx=5, ipady=4, ipadx=15)

    def on_model_selected(self, event):
        """防止使用者點選到分隔用的虛擬不可互動項目"""
        selected = self.model_combo.get()
        if selected.startswith("---"):
            # 自動還原為上一次的合法選擇
            self.model_combo.current(self.last_valid_model_index)
        else:
            # 記錄當前合法的選擇索引
            self.last_valid_model_index = self.model_combo.current()

    def toggle_custom_model(self):
        """展開或摺疊自定義模型輸入欄位"""
        if self.use_custom_model_var.get():
            # 展開自定義模型輸入框，並將標準下拉選單設為唯讀禁用，避免打架
            self.custom_model_frame.pack(fill=tk.X)
            self.model_combo.config(state="disabled")
            self.custom_model_cb.config(text="➖ 隱藏自定義模型名稱")
        else:
            # 摺疊收回自定義模型輸入框，還原標準下拉選單為啟用狀態
            self.custom_model_frame.pack_forget()
            self.model_combo.config(state="readonly")
            self.custom_model_cb.config(text="➕ 使用自定義模型名稱 (進階)")

    def open_advanced_config_window(self):
        """開啟獨立的進階參數編輯視窗 (Modal Toplevel Window)"""
        adv_win = tk.Toplevel(self.root)
        adv_win.title("🔧 進階參數設定 (config_advanced.json)")
        adv_win.geometry("560x540")
        adv_win.configure(bg=PANEL_BG)
        adv_win.transient(self.root)
        adv_win.grab_set()
        
        parent_x = self.root.winfo_x()
        parent_y = self.root.winfo_y()
        adv_win.geometry(f"+{parent_x + 280}+{parent_y + 110}")
        
        # 頂部文字標題
        tk.Label(adv_win, text="🔧 編輯進階行為參數 (Advanced Config)", bg=PANEL_BG, fg=HEADING_COLOR, 
                 font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, padx=25, pady=(20, 5))
        tk.Label(adv_win, text="以下設定將儲存至 config_advanced.json。此檔案包含非敏感的爬蟲與延時參數。", 
                 bg=PANEL_BG, fg="#858585", font=("Segoe UI", 9)).pack(anchor=tk.W, padx=25, pady=(0, 15))
        
        form_frame = tk.Frame(adv_win, bg=PANEL_BG)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=25)
        
        # 載入目前的進階值
        import os
        import json
        import config
        adv_path = "config_advanced.json"
        
        max_crawl = getattr(config, "MAX_CRAWL_PAGES", 100)
        max_login_turns = getattr(config, "MAX_LOGIN_TURNS", 5)
        obs_time = getattr(config, "RESULT_OBSERVATION_TIME", 1)
        action_delay = getattr(config, "ACTION_DELAY", 0.5)
        page_timeout = getattr(config, "PAGE_LOAD_TIMEOUT", 5000)
        
        fields = {}
        def add_field(label_text, var_name, default_val, desc_text=""):
            row = tk.Frame(form_frame, bg=PANEL_BG)
            row.pack(fill=tk.X, pady=(4, 1))
            
            lbl = tk.Label(row, text=label_text, bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10), width=30, anchor=tk.W)
            lbl.pack(side=tk.LEFT)
            
            entry = tk.Entry(row, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, 
                             highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                             font=("Segoe UI", 10), bd=0)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
            entry.insert(0, str(default_val))
            fields[var_name] = entry
            
            if desc_text:
                desc_row = tk.Frame(form_frame, bg=PANEL_BG)
                desc_row.pack(fill=tk.X, pady=(0, 4))
                tk.Label(desc_row, text="", bg=PANEL_BG, width=30).pack(side=tk.LEFT)
                desc_lbl = tk.Label(desc_row, text=desc_text, bg=PANEL_BG, fg="#858585", font=("Segoe UI", 8), justify=tk.LEFT)
                desc_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, anchor=tk.W)
            
        add_field("爬蟲最大巡檢頁數 (Max Crawl):", "MAX_CRAWL_PAGES", max_crawl, 
                  "全站無障礙巡檢（含地圖複用與盲爬）的子頁面最大掃描數。")
        add_field("AI 預登入最大回合 (Login Turns):", "MAX_LOGIN_TURNS", max_login_turns, 
                  "AI 在預先登入階段中最大的重試嘗試次數，防止失敗時造成算力浪費。")
        add_field("任務觀察等待時間 (Observation):", "RESULT_OBSERVATION_TIME", obs_time, 
                  "任務執行完畢（不論成功或失敗）後，瀏覽器停留給予人眼觀察的秒數。")
        add_field("操作等待延遲 (Action Delay):", "ACTION_DELAY", action_delay, 
                  "每次瀏覽器動作（如點擊、輸入）之後的延遲秒數，給予網頁載入緩衝。")
        add_field("頁面載入超時 (Page Timeout Ms):", "PAGE_LOAD_TIMEOUT", page_timeout, 
                  "Playwright 等待網頁頁面完全載入的最長毫秒限制。")
        
        btn_frame = tk.Frame(adv_win, bg=PANEL_BG)
        btn_frame.pack(fill=tk.X, pady=(15, 20), padx=25)
        
        def save_adv_config():
            try:
                max_crawl_val = int(fields["MAX_CRAWL_PAGES"].get().strip())
                max_login_turns_val = int(fields["MAX_LOGIN_TURNS"].get().strip())
                obs_time_val = int(fields["RESULT_OBSERVATION_TIME"].get().strip())
                action_delay_val = float(fields["ACTION_DELAY"].get().strip())
                page_timeout_val = int(fields["PAGE_LOAD_TIMEOUT"].get().strip())
            except ValueError:
                messagebox.showerror("錯誤", "數值格式不正確，請輸入數字！", parent=adv_win)
                return
                
            data = {
                "MAX_CRAWL_PAGES": max_crawl_val,
                "MAX_LOGIN_TURNS": max_login_turns_val,
                "RESULT_OBSERVATION_TIME": obs_time_val,
                "ACTION_DELAY": action_delay_val,
                "PAGE_LOAD_TIMEOUT": page_timeout_val
            }
            
            try:
                with open(adv_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    
                import importlib
                import config
                importlib.reload(config)
                
                messagebox.showinfo("成功", "進階參數已寫入 config_advanced.json 並即時生效！", parent=adv_win)
                adv_win.destroy()
            except Exception as e:
                messagebox.showerror("錯誤", f"儲存配置文件失敗: {e}", parent=adv_win)
                
        save_btn = tk.Button(btn_frame, text="💾 儲存並套用", bg=ACCENT_COLOR, fg=HEADING_COLOR, 
                            activebackground=ACCENT_HOVER, activeforeground=HEADING_COLOR, 
                            font=("Segoe UI", 10, "bold"), relief="flat", bd=0, command=save_adv_config)
        save_btn.pack(side=tk.RIGHT, padx=5, ipady=4, ipadx=15)
        
        cancel_btn = tk.Button(btn_frame, text="❌ 取消", bg=BTN_BG, fg=TEXT_COLOR, 
                              activebackground=BTN_HOVER, activeforeground=TEXT_COLOR, 
                              font=("Segoe UI", 10), relief="flat", bd=0, command=adv_win.destroy)
        cancel_btn.pack(side=tk.RIGHT, padx=5, ipady=4, ipadx=15)

    def refresh_sitemaps_list(self):
        """讀取 sitemaps/ 目錄下的所有 JSON 地圖檔並更新選單"""
        import os
        sitemaps_dir = os.path.join(os.getcwd(), "sitemaps")
        if not os.path.exists(sitemaps_dir):
            try:
                os.makedirs(sitemaps_dir, exist_ok=True)
            except Exception:
                pass
                
        options = ["None (不使用地圖)"]
        if os.path.exists(sitemaps_dir):
            try:
                files = [f for f in os.listdir(sitemaps_dir) if f.endswith(".json")]
                # 按修改時間遞減排序，最新的放最前面
                files.sort(key=lambda x: os.path.getmtime(os.path.join(sitemaps_dir, x)), reverse=True)
                options.extend(files)
            except Exception:
                pass
                
        self.sitemap_combo["values"] = options
        self.sitemap_combo.current(0)

    # ==========================================
    # 唯讀 Text 複製與選取輔助函數
    # ==========================================
    def block_keyboard_input(self, event):
        """阻止使用者透過鍵盤修改終端日誌內容，但允許選取與複製鍵"""
        ctrl_pressed = (event.state & 0x4) != 0
        if ctrl_pressed and event.keysym.lower() in ('c', 'a'):
            return None  # 允許複製與全選
        if event.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next", "Home", "End"):
            return None  # 允許捲動與導覽
        return "break"  # 阻止其他按鍵（如輸入、Backspace、Delete 等）

    def copy_selection(self):
        """複製選取的文字到剪貼簿"""
        try:
            selected_text = self.terminal_text.get("sel.first", "sel.last")
            self.root.clipboard_clear()
            self.root.clipboard_append(selected_text)
        except Exception:
            pass
        return "break"

    def select_all_text(self):
        """全選日誌內容"""
        self.terminal_text.tag_add("sel", "1.0", "end")
        return "break"

    def show_context_menu(self, event):
        """顯示右鍵快顯選單"""
        try:
            # 判斷是否有選取的文字，決定「複製」選項是否啟用
            has_sel = self.terminal_text.tag_ranges("sel")
            if has_sel:
                self.context_menu.entryconfig("複製 (Copy)", state=tk.NORMAL)
            else:
                self.context_menu.entryconfig("複製 (Copy)", state=tk.DISABLED)
        except Exception:
            self.context_menu.entryconfig("複製 (Copy)", state=tk.DISABLED)
            
        self.context_menu.post(event.x_root, event.y_root)

    # ==========================================
    # 控制邏輯與執行緒管理
    # ==========================================
    def append_log(self, text):
        """將文本印出到終端視窗並上色"""
        lines = text.split("\n")
        for i, line in enumerate(lines):
            # 新行換行
            if i > 0 or (text.startswith("\n") and self.terminal_text.index(tk.END + "-1c") != "1.0"):
                self.terminal_text.insert(tk.END, "\n")
                
            start_index = self.terminal_text.index(tk.END + "-1c")
            self.terminal_text.insert(tk.END, line)
            end_index = self.terminal_text.index(tk.END)
            
            # 判斷文字特徵並標註色彩 Tag
            line_lower = line.lower()
            if "error" in line_lower or "exception" in line_lower or "❌" in line or "failed" in line_lower or "崩潰" in line:
                self.terminal_text.tag_add("error", start_index, end_index)
            elif "warning" in line_lower or "⚠️" in line or "警告" in line:
                self.terminal_text.tag_add("warning", start_index, end_index)
            elif "success" in line_lower or "✓" in line or "✅" in line or "🎉" in line or "完成" in line or "pass" in line_lower:
                self.terminal_text.tag_add("success", start_index, end_index)
            elif "🎯" in line or ">>" in line or "[task]" in line_lower or "[config]" in line_lower or "====" in line:
                self.terminal_text.tag_add("highlight", start_index, end_index)
            elif "[ai]" in line_lower or "🤖" in line:
                self.terminal_text.tag_add("ai", start_index, end_index)
                
        self.terminal_text.see(tk.END)

    def clear_terminal(self):
        """清除終端內容"""
        self.terminal_text.delete("1.0", tk.END)

    def start_audit(self):
        """啟動檢測，並防重複點選"""
        if self.is_running:
            return
        
        # 收集輸入資訊
        task = self.task_entry.get("1.0", tk.END).strip()
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("警告", "請輸入目標網址！")
            return
        
        # 解析 WCAG Guideline
        wcag_sel = self.wcag_combo.get()
        wcag_val = None
        generate_sitemap = False
        
        if "繪製全站地圖" in wcag_sel or "Generate Map" in wcag_sel:
            generate_sitemap = True
            task = "探索全站路由生成網站地圖"
        elif "None" not in wcag_sel:
            wcag_val = wcag_sel.split(" ")[0].strip()
            
        # 解析 Sitemap 選項
        sitemap_sel = self.sitemap_combo.get()
        use_sitemap = False
        sitemap_file = None
        if sitemap_sel and not sitemap_sel.startswith("None"):
            use_sitemap = True
            sitemap_file = os.path.join("sitemaps", sitemap_sel)
            
        # 解析 Model
        if self.use_custom_model_var.get():
            model_val = self.custom_model_entry.get().strip()
            if not model_val:
                messagebox.showwarning("警告", "請輸入自定義模型名稱！")
                return
        else:
            model_sel = self.model_combo.get()
            model_val = model_sel.split(" ")[0].strip()
        
        # 解析 Device
        device_val = self.device_combo.get()
        
        # 解析 Max Turns
        try:
            turns_val = int(self.turns_spin.get())
        except ValueError:
            turns_val = 30
            

        # 解析 Checkboxes
        headless = self.headless_var.get()
        record = self.record_var.get()
        
        if not task and not generate_sitemap:
            messagebox.showwarning("警告", "請輸入檢測任務描述！")
            return

        # 切換 UI 狀態為執行中
        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        # 啟動載入動畫並更新顏色
        self.loader_label.config(fg=ACCENT_COLOR if not generate_sitemap else "#3f51b5")
        self.spinner.start()
        self.loader_text_index = 0
        self.dot_count = 0
        self.update_loader_text()
        
        self.clear_terminal()
        
        self.append_log(f"[GUI] 準備執行 Playwright AI 巡檢任務...\n")
        self.append_log(f"  - 模型: {model_val}\n")
        self.append_log(f"  - 目標 URL: {url}\n")
        if generate_sitemap:
            self.append_log(f"  - 任務類型: 🗺️ 繪製全站地圖 (AI Map)\n")
        else:
            self.append_log(f"  - WCAG 指南: {wcag_val if wcag_val else 'None'}\n")
            self.append_log(f"  - 網站地圖: {sitemap_sel if use_sitemap else 'None'}\n")
        self.append_log(f"  - 視窗模擬: {device_val}\n")
        self.append_log(f"  - 無頭模式: {headless}\n")
        self.append_log(f"  - 儲存記錄: {record}\n")
        self.append_log(f"{'='*60}\n\n")

        # 啟動背景執行緒跑 Python 程序
        thread = threading.Thread(
            target=self.run_subprocess_worker, 
            args=(task, url, wcag_val, model_val, device_val, turns_val, headless, record, generate_sitemap, sitemap_file)
        )
        thread.daemon = True
        thread.start()

    def run_subprocess_worker(self, task, url, wcag, model, device, max_turns, headless, record, generate_sitemap=False, sitemap_file=None):
        """背景執行緒：呼叫 subprocess 執行 agent.py"""
        # 尋找虛擬環境中的 python 執行檔，優先使用 venv
        venv_python = os.path.join(os.getcwd(), ".venv", "Scripts", "python.exe")
        if not os.path.exists(venv_python):
            # Fallback 尋找 Unix/Linux 路徑
            venv_python = os.path.join(os.getcwd(), ".venv", "bin", "python")
        
        python_exe = venv_python if os.path.exists(venv_python) else sys.executable
        
        # 構建 Command (-u 參數啟用 unbuffered stdout，以確保即時輸出日誌)
        cmd = [python_exe, "-u", "agent.py"]
        
        if model:
            cmd.extend(["-m", model])
        if url:
            cmd.extend(["--url", url])
        if wcag:
            cmd.extend(["--wcag", wcag])
        if device:
            cmd.extend(["-d", device])
        if max_turns:
            cmd.extend(["--max-turns", str(max_turns)])
        if headless:
            cmd.append("--headless")
        if record:
            cmd.append("--record")
        if generate_sitemap:
            cmd.append("--generate-sitemap")
        if sitemap_file:
            cmd.extend(["--sitemap", sitemap_file])
            
        # 最後加上位置參數任務字串
        cmd.append(task)
        
        try:
            # 啟動子進程：強制使用 UTF-8 編碼解碼，防止 Windows 預設 cp950 解碼特殊中文字元時崩潰
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            # 持續讀取 stdout 串流
            while self.process and self.process.stdout:
                line = self.process.stdout.readline()
                if not line and self.process.poll() is not None:
                    break
                if line:
                    self.log_queue.put(line)
                    
            # 結束狀態
            return_code = self.process.poll() if self.process else -1
            if return_code == 0:
                self.log_queue.put("\n[GUI SUCCESS] 檢測任務執行完畢！\n")
            elif return_code == -9 or return_code == 15 or (os.name == 'nt' and return_code == 1):
                # 偵測手動終止或強制關閉
                pass
            else:
                self.log_queue.put(f"\n[GUI ERROR] 進程異常結束，退出代碼: {return_code}\n")
                
        except Exception as e:
            self.log_queue.put(f"\n[GUI ERROR] 啟動背景程序失敗: {str(e)}\n")
            
        finally:
            self.process = None
            self.is_running = False
            self.root.after(0, self.reset_buttons)

    def stop_audit(self):
        """終止正在執行的子進程"""
        if self.process and self.is_running:
            self.append_log("\n[GUI WARNING] 正在強行中斷檢測進程，請稍候...\n")
            try:
                # 針對 Windows / Unix 提供妥善的終止
                self.process.terminate()
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                
            self.process = None
            self.is_running = False
            self.append_log("[GUI WARNING] 進程已強行中斷結束。\n")
            self.reset_buttons()

    def reset_buttons(self):
        """重設按鈕狀態並停止動畫"""
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        # 停止加載動畫，並重設提示文字為就緒狀態
        self.spinner.stop()
        self.loader_label.config(text="🤖 系統就緒，等待任務...", fg="#858585")
        # 自動刷新已存在的地圖檔案下拉選單
        self.refresh_sitemaps_list()

    def update_loader_text(self):
        """定時更新 AI 思考與操作狀態的動態提示文字"""
        if not self.is_running:
            return
            
        # 遞增動態圓點數量
        self.dot_count = (self.dot_count + 1) % 4
        dots = "." * self.dot_count
        
        # 每隔 4 次循環 (~1.6秒) 更換一次動作描述詞，增加真實動態感
        if self.dot_count == 0:
            self.loader_text_index = (self.loader_text_index + 1) % len(self.loader_texts)
            
        current_phrase = self.loader_texts[self.loader_text_index]
        self.loader_label.config(text=f"🤖 {current_phrase} {dots}")
        
        # 每 400 毫秒輪詢更新一次，動態效果最為流暢
        self.root.after(400, self.update_loader_text)

    def poll_log_queue(self):
        """定時輪詢日誌隊列，寫入 Text 終端"""
        try:
            while True:
                line = self.log_queue.get_nowait()
                self.append_log(line)
        except queue.Empty:
            pass
        
        # 每 100ms 輪詢一次
        if self.root:
            self.root.after(100, self.poll_log_queue)

    def open_records_directory(self):
        """開啟本地 records/ 記錄目錄資料夾"""
        records_dir = os.path.join(os.getcwd(), "records")
        if not os.path.exists(records_dir):
            try:
                os.makedirs(records_dir, exist_ok=True)
            except Exception:
                messagebox.showinfo("提示", "目前尚無任何檢測記錄目錄 (records/)")
                return
        
        try:
            os.startfile(records_dir)
            self.append_log(f"[GUI] 已打開紀錄目錄資料夾: {records_dir}\n")
        except Exception as e:
            messagebox.showerror("錯誤", f"無法開啟紀錄資料夾: {str(e)}")

# ==========================================
# 程式入口點
# ==========================================
def main():
    # Windows DPI 縮放意識設置，防止高解析度（Retina/4K）螢幕下字體與邊框模糊
    try:
        from ctypes import windll
        # Windows 8.1+ 優先使用 Per-monitor V2 DPI awareness
        windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            # 舊版 Windows 系統 DPI 意識
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                # 更早期的 Windows 全局 DPI 意識
                windll.user32.SetProcessDPIAware()
            except Exception:
                pass
                
    root = tk.Tk()
    app = WCAGAgentGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
