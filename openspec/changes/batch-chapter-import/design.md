# 详细设计文档

## 1. 背景与现状

### 1.1 技术背景

AI-NovelFlow 平台的章节管理基于 FastAPI + SQLAlchemy 后端和 React + TypeScript 前端。当前章节创建仅支持单条手动录入（`POST /api/novels/{id}/chapters/`），通过前端 `CreateChapterModal` 表单提交。数据存储使用 SQLite，章节模型包含 `number`、`title`、`content` 等字段。

### 1.2 现状分析

- **现有接口**：`POST /{novel_id}/chapters/` 一次只能创建一个章节
- **现有前端**：`CreateChapterModal.tsx` 提供序号、标题、内容的表单输入
- **Repository**：`ChapterRepository` 有 `create()` 单条创建方法，无批量操作
- **限制**：用户导入整本小说的 TXT 时，需逐章手动录入，效率极低

### 1.3 关键干系人

- 用户：上传小说 TXT 文件的创作者
- 后端：章节 API、Repository 层、新增文本解析工具
- 前端：NovelDetail 页面、新增 BatchImportModal 组件

## 2. 设计目标

### 目标

- 实现两阶段导入流程：预览 → 确认导入
- 后端自动检测 UTF-8/GBK 编码，解析章节标题
- 按章节号 upsert，替换时保留已有资源
- 部分成功容错，失败项单独返回
- 前端提供文件选择、预览列表、导入确认的完整交互

### 非目标

- 不支持自定义分隔符（后续可扩展）
- 不支持在线编辑预览中的章节分割点
- 不处理超大文件（>10MB）的分块上传

## 3. 整体架构

### 3.1 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│  前端 (React)                                                │
│                                                              │
│  NovelDetail ──▶ BatchImportModal ──▶ chapters.ts (API)     │
│       │                  │                                    │
│       │     ┌────────────┴────────────┐                      │
│       │     │ 阶段1: 预览              │  阶段2: 导入         │
│       │     │ POST .../preview         │  POST .../import    │
│       │     └────────────┬────────────┘                      │
└──────────────────────────┼───────────────────────────────────┘
                           │
┌──────────────────────────┼───────────────────────────────────┐
│  后端 (FastAPI)          ▼                                    │
│                                                              │
│  chapters.py (API Layer)                                     │
│       │                                                      │
│       ├── batch_import_preview() ──▶ 解析 + 返回预览         │
│       └── batch_import_chapters() ──▶ 解析 + bulk_upsert     │
│                        │                                     │
│                        ▼                                     │
│  text_utils.py (工具层)                                       │
│       ├── detect_encoding()                                  │
│       ├── parse_chapters_from_text()                         │
│       └── chinese_to_int()                                   │
│                        │                                     │
│                        ▼                                     │
│  chapter_repository.py (数据层)                               │
│       └── bulk_upsert()                                      │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 核心组件

| 组件 | 层级 | 职责 |
|------|------|------|
| `text_utils.py` | 工具层 | 编码检测、章节解析、中文数字转换 |
| `chapters.py` | API 层 | 两个新端点：预览和导入 |
| `ChapterRepository.bulk_upsert()` | 数据层 | 批量 upsert 操作，返回统计信息 |
| `BatchImportModal.tsx` | 前端组件 | 文件选择、预览列表、确认导入 |
| `useNovelDetailState.ts` | 前端 Hook | 批量导入状态管理 |
| `chapters.ts` | 前端 API | 新增 `batchImportPreview()` 和 `batchImport()` |

### 3.3 数据流设计

```
用户选择 TXT 文件
       │
       ▼
  前端: FileReader.readAsArrayBuffer (仅在预览阶段不需要，直接 FormData 上传)
       │
       ▼
  前端 → 后端: POST /batch-import/preview (FormData: file)
       │
       ▼
  后端: detect_encoding() → 读取文本 → parse_chapters_from_text()
       │
       ▼
  后端 → 前端: 预览结果 { chapters: [...], summary: { total, new, replace } }
       │
       ▼
  前端: 显示预览列表，用户确认
       │
       ▼
  前端 → 后端: POST /batch-import (FormData: file)
       │
       ▼
  后端: detect_encoding() → parse_chapters_from_text() → bulk_upsert()
       │
       ▼
  后端 → 前端: 导入结果 { total, created, updated, failed, errors, chapters }
       │
       ▼
  前端: 显示结果 → 刷新章节列表
```

## 4. 详细设计

### 4.1 接口设计

#### 接口：批量导入预览

- **请求方式**：POST
- **请求路径**：`/api/novels/{novel_id}/chapters/batch-import/preview`
- **Content-Type**：`multipart/form-data`
- **请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| novel_id | path string | 是 | 小说 ID |
| file | UploadFile | 是 | TXT 文件 |

- **响应结构**：

```json
{
  "success": true,
  "data": {
    "chapters": [
      { "number": 1, "title": "第一章 重生之始", "content_length": 1234, "action": "new" },
      { "number": 2, "title": "第二章 初露锋芒", "content_length": 1567, "action": "replace" }
    ],
    "summary": { "total": 50, "new": 30, "replace": 20 },
    "errors": []
  }
}
```

#### 接口：批量导入执行

- **请求方式**：POST
- **请求路径**：`/api/novels/{novel_id}/chapters/batch-import`
- **Content-Type**：`multipart/form-data`
- **请求参数**：同上

- **响应结构（部分成功）**：

```json
{
  "success": true,
  "data": {
    "total": 50,
    "created": 30,
    "updated": 18,
    "failed": 2,
    "errors": [
      { "segment": 3, "title": "未知", "reason": "无法识别章节标题" }
    ],
    "chapters": [ ... ]
  },
  "message": "导入完成：成功 48 个，失败 2 个"
}
```

- **响应结构（全部失败）**：

```json
{
  "success": false,
  "message": "无法解析章节，请检查文件格式",
  "data": { "errors": [...] }
}
```

### 4.2 数据模型

本次变更不新增数据表或字段。使用现有的 `chapters` 表结构。

### 4.3 核心算法

#### 4.3.1 编码检测

```python
def detect_encoding(raw_bytes: bytes) -> str:
    """检测文本编码，优先 UTF-8，回退 GBK"""
    try:
        raw_bytes.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        return 'gbk'
```

#### 4.3.2 中文数字转换

```python
_CN_NUMS = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
            '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
            '十': 10, '百': 100, '千': 1000, '万': 10000}

def chinese_to_int(text: str) -> int | None:
    """中文数字转阿拉伯数字，支持到万级别"""
    # 纯阿拉伯数字
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
```

#### 4.3.3 章节解析

```python
import re

# 匹配: 第X章 标题 或 Chapter X: 标题
CHAPTER_RE = re.compile(
    r'^(?:'
    r'第([\d零一二三四五六七八九十百千万]+)章\s*(.*)'
    r'|'
    r'Chapter\s+(\d+)\s*:?\s*(.*)'
    r')$'
)

def parse_chapters_from_text(text: str) -> tuple[list[dict], list[dict]]:
    """
    解析文本为章节列表
    Returns: (chapters, errors)
      chapters: [{"number": int, "title": str, "content": str}, ...]
      errors: [{"segment": int, "title": str, "reason": str}, ...]
    """
    lines = text.splitlines()
    chapters = []
    errors = []
    current = None  # {"number": int, "title": str, "content_lines": []}
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
```

#### 4.3.4 Repository bulk_upsert

```python
def bulk_upsert(self, novel_id: str, chapters_data: list[dict]) -> dict:
    """
    批量 upsert 章节
    Returns: {created: int, updated: int, failed: int, errors: list, chapters: list}
    """
    # 1. 获取已有章节号 -> 章节映射
    existing = self.db.query(Chapter).filter(
        Chapter.novel_id == novel_id
    ).all()
    existing_by_number = {c.number: c for c in existing}

    # 2. 检测传入数据中的重复 chapter number
    seen_numbers = set()
    created = 0
    updated = 0
    failed = 0
    errors = []
    result_chapters = []

    for ch in chapters_data:
        num = ch['number']
        if num in seen_numbers:
            failed += 1
            errors.append({'number': num, 'title': ch['title'], 'reason': f'章节号 {num} 重复'})
            continue
        seen_numbers.add(num)

        try:
            if num in existing_by_number:
                # 更新已有章节（仅更新 title 和 content，保留其他资源）
                existing_ch = existing_by_number[num]
                existing_ch.title = ch['title']
                existing_ch.content = ch['content']
                updated += 1
                result_chapters.append(self.to_response(existing_ch))
            else:
                # 新建章节
                new_ch = Chapter(
                    novel_id=novel_id,
                    number=num,
                    title=ch['title'],
                    content=ch['content'],
                )
                self.db.add(new_ch)
                created += 1
                # 先不 commit，批量提交
        except Exception as e:
            failed += 1
            errors.append({'number': num, 'title': ch['title'], 'reason': str(e)})

    # 3. 批量提交
    if created > 0 or updated > 0:
        self.db.commit()
        # refresh 新建的章节
        for ch in result_chapters:
            if ch.get('id') and not any(c.number == ch['number'] for c in existing):
                pass  # 已在 commit 时生成

        # 更新 novel.chapter_count
        from app.models.novel import Novel
        novel = self.db.query(Novel).filter(Novel.id == novel_id).first()
        if novel:
            novel.chapter_count = self.count_by_novel(novel_id)

    return {
        'created': created,
        'updated': updated,
        'failed': failed,
        'errors': errors,
        'chapters': result_chapters,
    }
```

### 4.4 异常处理

| 异常场景 | 处理策略 |
|----------|----------|
| 上传非 .txt 文件 | 返回 400，提示"仅支持 .txt 格式文件" |
| 文件内容为空 | 预览返回 total=0 的空列表，导入返回 0 成功 |
| 完全无法识别任何章节标题 | 返回 success=false，message="无法解析章节，请检查文件格式" |
| 部分章节内容为空 | 该章节记为失败，errors 中记录原因，其他章节正常处理 |
| 传入数据中有重复 chapter number | 第二个重复项记为失败 |
| 数据库写入异常 | 单个章节异常记为失败，不回滚其他章节 |
| 文件过大（>10MB） | 前端限制文件大小，上传前校验 |
| 网络中断 | 前端捕获异常，显示"网络请求失败，请重试" |

### 4.5 前端设计

#### 技术栈

- 框架：React 18 + TypeScript
- 状态管理：组件本地 useState（无需全局 Store）
- UI 组件库：Tailwind CSS（项目已有模式）

#### 组件设计

| 组件名 | 类型 | 文件路径 | 说明 |
|--------|------|----------|------|
| BatchImportModal | 组合组件 | `components/BatchImportModal.tsx` | 文件选择 + 预览列表 + 导入确认 |
| NovelDetail (修改) | 页面 | `index.tsx` | 新增"批量导入"按钮 |
| useNovelDetailState (修改) | Hook | `hooks/useNovelDetailState.ts` | 新增批量导入相关状态 |

#### BatchImportModal Props

```typescript
interface BatchImportModalProps {
  show: boolean;
  novelId: string;
  onClose: () => void;
  onImportComplete: () => void; // 导入成功后刷新章节列表
}
```

#### 交互逻辑

```
1. 用户点击"批量导入章节"按钮 → 打开 BatchImportModal
2. 用户选择 TXT 文件 → 自动触发预览请求
   - 请求中：显示 loading 状态
   - 预览成功：显示章节列表（序号、标题、字数、新增/替换标签）
   - 预览失败：显示错误提示
3. 用户点击"确认导入"按钮 → 触发导入请求
   - 按钮 loading + disabled
4. 导入成功 → toast 提示 → 关闭弹窗 → 刷新列表
5. 导入部分成功 → 显示成功数/失败数 + 错误详情
6. 网络异常 → 错误 toast → 按钮恢复
```

#### 预览界面布局

```
┌──────────────────────────────────────────────────────┐
│  批量导入章节                                    [×]  │
├──────────────────────────────────────────────────────┤
│                                                      │
│  [📁 选择 TXT 文件]  chapter_batch.txt (2.3MB)       │
│                                                      │
│  ──────────────────────────────────────────────────  │
│  解析到 50 个章节（30 个新增，20 个替换）              │
│  ──────────────────────────────────────────────────  │
│                                                      │
│  ┌────────────────────────────────────────────────┐ │
│  │  1. 第一章 重生之始      1,234字  [新增]       │ │
│  │  2. 第二章 初露锋芒      1,567字  [替换]       │ │
│  │  3. 第三章 暗流涌动        980字  [替换]       │ │
│  │  ...                                          │ │
│  │  50. 第五十章 最终决战    2,100字  [新增]      │ │
│  └────────────────────────────────────────────────┘ │
│                                                      │
│                              [取消]  [确认导入]      │
└──────────────────────────────────────────────────────┘
```

### 4.6 前端接口对接

| 接口 | 方法 | 调用时机 | 说明 |
|------|------|----------|------|
| `POST /api/novels/{id}/chapters/batch-import/preview` | FormData | 选择文件后 | 预览解析结果 |
| `POST /api/novels/{id}/chapters/batch-import` | FormData | 确认导入后 | 执行批量导入 |

前端 API 方法：

```typescript
// chapters.ts 新增
export const chapterApi = {
  // ... 已有方法

  /** 批量导入预览 */
  batchImportPreview: (novelId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.upload<{
      chapters: { number: number; title: string; content_length: number; action: 'new' | 'replace' }[];
      summary: { total: number; new: number; replace: number };
      errors: { segment: number; title: string; reason: string }[];
    }>(`/novels/${novelId}/chapters/batch-import/preview`, formData);
  },

  /** 批量导入执行 */
  batchImport: (novelId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.upload<{
      total: number;
      created: number;
      updated: number;
      failed: number;
      errors: { number?: number; title: string; reason: string }[];
      chapters: any[];
    }>(`/novels/${novelId}/chapters/batch-import`, formData);
  },
};
```

## 5. 技术决策

### 决策 1：编码检测策略

- **选型方案**：先尝试 UTF-8 解码，失败则回退 GBK
- **选择理由**：无需额外依赖，覆盖中文场景的绝大多数情况，实现简单
- **备选方案**：使用 `chardet` 库
- **放弃原因**：需要安装第三方依赖，且项目目前无此依赖，增加维护成本

### 决策 2：解析逻辑放在后端

- **选型方案**：后端接收文件后解析
- **选择理由**：大文件处理更高效；编码检测在后端更准确；避免前端 JS 处理 GBK 的兼容性问题（浏览器原生不支持 GBK 解码）
- **备选方案**：前端解析后发送 JSON
- **放弃原因**：JS 原生 TextDecoder 对 GBK 支持有限，且大文件前端处理性能差

### 决策 3：部分成功不回滚

- **选型方案**：部分章节失败时，成功的章节正常入库
- **选择理由**：提升导入成功率，用户不需要因为少数几个问题章节重新导入全部
- **备选方案**：全有或全无的事务回滚
- **放弃原因**：用户需要修复所有问题才能导入，体验差

### 决策 4：替换时保留已有资源

- **选型方案**：仅更新 `title` 和 `content`，保留 `parsed_data`、`shot_images` 等字段
- **选择理由**：用户明确选择，避免误操作导致已生成的角色、分镜、视频资源丢失
- **备选方案**：自动清除资源（调用 `clear_resources`）
- **放弃原因**：用户明确要求保留

## 6. 风险评估

| 风险点 | 风险等级 | 应对策略 |
|--------|----------|----------|
| 中文数字解析边界情况（如"第〇章"） | 低 | 在 `_CN_NUMS` 中补充 `零: 0`，"〇"作为同义处理 |
| 超大 TXT 文件（>10MB）导致内存占用高 | 中 | 前端限制文件大小为 10MB，后端也可添加检查 |
| 章节号重复（用户手动编辑 TXT 导致） | 低 | bulk_upsert 中检测重复，记录为失败 |
| GBK 文件中有部分 UTF-8 字符导致混合编码 | 低 | UTF-8 解码失败即回退 GBK，GBK 的 `errors='replace'` 处理异常字节 |
| 替换章节后用户误以为资源也会更新 | 中 | 在 UI 中明确提示"替换内容但保留已有资源" |

## 7. 迁移方案

### 7.1 部署步骤

1. 后端：新增 `backend/app/utils/text_utils.py` 文件
2. 后端：在 `backend/app/repositories/chapter_repository.py` 中新增 `bulk_upsert()` 方法
3. 后端：在 `backend/app/api/chapters.py` 中新增两个端点
4. 前端：在 `frontend/my-app/src/api/chapters.ts` 中新增 API 方法
5. 前端：新增 `BatchImportModal.tsx` 组件
6. 前端：修改 `NovelDetail/index.tsx` 添加按钮
7. 前端：修改 `useNovelDetailState.ts` 添加状态管理
8. 前端：在 5 种语言文件中添加翻译 key

### 7.2 回滚方案

- 纯代码变更，无数据库迁移
- 回滚时删除新增的文件和代码即可，不影响现有数据

## 8. 待定事项

- [ ] 文件大小限制是否需要在后端也做校验（目前仅前端限制）
- [ ] 是否需要在预览时显示前几行内容让用户确认解析是否正确
