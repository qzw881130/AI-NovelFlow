# 实施任务清单

## 1. 后端：文本解析工具

新增文本解析工具模块，提供编码检测、章节解析、中文数字转换功能。

- [x] 1.1 创建 `backend/app/utils/text_utils.py` 文件
  - 新增文件，包含编码检测、章节解析、中文数字转换三个核心函数

- [x] 1.2 实现 `detect_encoding(raw_bytes: bytes) -> str`
  - 先尝试 UTF-8 解码，失败回退 GBK
  - 单元测试：UTF-8 文件、GBK 文件、空字节

- [x] 1.3 实现 `chinese_to_int(text: str) -> int | None`
  - 支持阿拉伯数字直接返回
  - 支持中文数字（零一二三四五六七八九十百千万）组合转换
  - 覆盖：十一、十九、一百二十三、一千零一、一万 等
  - 单元测试：纯数字、中文数字、复杂组合、非法输入

- [x] 1.4 实现 `parse_chapters_from_text(text: str) -> tuple[list, list]`
  - 正则匹配中文格式：`第X章 标题`
  - 正则匹配英文格式：`Chapter X: 标题` 或 `Chapter X 标题`
  - 非标题行追加到当前章节 content
  - 文件开头无章节标题的行记录为错误
  - 空章节记录为错误
  - 单元测试：混合格式、纯中文格式、纯英文格式、无章节标题、空文本

## 2. 后端：Repository 层

在 ChapterRepository 中新增批量 upsert 方法。

- [x] 2.1 在 `backend/app/repositories/chapter_repository.py` 中新增 `bulk_upsert()` 方法
  - 文件: `backend/app/repositories/chapter_repository.py`
  - 输入: `novel_id: str, chapters_data: list[dict]`
  - 逻辑: 按 number 匹配已有章节，存在则更新 title+content（不碰其他字段），不存在则新建
  - 检测传入数据中的重复 chapter number，记为失败
  - 返回: `{created, updated, failed, errors, chapters}`
  - 依赖: 1.4（解析后的章节数据格式已确定）

- [x] 2.2 批量提交后更新 `novel.chapter_count`
  - 在 `bulk_upsert()` 末尾统计并更新小说章节总数

## 3. 后端：API 层

新增两个端点：预览和导入。

- [x] 3.1 在 `backend/app/api/chapters.py` 中新增 `batch_import_preview()` 端点
  - 路由: `POST /{novel_id}/chapters/batch-import/preview`
  - 参数: `file: UploadFile = File(...)`
  - 逻辑: 读取文件 → detect_encoding → parse_chapters_from_text → 与已有章节比对 action 类型 → 返回预览结果
  - 不入库
  - 校验: 文件扩展名必须为 .txt
  - 依赖: 1.2, 1.3, 1.4, 2.1

- [x] 3.2 在 `backend/app/api/chapters.py` 中新增 `batch_import_chapters()` 端点
  - 路由: `POST /{novel_id}/chapters/batch-import`
  - 参数: `file: UploadFile = File(...)`
  - 逻辑: 读取文件 → detect_encoding → parse_chapters_from_text → bulk_upsert → 返回导入结果
  - 解析失败（无章节）时返回 success=false
  - 部分成功时返回 success=true + errors
  - 依赖: 1.2, 1.3, 1.4, 2.1, 3.1

## 4. 前端：API 层

在 chapters.ts 中新增批量导入 API 方法。

- [x] 4.1 在 `frontend/my-app/src/api/chapters.ts` 中新增 `batchImportPreview()` 方法
  - FormData 上传 file，调用 preview 接口
  - 定义返回类型：`{ chapters, summary, errors }`

- [x] 4.2 在 `frontend/my-app/src/api/chapters.ts` 中新增 `batchImport()` 方法
  - FormData 上传 file，调用 import 接口
  - 定义返回类型：`{ total, created, updated, failed, errors, chapters }`
  - 依赖: 3.2（后端接口已就绪）

## 5. 前端：组件层

新增 BatchImportModal 组件，修改 NovelDetail 页面。

- [x] 5.1 创建 `frontend/my-app/src/pages/NovelDetail/components/BatchImportModal.tsx`
  - 文件选择（接受 .txt 文件，限制 10MB）
  - 选择文件后自动调用预览接口
  - 显示预览列表：序号、标题、字数、action 标签（新增=绿色、替换=橙色）
  - 显示统计摘要
  - 显示解析错误列表（如有）
  - 确认导入按钮：loading 状态 + disabled 防重复
  - 导入成功：toast + 关闭弹窗 + 回调刷新
  - 导入部分成功：展示错误详情
  - 导入失败：错误提示 + 按钮恢复
  - 依赖: 4.1, 4.2

- [x] 5.2 修改 `frontend/my-app/src/pages/NovelDetail/index.tsx`
  - 新增"批量导入章节"按钮（使用 Upload/FileText 图标）
  - 位置：与现有"添加章节"按钮并列
  - 引入 BatchImportModal 组件
  - 依赖: 5.1

- [x] 5.3 修改 `frontend/my-app/src/pages/NovelDetail/hooks/useNovelDetailState.ts`
  - 新增 `showBatchImportModal` 状态
  - 新增 `handleBatchImportComplete` 回调（刷新章节列表）
  - 依赖: 5.2

## 6. 前端：国际化

在 5 种语言文件中新增批量导入相关翻译 key。

- [x] 6.1 在以下 5 个文件中新增 `batchImport` 相关翻译 key
  - `frontend/my-app/src/i18n/locales/zh-CN/novels.ts`
  - `frontend/my-app/src/i18n/locales/en-US/novels.ts`
  - `frontend/my-app/src/i18n/locales/ja-JP/novels.ts`
  - `frontend/my-app/src/i18n/locales/ko-KR/novels.ts`
  - `frontend/my-app/src/i18n/locales/zh-TW/novels.ts`
  - 需覆盖 key: `batchImport.title`、`batchImport.selectFile`、`batchImport.previewTitle`、`batchImport.confirmImport`、`batchImport.importing`、`batchImport.importComplete`、`batchImport.partialSuccess`、`batchImport.importFailed`、`batchImport.newLabel`、`batchImport.replaceLabel`、`batchImport.errorDetails`
  - 依赖: 5.1（翻译 key 由 UI 文案确定）

## 7. 测试与验证

- [x] 7.1 后端单元测试 - text_utils.py
  - `detect_encoding`: UTF-8、GBK、空字节
  - `chinese_to_int`: 纯数字、中文数字、复杂组合、非法输入
  - `parse_chapters_from_text`: 混合格式、纯中文、纯英文、无标题、空文本

- [x] 7.2 后端集成测试 - bulk_upsert
  - 混合新建和更新
  - 重复 chapter number 检测
  - 数据库提交后 chapter_count 更新

- [x] 7.3 后端集成测试 - API 端点
  - 预览接口：正常解析、空文件、非 txt 文件
  - 导入接口：全部成功、部分失败、全部失败

- [x] 7.4 前端浏览器验证（使用 Chrome DevTools MCP 工具）
  - 启动开发服务器后，导航到 NovelDetail 页面（`navigate_page: url=http://localhost:5173/novels/{id}`）
  - 验证"批量导入章节"按钮存在且可点击（`take_snapshot` 确认 UI 元素）
  - 验证文件上传交互：触发文件选择、预览列表正确渲染（`take_screenshot` 对比预期布局）
  - 验证导入请求：检查网络面板确认 FormData 上传和接口响应（`list_network_requests: resourceTypes=["fetch", "xhr"]`）
  - 验证导入成功后章节列表刷新（`take_snapshot` 确认新增章节行）
  - 验证错误场景：上传非 txt 文件/空文件 → 控制台无 JS 报错（`list_console_messages: types=["error"]`），UI 显示正确提示
  - 验收：`take_screenshot` 截图确认预览界面和导入结果弹窗符合预期

## 任务依赖关系

```
1.x (文本解析工具)
       │
       ▼
2.x (Repository bulk_upsert)
       │
       ▼
3.x (API 端点: 预览 + 导入) ────┐
                                 │
                                 ▼
4.x (前端 API 方法) ──▶ 5.x (前端组件) ──▶ 6.x (国际化)
                                                    │
                                                    ▼
                                               7.x (测试验证)
```

## 建议实施顺序

| 阶段 | 任务 | 说明 |
|------|------|------|
| 阶段一 | 1.x | 后端文本解析工具，无外部依赖，可独立开发测试 |
| 阶段二 | 2.x | Repository 层批量 upsert，依赖 1.x 的数据格式 |
| 阶段三 | 3.x | API 端点，依赖 1.x + 2.x，可用 Postman 独立测试 |
| 阶段四 | 4.x | 前端 API 方法，依赖 3.x 接口定义 |
| 阶段五 | 5.x + 6.x | 前端组件 + 国际化，可并行开发 |
| 阶段六 | 7.x | 全链路测试，依赖以上全部完成 |

## 文件结构总览

```
backend/app/
├── utils/
│   └── text_utils.py                          [新增]
├── repositories/
│   └── chapter_repository.py                  [修改: 新增 bulk_upsert]
└── api/
    └── chapters.py                            [修改: 新增两个端点]

frontend/my-app/src/
├── api/
│   └── chapters.ts                            [修改: 新增两个方法]
├── pages/NovelDetail/
│   ├── index.tsx                              [修改: 新增按钮]
│   ├── hooks/
│   │   └── useNovelDetailState.ts             [修改: 新增状态]
│   └── components/
│       ├── CreateChapterModal.tsx              [不变]
│       └── BatchImportModal.tsx               [新增]
└── i18n/locales/
    ├── zh-CN/novels.ts                         [修改]
    ├── en-US/novels.ts                         [修改]
    ├── ja-JP/novels.ts                         [修改]
    ├── ko-KR/novels.ts                         [修改]
    └── zh-TW/novels.ts                         [修改]
```
