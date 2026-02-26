# Contributing Guide

Thank you for your interest in the AI-NovelFlow project! This document will help you understand how to contribute to the project.

## Development Standards

To maintain code quality and maintainability, we recommend following these development standards (please ask AI to refer to these standards when AI Coding):

- Keep each module functionally independent with clear, single responsibilities
- Code should be readable and maintainable, avoid redundant code, single file line count should not exceed 1000 lines
- When backend development involves database structure changes, add version upgrade migration files in the `migrations` directory. For release versions, ensure migration file compatibility and name them with release version numbers
- When cleaning up deprecated interfaces, synchronously delete all associated code, including constants, type definitions, import statements, etc.

### Frontend Development Standards

Component-based development, each component responsible for a single function, avoid complex components. Reference directory and component organization:

**Global Directories:**
- `public` directory for static assets
- `src/components` directory for global common components
- `src/pages` directory for all pages
- `src/stores` directory for state management
- `src/i18n` directory for internationalization translations
- `src/types` directory for common type definitions
- `src/constants` directory for common constant definitions
- `src/router` directory for routing configuration
- `src/api` directory for API configuration
- `src/utils` directory for common utility classes

**Page-level Directory Structure:**
- `index.tsx` page entry file
- `components` directory for page-level components
- `hooks` directory for page-level hook functions
- `stores` directory for page-level state management
- `types` directory for page-level type definitions
- `constants` directory for page-level constant definitions
- `utils` directory for page-level utility classes

**Naming Conventions:**
- Component files: PascalCase (e.g., `NovelCard.tsx`)
- Utility functions/hooks: camelCase (e.g., `useNovelStore.ts`)
- Constants: UPPER_SNAKE_CASE (e.g., `API_BASE`)
- Types/interfaces: PascalCase (e.g., `interface Novel`)

### Backend Development Standards

Modular development, each module responsible for a single function, following layered architecture:

**Directory Structure:**
- `app/api` directory for all HTTP API endpoints (routing layer)
- `app/services` directory for all business logic implementation (business layer)
- `app/repositories` directory for database operation definitions (data layer)
- `app/models` directory for database model definitions (ORM layer)
- `app/schemas` directory for all API input parameter definitions and validation
- `app/core` directory for core configuration
- `app/constants` directory for common constant definitions
- `app/utils` directory for common utility classes
- `migrations` directory for version upgrade database migration files
- `workflows` directory for system preset workflow files

**Layer Responsibilities:**
| Layer | Directory | Responsibility |
|-------|-----------|----------------|
| API | `api/` | Route definition, parameter validation, calling Service, formatting response |
| Service | `services/` | Business logic implementation, process orchestration, calling external services |
| Repository | `repositories/` | Database query encapsulation, avoid N+1 queries |
| Model | `models/` | SQLAlchemy ORM model definitions |
| Schema | `schemas/` | Pydantic models, request/response data validation |

**Naming Conventions:**
- Class names: PascalCase (e.g., `NovelRepository`)
- Functions/methods: snake_case (e.g., `get_novel_by_id`)
- Constants: UPPER_SNAKE_CASE (e.g., `MAX_RETRY_COUNT`)
- Private methods: `_` prefix (e.g., `_parse_response`)

### Internationalization Standards

The project supports 5 languages (Simplified Chinese, Traditional Chinese, English, Japanese, Korean), all user-visible text must be processed through the i18n system.

**Translation File Format Standards:**
```typescript
export default {
  // Module comment (required)
  moduleName: {
    key: 'value',
    nested: {
      key: 'value',
    },
  },

  // Next module (keep one empty line between modules)
  anotherModule: {
    key: 'value',
  },
};
```

**Important Rules:**
- Must add Chinese comment before each module
- Keep one empty line between comment and content
- Keep one empty line between modules
- **Key names must be globally unique**, avoid using the same key name in different modules
- New translations must be synchronized to all language files

**Usage in Components:**
```typescript
import { useTranslation } from '../i18n';

function MyComponent() {
  const { t } = useTranslation();
  return <h1>{t('moduleName.key')}</h1>;
}
```

## Git Workflow

### Commit Message Standards

Use Conventional Commits:

```
<type>(<scope>): <description>
```

**Type Description:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation update
- `style`: Code format (does not affect functionality)
- `refactor`: Refactoring
- `perf`: Performance optimization
- `test`: Test related
- `chore`: Build/tool related

**Examples:**
```
feat(api): add chapter video export endpoint

fix(character): fix incremental update not working during character parsing
```

## Pull Request Process

### Pre-submission Checklist

- [ ] Code follows project code standards
- [ ] i18n text has been synchronized to all language files
- [ ] Commit message follows Conventional Commits specification
- [ ] Local tests pass

### PR Title Format

```
<type>: <short description>
```

Examples:
- `feat: add video export feature`
- `fix: fix character parsing incremental update issue`

## Issue Feedback

### Bug Reports

Please include the following information:
- Problem description
- Steps to reproduce
- Expected behavior vs actual behavior
- Environment information (OS, Python version, Node.js version)
- Relevant logs

### Feature Requests

Please include the following information:
- Feature description
- Use case
- Expected implementation approach (optional)

