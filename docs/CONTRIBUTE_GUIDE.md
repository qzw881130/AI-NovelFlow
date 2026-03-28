# 代码贡献指南

感谢您对 AI-NovelFlow 项目的关注！本文档将帮助您了解如何为项目做出贡献。

## 目录

- [开发规范](#开发规范)
- [OpenSpec 驱动开发](#openspec-驱动开发)
- [Git 工作流](#git-工作流)
- [Pull Request 流程](#pull-request-流程)
- [问题反馈](#问题反馈)

---

## 开发规范

为保持代码质量和可维护性，我们建议遵循以下开发规范（AI Coding 时请要求 AI 参考本规范）：

- 各模块保持功能独立，职责明确单一
- 代码要易读易维护，避免冗余代码，单个文件行数建议不超过 1000 行
- 后端开发涉及到 db 结构变更时，需在 `migrations` 目录下新增版本升级数据库迁移文件，release 版本为保证用户平稳升级，迁移文件需确保兼容性，并以 release 版本号命名
- 清理废弃接口时需同步删除全部关联代码，包括常量、类型定义、导入语句等

### 前端开发规范

组件化开发，每个组件负责单一功能，避免复杂组件。参考目录和组件划分：

**全局目录：**
- `public` 目录下存放静态资源
- `src/components` 目录下存放全局通用组件
- `src/pages` 目录下存放所有页面
- `src/stores` 目录下存放状态管理
- `src/i18n` 目录下存放国际化翻译
- `src/types` 目录下存放通用类型定义
- `src/constants` 目录下存放通用常量定义
- `src/router` 目录下存放路由配置
- `src/api` 目录下存放接口配置
- `src/utils` 目录下存放通用工具类

**页面级目录拆分：**
- `index.tsx` 页面入口文件
- `components` 目录下存放页面级组件
- `hooks` 目录下存放页面级 hook 函数
- `stores` 目录下存放页面级状态管理
- `types` 目录下存放页面级类型定义
- `constants` 目录下存放页面级常量定义
- `utils` 目录下存放页面级工具类


### 后端开发规范

模块化开发，每个模块负责单一功能，遵循分层架构：

**目录结构：**
- `app/api` 目录下存放所有 HTTP API 接口（路由层）
- `app/services` 目录下存放所有业务逻辑实现（业务层）
- `app/repositories` 目录下存放数据库操作定义（数据层）
- `app/models` 目录下存放数据库模型定义（ORM 层）
- `app/schemas` 目录下存放所有 API 接口入参定义和校验
- `app/core` 目录下存放核心配置
- `app/constants` 目录下存放通用常量定义
- `app/utils` 目录下存放通用工具类
- `migrations` 目录下存放版本升级数据库迁移文件
- `workflows` 目录下存放系统预设工作流文件

**分层职责：**
| 层级 | 目录 | 职责 |
|------|------|------|
| API | `api/` | 路由定义、参数校验、调用 Service、格式化响应 |
| Service | `services/` | 业务逻辑实现、流程编排、调用外部服务 |
| Repository | `repositories/` | 数据库查询封装、避免 N+1 查询 |
| Model | `models/` | SQLAlchemy ORM 模型定义 |
| Schema | `schemas/` | Pydantic 模型，请求/响应数据验证 |


### 国际化规范

项目支持 5 种语言（简体中文、繁体中文、英文、日文、韩文），所有用户可见文本必须通过 i18n 系统处理。

**翻译文件格式规范：**
```typescript
export default {
  // 模块注释（必须添加）
  moduleName: {
    key: 'value',
    nested: {
      key: 'value',
    },
  },

  // 下一个模块（模块间保留一个空行）
  anotherModule: {
    key: 'value',
  },
};
```

**重要规则：**
- 每个模块前必须添加中文注释
- 注释与内容间保留一个空行
- 模块间保留一个空行
- **键名必须全局唯一**，避免不同模块使用相同键名
- 新增翻译需同步更新所有语言文件

**组件中使用：**
```typescript
import { useTranslation } from '../i18n';

function MyComponent() {
  const { t } = useTranslation();
  return <h1>{t('moduleName.key')}</h1>;
}
```

---

## OpenSpec 驱动开发

本项目采用 **OpenSpec** 作为 AI 辅助编程的核心驱动工具。所有功能开发、Bug 修复、架构变更都应通过 OpenSpec 工作流进行管理。

**OpenSpec 仓库**：https://github.com/Fission-AI/OpenSpec/blob/main/README.md

### 为什么使用 OpenSpec

- **结构化产出**：强制通过 proposal → design → specs → tasks 的流程，确保设计先行
- **规范一致性**：统一的变更管理，便于追溯和审查
- **AI 友好**：产出物格式标准化，AI 可以准确理解和执行
- **知识沉淀**：specs 目录积累项目的能力规范文档

### 目录结构

```
openspec/
├── config.yaml              # OpenSpec 全局配置
├── specs/                   # 主规范目录（能力文档）
│   ├── character-parse/
│   │   └── spec.md
│   ├── character-voice/
│   │   └── spec.md
│   ├── voice-workflow-builder/
│   │   └── spec.md
│   └── workflow-node-mapping/
│       └── spec.md
└── changes/                 # 变更目录
    ├── <change-name>/       # 进行中的变更
    │   ├── .openspec.yaml
    │   ├── proposal.md
    │   ├── design.md
    │   ├── tasks.md
    │   └── specs/           # Delta specs
    └── archive/             # 已归档的变更
        └── YYYY-MM-DD-<name>/
```

### 工作流程

标准工作流程：

```
new → continue → apply → (continue) → verify → sync → archive
```

#### 1. 创建变更

使用 `/opsx:new` 创建新的变更目录和初始配置：

```
/opsx:new
```

此命令会创建变更目录和 `.openspec.yaml` 配置文件。

#### 2. 生成产出物

使用 `/opsx:continue` 逐个生成产出物：

```
/opsx:continue
```

每次调用会生成下一个产出物，按顺序：

| 顺序 | 产出物 | 说明 |
|------|--------|------|
| 1 | `proposal.md` | 变更提案：Why、What、Impact |
| 2 | `design.md` | 技术设计：方案细节、接口定义 |
| 3 | `specs/*.md` | Delta specs：本次变更涉及的规范变更 |
| 4 | `tasks.md` | 任务清单：具体的实现步骤 |

**快捷方式**：如果需求明确，可使用 `/opsx:propose` 或 `/opsx:ff` 一次性生成所有产出物。

#### 3. 探索模式（可选）

当需求不清晰时，可在任何阶段使用 `/opsx:explore` 进入探索模式：

```
/opsx:explore
```

探索模式用于：
- 理解问题和需求
- 调查现有代码
- 澄清技术方案
- 在正式创建变更前进行思考

#### 4. 实现变更

产出物完成后，使用 `/opsx:apply` 开始实现：

```
/opsx:apply
```

AI 会按照 `tasks.md` 中的任务清单逐步执行实现。如果实现过程中发现问题，可使用 `/opsx:continue` 更新产出物。

#### 5. 验证实现

实现完成后，使用 `/opsx:verify` 验证：

```
/opsx:verify
```

验证内容包括：
- 代码是否与设计一致
- 任务是否全部完成
- 规范是否正确实现

#### 6. 同步规范

验证通过后，使用 `/opsx:sync` 将 Delta specs 同步到主 specs 目录：

```
/opsx:sync
```

此步骤将 `changes/<name>/specs/` 下的规范变更合并到 `specs/` 目录。

#### 7. 归档变更

最后使用 `/opsx:archive` 归档变更：

```
/opsx:archive
```

归档操作会将变更目录移动到 `archive/`，并按日期命名（`YYYY-MM-DD-<name>`）。

**注意**：`/opsx:archive` 会在归档前自动检查是否需要同步，如未同步会提示用户。

### 常用命令速查

| 命令 | 说明 |
|------|------|
| `/opsx:new` | 创建新变更 |
| `/opsx:continue` | 生成下一个产出物 |
| `/opsx:propose` | 快速提案（一次性生成所有产出物） |
| `/opsx:ff` | Fast-forward 模式 |
| `/opsx:explore` | 探索模式 |
| `/opsx:apply` | 开始实现 |
| `/opsx:verify` | 验证实现 |
| `/opsx:sync` | 同步 Delta specs 到主 specs |
| `/opsx:archive` | 归档变更 |
| `/opsx:bulk-archive` | 批量归档 |

### 规范文件（Specs）编写指南

规范文件位于 `openspec/specs/<capability>/spec.md`，使用以下格式：

```markdown
## Requirement: <需求标题>

<需求描述>

### Scenario: <场景标题>
- **WHEN** <触发条件>
- **THEN** 系统 SHALL <预期行为>
- **AND** 系统 SHALL <附加行为>
```

**Delta Specs**（变更目录下的 specs）使用额外标记：

- `## NEW Requirements` - 新增需求
- `## MODIFIED Requirements` - 修改需求
- `## REMOVED Requirements` - 删除需求

### 最佳实践

1. **一个变更一个功能**：保持变更范围小而专注
2. **先设计后实现**：确保 proposal 和 design 完成后再 apply
3. **任务粒度适中**：每个任务应可在 2 小时内完成
4. **及时归档**：完成的变更及时归档，避免 changes 目录堆积
5. **保持规范更新**：归档前确保 Delta specs 已同步到主 specs

---

## Git 工作流

### 提交信息规范

使用约定式提交（Conventional Commits）：

```
<类型>(<范围>): <描述>
```

**类型说明：**
- `feat`: 新功能
- `fix`: 修复 Bug
- `docs`: 文档更新
- `style`: 代码格式（不影响功能）
- `refactor`: 重构
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建/工具相关

**示例：**
```
feat(api): 添加章节视频导出接口

fix(character): 修复角色解析时增量更新不生效的问题
```

---

## Pull Request 流程

### 提交前检查清单

- [ ] 代码符合项目代码规范
- [ ] 国际化文本已同步更新到所有语言文件
- [ ] 提交信息符合约定式提交规范
- [ ] 本地测试通过

### PR 标题格式

```
<类型>: <简短描述>
```

示例：
- `feat: 添加视频导出功能`
- `fix: 修复角色解析增量更新问题`

---

## 问题反馈

### Bug 报告

请包含以下信息：
- 问题描述
- 复现步骤
- 期望行为 vs 实际行为
- 环境信息（操作系统、Python 版本、Node.js 版本）
- 相关日志

### 功能请求

请包含以下信息：
- 功能描述
- 使用场景
- 期望的实现方式（可选）

---

## 相关文档

- [README.md](../README.md) - 项目说明文档
- [OpenSpec 仓库](https://github.com/Fission-AI/OpenSpec/blob/main/README.md) - OpenSpec 官方文档