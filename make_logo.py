# -*- coding: utf-8 -*-
"""生成项目 Logo：深色底 + 四角色色圆 + 对话气泡，1024x1024 PNG。"""
from PIL import Image, ImageDraw, ImageFont
import os

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 圆角方形底色（深蓝灰）
BG = "#1E293B"
radius = 180
d.rounded_rectangle([0, 0, S - 1, S - 1], radius=radius, fill=BG)

# 四个角色代表色
COLORS = ["#2D7DFF", "#FF7A2D", "#2EA84B", "#9B59D0"]  # 经理/策划/工程师/评审
# 四叶草布局：上 左 右 下
POSITIONS = [(512, 210), (272, 470), (752, 470), (512, 730)]
R = 158  # 圆半径

# 先画四个圆（带一点内阴影效果：偏移画深色底圆再画主色圆）
for (cx, cy), col in zip(POSITIONS, COLORS):
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill="#0F172A")          # 阴影
    d.ellipse([cx - R + 8, cy - R + 8, cx + R + 8, cy + R + 8], fill=col)  # 高光偏移主圆

# 中间覆盖一个小一点的四色圆环/中央元素：对话气泡
bubble_col = "#FFFFFF"
# 气泡主体（居中偏上）
bw, bh = 380, 250
bx0, by0 = (S - bw) // 2, (S - bh) // 2 - 40
d.rounded_rectangle([bx0, by0, bx0 + bw, by0 + bh], radius=48, fill=bubble_col)
# 气泡尾巴
d.polygon([(bx0 + 90, by0 + bh), (bx0 + 150, by0 + bh + 70), (bx0 + 210, by0 + bh)], fill=bubble_col)

# 气泡内的三圆点省略号（AI 讨论感）
dot_r = 26
dot_y = by0 + bh // 2
d.ellipse([bx0 + 110 - dot_r, dot_y - dot_r, bx0 + 110 + dot_r, dot_y + dot_r], fill=COLORS[0])
d.ellipse([bx0 + 190 - dot_r, dot_y - dot_r, bx0 + 190 + dot_r, dot_y + dot_r], fill=COLORS[2])
d.ellipse([bx0 + 270 - dot_r, dot_y - dot_r, bx0 + 270 + dot_r, dot_y + dot_r], fill=COLORS[3])

# 底部文字 "AI 团队群聊"
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
img.save(out, "PNG")
print("Logo 已生成:", out, img.size)