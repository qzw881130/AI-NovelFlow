"""
文本解析工具

提供编码检测、章节解析、中文数字转换功能，用于批量导入章节。
"""
import re
from typing import Tuple, List, Dict, Optional

# 中文数字映射表
_CN_NUMS = {
    '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
    '十': 10, '百': 100, '千': 1000, '万': 10000
}


def detect_encoding(raw_bytes: bytes) -> str:
    """检测文本编码，优先 UTF-8，失败回退 GBK。"""
    try:
        raw_bytes.decode('utf-8')
        return 'utf-8'
    except (UnicodeDecodeError, ValueError):
        return 'gbk'


def chinese_to_int(text: str) -> Optional[int]:
    """
    中文数字转阿拉伯数字。

    支持阿拉伯数字直接返回，中文数字（零一二三四五六七八九十百千万）组合转换。
    覆盖：十一、十九、一百二十三、一千零一、一万 等。
    """
    if not text:
        return None

    # 纯阿拉伯数字直接返回
    if text.isdigit():
        return int(text)

    # 中文数字解析
    result = 0
    current = 0
    for ch in text:
        val = _CN_NUMS.get(ch)
        if val is None:
            return None
        if val >= 10:
            if current == 0:
                current = 1
            result += current * val
            current = 0
        else:
            current += val
    result += current
    return result if result > 0 else None


# 匹配: 第X章 标题 或 Chapter X: 标题
# group(1)/(2): 中文格式的章节号和标题剩余部分
# group(3)/(4): 英文格式的章节号和标题剩余部分
CHAPTER_RE = re.compile(
    r'^(?:'
    r'第([\d零一二三四五六七八九十百千万]+)章\s*(.*)'
    r'|'
    r'Chapter\s+(\d+)\s*:?\s*(.*)'
    r')$'
)


def parse_chapters_from_text(text: str) -> Tuple[List[Dict], List[Dict]]:
    """
    解析文本为章节列表。

    Returns:
        (chapters, errors)
        chapters: [{"number": int, "title": str, "content": str}, ...]
        errors: [{"segment": int, "title": str, "reason": str}, ...]
    """
    lines = text.splitlines()
    chapters: List[Dict] = []
    errors: List[Dict] = []
    current: Optional[Dict] = None
    segment_idx = 0

    for line in lines:
        match = CHAPTER_RE.match(line.strip())
        if match:
            # 保存上一个章节
            if current is not None:
                content = '\n'.join(current['content_lines']).strip()
                if content:
                    chapters.append({
                        'number': current['number'],
                        'title': current['title'],
                        'content': content,
                    })
                else:
                    errors.append({
                        'segment': segment_idx,
                        'title': current['title'],
                        'reason': '章节内容为空',
                    })

            # 提取新章节信息
            if match.group(1) is not None:  # 中文格式
                num = chinese_to_int(match.group(1))
                title_rest = match.group(2).strip()
                title = f"第{match.group(1)}章 {title_rest}".strip()
            else:  # 英文格式
                num = int(match.group(3))
                title_rest = match.group(4).strip()
                title = f"Chapter {match.group(3)}: {title_rest}".strip() if title_rest else f"Chapter {match.group(3)}"

            if num is None:
                errors.append({
                    'segment': segment_idx,
                    'title': line.strip(),
                    'reason': '章节号解析失败',
                })
                current = None
                continue

            segment_idx += 1
            current = {'number': num, 'title': title, 'content_lines': []}
        else:
            if current is not None:
                current['content_lines'].append(line)
            else:
                # 文件开头无章节标题的文本
                if line.strip():
                    errors.append({
                        'segment': segment_idx,
                        'title': '未知',
                        'reason': '无法识别章节标题',
                    })
                    segment_idx += 1

    # 保存最后一个章节
    if current is not None:
        content = '\n'.join(current['content_lines']).strip()
        if content:
            chapters.append({
                'number': current['number'],
                'title': current['title'],
                'content': content,
            })
        else:
            errors.append({
                'segment': segment_idx,
                'title': current['title'],
                'reason': '章节内容为空',
            })

    return chapters, errors
