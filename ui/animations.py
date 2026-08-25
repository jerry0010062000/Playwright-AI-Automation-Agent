"""
ASACC UI Animations Module
Contains ASCII 3D Donut and Doom Fire rendering widgets for loading states.
"""

import math
import random
import tkinter as tk
from ui.theme import PANEL_BG


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
