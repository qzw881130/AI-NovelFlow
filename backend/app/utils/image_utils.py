"""
图片工具函数

封装图片处理相关的工具函数
"""
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont


def load_chinese_font(size: int) -> ImageFont:
    """
    加载中文字体
    
    Args:
        size: 字体大小
        
    Returns:
        PIL ImageFont 对象
    """
    font_paths = [
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Windows
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    
    for font_path in font_paths:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            continue
    
    return ImageFont.load_default()


def merge_character_images(
    novel_id: str,
    chapter_id: str,
    shot_index: int,
    character_images: List[Tuple[str, str]],
    file_storage
) -> Optional[str]:
    """
    合并多个角色图片为一个参考图
    
    Args:
        novel_id: 小说ID
        chapter_id: 章节ID
        shot_index: 分镜索引
        character_images: [(角色名, 图片路径), ...]
        file_storage: 文件存储服务实例
        
    Returns:
        合并后的图片路径，失败返回 None
    """
    import os
    import glob
    
    if not character_images:
        return None
    
    try:
        # 删除旧的合并角色图
        story_dir = file_storage._get_story_dir(novel_id)
        chapter_short = chapter_id[:8] if chapter_id else "unknown"
        merged_dir = story_dir / f"chapter_{chapter_short}" / "merged_characters"
        if merged_dir.exists():
            old_files = glob.glob(str(merged_dir / f"shot_{shot_index:03d}_*_characters.png"))
            for old_file in old_files:
                try:
                    os.remove(old_file)
                    print(f"[MergeCharacters] Removed old merged character image: {old_file}")
                except Exception as e:
                    print(f"[MergeCharacters] Failed to remove old file {old_file}: {e}")
        
        # 获取角色名列表
        character_names = [name for name, _ in character_images]
        merged_path = file_storage.get_merged_characters_path(novel_id, chapter_id, shot_index, character_names)
        
        # 计算布局
        count = len(character_images)
        if count == 1:
            cols, rows = 1, 1
        elif count <= 3:
            cols, rows = 1, count
        elif count == 4:
            cols, rows = 2, 2
        elif count <= 6:
            cols, rows = 3, 2
        else:
            cols = 3
            rows = (count + 2) // 3
        
        # 加载所有图片
        images = []
        for char_name, img_path in character_images:
            img = Image.open(img_path)
            images.append((char_name, img))
        
        # 设置布局参数
        name_height = 24
        padding = 15
        img_spacing = 10
        text_offset = 5
        
        # 使用原图，不进行缩放
        processed_images = [(char_name, img.copy()) for char_name, img in images]
        
        # 计算每列的最大宽度
        col_widths = []
        for col in range(cols):
            max_w = 0
            for idx in range(col, len(processed_images), cols):
                _, img = processed_images[idx]
                max_w = max(max_w, img.width)
            col_widths.append(max_w)
        
        # 计算每行的实际高度
        row_heights = []
        for row in range(rows):
            max_h = 0
            for idx in range(row * cols, min((row + 1) * cols, len(processed_images))):
                _, img = processed_images[idx]
                max_h = max(max_h, img.height)
            row_heights.append(max_h + name_height + text_offset)
        
        # 计算画布尺寸
        canvas_width = sum(col_widths) + (cols - 1) * img_spacing + 2 * padding
        canvas_height = sum(row_heights) + 2 * padding
        canvas = Image.new('RGB', (canvas_width, canvas_height), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        
        # 加载字体
        font = load_chinese_font(16)
        
        # 绘制每个角色
        current_y = padding
        for idx, (char_name, img) in enumerate(processed_images):
            col = idx % cols
            row = idx // cols
            
            x = padding + sum(col_widths[:col]) + col * img_spacing
            y = current_y
            
            img_x = x + (col_widths[col] - img.width) // 2
            img_y = y + (row_heights[row] - name_height - text_offset - img.height) // 2
            canvas.paste(img, (img_x, img_y))
            
            text_bbox = draw.textbbox((0, 0), char_name, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_x = x + (col_widths[col] - text_width) // 2
            text_y = img_y + img.height + text_offset
            draw.text((text_x, text_y), char_name, fill=(51, 51, 51), font=font)
            
            if col == cols - 1 or idx == len(processed_images) - 1:
                current_y += row_heights[row]
        
        # 保存合并图片
        canvas.save(merged_path, "PNG")
        print(f"[MergeCharacters] Merged character image saved: {merged_path}")
        
        return str(merged_path)
        
    except Exception as e:
        print(f"[MergeCharacters] Failed to merge character images: {e}")
        import traceback
        traceback.print_exc()
        return None
