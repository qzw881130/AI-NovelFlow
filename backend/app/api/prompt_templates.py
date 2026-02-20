from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.models.prompt_template import PromptTemplate

router = APIRouter(tags=["prompt_templates"])


# 系统预设的人设提示词模板（角色生成）
SYSTEM_CHARACTER_TEMPLATES = [
    {
        "name": "标准动漫风格",
        "description": "适合大多数动漫角色的标准人设生成",
        "template": "character portrait, anime style, high quality, detailed, {appearance}, single character, centered, clean background, professional artwork, 8k",
        "style": "anime style, high quality, detailed, professional artwork",
        "type": "character"
    },
    {
        "name": "写实风格",
        "description": "写实风格的角色人设",
        "template": "character portrait, realistic style, photorealistic, highly detailed, {appearance}, single character, centered, professional photography, studio lighting, 8k",
        "style": "realistic style, photorealistic, highly detailed, professional photography",
        "type": "character"
    },
    {
        "name": "Q版卡通",
        "description": "可爱Q版卡通风格",
        "template": "chibi character, cute cartoon style, kawaii, {appearance}, single character, centered, colorful, clean background, professional artwork, 4k",
        "style": "chibi character, cute cartoon style, kawaii, colorful",
        "type": "character"
    },
    {
        "name": "水墨风格",
        "description": "中国传统水墨画风格",
        "template": "character portrait, Chinese ink painting style, traditional art, {appearance}, single character, centered, elegant, artistic, high quality",
        "style": "Chinese ink painting style, traditional art, elegant, artistic",
        "type": "character"
    }
]

# 系统预设的章节拆分提示词模板
SYSTEM_CHAPTER_SPLIT_TEMPLATES = [
    {
        "name": "标准分镜拆分",
        "description": "适用于大多数小说的标准分镜拆分",
        "template": """你是一名资深电影导演、分镜设计师、动画脚本结构专家。

任务：
将用户提供的小说章节内容，拆分为适用于AI动画制作的分镜数据结构，采用电影级分镜语言，可同时用于生图与图生视频（如 LTX-2）。

━━━━━━━━━━━━━━━━━━
核心要求
━━━━━━━━━━━━━━━━━━

1. 严格按照影视镜头语言拆分
2. 每个分镜必须包含：
   - description（用于生图的静态构图描述）
   - video_description（用于图生视频的动态时间描述，且必须包含台词或明确标注无台词）
3. description 必须包含：
   - Scene（场景环境 + 光线 + 摄影机）
   - Characters（逐个角色锁定形象 + 服装关键词 + 当前动作）
   - Action（一句话总结镜头主行为）
4. video_description 必须包含：
   - Character Constraints（人物一致性锁定）
   - Motion Timeline（时间展开式动作）
   - Dialogue（spoken, no on-screen text：逐字保留原文台词；无台词必须写 NONE）
5. description 长度控制在 100–160 字
6. video_description 长度控制在 90–180 字（包含 Dialogue 段或 NONE）
7. 所有视觉描述必须符合：##STYLE## style, high quality, detailed
8. 不允许普通叙事句
9. 不允许心理描写
10. 不允许解释性文字
11. 输出必须是纯 JSON
12. 不允许 Markdown

━━━━━━━━━━━━━━━━━━
description 强制结构模板
━━━━━━━━━━━━━━━━━━

description 必须输出为单个字符串，并且必须包含如下换行结构（使用 \\n）：

"Scene: ...\\nCharacters:\\n- 角色A: ...\\n- 角色B: ...\\nAction: ..."

模板：
Scene: {中文场景环境句子}, {光线描述}, {镜头类型与机位描述}, ##STYLE## style, high quality, detailed。
Characters:
- {角色名1}: 保持参考人设的面部、发型、体型比例与服装轮廓不变; {宋代/对应时代服饰关键词}; {当前镜头动作}.
- {角色名2}: 保持参考人设的面部、发型、体型比例与服装轮廓不变; {宋代/对应时代服饰关键词}; {当前镜头动作}.
Action: {一句话概括主要角色正在发生的动作行为}。

说明：
- 必须完整包含 Scene / Characters / Action 三部分
- 不得缺失任何部分
- description 中严禁出现任何台词文字或引号内容
- description 的每一部分必须分行，不得写在同一行

━━━━━━━━━━━━━━━━━━
video_description 强制结构（LTX-2 优化版，含台词）
━━━━━━━━━━━━━━━━━━

video_description 必须严格输出为单个字符串，并且必须包含如下换行结构（使用 \\n）：

"Character Constraints:\\n- 角色A: ...\\n- 角色B: ...\\nMotion: ...\\nDialogue (spoken, no on-screen text): ..."

模板：
Character Constraints:
- {角色名1}: 保持参考人设的面部、发型、体型比例与服装轮廓不变; 保持{服饰关键词}; 不得改变年龄、体型与身份。
- {角色名2}: 保持参考人设的面部、发型、体型比例与服装轮廓不变; 保持{服饰关键词}; 不得改变年龄、体型与身份。
Motion:
{时间展开式动作描述，必须包含：起始状态 → 动作过程 → 镜头运动 → 结束状态}
Dialogue (spoken, no on-screen text):
- {说话角色名}: "{必须逐字复制原文台词}"
（若该镜头无原文直接引语，则必须改为：Dialogue (spoken, no on-screen text): NONE，且不得输出任何 "- 角色名: ..." 行）

━━━━━━━━━━━━━━━━━━
【字符串换行与排版硬约束（必须执行）】
━━━━━━━━━━━━━━━━━━

1) description 与 video_description 必须使用换行符 "\\n" 进行分段排版（JSON 字符串中必须显式包含 \\n）。
2) 必须严格按以下行结构输出（每一行之间用 \\n 分隔）：

description 行结构必须为：
"Scene: ...\\nCharacters:\\n- 角色A: ...\\n- 角色B: ...\\nAction: ..."

video_description 行结构必须为：
"Character Constraints:\\n- 角色A: ...\\n- 角色B: ...\\nMotion: ...\\nDialogue (spoken, no on-screen text): ..."

3) 禁止把 Character Constraints / Motion / Dialogue 写在同一行；必须逐段换行。
4) 列表项必须每个角色独占一行，并以 "- " 开头（例如 "\\n- 曹操: ..."）。
5) 若 Dialogue 为 NONE，也必须独占一行：
"Dialogue (spoken, no on-screen text): NONE"

━━━━━━━━━━━━━━━━━━
video_description 动作约束规则
━━━━━━━━━━━━━━━━━━

1. 必须使用时间展开语言：缓慢 / 逐渐 / 开始 / 随后 / 最终 等
2. 必须描述起始状态
3. 必须描述动作连续过程
4. 若涉及物理变化（重量、位移、水面变化等）必须写清变化过程
5. 必须写明镜头运动方式：固定镜头 / 缓慢推进 / 轻微平移 / 稳定跟随
6. 动作数量不超过2个连续行为（避免视频崩坏）
7. 禁止新增角色
8. 禁止新增剧情
9. 禁止加入画面文字（任何字幕/标题/屏幕文字叠加均禁止）
10. 禁止改变人物形象
11. 禁止改变服装
12. 禁止改变人物体型比例
13. Motion 中禁止出现心理词（如：若有所思/感到/心想/沉思）；必须改为可见表情或动作（如：眉头微皱/目光停留/嘴角上扬）。

━━━━━━━━━━━━━━━━━━
【video_description 台词强制规则（逐字保留原文，禁止空台词）】
━━━━━━━━━━━━━━━━━━

1) Dialogue 段只允许收录原文中明确出现的直接引语（例如：他说："……"），必须逐字复制（含原标点与引号内文字），不得改写、润色、缩写、扩写，禁止新增台词。
2) Dialogue 段每个镜头最多 2 句；超过 2 句必须拆镜头分别承载。
3) Dialogue 段只表示"口播/对白 (spoken)"，严禁描述为画面文字：不得出现"字幕/文字叠加/屏幕出现文字/标题条"等表述。
4) 台词只能出现在 video_description 的 Dialogue 段：
   - description 中严禁出现任何台词文字或引号内容
   - video_description 的 Character Constraints 与 Motion 中也严禁出现台词文字或引号内容
5) Dialogue 的 speaker 必须来自 allowed_characters；若原文未点名说话人，必须依据上下文判定最可能说话角色且仍需在白名单内。
6) 禁止使用"某人/众人/人群"等泛称作为 speaker；必须映射为白名单内具体编号角色（如 群臣1、侍从1、围观者1）。
7) 严禁输出空台词：禁止出现 speaker 对应的 line 为空字符串、空引号或仅空白（如 ""、" "、"\\n"）。
8) 仅当原文存在"明确的直接引语"时，才允许输出 Dialogue 行；若该镜头没有任何原文直接引语，则必须写为：
   Dialogue (spoken, no on-screen text): NONE
   （注意：此时不得输出任何 "- 角色名: ..." 的行）
9) 若原文有对白但该镜头不承载对白（对白已拆到前后镜头），则同样必须使用 Dialogue: NONE，禁止随意搬运、重复或伪造台词。
10) 若连续镜头属于对话段落，必须将"有台词镜头"与"无台词反应镜头"分开：
    - 有台词镜头：Dialogue 输出原文台词
    - 反应/动作镜头：Dialogue: NONE
    禁止在反应镜头中补台词或输出空台词。

━━━━━━━━━━━━━━━━━━
分镜规则
━━━━━━━━━━━━━━━━━━

- id：从1递增
- characters：当前镜头出现角色
- scene：当前镜头所在场景
- duration：3-10秒，根据动作复杂度自动判断

角色命名必须全程保持唯一且一致：

- 所有角色名称必须在首次解析时确定为唯一标准名称
- 后续所有镜头必须严格复用该名称
- 若同类型角色存在多个且无真实姓名：
  - 必须使用阿拉伯数字编号（如"骗子1""骗子2""群臣1""围观者1"）
  - 编号按首次出场顺序递增
  - 禁止使用"甲/乙""A/B""其中一人""另一人"等变体
- 一旦名称确定，不得更改、简化或替换

━━━━━━━━━━━━━━━━━━
【角色白名单硬约束（必须执行，100%不越界）】
━━━━━━━━━━━━━━━━━━

你将收到一个 allowed_characters 数组，表示本章允许出现的角色名称列表。

规则：

1) 任何输出字段中出现的角色名必须严格来自 allowed_characters，禁止出现任何不在 allowed_characters 中的角色名。范围包括：
   - shots[].characters
   - description 的 Characters 段落中的角色名
   - video_description 的 Character Constraints 段落中的角色名
   - video_description 的 Dialogue 段落中的 speaker

2) 当正文出现"众人/群臣/士兵/百姓/侍从/随从/围观者/人群"等泛称时：
   - 必须改写为 allowed_characters 中对应的具体角色名（例如：群臣1、群臣2、围观者1、围观者2）。
   - 若 allowed_characters 中没有任何可对应的具体角色名，则该镜头不得使用该泛称；必须改为"远处模糊背景人群/背景剪影"等环境元素，并且不得把背景人群写入 shots[].characters，也不得作为 Dialogue 的 speaker。

3) 严禁新增角色：如果原文出现 allowed_characters 之外的角色，必须：
   - 要么不在镜头中出现该角色（改为背景剪影且不入 characters 列表），
   - 要么将镜头改写为只表现 allowed_characters 的动作与反应（不改变剧情走向）。

4) 输出顶级字段 "characters" 必须是 allowed_characters 的子集（去重），不得包含白名单外角色。

5) 一致性校验（必须执行）：
   - 每个镜头中 shots[].characters 必须与 description 的 Characters 列表、video_description 的 Character Constraints 列表一致（同一组角色，顺序可不同）。
   - 禁止出现 shots[].characters 为空但 description/video_description 列出角色的情况。

━━━━━━━━━━━━━━━━━━
时长规则
━━━━━━━━━━━━━━━━━━

- 静态画面：3-5秒
- 对话画面：5-8秒
- 动作冲突或物理变化：6-10秒

━━━━━━━━━━━━━━━━━━
禁止
━━━━━━━━━━━━━━━━━━

- 不得输出 image_path、image_url、merged_character_image 等字段
- 不得添加额外键
- 不得改变剧情
- 不得合并多个剧情行为到一个镜头
- 不得省略 Scene / Characters / Action 任意一部分
- 不得输出任何解释性文字，只返回JSON

━━━━━━━━━━━━━━━━━━
输出格式必须严格如下
━━━━━━━━━━━━━━━━━━

{{
  "chapter": "第3章 客人",
  "characters": [
    "萧炎",
    "萧战",
    "葛叶"
  ],
  "scenes": [
    "萧家门口",
    "萧家大厅",
    "练武场"
  ],
  "shots": [
    {{
      "id": 1,
      "description": "Scene: ...\\nCharacters:\\n- ...\\nAction: ...",
      "video_description": "Character Constraints:\\n- ...\\nMotion: ...\\nDialogue (spoken, no on-screen text): ...",
      "characters": [
        "萧炎"
      ],
      "scene": "萧家门口",
      "duration": 5
    }}
  ]
}}""",
        "type": "chapter_split"
    },
    {
        "name": "电影风格分镜",
        "description": "电影级分镜拆分，强调画面构图和镜头语言",
        "template": """你是一名资深电影导演、分镜设计师、动画脚本结构专家。

任务：
将用户提供的小说章节内容，拆分为适用于AI动画制作的分镜数据结构，采用电影级分镜语言，可同时用于生图与图生视频（如 LTX-2）。

━━━━━━━━━━━━━━━━━━
核心要求
━━━━━━━━━━━━━━━━━━

1. 严格按照影视镜头语言拆分
2. 每个分镜必须包含：
   - description（用于生图的静态构图描述）
   - video_description（用于图生视频的动态时间描述，且必须包含台词或明确标注 NONE）
3. description 必须包含：
   - Scene（场景环境 + 光线 + 摄影机）
   - Characters（逐个角色锁定形象 + 服装关键词 + 当前动作）
   - Action（一句话总结镜头主行为）
4. video_description 必须包含：
   - Character Constraints（人物一致性锁定）
   - Motion Timeline（时间展开式动作）
   - Dialogue（spoken, no on-screen text：逐字保留原文台词）
5. description 长度控制在 100–160 字
6. video_description 长度控制在 90–220 字（包含 Dialogue 段）
7. 所有视觉描述必须符合：##STYLE## style, high quality, detailed
8. 不允许普通叙事句
9. 不允许心理描写
10. 不允许解释性文字
11. 输出必须是纯 JSON
12. 不允许 Markdown

━━━━━━━━━━━━━━━━━━
【关键改进：台词零丢失硬约束（必须执行）】
━━━━━━━━━━━━━━━━━━

你必须确保“原文中的所有直接引语（引号内台词）100%被保留，不得遗漏”。

执行步骤（强制）：

A) 先从原文中提取一个 quotes 数组（仅内部校验用，不得输出该字段），内容为：
- 原文所有直接引语（中文引号“ ”或英文引号""内的句子）
- 必须逐字复制，包含原标点与原文字，不得改写
- 不得遗漏任何一条引语

B) 再将 quotes 数组中的每一条台词，逐条分配到某一个镜头的 video_description.Dialogue 中：
- 每条台词必须出现且只出现一次（不重复、不丢失）
- 若某条台词过长或同段出现多句，必须拆成多个镜头承载（宁可多镜头，不允许丢台词）
- 任何没有台词的镜头必须写：Dialogue (spoken, no on-screen text): NONE

C) 完整性校验（必须执行，失败即输出错误重写）：
- 输出完成后，你必须自检：逐条核对 quotes 中每条台词是否都已出现在某个镜头的 Dialogue 中
- 若发现任何台词未被分配（遗漏），必须增加镜头并补齐
- 严禁输出空台词：禁止出现 speaker: "" 或 " " 或仅空白；无台词只能用 NONE

D) 台词归属规则：
- Dialogue 的 speaker 必须来自 allowed_characters
- 原文未明确说话人时，必须根据上下文指派最合理的白名单角色（例如“有的人提议”→ 群臣1/群臣2/围观者1/围观者2 之一）
- 禁止用“众人/有人/某人/人群”等泛称作为 speaker；必须映射到白名单具体编号角色

━━━━━━━━━━━━━━━━━━
description 强制结构模板
━━━━━━━━━━━━━━━━━━

description 必须输出为单个字符串，并且必须包含如下换行结构（使用 \n）：

"Scene: ...\nCharacters:\n- 角色A: ...\n- 角色B: ...\nAction: ..."

模板：
Scene: {中文场景环境句子}, {光线描述}, {镜头类型与机位描述}, ##STYLE## style, high quality, detailed。
Characters:
- {角色名1}: 保持参考人设的面部、发型、体型比例与服装轮廓不变; {宋代/对应时代服饰关键词}; {当前镜头动作}.
- {角色名2}: 保持参考人设的面部、发型、体型比例与服装轮廓不变; {宋代/对应时代服饰关键词}; {当前镜头动作}.
Action: {一句话概括主要角色正在发生的动作行为}。

说明：
- 必须完整包含 Scene / Characters / Action 三部分
- 不得缺失任何部分
- description 中严禁出现任何台词文字或引号内容（台词只能在 video_description 的 Dialogue 段出现）
- description 的每一部分必须分行，不得写在同一行

━━━━━━━━━━━━━━━━━━
video_description 强制结构（LTX-2 优化版，含台词）
━━━━━━━━━━━━━━━━━━

video_description 必须严格输出为单个字符串，并且必须包含如下换行结构（使用 \n）：

"Character Constraints:\n- 角色A: ...\n- 角色B: ...\nMotion:\n...\nDialogue (spoken, no on-screen text):\n- 角色A: "...""

模板：
Character Constraints:
- {角色名1}: 保持参考人设的面部、发型、体型比例与服装轮廓不变; 保持{服饰关键词}; 不得改变年龄、体型与身份。
- {角色名2}: 保持参考人设的面部、发型、体型比例与服装轮廓不变; 保持{服饰关键词}; 不得改变年龄、体型与身份。
Motion:
{时间展开式动作描述，必须包含：起始状态 → 动作过程 → 镜头运动 → 结束状态}
Dialogue (spoken, no on-screen text):
- {说话角色名}: "{必须逐字复制原文台词}"

无台词时必须写：
Dialogue (spoken, no on-screen text): NONE

━━━━━━━━━━━━━━━━━━
【字符串换行与排版硬约束（必须执行）】
━━━━━━━━━━━━━━━━━━

1) description 与 video_description 必须使用换行符 "\n" 进行分段排版（JSON 字符串中必须显式包含 \n）。
2) 禁止把 Character Constraints / Motion / Dialogue 写在同一行；必须逐段换行。
3) 列表项必须每个角色独占一行，并以 "- " 开头。
4) 若 Dialogue 为 NONE，也必须独占一行：
"Dialogue (spoken, no on-screen text): NONE"

━━━━━━━━━━━━━━━━━━
video_description 动作约束规则
━━━━━━━━━━━━━━━━━━

1. 必须使用时间展开语言：缓慢 / 逐渐 / 开始 / 随后 / 最终 等
2. 必须描述起始状态
3. 必须描述动作连续过程
4. 若涉及物理变化（重量、位移、水面变化等）必须写清变化过程
5. 必须写明镜头运动方式：固定镜头 / 缓慢推进 / 轻微平移 / 稳定跟随
6. 动作数量不超过2个连续行为（避免视频崩坏）
7. 禁止新增角色
8. 禁止新增剧情
9. 禁止加入画面文字（任何字幕/标题/屏幕文字叠加均禁止）
10. 禁止改变人物形象/服装/体型比例
11. Motion 中禁止出现心理词（如：若有所思/感到/心想/沉思）；必须改为可见表情或动作（如：眉头微皱/目光停留/嘴角上扬）。

━━━━━━━━━━━━━━━━━━
分镜规则
━━━━━━━━━━━━━━━━━━

- id：从1递增
- characters：当前镜头出现角色（必须与 description 和 video_description 中出现的角色一致）
- scene：当前镜头所在场景
- duration：3-10秒，根据动作复杂度自动判断

━━━━━━━━━━━━━━━━━━
角色命名必须全程保持唯一且一致
━━━━━━━━━━━━━━━━━━

- 所有角色名称必须在首次解析时确定为唯一标准名称
- 后续所有镜头必须严格复用该名称
- 若同类型角色存在多个且无真实姓名：
  - 必须使用阿拉伯数字编号（如“骗子1”“骗子2”“群臣1”“围观者1”）
  - 编号按首次出场顺序递增
  - 禁止使用“甲/乙”“A/B”“其中一人”“另一人”等变体
- 一旦名称确定，不得更改、简化或替换

━━━━━━━━━━━━━━━━━━
【角色白名单硬约束（必须执行，100%不越界）】
━━━━━━━━━━━━━━━━━━

你将收到一个 allowed_characters 数组，表示本章允许出现的角色名称列表。

规则：

1) 任何输出字段中出现的角色名必须严格来自 allowed_characters，禁止出现任何不在 allowed_characters 中的角色名。范围包括：
   - shots[].characters
   - description 的 Characters 段落中的角色名
   - video_description 的 Character Constraints 段落中的角色名
   - video_description 的 Dialogue 段落中的 speaker

2) 当正文出现“众人/群臣/士兵/百姓/侍从/随从/围观者/人群”等泛称时：
   - 必须改写为 allowed_characters 中对应的具体角色名（例如：群臣1、群臣2、围观者1、围观者2）。
   - 若 allowed_characters 中没有任何可对应的具体角色名，则该镜头不得把泛称写入 shots[].characters；只能作为“背景剪影/远处人群”环境元素描述（且不得作为 speaker）。

━━━━━━━━━━━━━━━━━━
禁止
━━━━━━━━━━━━━━━━━━

- 不得输出 image_path、image_url、merged_character_image 等字段
- 不得添加额外键
- 不得改变剧情
- 不得合并多个剧情行为到一个镜头
- 不得省略 Scene / Characters / Action 任意一部分
- 不得输出任何解释性文字，只返回JSON

━━━━━━━━━━━━━━━━━━
输出格式必须严格如下
━━━━━━━━━━━━━━━━━━

{
  "chapter": "…",
  "characters": ["…"],
  "scenes": ["…"],
  "shots": [
    {
      "id": 1,
      "description": "Scene: ...\nCharacters:\n- ...\nAction: ...",
      "video_description": "Character Constraints:\n- ...\nMotion:\n...\nDialogue (spoken, no on-screen text):\n- ...: \"...\"",
      "characters": ["..."],
      "scene": "...",
      "duration": 5
    }
  ]
}""",
        "type": "chapter_split"
    }
]

# 合并所有系统模板
SYSTEM_PROMPT_TEMPLATES = SYSTEM_CHARACTER_TEMPLATES + SYSTEM_CHAPTER_SPLIT_TEMPLATES


def get_template_name_key(name: str) -> str:
    """获取模板名称的翻译键"""
    return f"promptConfig.templateNames.{name}"


def get_template_description_key(name: str) -> str:
    """获取模板描述的翻译键"""
    return f"promptConfig.templateDescriptions.{name}"


def init_system_prompt_templates(db: Session):
    """初始化系统预设提示词模板"""
    print("[初始化] 更新系统预设提示词模板...")
    
    # 创建或更新系统预设模板
    for tmpl_data in SYSTEM_PROMPT_TEMPLATES:
        # 检查是否已存在同名同类型的系统模板
        existing = db.query(PromptTemplate).filter(
            PromptTemplate.name == tmpl_data["name"],
            PromptTemplate.type == tmpl_data.get("type", "character"),
            PromptTemplate.is_system == True
        ).first()
        
        if existing:
            # 更新现有模板内容
            existing.description = tmpl_data["description"]
            existing.template = tmpl_data["template"]
        else:
            # 创建新模板
            template = PromptTemplate(
                name=tmpl_data["name"],
                description=tmpl_data["description"],
                template=tmpl_data["template"],
                type=tmpl_data.get("type", "character"),
                is_system=True,
                is_active=True
            )
            db.add(template)
    
    db.commit()
    print("[初始化] 系统预设提示词模板更新完成")


class PromptTemplateCreate(BaseModel):
    name: str
    description: str = ""
    template: str
    type: str = "character"  # character 或 chapter_split


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    template: Optional[str] = None
    type: Optional[str] = None


class PromptTemplateResponse(BaseModel):
    id: str
    name: str
    description: str
    template: str
    type: str
    isSystem: bool
    isActive: bool
    createdAt: str
    
    class Config:
        from_attributes = True


@router.get("/", response_model=dict)
def list_prompt_templates(
    type: Optional[str] = Query(None, description="筛选类型: character 或 chapter_split"),
    db: Session = Depends(get_db)
):
    """获取所有提示词模板"""
    query = db.query(PromptTemplate)
    
    if type:
        query = query.filter(PromptTemplate.type == type)
    
    templates = query.order_by(
        PromptTemplate.is_system.desc(),
        PromptTemplate.created_at.desc()
    ).all()
    
    return {
        "success": True,
        "data": [
            {
                "id": t.id,
                "name": t.name,
                "nameKey": get_template_name_key(t.name) if t.is_system else None,
                "description": t.description,
                "descriptionKey": get_template_description_key(t.name) if t.is_system else None,
                "template": t.template,
                "type": t.type or "character",
                "isSystem": t.is_system,
                "isActive": t.is_active,
                "createdAt": t.created_at.isoformat() if t.created_at else None,
            }
            for t in templates
        ]
    }


@router.get("/{template_id}", response_model=dict)
def get_prompt_template(template_id: str, db: Session = Depends(get_db)):
    """获取单个提示词模板"""
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    
    return {
        "success": True,
        "data": {
            "id": template.id,
            "name": template.name,
            "nameKey": get_template_name_key(template.name) if template.is_system else None,
            "description": template.description,
            "descriptionKey": get_template_description_key(template.name) if template.is_system else None,
            "template": template.template,
            "type": template.type or "character",
            "isSystem": template.is_system,
            "isActive": template.is_active,
            "createdAt": template.created_at.isoformat() if template.created_at else None,
        }
    }


@router.post("/", response_model=dict)
def create_prompt_template(data: PromptTemplateCreate, db: Session = Depends(get_db)):
    """创建用户自定义提示词模板"""
    template = PromptTemplate(
        name=data.name,
        description=data.description,
        template=data.template,
        type=data.type,
        is_system=False,  # 用户创建的默认为非系统
        is_active=True
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    
    return {
        "success": True,
        "message": "提示词模板创建成功",
        "data": {
            "id": template.id,
            "name": template.name,
            "nameKey": get_template_name_key(template.name) if template.is_system else None,
            "description": template.description,
            "descriptionKey": get_template_description_key(template.name) if template.is_system else None,
            "template": template.template,
            "type": template.type or "character",
            "isSystem": template.is_system,
            "isActive": template.is_active,
            "createdAt": template.created_at.isoformat() if template.created_at else None,
        }
    }


@router.post("/{template_id}/copy", response_model=dict)
def copy_prompt_template(template_id: str, db: Session = Depends(get_db)):
    """复制系统提示词模板为用户自定义模板"""
    source = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="源提示词模板不存在")
    
    # 创建副本
    new_template = PromptTemplate(
        name=f"{source.name} (副本)",
        description=source.description,
        template=source.template,
        type=source.type or "character",
        is_system=False,  # 复制出来的为用户类型
        is_active=True
    )
    db.add(new_template)
    db.commit()
    db.refresh(new_template)
    
    return {
        "success": True,
        "message": "提示词模板复制成功",
        "data": {
            "id": new_template.id,
            "name": new_template.name,
            "nameKey": get_template_name_key(new_template.name) if new_template.is_system else None,
            "description": new_template.description,
            "descriptionKey": get_template_description_key(new_template.name) if new_template.is_system else None,
            "template": new_template.template,
            "type": new_template.type or "character",
            "isSystem": new_template.is_system,
            "isActive": new_template.is_active,
            "createdAt": new_template.created_at.isoformat() if new_template.created_at else None,
        }
    }


@router.put("/{template_id}", response_model=dict)
def update_prompt_template(
    template_id: str, 
    data: PromptTemplateUpdate, 
    db: Session = Depends(get_db)
):
    """更新提示词模板（仅用户自定义可编辑）"""
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    
    if template.is_system:
        raise HTTPException(status_code=403, detail="系统预设提示词不可编辑")
    
    if data.name is not None:
        template.name = data.name
    if data.description is not None:
        template.description = data.description
    if data.template is not None:
        template.template = data.template
    if data.type is not None:
        template.type = data.type
    
    db.commit()
    db.refresh(template)
    
    return {
        "success": True,
        "message": "提示词模板更新成功",
        "data": {
            "id": template.id,
            "name": template.name,
            "nameKey": get_template_name_key(template.name) if template.is_system else None,
            "description": template.description,
            "descriptionKey": get_template_description_key(template.name) if template.is_system else None,
            "template": template.template,
            "type": template.type or "character",
            "isSystem": template.is_system,
            "isActive": template.is_active,
            "createdAt": template.created_at.isoformat() if template.created_at else None,
        }
    }


@router.delete("/{template_id}", response_model=dict)
def delete_prompt_template(template_id: str, db: Session = Depends(get_db)):
    """删除提示词模板（仅用户自定义可删除）"""
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="提示词模板不存在")
    
    if template.is_system:
        raise HTTPException(status_code=403, detail="系统预设提示词不可删除")
    
    db.delete(template)
    db.commit()
    
    return {"success": True, "message": "提示词模板删除成功"}


@router.get("/system/default", response_model=dict)
def get_default_system_template(
    type: Optional[str] = Query("character", description="模板类型: character 或 chapter_split"),
    db: Session = Depends(get_db)
):
    """获取默认的系统提示词模板"""
    template = db.query(PromptTemplate).filter(
        PromptTemplate.is_system == True,
        PromptTemplate.type == type
    ).order_by(PromptTemplate.created_at.asc()).first()
    
    if not template:
        raise HTTPException(status_code=404, detail="未找到系统提示词模板")
    
    return {
        "success": True,
        "data": {
            "id": template.id,
            "name": template.name,
            "nameKey": get_template_name_key(template.name) if template.is_system else None,
            "description": template.description,
            "descriptionKey": get_template_description_key(template.name) if template.is_system else None,
            "template": template.template,
            "type": template.type or "character",
            "isSystem": template.is_system,
            "isActive": template.is_active,
            "createdAt": template.created_at.isoformat() if template.created_at else None,
        }
    }
