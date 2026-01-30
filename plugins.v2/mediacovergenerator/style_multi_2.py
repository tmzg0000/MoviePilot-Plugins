import base64
from collections import Counter
import io
from pathlib import Path
from PIL import Image, ImageFilter, ImageDraw, ImageFont, ImageOps
import numpy as np
import os
import math
import random
import textwrap
from app.log import logger

# 配置：使用超大画布(3200x3200)逻辑
POSTER_GEN_CONFIG = {
    "CANVAS_WIDTH": 1920,
    "CANVAS_HEIGHT": 1080,
    "CELL_WIDTH": 420,  # 单张海报宽
    "CELL_HEIGHT": 630,  # 单张海报高
    "MARGIN_X": 40,  # 水平间距
    "MARGIN_Y": 40,  # 垂直间距
    "ROTATION": -20,  # 整体旋转角度
    "CORNER_RADIUS": 25,  # 圆角
}


def add_shadow(img, offset=(10, 10), shadow_color=(0, 0, 0, 140), blur_radius=15):
    """为单张图片添加阴影"""
    shadow_width = img.width + abs(offset[0]) + blur_radius * 2
    shadow_height = img.height + abs(offset[1]) + blur_radius * 2

    # 创建大一点的画布放阴影
    shadow_layer = Image.new("RGBA", (shadow_width, shadow_height), (0, 0, 0, 0))

    # 绘制阴影实体
    shadow_box = Image.new("RGBA", img.size, shadow_color)
    shadow_x = blur_radius + max(0, offset[0])
    shadow_y = blur_radius + max(0, offset[1])
    shadow_layer.paste(shadow_box, (shadow_x, shadow_y))

    # 模糊阴影
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur_radius))

    # 贴上原图
    img_x = blur_radius + max(0, -offset[0])
    img_y = blur_radius + max(0, -offset[1])
    shadow_layer.paste(img, (img_x, img_y), img if img.mode == "RGBA" else None)

    return shadow_layer


def add_film_grain(image, intensity=0.03):
    """添加胶片颗粒感"""
    if image.mode != 'RGBA' and image.mode != 'RGB':
        image = image.convert('RGBA')
    img_array = np.array(image, dtype=np.float32)
    noise = np.random.normal(0, 255 * intensity, img_array.shape)
    img_array = np.clip(img_array + noise, 0, 255)
    return Image.fromarray(img_array.astype(np.uint8), image.mode)


def create_blur_background(image_path, width, height):
    """创建模糊底图"""
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            img = ImageOps.fit(img, (width, height), method=Image.Resampling.LANCZOS)
            # 背景模糊一点，避免抢眼
            return img.filter(ImageFilter.GaussianBlur(80))
    except:
        return Image.new("RGB", (width, height), (240, 240, 240))


def create_style_multi_2(library_dir, title, font_path, font_size=(1, 1)):
    """
    风格2：全屏倾斜海报墙 + 居中标题 + 黑色加粗描边文字
    """
    try:
        # 1. 基础参数
        zh_font_size_ratio, en_font_size_ratio = font_size
        zh_font_path, en_font_path = font_path
        title_zh, title_en = title

        cw = POSTER_GEN_CONFIG["CANVAS_WIDTH"]
        ch = POSTER_GEN_CONFIG["CANVAS_HEIGHT"]

        poster_folder = Path(library_dir)
        supported_formats = (".jpg", ".jpeg", ".png", ".webp")
        poster_files = [os.path.join(poster_folder, f) for f in os.listdir(poster_folder)
                        if f.lower().endswith(supported_formats)]
        poster_files.sort()

        if not poster_files: return False

        # 2. 计算大画布尺寸 (3200x3200)
        big_w, big_h = 3200, 3200
        big_canvas = Image.new("RGBA", (big_w, big_h), (0, 0, 0, 0))

        cell_w = POSTER_GEN_CONFIG["CELL_WIDTH"]
        cell_h = POSTER_GEN_CONFIG["CELL_HEIGHT"]
        margin_x = POSTER_GEN_CONFIG["MARGIN_X"]
        margin_y = POSTER_GEN_CONFIG["MARGIN_Y"]

        # 计算行列数
        cols = math.ceil(big_w / (cell_w + margin_x)) + 1
        rows = math.ceil(big_h / (cell_h + margin_y)) + 1

        # 扩展素材
        total_slots = cols * rows
        extended_posters = poster_files * (math.ceil(total_slots / len(poster_files)) + 1)

        # 3. 绘制平铺海报
        idx = 0
        grid_width = cols * (cell_w + margin_x)
        grid_height = rows * (cell_h + margin_y)
        start_x = (big_w - grid_width) // 2
        start_y = (big_h - grid_height) // 2

        for r in range(rows):
            for c in range(cols):
                try:
                    p_path = extended_posters[idx]
                    idx += 1

                    with Image.open(p_path) as img:
                        img_resized = ImageOps.fit(img, (cell_w, cell_h), method=Image.Resampling.LANCZOS)

                        # 圆角
                        if POSTER_GEN_CONFIG["CORNER_RADIUS"] > 0:
                            mask = Image.new("L", (cell_w, cell_h), 0)
                            ImageDraw.Draw(mask).rounded_rectangle(
                                [(0, 0), (cell_w, cell_h)],
                                radius=POSTER_GEN_CONFIG["CORNER_RADIUS"],
                                fill=255
                            )
                            img_rgba = img_resized.convert("RGBA")
                            img_rgba.putalpha(mask)
                            img_resized = img_rgba

                        # 添加阴影
                        final_piece = add_shadow(img_resized, offset=(8, 8), blur_radius=12)

                        # 计算位置：整齐网格
                        x = start_x + c * (cell_w + margin_x)
                        y = start_y + r * (cell_h + margin_y)

                        big_canvas.paste(final_piece, (x, y), final_piece)

                except Exception as e:
                    continue

        # 4. 整体旋转
        rotated_big = big_canvas.rotate(POSTER_GEN_CONFIG["ROTATION"], resample=Image.Resampling.BICUBIC)

        # 5. 裁剪中心区域
        final_canvas = create_blur_background(poster_files[0], cw, ch).convert("RGBA")

        center_x = big_w // 2
        center_y = big_h // 2
        left = center_x - cw // 2
        top = center_y - ch // 2

        crop_img = rotated_big.crop((left, top, left + cw, top + ch))
        final_canvas.paste(crop_img, (0, 0), crop_img)

        # 7. 添加噪点
        final_canvas = add_film_grain(final_canvas, intensity=0.04)

        # 8. 绘制文字 (居中 + 黑色加粗描边)
        draw = ImageDraw.Draw(final_canvas)

        # 字体
        zh_size = int(140 * float(zh_font_size_ratio))
        zh_font = ImageFont.truetype(zh_font_path, zh_size)

        en_size = int(60 * float(en_font_size_ratio))
        en_font = ImageFont.truetype(en_font_path, en_size)

        # 换行逻辑
        zh_lines = textwrap.wrap(title_zh, width=12)
        if title_en:
            en_lines = textwrap.wrap(title_en, width=40, break_long_words=False)
        else:
            en_lines = []

        # 计算尺寸
        line_spacing = 20
        total_text_height = 0
        text_blocks = []

        for line in zh_lines:
            bbox = draw.textbbox((0, 0), line, font=zh_font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            text_blocks.append((line, zh_font, w, h))
            total_text_height += h + line_spacing

        for line in en_lines:
            bbox = draw.textbbox((0, 0), line, font=en_font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            text_blocks.append((line, en_font, w, h))
            total_text_height += h + line_spacing

        if text_blocks: total_text_height -= line_spacing

        cur_y = (ch - total_text_height) // 2

        # 核心修改：使用 stroke_width 实现加粗描边
        # stroke_width=10 为描边宽度，可以根据需要调整(建议8-20)
        stroke_width = 15
        stroke_color = (0, 0, 0, 255)  # 纯黑描边

        for text, font, w, h in text_blocks:
            draw.text(
                ((cw - w) // 2, cur_y),
                text,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke_width,
                stroke_fill=stroke_color
            )
            cur_y += h + line_spacing

        # 9. 输出
        buffer = io.BytesIO()
        final_rgb = final_canvas.convert("RGB")
        final_rgb.save(buffer, format="WEBP", quality=85, optimize=True)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

    except Exception as e:
        logger.error(f"Style Multi 2 Error: {e}")
        return False