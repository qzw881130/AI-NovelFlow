"""
text_utils 单元测试
"""
import pytest
from app.utils.text_utils import detect_encoding, chinese_to_int, parse_chapters_from_text


class TestDetectEncoding:
    def test_utf8_encoding(self):
        text = "你好世界".encode('utf-8')
        assert detect_encoding(text) == 'utf-8'

    def test_gbk_encoding(self):
        text = "你好世界".encode('gbk')
        assert detect_encoding(text) == 'gbk'

    def test_empty_bytes(self):
        assert detect_encoding(b'') == 'utf-8'

    def test_ascii_text(self):
        text = b"Hello World"
        assert detect_encoding(text) == 'utf-8'

    def test_utf8_with_bom(self):
        text = b'\xef\xbb\xbf\xe4\xbd\xa0\xe5\xa5\xbd'
        assert detect_encoding(text) == 'utf-8'


class TestChineseToInt:
    def test_arabic_number(self):
        assert chinese_to_int('123') == 123

    def test_single_digit(self):
        assert chinese_to_int('一') == 1
        assert chinese_to_int('九') == 9

    def test_teens(self):
        assert chinese_to_int('十一') == 11
        assert chinese_to_int('十九') == 19

    def test_hundreds(self):
        assert chinese_to_int('一百') == 100
        assert chinese_to_int('一百二十三') == 123

    def test_thousands(self):
        assert chinese_to_int('一千') == 1000
        assert chinese_to_int('一千零一') == 1001

    def test_ten_thousands(self):
        assert chinese_to_int('一万') == 10000
        assert chinese_to_int('一千零二十一') == 1021

    def test_zero(self):
        assert chinese_to_int('零') is None

    def test_invalid_input(self):
        assert chinese_to_int('abc') is None
        assert chinese_to_int('') is None
        assert chinese_to_int('第章') is None

    def test_mixed_invalid(self):
        assert chinese_to_int('十一abc') is None


class TestParseChaptersFromText:
    def test_chinese_format_arabic(self):
        text = "第1章 重生之始\n这是内容\n第2章 初露锋芒\n更多内容"
        chapters, errors = parse_chapters_from_text(text)
        assert len(chapters) == 2
        assert chapters[0]['number'] == 1
        assert chapters[0]['title'] == "第1章 重生之始"
        assert chapters[0]['content'] == "这是内容"
        assert chapters[1]['number'] == 2
        assert chapters[1]['title'] == "第2章 初露锋芒"
        assert chapters[1]['content'] == "更多内容"

    def test_chinese_format_chinese_number(self):
        text = "第一百二十三章 最终决战\n决战内容"
        chapters, errors = parse_chapters_from_text(text)
        assert len(chapters) == 1
        assert chapters[0]['number'] == 123

    def test_english_format_with_colon(self):
        text = "Chapter 1: The Beginning\nStory content here\nChapter 5: The Battle\nBattle scene"
        chapters, errors = parse_chapters_from_text(text)
        assert len(chapters) == 2
        assert chapters[0]['number'] == 1
        assert chapters[1]['number'] == 5
        assert "The Beginning" in chapters[0]['title']

    def test_english_format_no_colon(self):
        text = "Chapter 10 Return Home\nGoing back"
        chapters, errors = parse_chapters_from_text(text)
        assert len(chapters) == 1
        assert chapters[0]['number'] == 10

    def test_mixed_format(self):
        text = "第1章 开始\ncontent1\nChapter 2: The Journey\njourney content"
        chapters, errors = parse_chapters_from_text(text)
        assert len(chapters) == 2
        assert chapters[0]['number'] == 1
        assert chapters[1]['number'] == 2

    def test_no_chapter_titles(self):
        text = "这是一段没有章节标题的文本\n随便写的内容"
        chapters, errors = parse_chapters_from_text(text)
        assert len(chapters) == 0
        assert len(errors) > 0
        assert errors[0]['reason'] == '无法识别章节标题'

    def test_empty_text(self):
        chapters, errors = parse_chapters_from_text("")
        assert len(chapters) == 0
        assert len(errors) == 0

    def test_empty_chapter_content(self):
        text = "第1章 空章节\n第2章 有内容\n这里是第二章的具体内容描述"
        chapters, errors = parse_chapters_from_text(text)
        assert len(chapters) == 1
        assert chapters[0]['number'] == 2
        assert len(errors) == 1
        assert errors[0]['reason'] == '章节内容为空'

    def test_content_after_last_chapter(self):
        text = "第1章 标题\n章节内容\n最后一行内容"
        chapters, errors = parse_chapters_from_text(text)
        assert len(chapters) == 1
        assert "最后一行内容" in chapters[0]['content']

    def test_whitespace_handling(self):
        text = "第1章  多余空格\n内容\n  第2章  前导空格  \n内容2"
        chapters, errors = parse_chapters_from_text(text)
        assert len(chapters) == 2
