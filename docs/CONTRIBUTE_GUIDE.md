# 代码贡献指南

感谢您对 AI-NovelFlow 项目的关注！本文档将帮助您了解如何为项目做出贡献。

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

**命名约定：**
- 组件文件：PascalCase（如 `NovelCard.tsx`）
- 工具函数/hook：camelCase（如 `useNovelStore.ts`）
- 常量：UPPER_SNAKE_CASE（如 `API_BASE`）
- 类型/接口：PascalCase（如 `interface Novel`）

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

**命名约定：**
- 类名：PascalCase（如 `NovelRepository`）
- 函数/方法：snake_case（如 `get_novel_by_id`）
- 常量：UPPER_SNAKE_CASE（如 `MAX_RETRY_COUNT`）
- 私有方法：`_` 前缀（如 `_parse_response`）

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

