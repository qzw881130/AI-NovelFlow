"""JSON 解析工具 - 统一解析 LLM 返回的 JSON 内容"""
import json
import re
from typing import Any, Dict, Optional


def parse_llm_json(content: str) -> Dict[str, Any]:
    """
    统一解析 LLM 返回的 JSON 内容
    
    处理以下格式:
    1. 纯 JSON 对象
    2. 包含在 <think/> 标签中的 JSON
    3. Markdown 代码块中的 JSON
    4. 混合文本中的 JSON 对象
    
    Args:
        content: LLM 返回的原始内容
        
    Returns:
        解析后的字典
        
    Raises:
        json.JSONDecodeError: 无法解析为 JSON 时抛出
    """
    if not content:
        raise json.JSONDecodeError("Empty content", content, 0)
    
    text = content.strip()
    
    # 1. 处理 <think/> 或 <think /> 标签
    if "<think" in text:
        # 匹配 <think...>...</think*> 或 <think/>
        text = re.sub(r'<think[^>]*>.*?</think\s*>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = text.strip()
    
    # 2. 处理 Markdown 代码块
    if "```json" in text:
        # 提取 ```json ... ``` 中的内容
        match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if match:
            text = match.group(1).strip()
    elif "```" in text:
        # 提取 ``` ... ``` 中的内容
        match = re.search(r'```\s*([\s\S]*?)\s*```', text)
        if match:
            text = match.group(1).strip()
    
    # 3. 尝试直接解析
    if text.startswith("{") and text.endswith("}"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    
    # 4. 提取第一个 JSON 对象
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        json_str = match.group()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    # 5. 最后尝试直接解析原始内容
    return json.loads(text)


def safe_parse_llm_json(content: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    安全解析 LLM JSON，失败时返回默认值而非抛出异常
    
    Args:
        content: LLM 返回的原始内容
        default: 解析失败时返回的默认值
        
    Returns:
        解析后的字典，或默认值
    """
    if default is None:
        default = {}
    
    try:
        return parse_llm_json(content)
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        print(f"[JSON Parser] Parse failed: {e}")
        return default


def extract_json_objects(content: str) -> list:
    """
    从文本中提取所有 JSON 对象
    
    Args:
        content: 可能包含多个 JSON 对象的文本
        
    Returns:
        解析后的字典列表
    """
    results = []
    
    # 处理 think 标签
    if "<think" in content:
        content = re.sub(r'<think[^>]*>.*?</think\s*>', '', content, flags=re.DOTALL | re.IGNORECASE)
    
    # 查找所有 JSON 对象
    brace_count = 0
    start = None
    
    for i, char in enumerate(content):
        if char == '{':
            if brace_count == 0:
                start = i
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0 and start is not None:
                json_str = content[start:i+1]
                try:
                    results.append(json.loads(json_str))
                except json.JSONDecodeError:
                    pass
                start = None
    
    return results
