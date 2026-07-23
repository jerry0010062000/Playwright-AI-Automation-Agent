import sys
import os
import json
import subprocess
import threading
import queue
import math
import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import webbrowser
import glob
import random
from reporting.single_page_report import get_page_report_relpath

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

class LoadingSpinner(tk.Label):
    """自訂 3D 甜甜圈 與 Doom 火焰 ASCII 渲染載入動畫，每次執行時隨機播放其中一種"""
    def __init__(self, parent, bg=PANEL_BG, **kwargs):
        # 使用 Consolas 9pt 等寬字型以防對齊錯位，前景色使用明亮終端綠
        super().__init__(parent, bg=bg, fg="#4ec9b0", font=("Consolas", 9), justify=tk.LEFT, anchor=tk.W, **kwargs)
        self.buf_len = 44  # 適合左側面板寬度，提供更多像素細節
        self.height = 11   # 高度 11 行
        self.running = False
        
        # 動態模式選擇: "donut" 或 "fire"
        self.anim_mode = "donut"
        
        # 3D 甜甜圈角度
        self.A = 0.0
        self.B = 0.0
        
        # Doom 火焰狀態
        self.fire_chars = "   .,-~:+*#%@$M"
        self.fire_grid = [[0] * self.buf_len for _ in range(self.height)]
        
        self.init_scene()
        self.update_display()

    def init_scene(self):
        if self.anim_mode == "donut":
            self.A = 0.0
            self.B = 0.0
        elif self.anim_mode == "fire":
            self.fire_grid = [[0] * self.buf_len for _ in range(self.height)]

    def start(self):
        if not self.running:
            self.running = True
            # 固定使用 3D 甜甜圈動畫
            self.anim_mode = "donut"
            self.init_scene()
            self.animate()
            
    def stop(self):
        self.running = False
        self.update_display()
        
    def animate(self):
        if not self.running:
            return
        self.tick()
        self.update_display()
        # 40ms 一幀 (~25 FPS)
        self.after(40, self.animate)
        
    def tick(self):
        if self.anim_mode == "donut":
            self.A += 0.07
            self.B += 0.03
        elif self.anim_mode == "fire":
            self.update_fire()
            
    def update_fire(self):
        max_temp = len(self.fire_chars) - 1
        # 底部火源恆熱
        for x in range(self.buf_len):
            self.fire_grid[self.height - 1][x] = max_temp
            
        # 自下而上傳播熱量並隨機衰減
        for y in range(1, self.height):
            for x in range(self.buf_len):
                src_val = self.fire_grid[y][x]
                if src_val == 0:
                    self.fire_grid[y - 1][x] = 0
                else:
                    decay = random.randint(0, 2)
                    dst_x = (x - decay + 1) % self.buf_len
                    dst_y = y - 1
                    self.fire_grid[dst_y][dst_x] = max(0, src_val - decay)
        
    def update_display(self):
        if not self.running:
            # 靜止狀態下，顯示一個靜態美觀的 3D 甜甜圈
            self.config(text=self.render_donut(0.8, 0.8))
        else:
            if self.anim_mode == "donut":
                self.config(text=self.render_donut(self.A, self.B))
            elif self.anim_mode == "fire":
                self.config(text=self.render_fire())
                
    def render_fire(self):
        output = []
        for y in range(self.height):
            row_chars = [self.fire_chars[self.fire_grid[y][x]] for x in range(self.buf_len)]
            output.append("".join(row_chars))
        return "\n".join(output)
            
    def render_donut(self, A, B):
        output = [[" "] * self.buf_len for _ in range(self.height)]
        zbuffer = [[0.0] * self.buf_len for _ in range(self.height)]
        
        cosA, sinA = math.cos(A), math.sin(A)
        cosB, sinB = math.cos(B), math.sin(B)
        
        R1 = 1
        R2 = 2
        K2 = 5
        
        theta = 0.0
        while theta < 6.28:
            costheta = math.cos(theta)
            sintheta = math.sin(theta)
            
            phi = 0.0
            while phi < 6.28:
                cosphi = math.cos(phi)
                sinphi = math.sin(phi)
                
                circlex = R2 + R1 * costheta
                circley = R1 * sintheta
                
                x = circlex * (cosB * cosphi + sinA * sinB * sinphi) - circley * cosA * sinB
                y = circlex * (sinB * cosphi - sinA * cosB * sinphi) + circley * cosA * cosB
                z = K2 + cosA * circlex * sinphi + circley * sinA
                ooz = 1.0 / z
                
                xp = int(22 + 30 * ooz * x)
                yp = int(5.5 + 11 * ooz * y)
                
                L = cosphi * costheta * sinB - cosA * costheta * sinphi - sinA * sintheta + cosB * (cosA * sintheta - costheta * sinA * sinphi)
                
                if L > 0:
                    if 0 <= xp < self.buf_len and 0 <= yp < self.height:
                        if ooz > zbuffer[yp][xp]:
                            zbuffer[yp][xp] = ooz
                            luminance_index = int(L * 8)
                            if luminance_index > 11:
                                luminance_index = 11
                            chars = ".,-~:;=!*#$@"
                            output[yp][xp] = chars[luminance_index]
                phi += 0.07
            theta += 0.07
            
        return "\n".join("".join(row) for row in output)


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
        
        # 根據預設選擇「請選擇任務」，初始化隱藏次要設定與開始按鈕禁用
        self.root.after(100, self.on_main_task_selected)

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
                  
        # Sitemap Combobox 專屬高亮藍色樣式
        style.configure("Sitemap.TCombobox", fieldbackground="#1c2538", background="#2a3b5c", foreground="#ffffff", 
                        arrowcolor="#ffffff", padding=6, arrowsize=14)
        style.map("Sitemap.TCombobox", 
                  fieldbackground=[("readonly", "#1c2538")],
                  foreground=[("readonly", "#ffffff")])
        
        # Checkbutton 樣式
        style.configure("TCheckbutton", background=PANEL_BG, foreground=TEXT_COLOR, font=("Segoe UI", 10))
        style.map("TCheckbutton",
                  background=[("active", PANEL_BG)],
                  foreground=[("active", TEXT_COLOR)])

        # Treeview 暗黑高對比樣式設定 (保護眼睛)
        style.configure("Treeview", 
                        background="#111827", 
                        foreground="#f9fafb", 
                        fieldbackground="#111827", 
                        rowheight=28,
                        font=("Segoe UI", 9))
        style.configure("Treeview.Heading", 
                        background="#1f2937", 
                        foreground="#f9fafb", 
                        font=("Segoe UI", 10, "bold"))
        style.map("Treeview", 
                  background=[("selected", "#3b82f6")],
                  foreground=[("selected", "#ffffff")])

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
        
        tk.Label(left_content, text="檢測設定面板", bg=PANEL_BG, fg=HEADING_COLOR, font=("Segoe UI", 13, "bold")).pack(anchor=tk.W, pady=(0, 15))

        # 0. 選擇專案網站地圖 (Sitemap - Core project map - placed at the very top)
        sitemap_frame = tk.LabelFrame(left_content, text=" Core Project Map (專案網站地圖) ", bg=PANEL_BG, fg=ACCENT_COLOR, 
                                      font=("Segoe UI", 10, "bold"), labelanchor="nw", relief="solid", bd=1)
        sitemap_frame.pack(fill=tk.X, pady=(0, 15), ipady=5, ipadx=5)
        
        self.sitemap_combo = ttk.Combobox(sitemap_frame, state="readonly", style="Sitemap.TCombobox")
        self.sitemap_combo.pack(fill=tk.X, padx=8, pady=(5, 8))
        self.refresh_sitemaps_list()
        self.sitemap_combo.bind("<<ComboboxSelected>>", self.on_sitemap_selected)
        
        # 地圖管理按鈕列
        sitemap_btn_frame = tk.Frame(sitemap_frame, bg=PANEL_BG)
        sitemap_btn_frame.pack(fill=tk.X, padx=8, pady=(0, 5))
        
        tk.Button(sitemap_btn_frame, text="➕ 新增", bg=BTN_BG, fg=TEXT_COLOR, 
                  activebackground=BTN_HOVER, activeforeground=TEXT_COLOR, 
                  font=("Segoe UI", 9), relief="flat", bd=0, command=self.create_new_sitemap).pack(side=tk.LEFT, padx=(0, 5), ipady=2, ipadx=8)
        
        tk.Button(sitemap_btn_frame, text="🗑️ 刪除", bg="#dc2626", fg=TEXT_COLOR, 
                  activebackground="#b91c1c", activeforeground=TEXT_COLOR, 
                  font=("Segoe UI", 9), relief="flat", bd=0, command=self.delete_sitemap).pack(side=tk.LEFT, padx=(0, 5), ipady=2, ipadx=8)
        
        tk.Button(sitemap_btn_frame, text="🔄 刷新", bg=BTN_BG, fg=TEXT_COLOR, 
                  activebackground=BTN_HOVER, activeforeground=TEXT_COLOR, 
                  font=("Segoe UI", 9), relief="flat", bd=0, command=self.refresh_sitemaps_list).pack(side=tk.LEFT, ipady=2, ipadx=8)

        # 0.5 主要任務選單 (Main Task Selection)
        tk.Label(left_content, text="主要任務類別 (Main Task):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(5, 3))
        main_task_options = [
            "請選擇任務 (Please select a task)",
            "探索與初始化網站地圖 (Explore & Initialize Sitemap)",
            "動態單頁無障礙檢測",
            "靜態全站無障礙檢測"
        ]
        self.main_task_combo = ttk.Combobox(left_content, values=main_task_options, state="readonly", style="TCombobox")
        self.main_task_combo.pack(fill=tk.X, pady=(0, 12))
        self.main_task_combo.current(0)
        self.main_task_combo.bind("<<ComboboxSelected>>", self.on_main_task_selected)

        # 0.6. 主要任務說明卡片 (Main Task Help Card - Dynamic)
        self.help_frame = tk.LabelFrame(left_content, text=" 💡 任務說明與 WCAG 規範定義 ", bg=PANEL_BG, fg="#858585",
                                        font=("Segoe UI", 9, "bold"), labelanchor="nw", relief="solid", bd=1)
        self.help_content_label = tk.Label(self.help_frame, text="", bg=PANEL_BG, fg=TEXT_COLOR,
                                           font=("Segoe UI", 9), justify=tk.LEFT, anchor=tk.W, wraplength=320)
        self.help_content_label.pack(fill=tk.BOTH, expand=True, padx=8, pady=5)

        # 0.8 分隔線 (Divider - Separating core selectors from secondary configurations)
        self.divider = ttk.Separator(left_content, orient='horizontal')
        self.divider.pack(fill=tk.X, pady=(5, 15))

        # 0.9 次要設定容器 (Secondary Configurations Container)
        # 預設為「請選擇任務」，故初始狀態先不 pack，後續由選單切換決定是否顯示
        self.secondary_container = tk.Frame(left_content, bg=PANEL_BG)

        # 1. 初始 URL 與自動登入帳密 (URL & Credentials - Priority directly below Sitemap)
        tk.Label(self.secondary_container, text="檢測目標網址 (Initial URL):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(5, 3))
        self.url_entry = tk.Entry(self.secondary_container, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, 
                                  highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR, 
                                  font=("Segoe UI", 10), bd=0)
        self.url_entry.pack(fill=tk.X, pady=(0, 12), ipady=3)
        self.url_entry.insert(0, "http://localhost:8000")

        # 1.5. 單頁路徑/網址容器 (Page Path Container - Dynamic)
        self.page_container = tk.Frame(self.secondary_container, bg=PANEL_BG)
        # 預設為靜態模式，先不 pack
        self.page_label = tk.Label(self.page_container, text="單頁路徑 (Page Path):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10, "bold"))
        self.page_label.pack(anchor=tk.W, pady=(5, 3))
        self.page_entry = tk.Entry(self.page_container, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, 
                                   highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR, 
                                   font=("Segoe UI", 10), bd=0)
        self.page_entry.pack(fill=tk.X, pady=(0, 12), ipady=3)
        self.page_entry.insert(0, "")

        self.auth_row = tk.Frame(self.secondary_container, bg=PANEL_BG)
        self.auth_row.pack(fill=tk.X, pady=(0, 12))
        
        auth_left = tk.Frame(self.auth_row, bg=PANEL_BG)
        auth_left.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        tk.Label(auth_left, text="登入帳號 (Username):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 2))
        self.username_entry = tk.Entry(auth_left, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
                                       highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                                       font=("Segoe UI", 10), bd=0)
        self.username_entry.pack(fill=tk.X, ipady=2)
        
        auth_right = tk.Frame(self.auth_row, bg=PANEL_BG)
        auth_right.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        tk.Label(auth_right, text="登入密碼 (Password):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 2))
        
        pass_container = tk.Frame(auth_right, bg=PANEL_BG)
        pass_container.pack(fill=tk.X)
        
        self.password_entry = tk.Entry(pass_container, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
                                       highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                                       font=("Segoe UI", 10), bd=0, show="*")
        self.password_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=2)
        
        def toggle_pass_visibility():
            if self.password_entry.cget("show") == "*":
                self.password_entry.config(show="")
                self.eye_btn.config(text="🙈")
            else:
                self.password_entry.config(show="*")
                self.eye_btn.config(text="👁")
                
        self.eye_btn = tk.Button(pass_container, text="👁", bg=BTN_BG, fg=TEXT_COLOR, 
                                 activebackground=BTN_HOVER, activeforeground=TEXT_COLOR,
                                 font=("Segoe UI", 9), relief="flat", bd=0, width=3, command=toggle_pass_visibility)
        self.eye_btn.pack(side=tk.RIGHT, padx=(3, 0), ipady=1)
        
        # 從 config 載入預設值
        import config
        self.username_entry.insert(0, getattr(config, "AUTO_LOGIN_USERNAME", ""))
        self.password_entry.insert(0, getattr(config, "AUTO_LOGIN_PASSWORD", ""))

        # 3. 任務描述大文字框容器 (Task Description Container - Dynamic)
        self.task_container = tk.Frame(self.secondary_container, bg=PANEL_BG)
        # 預設為靜態模式，先不 pack
        self.task_label = tk.Label(self.task_container, text="任務描述 (Task Description):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10))
        self.task_label.pack(anchor=tk.W, pady=(5, 3))
        self.task_entry = tk.Text(self.task_container, height=4, width=30, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, 
                                  highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR, 
                                  font=("Segoe UI", 10), bd=0)
        self.task_entry.pack(fill=tk.X, pady=(0, 12))
        self.task_entry.insert(tk.END, "我要求你對網頁進行自動化測試任務。")

        # 4. WCAG 指南章節選擇容器 (WCAG Guidelines Container - Dynamic)
        self.wcag_container = tk.Frame(self.secondary_container, bg=PANEL_BG)
        # 預設為靜態模式，先不 pack
        self.wcag_label = tk.Label(self.wcag_container, text="WCAG 2.2 檢測章節 (Guideline):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10))
        self.wcag_label.pack(anchor=tk.W, pady=(5, 3))
        self.full_wcag_options = [
            "None (不執行特定 WCAG 檢測)",
            "ALL (靜態全量 - 1.1, 1.3, 1.4, 3.1, 4.1 0-Token 推薦)",
            "DYNAMIC_ALL (動態全量 - 2.1, 2.2, 2.4, 2.5 視覺與焦點)",
            "1.1 (靜態 - 替代文字 1.1.1)",
            "1.2 (靜態 - 時基媒體 1.2.1, 1.2.2)",
            "1.3 (靜態 - 易讀與 DOM 結構 1.3.1, 1.3.5)",
            "1.4 (靜態 - 對比度與色彩 1.4.1, 1.4.3, 1.4.11)",
            "2.1 (動態 - 鍵盤可達與無陷阱 2.1.1, 2.1.2, 2.1.4)",
            "2.2 (動態 - 足夠時間 2.2.1)",
            "2.3 (動態 - 預防閃爍 2.3.1)",
            "2.4 (動態 - 導覽尋找與焦點可見 2.4.1, 2.4.2, 2.4.7)",
            "2.5 (動態 - 輸入裝置 2.5.3)",
            "3.1 (靜態 - 語言標籤 3.1.1)",
            "3.2 (靜態 - 可預測性 3.2.1)",
            "3.3 (靜態 - 輸入協助 3.3.1)",
            "4.1 (靜態 - 相容性與唯一 ID 4.1.2)"
        ]
        self.dynamic_wcag_options = [
            "DYNAMIC_ALL (動態全量 - 2.1, 2.2, 2.4, 2.5 視覺與焦點)",
            "2.1 (動態 - 鍵盤可達與無陷阱 2.1.1, 2.1.2, 2.1.4)",
            "2.2 (動態 - 足夠時間 2.2.1)",
            "2.3 (動態 - 預防閃爍 2.3.1)",
            "2.4 (動態 - 導覽尋找與焦點可見 2.4.1, 2.4.2, 2.4.7)",
            "2.5 (動態 - 輸入裝置 2.5.3)"
        ]
        self.static_wcag_options = [
            "ALL (靜態全量 - 1.1, 1.3, 1.4, 3.1, 4.1 0-Token 推薦)",
            "1.1 (靜態 - 替代文字 1.1.1)",
            "1.2 (靜態 - 時基媒體 1.2.1, 1.2.2)",
            "1.3 (靜態 - 易讀與 DOM 結構 1.3.1, 1.3.5)",
            "1.4 (靜態 - 對比度與色彩 1.4.1, 1.4.3, 1.4.11)",
            "3.1 (靜態 - 語言標籤 3.1.1)",
            "3.2 (靜態 - 可預測性 3.2.1)",
            "3.3 (靜態 - 輸入協助 3.3.1)",
            "4.1 (靜態 - 相容性與唯一 ID 4.1.2)"
        ]
        self.wcag_combo = ttk.Combobox(self.wcag_container, values=self.full_wcag_options, state="readonly", style="TCombobox")
        self.wcag_combo.pack(fill=tk.X, pady=(0, 12))
        self.wcag_combo.current(0)  # 預設選 None
        self.wcag_combo.bind("<<ComboboxSelected>>", self.on_wcag_selected)

        # 地圖動態校對內部變數 (由主要任務選單控制)
        self.verify_sitemap_var = tk.BooleanVar(value=False)

        # 4. AI 模型選擇 (不同公司用不可選標籤隔開)
        tk.Label(self.secondary_container, text="計費與決策 AI 模型 (Model):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(5, 3))
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
        self.model_combo = ttk.Combobox(self.secondary_container, values=model_options, state="readonly", style="TCombobox")
        self.model_combo.pack(fill=tk.X, pady=(0, 5))
        self.model_combo.current(1)  # 預設指向 claude-sonnet-4-5 (預設)
        self.last_valid_model_index = 1
        
        # 監聽選擇，如果是分隔欄位則自動恢復上次選擇
        self.model_combo.bind("<<ComboboxSelected>>", self.on_model_selected)
        
        # 自定義模型切換 Checkbox (預設不選取以保持摺疊)
        self.use_custom_model_var = tk.BooleanVar(value=False)
        self.custom_model_cb = tk.Checkbutton(self.secondary_container, text="使用自定義模型名稱 (進階)", 
                                              variable=self.use_custom_model_var, command=self.toggle_custom_model,
                                              bg=PANEL_BG, fg="#858585", selectcolor=BG_COLOR,
                                              activebackground=PANEL_BG, activeforeground="#858585",
                                              font=("Segoe UI", 9, "italic"), highlightthickness=0, bd=0)
        self.custom_model_cb.pack(anchor=tk.W, pady=(0, 10))
        
        # 自定義模型輸入框容器 (預設不 pack，即摺疊)
        self.custom_model_frame = tk.Frame(self.secondary_container, bg=PANEL_BG)
        
        tk.Label(self.custom_model_frame, text="自定義模型名稱 (Custom Model):", bg=PANEL_BG, fg=TEXT_COLOR, 
                 font=("Segoe UI", 10, "italic")).pack(anchor=tk.W, pady=(0, 3))
        
        self.custom_model_entry = tk.Entry(self.custom_model_frame, bg=BG_COLOR, fg=TEXT_COLOR, insertbackground=TEXT_COLOR, 
                                           highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=ACCENT_COLOR,
                                           font=("Segoe UI", 10), bd=0)
        self.custom_model_entry.pack(fill=tk.X, ipady=3, pady=(0, 10))
        self.custom_model_entry.insert(0, "claude-3-5-sonnet-20241022")

        # 5. 模擬裝置型態
        tk.Label(self.secondary_container, text="瀏覽器視窗模擬 (Device Viewport):", bg=PANEL_BG, fg=TEXT_COLOR, font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(5, 3))
        device_options = ["desktop", "mobile", "tablet"]
        self.device_combo = ttk.Combobox(self.secondary_container, values=device_options, state="readonly", style="TCombobox")
        self.device_combo.pack(fill=tk.X, pady=(0, 12))
        self.device_combo.current(0)

        # 6. 最大回合數與數值控制
        row_settings = tk.Frame(self.secondary_container, bg=PANEL_BG)
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
        
        cb_frame = tk.Frame(self.secondary_container, bg=PANEL_BG)
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
        
        self.loader_label = tk.Label(self.loader_frame, text="🤖 系統就緒，等待任務...", bg=PANEL_BG, fg="#858585", 
                                     font=("Segoe UI", 10, "italic"), anchor=tk.W)
        self.loader_label.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(5, 2))
        
        self.spinner = LoadingSpinner(self.loader_frame, bg=PANEL_BG)
        self.spinner.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 10))

        # ----------------------------------------------------
        # 右側面板：頁籤切換系統 (CMD 終端 + 原生 Sitemap 樹狀地圖)
        # ----------------------------------------------------
        right_panel = tk.Frame(main_container, bg=PANEL_BG, highlightbackground=BORDER_COLOR, highlightthickness=1)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0), pady=10)
        
        # 建立 Notebook 頁籤
        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # --- 頁籤 1: 實時 CMD 終端 ---
        term_tab = tk.Frame(self.notebook, bg=PANEL_BG)
        self.notebook.add(term_tab, text=" 💻 實時 CMD 終端 ")
        
        right_content = tk.Frame(term_tab, bg=PANEL_BG)
        right_content.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
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

        # 樹狀圖右鍵選單 (Treeview Context Menu)
        self.tree_context_menu = tk.Menu(self.root, tearoff=0, bg=PANEL_BG, fg=TEXT_COLOR,
                                         activebackground=ACCENT_COLOR, activeforeground=HEADING_COLOR, bd=1, relief="solid")
        self.tree_context_menu.add_command(label="複製相對路徑 (Copy Path)", command=self.copy_tree_relative_path)
        self.tree_context_menu.add_command(label="複製完整網址 (Copy Full URL)", command=self.copy_tree_full_url)
        self.tree_context_menu.add_command(label="快速插入至 Page 欄位", command=self.quick_insert_page)
        self.tree_context_menu.add_command(label="開啟無障礙單頁報告 (Open Report)", command=self.open_selected_page_report)

        # --- 頁籤 2: 原生 Sitemap 樹狀地圖視覺化系統 ---
        tree_tab = tk.Frame(self.notebook, bg=PANEL_BG)
        self.notebook.add(tree_tab, text=" 🗺️ 網站地圖樹狀圖 (Sitemap Tree) ")
        
        tree_content = tk.Frame(tree_tab, bg=PANEL_BG)
        tree_content.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)
        
        # 樹狀圖頂部工具列
        tree_header = tk.Frame(tree_content, bg=PANEL_BG)
        tree_header.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(tree_header, text="🗺️ 網站地圖全頁面探索進度 (Parent-Child Hierarchy Tree)", style="Heading.TLabel").pack(side=tk.LEFT)
        
        self.auto_refresh_tree_var = tk.BooleanVar(value=True)
        tk.Checkbutton(tree_header, text="⏱️ 自動刷新 (3秒)", variable=self.auto_refresh_tree_var,
                       bg=PANEL_BG, fg=TEXT_COLOR, selectcolor=BG_COLOR,
                       activebackground=PANEL_BG, activeforeground=TEXT_COLOR,
                       font=("Segoe UI", 9), highlightthickness=0, bd=0).pack(side=tk.RIGHT, padx=5)

        tk.Button(tree_header, text="📄 查看頁面報告", bg=BTN_BG, fg=TEXT_COLOR,
                  activebackground=BTN_HOVER, activeforeground=TEXT_COLOR,
                  font=("Segoe UI", 9), relief="flat", bd=0, command=self.open_selected_page_report).pack(side=tk.RIGHT, padx=5)

        tk.Button(tree_header, text="🗑️ 重置校對狀態", bg="#991b1b", fg=HEADING_COLOR, 
                  activebackground="#ef4444", activeforeground=HEADING_COLOR, 
                  font=("Segoe UI", 9, "bold"), relief="flat", bd=0, command=self.reset_sitemap_status).pack(side=tk.RIGHT, padx=5)
                  
        tk.Button(tree_header, text="🔄 重新載入地圖", bg=BTN_BG, fg=TEXT_COLOR, 
                  activebackground=BTN_HOVER, activeforeground=TEXT_COLOR, 
                  font=("Segoe UI", 9), relief="flat", bd=0, command=self.refresh_sitemap_tree).pack(side=tk.RIGHT, padx=5)

        # 樹狀圖統計資訊列
        self.tree_stats_label = tk.Label(tree_content, text="總頁數: 0 | 已靜態校對: 0 | 已動態校對: 0 | 待探索: 0", 
                                         bg=PANEL_BG, fg="#9cdcfe", font=("Segoe UI", 10, "bold"), anchor=tk.W)
        self.tree_stats_label.pack(fill=tk.X, pady=(0, 10))

        # Tkinter Treeview 視圖
        tree_container = tk.Frame(tree_content, bg=BG_COLOR)
        tree_container.pack(fill=tk.BOTH, expand=True)
        
        self.tree_view = ttk.Treeview(tree_container, columns=("title", "status", "static_time", "dynamic_time"), show="tree headings")
        self.tree_view.heading("#0", text=" 頁面相對路徑 (Path)")
        self.tree_view.heading("title", text="頁面標題 (Title)")
        self.tree_view.heading("status", text="探索狀態 (Status)")
        self.tree_view.heading("static_time", text="靜態校對時間")
        self.tree_view.heading("dynamic_time", text="動態 AI 校對時間")
        
        self.tree_view.column("#0", width=250, anchor=tk.W)
        self.tree_view.column("title", width=200, anchor=tk.W)
        self.tree_view.column("status", width=130, anchor=tk.CENTER)
        self.tree_view.column("static_time", width=140, anchor=tk.CENTER)
        self.tree_view.column("dynamic_time", width=140, anchor=tk.CENTER)

        # 設定顏色標籤 (Color Tags)
        self.tree_view.tag_configure("full_ok", foreground="#fb923c")
        self.tree_view.tag_configure("static_ok", foreground="#34d399")
        self.tree_view.tag_configure("dynamic_ok", foreground="#38bdf8")
        self.tree_view.tag_configure("initialized", foreground="#a78bfa")
        self.tree_view.tag_configure("pending", foreground="#fbbf24")
        self.tree_view.tag_configure("error", foreground="#f87171")
        self.tree_view.tag_configure("category", foreground="#888888")
        
        tree_scroll_y = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.tree_view.yview)
        tree_scroll_x = ttk.Scrollbar(tree_container, orient=tk.HORIZONTAL, command=self.tree_view.xview)
        self.tree_view.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_view.bind("<Double-1>", lambda e: self.open_selected_page_report())
        self.tree_view.bind("<Button-3>", self.show_tree_context_menu)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="清除視窗 (Clear Log)", command=self.clear_terminal)
        
        self.terminal_text.bind("<Button-3>", self.show_context_menu)
        
        # 初始化終端狀態與 3D 專案縮寫歡迎橫幅
        self.show_welcome_banner()
        self.root.after(500, self.refresh_sitemap_tree)
        self.root.after(3000, self.auto_refresh_tree_loop)
        
        # 初始化時預設選擇網站地圖可視化頁籤 (tab 1)
        self.notebook.select(1)

    def get_welcome_banner(self):
        """傳回 3D 專案縮寫 PW-AI ASCII 歡迎橫幅"""
        return (
            "=========================================================\n"
            "  ██████╗ ██╗██╗    ██╗      █████╗ ██╗\n"
            "  ██╔══██╗██║██║    ██║     ██╔══██╗██║\n"
            "  ██████╔╝██║██║ █╗ ██║     ███████║██║\n"
            "  ██╔═══╝ ██║██║███╗██║     ██╔══██║██║\n"
            "  ██║     ██║╚███╔███╔╝     ██║  ██║██║\n"
            "  ╚═╝     ╚═╝ ╚══╝╚══╝      ╚═╝  ╚═╝╚═╝\n"
            "  -------------------------------------------------------\n"
            "  🎭 Playwright AI Automation & WCAG Sitemap Agent v2.5\n"
            "=========================================================\n"
            "[GUI] 歡迎使用 Playwright AI 巡檢與地圖同步控制台！\n"
            "[GUI] 請於左側選擇主要任務類別，點選「🚀 啟動檢測任務」開始。\n\n"
        )

    def show_welcome_banner(self):
        """輸出歡迎橫幅"""
        self.append_log(self.get_welcome_banner())

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
            login_user = self.username_entry.get().strip()
            login_pass = self.password_entry.get().strip()
            
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
        sitemaps_dir = os.path.join(os.getcwd(), "sitemaps")
        if not os.path.exists(sitemaps_dir):
            try:
                os.makedirs(sitemaps_dir, exist_ok=True)
            except Exception:
                pass
                
        # 記住目前選取的項目
        current_val = self.sitemap_combo.get()
                
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
        
        # 嘗試恢復先前選取的項目，如果不存在則設為 None
        if current_val in options:
            self.sitemap_combo.set(current_val)
        else:
            self.sitemap_combo.current(0)

    def create_new_sitemap(self):
        """新增一個空白的 sitemap 文件"""
        import json
        
        # 彈出對話框讓用戶輸入名稱
        sitemap_name = simpledialog.askstring(
            "新增網站地圖",
            "請輸入新地圖名稱 (不需要 .json 副檔名):",
            parent=self.root
        )
        
        if not sitemap_name:
            return  # 用戶取消
        
        # 移除可能的 .json 副檔名
        if sitemap_name.endswith(".json"):
            sitemap_name = sitemap_name[:-5]
        
        # 檢查名稱是否合法
        if not sitemap_name or not sitemap_name.strip():
            messagebox.showwarning("無效名稱", "地圖名稱不能為空！")
            return
        
        # 清理名稱（移除特殊字元）
        sitemap_name = re.sub(r'[<>:"/\\|?*]', '', sitemap_name.strip())
        
        if not sitemap_name:
            messagebox.showwarning("無效名稱", "地圖名稱包含無效字元！")
            return
        
        # 創建文件路徑
        sitemaps_dir = os.path.join(os.getcwd(), "sitemaps")
        os.makedirs(sitemaps_dir, exist_ok=True)
        
        file_path = os.path.join(sitemaps_dir, f"{sitemap_name}.json")
        
        # 檢查文件是否已存在
        if os.path.exists(file_path):
            messagebox.showwarning("文件已存在", f"地圖 '{sitemap_name}.json' 已經存在！")
            return
        
        # 創建最小的 sitemap 結構
        minimal_sitemap = {
            "nodes": {
                "/": {
                    "url": "/",
                    "title": "Root",
                    "parent": None,
                    "children": [],
                    "status": "UNVERIFIED"
                }
            }
        }
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(minimal_sitemap, f, ensure_ascii=False, indent=2)
            
            messagebox.showinfo("成功", f"成功創建地圖：{sitemap_name}.json")
            
            # 刷新列表並選中新創建的地圖
            self.refresh_sitemaps_list()
            self.sitemap_combo.set(f"{sitemap_name}.json")
            self.on_sitemap_selected()  # 觸發選擇事件以更新右側樹狀圖
            
        except Exception as e:
            messagebox.showerror("錯誤", f"創建地圖失敗：{str(e)}")

    def delete_sitemap(self):
        """刪除當前選中的 sitemap 文件"""
        current_selection = self.sitemap_combo.get()
        
        # 檢查是否選中了有效的地圖
        if not current_selection or current_selection.startswith("None"):
            messagebox.showwarning("未選中地圖", "請先選擇要刪除的地圖！")
            return
        
        # 確認刪除
        confirm = messagebox.askyesno(
            "確認刪除",
            f"確定要刪除地圖 '{current_selection}' 嗎？\n\n此操作無法撤銷！",
            icon='warning'
        )
        
        if not confirm:
            return
        
        # 執行刪除
        sitemaps_dir = os.path.join(os.getcwd(), "sitemaps")
        file_path = os.path.join(sitemaps_dir, current_selection)
        
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                messagebox.showinfo("成功", f"已刪除地圖：{current_selection}")
                
                # 刷新列表並選中 None
                self.refresh_sitemaps_list()
                self.sitemap_combo.current(0)  # 選中 "None"
                self.on_sitemap_selected()  # 更新右側樹狀圖
            else:
                messagebox.showerror("錯誤", f"找不到文件：{current_selection}")
        except Exception as e:
            messagebox.showerror("錯誤", f"刪除失敗：{str(e)}")



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

    def refresh_sitemap_tree(self):
        """刷新並載入原生 Tkinter Treeview Sitemap 樹狀視覺化地圖"""
        import json
        map_name = self.sitemap_combo.get() if hasattr(self, "sitemap_combo") else "smart4-map.json"
        if not map_name or "None" in map_name:
            self.tree_view.delete(*self.tree_view.get_children())
            self.tree_stats_label.config(text="📊 自由網頁探索模式 (未加載專案網站地圖)")
            return
            
        map_path = os.path.join("sitemaps", map_name)
        
        if not os.path.exists(map_path):
            self.tree_stats_label.config(text="⚠️ 找不到 sitemap JSON 檔案")
            return

        try:
            with open(map_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            nodes = data.get("nodes", {})
            
            # 1. 記憶目前使用者已展開折疊的 IID 節點 (避免刷新時自動收合)
            opened_iids = set()
            def record_opened(parent_id=""):
                for child in self.tree_view.get_children(parent_id):
                    try:
                        if self.tree_view.item(child, "open"):
                            opened_iids.add(child)
                    except Exception:
                        pass
                    record_opened(child)
            record_opened("")

            self.tree_view.delete(*self.tree_view.get_children())
            
            total = len(nodes)
            static_c = 0
            dynamic_c = 0
            full_c = 0
            pending_c = 0
            dead_c = 0
            
            # 輔助函式：發動遞迴插入節點
            inserted = set()
            
            # 1. 建立乾淨的父子關係映射，排除 distant duplicates，僅保留 direct children
            clean_children = {p: [] for p in nodes}
            for p, n in nodes.items():
                parent = n.get("parent")
                if parent in clean_children:
                    clean_children[parent].append(p)

            def insert_node(p_path, parent_id=""):
                nonlocal static_c, dynamic_c, full_c, pending_c, dead_c
                if p_path not in nodes or p_path in inserted:
                    return
                inserted.add(p_path)
                
                n = nodes[p_path]
                title = n.get("title", "未命名頁面")
                v_static = n.get("verified_at", "")
                v_dynamic = n.get("dynamic_verified_at", "")
                status_raw = str(n.get("status", "OK"))
                is_err = n.get("error", False)
                
                is_dead = is_err or ("404" in status_raw and status_raw != "CATEGORY") or ("HTTP_" in status_raw and status_raw != "CATEGORY") or "500" in status_raw
                
                tag = "pending"
                status_str = "⏳ 待探索"
                if is_dead:
                    tag = "error"
                    status_str = f"❌ 異常 ({status_raw})"
                    dead_c += 1
                elif status_raw == "CATEGORY":
                    tag = "category"
                    status_str = "📁 導覽目錄"
                elif v_static and v_dynamic:
                    tag = "full_ok"
                    status_str = "🌟 靜/動雙重校對"
                    full_c += 1
                elif v_dynamic:
                    tag = "dynamic_ok"
                    status_str = "🤖 已動態校對"
                    dynamic_c += 1
                elif v_static:
                    tag = "static_ok"
                    status_str = "✅ 已靜態校對"
                    static_c += 1
                elif n.get("initialized"):
                    tag = "initialized"
                    status_str = "🔑 已認證存在"
                else:
                    pending_c += 1
                    
                icon = "📄 " if n.get("is_leaf") else "📁 "
                display_path = icon + p_path
                
                item_id = self.tree_view.insert(
                    parent_id, "end", iid=p_path, text=display_path,
                    values=(title, status_str, v_static or "-", v_dynamic or "-"),
                    tags=(tag,)
                )
                
                # 遍歷子節點 (字母順序排序)
                for child_path in sorted(clean_children.get(p_path, [])):
                    insert_node(child_path, parent_id=p_path)

            # 找到根節點 (Parent 為 None 或不在 nodes 中) (字母順序排序)
            root_paths = sorted([p for p, n in nodes.items() if not n.get("parent") or n.get("parent") not in nodes])
            for rp in root_paths:
                insert_node(rp, parent_id="")
                
            # 補漏剩餘未插入的獨立節點 (字母順序排序)
            for p in sorted(nodes.keys()):
                if p not in inserted:
                    insert_node(p, parent_id="")

            # 2. 恢復展開原先已打開折疊的節點
            for open_id in opened_iids:
                if self.tree_view.exists(open_id):
                    try:
                        self.tree_view.item(open_id, open=True)
                    except Exception:
                        pass
                    
            self.tree_stats_label.config(
                text=f"📊 地圖: {map_name} | 總頁數: {total} | 🌟 雙重: {full_c} | ✅ 靜態: {static_c} | 🤖 動態: {dynamic_c} | ⏳ 待探索: {pending_c} | ❌ 異常/死鏈: {dead_c}"
            )
        except Exception as e:
            self.tree_stats_label.config(text=f"⚠️ 載入地圖失敗: {e}")

    def reset_sitemap_status(self):
        """清除當前選取地圖中所有頁面的靜態與動態校對時間戳記 (含 Pop-up 警告對話框)"""
        import json
        map_name = self.sitemap_combo.get().strip() if hasattr(self, "sitemap_combo") else "smart4-map.json"
        map_path = os.path.join("sitemaps", map_name)
        
        if not os.path.exists(map_path):
            messagebox.showerror("錯誤", f"找不到地圖檔案: {map_name}")
            return
            
        confirm = messagebox.askyesno(
            "⚠️ 警告：重置地圖校對狀態",
            f"確定要清除地圖 [{map_name}] 中所有頁面的【靜態與動態校對記錄】嗎？\n\n"
            "此動作不可逆，全站所有頁面將被恢復為『⏳ 待探索』初始狀態！",
            icon="warning"
        )
        
        if confirm:
            try:
                with open(map_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                nodes = data.get("nodes", {})
                for p, n in nodes.items():
                    n.pop("verified_at", None)
                    n.pop("dynamic_verified_at", None)
                    n.pop("initialized", None)
                    n.pop("initialized_at", None)
                    if "status" in n and n["status"] != "OK" and not n["status"].startswith("HTTP"):
                        n["status"] = "OK"
                        
                with open(map_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                    
                self.refresh_sitemap_tree()
                self.append_log(f"\n[GUI] 🗑️ 成功重置地圖 [{map_name}] 探索狀態為 0% 待探索！")
                messagebox.showinfo("重置成功", f"已成功清空 [{map_name}] 的全站校對記錄！")
            except Exception as e:
                messagebox.showerror("錯誤", f"重置地圖記錄失敗: {e}")

    def auto_refresh_tree_loop(self):
        """每 3 秒輪詢自動刷新 Treeview 地圖狀態 (實時追蹤探索進度)"""
        try:
            if hasattr(self, "auto_refresh_tree_var") and self.auto_refresh_tree_var.get():
                self.refresh_sitemap_tree()
        except Exception:
            pass
        finally:
            self.root.after(3000, self.auto_refresh_tree_loop)

    def update_start_button_state(self):
        """根據主要任務選單與網站地圖選單的狀態，啟用/禁用開始按鈕"""
        task_sel = self.main_task_combo.get()
        sitemap_sel = self.sitemap_combo.get()
        
        has_valid_task = not task_sel.startswith("請選擇")
        has_valid_sitemap = sitemap_sel and not sitemap_sel.startswith("None")
        
        if has_valid_task and has_valid_sitemap:
            self.start_btn.config(state=tk.NORMAL)
        else:
            self.start_btn.config(state=tk.DISABLED)

    def on_sitemap_selected(self, event=None):
        """當地圖檔案被選取時，自動讀取並載入其 target_url、帳密配置等"""
        map_name = self.sitemap_combo.get().strip()
        self.refresh_sitemap_tree()
        
        if map_name.startswith("None"):
            self.update_start_button_state()
            return
            
        map_path = os.path.join("sitemaps", map_name)
        if os.path.exists(map_path):
            try:
                with open(map_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # 1. 自動更新 URL 欄位
                target_url = data.get("target_url")
                if target_url:
                    self.url_entry.delete(0, tk.END)
                    self.url_entry.insert(0, target_url)
                    
                # 2. 自動更新帳密欄位
                default_user = data.get("default_username")
                default_pass = data.get("default_password")
                if default_user is not None:
                    self.username_entry.delete(0, tk.END)
                    self.username_entry.insert(0, default_user)
                if default_pass is not None:
                    self.password_entry.delete(0, tk.END)
                    self.password_entry.insert(0, default_pass)
                
                # 3. 主要任務選單與聯動
                main_task = data.get("main_task")
                if main_task and main_task in self.main_task_combo["values"]:
                    self.main_task_combo.set(main_task)
                    self.on_main_task_selected()
                    
                # 4. 單頁路徑
                page_path = data.get("page_path")
                if page_path is not None:
                    self.page_entry.delete(0, tk.END)
                    self.page_entry.insert(0, page_path)
                    
                # 5. WCAG 下拉選單 (如果是特製的則覆蓋)
                wcag_sel = data.get("wcag_sel")
                if wcag_sel and wcag_sel in self.wcag_combo["values"]:
                    self.wcag_combo.set(wcag_sel)
                    
                # 6. AI 模型設定
                use_custom_model = data.get("use_custom_model")
                if use_custom_model is not None:
                    self.use_custom_model_var.set(use_custom_model)
                    self.toggle_custom_model()
                
                custom_model = data.get("custom_model")
                if custom_model:
                    self.custom_model_entry.delete(0, tk.END)
                    self.custom_model_entry.insert(0, custom_model)
                    
                model = data.get("model")
                if model and model in self.model_combo["values"]:
                    self.model_combo.set(model)
                    
                # 7. 裝置、回合與無頭/記錄
                device = data.get("device")
                if device and device in self.device_combo["values"]:
                    self.device_combo.set(device)
                    
                max_turns = data.get("max_turns")
                if max_turns is not None:
                    self.turns_spin.delete(0, "end")
                    self.turns_spin.insert(0, str(max_turns))
                    
                headless = data.get("headless")
                if headless is not None:
                    self.headless_var.set(headless)
                    
                record = data.get("record")
                if record is not None:
                    self.record_var.set(record)
                
                self.append_log(f"\n[GUI] 🗺️ 地圖 [{map_name}] 讀取成功，已自動載入上次配置的任務設定項目！")
            except Exception as e:
                self.append_log(f"\n[GUI] ⚠️ 讀取地圖設定時發生錯誤: {e}")
        self.update_start_button_state()

    def open_selected_page_report(self, event=None):
        """開啟樹狀圖中選取頁面的無障礙單頁報告文檔"""
        item_id = self.tree_view.focus() if hasattr(self, "tree_view") else None
        if not item_id:
            selection = self.tree_view.selection()
            if selection:
                item_id = selection[0]
                
        if not item_id:
            messagebox.showinfo("提示", "請先點選樹狀地圖中的某個頁面！")
            return

        map_name = self.sitemap_combo.get().strip() if hasattr(self, "sitemap_combo") else "smart4-map.json"
        map_path = os.path.join("sitemaps", map_name)
        map_stem = os.path.splitext(os.path.basename(map_name))[0]

        report_relpath = None
        if os.path.exists(map_path):
            try:
                with open(map_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                nodes = data.get("nodes", {})
                if item_id in nodes:
                    report_relpath = nodes[item_id].get("report_file")
            except Exception:
                pass

        if not report_relpath:
            report_relpath = get_page_report_relpath(map_name, item_id)

        full_path = os.path.abspath(report_relpath)
        if os.path.exists(full_path):
            try:
                os.startfile(full_path)
                self.append_log(f"\n[GUI] 📄 已開啟頁面 [{item_id}] 的巡檢報告文檔: {full_path}")
            except Exception as e:
                messagebox.showerror("錯誤", f"無法開啟報告檔案: {e}")
        else:
            messagebox.showinfo("尚未生成報告", f"頁面 [{item_id}] 尚在『⏳ 待探索』狀態，尚未生成單頁無障礙報告文檔。\n\n預期檔案位置: {full_path}")

    def show_tree_context_menu(self, event):
        """在 Treeview 上顯示右鍵選單"""
        iid = self.tree_view.identify_row(event.y)
        if iid:
            self.tree_view.selection_set(iid)
            self.tree_context_menu.post(event.x_root, event.y_root)

    def copy_tree_relative_path(self):
        """複製選中節點的相對路徑"""
        selected = self.tree_view.selection()
        if not selected:
            return
        rel_path = selected[0]
        self.root.clipboard_clear()
        self.root.clipboard_append(rel_path)
        self.append_log(f"\n[GUI] 📋 已複製相對路徑到剪貼簿: {rel_path}")

    def copy_tree_full_url(self):
        """複製選中節點的完整網址"""
        selected = self.tree_view.selection()
        if not selected:
            return
        rel_path = selected[0]
        base_url = self.url_entry.get().strip()
        if not base_url:
            base_url = "http://localhost:8000"
        import urllib.parse
        full_url = urllib.parse.urljoin(base_url, rel_path)
        self.root.clipboard_clear()
        self.root.clipboard_append(full_url)
        self.append_log(f"\n[GUI] 📋 已複製完整網址到剪貼簿: {full_url}")

    def quick_insert_page(self):
        """地圖右鍵快速插入至 Page 欄位"""
        selected = self.tree_view.selection()
        if not selected:
            self.append_log("\n[GUI WARNING] 未選取任何地圖節點，無法插入。")
            return
        rel_path = selected[0]
        
        sel = self.main_task_combo.get()
        if "動態單頁" not in sel:
            messagebox.showinfo("提示", "請先切換主要任務至『動態單頁無障礙檢測』以啟用單頁路徑欄位！")
            return
            
        orig_state = self.page_entry.cget("state")
        try:
            self.page_entry.config(state=tk.NORMAL)
            self.page_entry.delete(0, tk.END)
            self.page_entry.insert(0, rel_path)
            self.append_log(f"\n[GUI] ⚡ 已自動插入相對路徑至 Page Path: {rel_path}")
        except Exception as e:
            self.append_log(f"\n[GUI ERROR] 快速插入失敗: {e}")
        finally:
            self.page_entry.config(state=orig_state)

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
        """清除終端內容並重繪 3D 專案縮寫歡迎橫幅"""
        self.terminal_text.delete("1.0", tk.END)
        self.show_welcome_banner()

    def open_visualizer(self):
        """開啟 Sitemap 樹狀地圖視覺化系統"""
        import webbrowser
        viz_path = os.path.abspath("sitemap_visualizer.html")
        if os.path.exists(viz_path):
            webbrowser.open(f"file:///{viz_path}")
            self.append_log(f"\n[GUI] 🌐 成功開啟 Sitemap 地圖視覺化系統: {viz_path}")
        else:
            messagebox.showerror("錯誤", "找不到 sitemap_visualizer.html 檔案！")



    def on_wcag_selected(self, event=None):
        """當 WCAG 章節下拉選單切換時，自動更新 AI 模型選單啟用狀態"""
        self.update_model_combo_state()

    def update_model_combo_state(self):
        """根據目前的 WCAG 任務類型，提示用戶任務類型 (但不強制禁用模型選擇)"""
        wcag_sel = self.wcag_combo.get().split(" ")[0].strip()
        main_task = self.main_task_combo.get()
        
        # 判定是否為靜態 0-Token 任務
        is_static = ("靜態全站" in main_task) or (wcag_sel == "ALL") or (wcag_sel in ["1.1", "1.2", "1.3", "1.4", "3.1", "3.2", "3.3", "4.1"])
        
        # 重要：即使是靜態 WCAG 任務，仍需要 AI 模型進行登入操作
        # 因此不再禁用模型選擇器，讓用戶自由選擇
        # 用戶可以選擇 0-Token 跳過登入，或選擇 AI 模型進行自動登入
        self.model_combo["state"] = "readonly"
        
        # 如果用戶之前選擇過模型，保持選擇
        if not self.model_combo.get() or self.model_combo.get().startswith("請選擇"):
            # 靜態任務推薦 0-Token（如果不需要登入），但不強制
            if is_static:
                self.model_combo.set("0-Token (本地極速免模型)")
            else:
                self.model_combo.current(1)

    def update_layout_visibility(self):
        """根據目前主要任務類別，動態調整左側面板欄位可見度"""
        if not hasattr(self, "secondary_container"):
            return
            
        sel = self.main_task_combo.get()
        
        # 1. 如果是「請選擇任務」，隱藏所有次要設定與說明卡片
        if sel.startswith("請選擇"):
            self.secondary_container.pack_forget()
            self.help_frame.pack_forget()
            self.update_start_button_state()
            return
            
        # 否則，顯示說明卡片與次要設定，並動態更新開始按鈕啟用狀態
        self.help_frame.pack(fill=tk.X, pady=(0, 15), after=self.main_task_combo)
        self.secondary_container.pack(fill=tk.BOTH, expand=True, after=self.divider)
        self.update_start_button_state()
        
        show_page = "動態單頁" in sel
        show_task = "靜態全站" not in sel
        show_wcag = "靜態全站" not in sel and "探索" not in sel
        
        # 2. 先全部 pack_forget
        self.page_container.pack_forget()
        self.task_container.pack_forget()
        self.wcag_container.pack_forget()
        
        # 3. 按順序重新 pack
        # page_container 應該在 url_entry 之後
        if show_page:
            self.page_container.pack(fill=tk.X, after=self.url_entry)
            
        # task_container 應該在 auth_row 之後
        if show_task:
            self.task_container.pack(fill=tk.X, after=self.auth_row)
            
        # wcag_container 應該在 task_container 之後 (若顯示)，否則在 auth_row 之後
        if show_wcag:
            anchor_widget = self.task_container if show_task else self.auth_row
            self.wcag_container.pack(fill=tk.X, after=anchor_widget)

    def on_main_task_selected(self, event=None):
        """主任務選單切換事件處置"""
        sel = self.main_task_combo.get()
        
        if sel.startswith("請選擇"):
            self.update_layout_visibility()
            return
            
        if "靜態全站" in sel:
            self.wcag_combo["values"] = self.static_wcag_options
            idx = 0
            for i, opt in enumerate(self.static_wcag_options):
                if opt.startswith("ALL"):
                    idx = i
                    break
            self.wcag_combo.current(idx)
            self.wcag_combo.config(state="disabled")
            self.task_entry.delete("1.0", tk.END)
            self.task_entry.insert(tk.END, "執行全站靜態 WCAG 1.1~4.1 全量無障礙審查 (0-Token 高速模式)")
            
            help_text = (
                "【任務定義】\n"
                "透過網站地圖（Sitemap）全量遍歷所有網頁，並調用 Axe-core 本地無障礙審查引擎，對 HTML DOM 結構、靜態屬性、標記進行高速無障礙檢測。\n\n"
                "【所含 WCAG 章節】\n"
                "靜態全量（WCAG 1.1~4.1）\n"
                "• 1.1 非文字內容替代文字 (Text Alternatives)\n"
                "• 1.3 資訊與關聯性 (Info and Relationships)\n"
                "• 1.4 對比度與色彩 (Contrast & Colour)\n"
                "• 3.1 可讀性與語言標籤 (Language of Page)\n"
                "• 4.1 相容性與唯一 ID (HTML DOM Validity)"
            )
            self.help_content_label.config(text=help_text)
            
        elif "動態單頁" in sel:
            self.wcag_combo["values"] = self.dynamic_wcag_options
            idx = 0
            for i, opt in enumerate(self.dynamic_wcag_options):
                if opt.startswith("DYNAMIC_ALL"):
                    idx = i
                    break
            self.wcag_combo.current(idx)
            self.wcag_combo.config(state="readonly")
            self.task_entry.delete("1.0", tk.END)
            self.task_entry.insert(tk.END, "執行全站動態 WCAG 2.1/2.2/2.4/2.5 鍵盤焦點與 AI 視覺無障礙審查")
            
            help_text = (
                "【任務定義】\n"
                "對指定的單一頁面進行深入的動態互動性檢測。運用 AI 視覺模擬與模擬鍵盤焦點移動，分析複雜互動組件（如彈窗、下拉選單、選單切換等）的可用性與無障礙程度。\n\n"
                "【所含 WCAG 章節】\n"
                "動態全量（WCAG 2.1/2.2/2.4/2.5）\n"
                "• 2.1 鍵盤可達性（Keyboard Accessible）\n"
                "• 2.2 足夠時間（Enough Time）\n"
                "• 2.4 可導覽性與焦點可見（Navigable & Focus Visible）\n"
                "• 2.5 輸入協助與標籤（Input Modalities）"
            )
            self.help_content_label.config(text=help_text)
            
        elif "探索" in sel:
            self.wcag_combo["values"] = self.full_wcag_options
            self.wcag_combo.current(0)
            self.wcag_combo.config(state="disabled")
            self.task_entry.delete("1.0", tk.END)
            self.task_entry.insert(tk.END, "探索與初始化網站地圖：自動發現頁面、校對狀態")
            
            help_text = (
                "【任務定義】\n"
                "自動化探索目標網站，遍歷並爬取所有頁面的網址、網頁標題與 HTTP 狀態碼，藉此建立專案網站地圖 JSON。\n\n"
                "【所含 WCAG 章節】\n"
                "本任務為結構探索與校對階段，不包含 WCAG 規範評估。"
            )
            self.help_content_label.config(text=help_text)
            
        self.update_model_combo_state()
        self.update_layout_visibility()

    def save_sitemap_config(self, sitemap_path):
        """當按下開始後，為選定的專案網站地圖存檔其配置參數"""
        if not sitemap_path or not os.path.exists(sitemap_path):
            return
            
        try:
            with open(sitemap_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            # 寫入目前 UI 設定值到 JSON 頂層欄位
            data["target_url"] = self.url_entry.get().strip()
            data["default_username"] = self.username_entry.get().strip()
            data["default_password"] = self.password_entry.get().strip()
            data["main_task"] = self.main_task_combo.get()
            data["page_path"] = self.page_entry.get().strip()
            data["wcag_sel"] = self.wcag_combo.get()
            
            # AI 模型
            data["use_custom_model"] = self.use_custom_model_var.get()
            data["custom_model"] = self.custom_model_entry.get().strip()
            data["model"] = self.model_combo.get()
            
            # 其他次要設定
            data["device"] = self.device_combo.get()
            try:
                data["max_turns"] = int(self.turns_spin.get())
            except ValueError:
                data["max_turns"] = 30
            data["headless"] = self.headless_var.get()
            data["record"] = self.record_var.get()
            
            with open(sitemap_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                
            self.append_log(f"[GUI] 💾 已為地圖 [{os.path.basename(sitemap_path)}] 存檔目前所有設定項目！\n")
        except Exception as e:
            self.append_log(f"[GUI] ⚠️ 儲存地圖設定時發生錯誤: {e}\n")

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

        # 檢查是否選擇了地圖檔案
        sitemap_sel = self.sitemap_combo.get()
        if not sitemap_sel or sitemap_sel.startswith("None") or sitemap_sel.strip() == "":
            messagebox.showwarning("警告", "請先選擇或新增專案網站地圖！")
            return
        
        # 解析主要任務與選單 (Main Task Selection)
        main_task_sel = self.main_task_combo.get()
        wcag_sel = self.wcag_combo.get()
        wcag_val = None
        verify_sitemap = False
        
        if "靜態全站" in main_task_sel:
            wcag_val = "ALL"
        elif "動態單頁" in main_task_sel:
            # 支援設置小節，從 wcag_combo 中取出前綴 (例如 DYNAMIC_ALL, 2.1 等)
            wcag_sel_prefix = wcag_sel.split(" ")[0].strip()
            if wcag_sel_prefix and not wcag_sel_prefix.startswith("None"):
                wcag_val = wcag_sel_prefix
            else:
                wcag_val = "DYNAMIC_ALL"
        elif "探索" in main_task_sel or "Explore" in main_task_sel or "Initialize" in main_task_sel:
            verify_sitemap = True
            if not task:
                task = "探索與初始化網站地圖"

        # 解析單頁路徑與網址組合 (如果是動態單頁無障礙檢測)
        is_page_unit = "動態單頁" in main_task_sel
        if is_page_unit:
            page_path = self.page_entry.get().strip()
            if page_path:
                import urllib.parse
                url = urllib.parse.urljoin(url, page_path)

        # 解析 Sitemap 選項
        sitemap_sel = self.sitemap_combo.get()
        use_sitemap = False
        sitemap_file = None
        
        # 不論是全站還是單頁，只要選取了有效的地圖，就代入 sitemap_file 參數供報告記錄
        if sitemap_sel and not sitemap_sel.startswith("None"):
            use_sitemap = True
            sitemap_file = os.path.join("sitemaps", sitemap_sel)
        elif verify_sitemap:
            # 若進行地圖校對但未選取特定檔案，預設自動搜尋並使用最新的地圖檔
            sitemaps_dir = os.path.join(os.getcwd(), "sitemaps")
            if os.path.exists(sitemaps_dir):
                files = [f for f in os.listdir(sitemaps_dir) if f.endswith(".json")]
                if files:
                    files.sort(key=lambda x: os.path.getmtime(os.path.join(sitemaps_dir, x)), reverse=True)
                    sitemap_sel = files[0]
                    use_sitemap = True
                    sitemap_file = os.path.join("sitemaps", sitemap_sel)

        # 若為靜態全站巡檢，必須選擇 Sitemap 地圖檔以供全量遍歷
        if "靜態全站" in main_task_sel and not sitemap_file:
            messagebox.showwarning("警告", "『靜態全站無障礙檢測』為全站掃描，請先選擇或新增專案網站地圖！")
            return

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
        
        if not task and not verify_sitemap:
            messagebox.showwarning("警告", "請輸入檢測任務描述或選擇主要任務！")
            return

        # 收集登入憑證
        username_val = self.username_entry.get().strip()
        password_val = self.password_entry.get().strip()

        # 切換 UI 狀態為執行中
        self.is_running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.toggle_widgets_state(False)
        
        # 開始後自動切換至「實時 CMD 終端」頁籤 (tab 0)
        self.notebook.select(0)
        
        # 啟動載入動畫並更新顏色
        self.loader_label.config(fg=ACCENT_COLOR)
        self.spinner.start()
        self.loader_text_index = 0
        self.dot_count = 0
        self.update_loader_text()
        
        self.clear_terminal()
        
        self.append_log(f"[GUI] 準備執行 Playwright AI 巡檢任務...\n")
        self.append_log(f"  - 模型: {model_val}\n")
        self.append_log(f"  - 目標 URL: {url}\n")
        if verify_sitemap:
            self.append_log(f"  - 任務類型: 🗺️ 探索與初始化網站地圖 (--verify-sitemap)\n")
            self.append_log(f"  - 目標地圖: {sitemap_sel if use_sitemap else '自動創建'} (若不存在則自動創建)\n")
        else:
            self.append_log(f"  - WCAG 指南: {wcag_val if wcag_val else 'None'}\n")
            self.append_log(f"  - 網站地圖: {sitemap_sel if use_sitemap else 'None'}\n")
        self.append_log(f"  - 視窗模擬: {device_val}\n")
        self.append_log(f"  - 無頭模式: {headless}\n")
        self.append_log(f"  - 儲存記錄: {record}\n")
        self.append_log(f"{'='*60}\n\n")

        # 決定要存檔設定的地圖路徑
        current_sitemap_name = self.sitemap_combo.get().strip()
        save_sitemap_path = None
        if current_sitemap_name and not current_sitemap_name.startswith("None"):
            save_sitemap_path = os.path.join("sitemaps", current_sitemap_name)
            
        if save_sitemap_path:
            self.save_sitemap_config(save_sitemap_path)

        # 啟動背景執行緒跑 Python 程序
        thread = threading.Thread(
            target=self.run_subprocess_worker, 
            args=(task, url, wcag_val, model_val, device_val, turns_val, headless, record, sitemap_file, verify_sitemap, username_val, password_val, is_page_unit)
        )
        thread.daemon = True
        thread.start()

    def run_subprocess_worker(self, task, url, wcag, model, device, max_turns, headless, record, sitemap_file=None, verify_sitemap=False, username=None, password=None, single_page=False):
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
        if verify_sitemap:
            cmd.append("--verify-sitemap")
        if sitemap_file:
            cmd.extend(["--sitemap", sitemap_file])
        if single_page:
            cmd.append("--single-page")
        if username:
            cmd.extend(["--username", username])
        if password:
            cmd.extend(["--password", password])
            
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
        self.toggle_widgets_state(True)
        # 停止加載動畫，並重設提示文字為就緒狀態
        self.spinner.stop()
        self.loader_label.config(text="🤖 系統就緒，等待任務...", fg="#858585")
        # 自動刷新已存在的地圖檔案下拉選單
        self.refresh_sitemaps_list()

    def toggle_widgets_state(self, state):
        """啟用/禁用左側設定面板中所有的輸入與選單組件 (防錯手防呆策略)"""
        tk_state = tk.NORMAL if state else tk.DISABLED
        combo_state = "readonly" if state else "disabled"
        text_state = tk.NORMAL if state else tk.DISABLED
        
        self.main_task_combo.config(state=combo_state)
        self.task_entry.config(state=text_state)
        self.url_entry.config(state=tk_state)
        self.page_entry.config(state=tk_state)
        self.username_entry.config(state=tk_state)
        self.password_entry.config(state=tk_state)
        self.eye_btn.config(state=tk_state)
        
        # sitemap_combo
        self.sitemap_combo.config(state=combo_state)
        
        # wcag_combo
        if state:
            sel = self.main_task_combo.get()
            if "靜態全站" in sel or "探索" in sel or sel.startswith("請選擇"):
                self.wcag_combo.config(state="disabled")
            else:
                self.wcag_combo.config(state="readonly")
            self.update_model_combo_state()
        else:
            self.wcag_combo.config(state="disabled")
            self.model_combo.config(state="disabled")
            
        self.custom_model_cb.config(state=tk_state)
        self.custom_model_entry.config(state=tk_state)
        self.device_combo.config(state=combo_state)
        self.turns_spin.config(state=tk_state)

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
