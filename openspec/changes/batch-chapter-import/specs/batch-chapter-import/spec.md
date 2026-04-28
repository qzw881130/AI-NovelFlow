# 功能规格说明

## ADDED Requirements

### Requirement: TXT 文件上传与编码检测

系统 SHALL 接收用户上传的 TXT 文件，并自动检测文件编码（UTF-8 或 GBK）。

#### Scenario: 上传 UTF-8 编码的 TXT 文件
- **WHEN** 用户上传 UTF-8 编码的 TXT 文件
- **THEN** 系统 SHALL 正确识别编码为 UTF-8
- **AND** 文件内容 SHALL 无乱码解析

#### Scenario: 上传 GBK 编码的 TXT 文件
- **WHEN** 用户上传 GBK 编码的 TXT 文件
- **THEN** 系统 SHALL 在 UTF-8 解码失败后回退使用 GBK 解码
- **AND** 文件内容 SHALL 无乱码解析

#### Scenario: 上传非 TXT 格式文件
- **WHEN** 用户上传的文件扩展名不是 .txt
- **THEN** 系统 SHALL 返回 400 错误
- **AND** 错误消息 SHALL 提示"仅支持 .txt 格式文件"

#### Scenario: 上传空文件
- **WHEN** 用户上传的 TXT 文件内容为空
- **THEN** 系统 SHALL 返回解析结果，章节列表为空
- **AND** 预览接口返回 `"total": 0`

### Requirement: 章节标题格式解析

系统 SHALL 支持以下两种章节标题格式的自动识别：
1. 中文格式：`第X章 标题`（X 可为阿拉伯数字或中文数字）
2. 英文格式：`Chapter X: 标题` 或 `Chapter X 标题`

#### Scenario: 解析中文格式章节（阿拉伯数字）
- **WHEN** TXT 内容包含 "第1章 重生之始"
- **THEN** 系统 SHALL 解析出 number=1, title="第1章 重生之始"

#### Scenario: 解析中文格式章节（中文数字）
- **WHEN** TXT 内容包含 "第一百二十三章 最终决战"
- **THEN** 系统 SHALL 解析出 number=123, title="第一百二十三章 最终决战"

#### Scenario: 解析英文格式章节
- **WHEN** TXT 内容包含 "Chapter 5: The Battle"
- **THEN** 系统 SHALL 解析出 number=5, title="Chapter 5: The Battle"

#### Scenario: 解析英文格式章节（无冒号）
- **WHEN** TXT 内容包含 "Chapter 10 Return Home"
- **THEN** 系统 SHALL 解析出 number=10, title="Chapter 10 Return Home"

#### Scenario: 中文数字包含复杂组合
- **WHEN** TXT 内容包含 "第一千零二十一章"
- **THEN** 系统 SHALL 解析出 number=1021

#### Scenario: 章节标题后紧跟正文内容
- **WHEN** 章节标题行之后出现非标题行文本
- **THEN** 系统 SHALL 将该文本追加到当前章节的 content 中
- **AND** 直到下一个章节标题或文件结尾

#### Scenario: 无法识别章节标题的文本段落
- **WHEN** TXT 开头没有任何章节标题格式的行
- **THEN** 系统 SHALL 将该段落标记为解析失败
- **AND** 失败原因 SHALL 为"无法识别章节标题"

### Requirement: 导入预览接口

系统 SHALL 提供预览接口，解析 TXT 文件但不入库，返回章节列表及操作类型。

#### Scenario: 预览全新章节导入
- **WHEN** 用户上传包含 1-50 章的 TXT 文件
- **AND** 小说当前无任何章节
- **THEN** 预览结果中所有章节的 action SHALL 为 "new"
- **AND** summary.new SHALL 为 50

#### Scenario: 预览部分替换导入
- **WHEN** 用户上传包含 1-30 章的 TXT 文件
- **AND** 小说已有 1-20 章
- **THEN** 预览结果中 1-20 章的 action SHALL 为 "replace"
- **AND** 21-30 章的 action SHALL 为 "new"
- **AND** summary.replace SHALL 为 20, summary.new SHALL 为 10

#### Scenario: 预览包含解析失败的章节
- **WHEN** TXT 文件中部分段落无法识别章节标题
- **THEN** 预览结果 SHALL 包含 errors 数组
- **AND** errors 中每项 SHALL 包含 segment 序号和 reason

### Requirement: 批量导入接口（Upsert 语义）

系统 SHALL 提供批量导入接口，按章节号匹配，已存在的章节替换 title 和 content，不存在的章节新建。

#### Scenario: 批量导入全新章节
- **WHEN** 导入 50 个不存在的章节
- **THEN** 系统 SHALL 创建 50 个新章节
- **AND** novel.chapter_count SHALL 更新为 50
- **AND** 返回 created=50, updated=0, failed=0

#### Scenario: 批量导入替换已有章节
- **WHEN** 导入包含 1-20 章的 TXT 文件
- **AND** 小说已有 1-10 章
- **THEN** 1-10 章 SHALL 更新 title 和 content
- **AND** 11-20 章 SHALL 新建
- **AND** 返回 created=10, updated=10, failed=0

#### Scenario: 替换章节时保留已有资源
- **WHEN** 替换一个已有章节（该章节已生成 parsed_data、shot_images 等）
- **THEN** 系统 SHALL 仅更新 title 和 content 字段
- **AND** parsed_data、shot_images、shot_videos 等资源字段 SHALL 保持不变

#### Scenario: 部分章节导入失败
- **WHEN** 导入 50 个章节，其中 3 个解析失败
- **THEN** 系统 SHALL 成功创建/更新 47 个章节
- **AND** 返回 success=true
- **AND** failed=3, errors 数组包含 3 个失败项的详情
- **AND** message SHALL 为 "导入完成：成功 47 个，失败 3 个"

#### Scenario: 所有章节均解析失败
- **WHEN** 上传的 TXT 文件完全无法识别任何章节格式
- **THEN** 系统 SHALL 返回 success=false
- **AND** errors 数组 SHALL 包含所有失败项
- **AND** message SHALL 为 "无法解析章节，请检查文件格式"

### Requirement: ChapterRepository bulk_upsert 方法

ChapterRepository SHALL 提供 bulk_upsert 方法，支持批量 upsert 操作并返回统计信息。

#### Scenario: bulk_upsert 混合新建和更新
- **WHEN** 调用 bulk_upsert 传入 10 个章节数据
- **AND** 其中 4 个 chapter number 已存在，6 个不存在
- **THEN** 系统 SHALL 更新 4 个已有章节
- **AND** 系统 SHALL 创建 6 个新章节
- **AND** 返回 {created: 6, updated: 4, failed: 0, errors: [], chapters: [...]}

#### Scenario: bulk_upsert 遇到重复章节号
- **WHEN** 传入的章节数据中有两个相同 number 的章节
- **THEN** 系统 SHALL 将第二个重复项记录为失败
- **AND** errors 中 SHALL 包含 "章节号 X 重复"

### Requirement: 前端批量导入 UI 交互

NovelDetail 页面 SHALL 提供批量导入入口和预览确认流程。

#### Scenario: 用户点击批量导入按钮
- **WHEN** 用户点击 NovelDetail 页面的"批量导入章节"按钮
- **THEN** 系统 SHALL 打开 BatchImportModal 弹窗

#### Scenario: 用户选择文件后自动预览
- **WHEN** 用户在 BatchImportModal 中选择 TXT 文件
- **THEN** 系统 SHALL 自动调用预览接口
- **AND** 显示章节列表预览（序号、标题、字数、操作类型）
- **AND** 显示统计摘要（新增数、替换数、失败数）

#### Scenario: 预览确认导入
- **WHEN** 用户点击"确认导入"按钮
- **THEN** 系统 SHALL 调用导入接口
- **AND** 按钮 SHALL 显示 loading 状态
- **AND** 按钮 SHALL 禁用防止重复点击

#### Scenario: 导入成功
- **WHEN** 导入接口返回成功
- **THEN** 系统 SHALL 显示成功 toast 提示
- **AND** 系统 SHALL 关闭弹窗
- **AND** 系统 SHALL 刷新章节列表

#### Scenario: 导入部分成功
- **WHEN** 导入接口返回部分成功（failed > 0）
- **THEN** 系统 SHALL 显示警告提示，提示成功和失败数量
- **AND** 系统 SHALL 展示错误详情列表
- **AND** 用户 SHALL 可选择关闭详情或继续查看

#### Scenario: 导入失败
- **WHEN** 导入接口返回失败（success=false）
- **THEN** 系统 SHALL 显示错误 toast 提示
- **AND** 按钮 SHALL 恢复可用状态
- **AND** 用户 SHALL 可重新选择文件

#### Scenario: 网络请求异常
- **WHEN** 预览或导入接口网络请求失败
- **THEN** 系统 SHALL 显示错误提示 "网络请求失败，请重试"
- **AND** 按钮 SHALL 恢复可用状态

### Requirement: 国际化翻译

系统 SHALL 为批量导入功能新增的翻译 key 在 5 种语言文件中提供对应条目。

#### Scenario: 5 种语言翻译完整
- **WHEN** 新增翻译 key
- **THEN** zh-CN、en-US、ja-JP、ko-KR、zh-TW 五种语言文件 SHALL 均包含对应翻译
- **AND** 翻译 key SHALL 以 `batchImport.` 为前缀
