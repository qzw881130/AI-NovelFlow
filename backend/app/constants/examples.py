"""内置示例目录。章节正文直接复用原有预设数据。"""
from app.constants.test_case import (
    XIAOMA_CHAPTERS, XIAOMA_NOVEL_CONFIG,
    REDRIDINGHOOD_CHAPTERS, REDRIDINGHOOD_NOVEL_CONFIG,
    EMPEROR_CHAPTERS, EMPEROR_NOVEL_CONFIG,
)

EXAMPLES = {
    "xiaoma": {
        "title": XIAOMA_NOVEL_CONFIG["title"],
        "category": "经典童话",
        "description": "小马在老牛与松鼠不同的回答中学会亲自尝试，勇敢渡河。",
        "chapters": XIAOMA_CHAPTERS,
    },
    "red-riding-hood": {
        "title": REDRIDINGHOOD_NOVEL_CONFIG["title"],
        "category": "格林童话",
        "description": "小红帽穿过森林探望外婆，遇到大灰狼，最终得到猎人帮助。",
        "chapters": REDRIDINGHOOD_CHAPTERS,
    },
    "emperor": {
        "title": EMPEROR_NOVEL_CONFIG["title"],
        "category": "安徒生童话",
        "description": "爱穿新衣的皇帝受骗子蒙蔽，游行时被孩子说出真相。",
        "chapters": EMPEROR_CHAPTERS,
    },
}
