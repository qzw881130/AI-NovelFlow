# Contributing Guide

Thank you for your interest in the AI-NovelFlow project! This document will help you understand how to contribute to the project.

## Table of Contents

- [Development Standards](#development-standards)
- [OpenSpec-Driven Development](#openspec-driven-development)
- [Git Workflow](#git-workflow)
- [Pull Request Process](#pull-request-process)
- [Issue Feedback](#issue-feedback)

---

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

---

## OpenSpec-Driven Development

This project uses **OpenSpec** as the core driving tool for AI-assisted programming. All feature development, bug fixes, and architectural changes should be managed through the OpenSpec workflow.

**OpenSpec Repository**: https://github.com/Fission-AI/OpenSpec/blob/main/README.md

### Why OpenSpec

- **Structured Output**: Enforces proposal → design → specs → tasks flow, ensuring design-first approach
- **Consistency**: Unified change management for easy tracking and review
- **AI-Friendly**: Standardized artifact formats that AI can understand and execute accurately
- **Knowledge Accumulation**: specs directory accumulates project capability documentation

### Directory Structure

```
openspec/
├── config.yaml              # OpenSpec global configuration
├── specs/                   # Main specs directory (capability docs)
│   ├── character-parse/
│   │   └── spec.md
│   ├── character-voice/
│   │   └── spec.md
│   ├── voice-workflow-builder/
│   │   └── spec.md
│   └── workflow-node-mapping/
│       └── spec.md
└── changes/                 # Changes directory
    ├── <change-name>/       # Active changes
    │   ├── .openspec.yaml
    │   ├── proposal.md
    │   ├── design.md
    │   ├── tasks.md
    │   └── specs/           # Delta specs
    └── archive/             # Archived changes
        └── YYYY-MM-DD-<name>/
```

### Workflow

Standard workflow:

```
new → continue → apply → (continue) → verify → sync → archive
```

#### 1. Create Change

Use `/opsx:new` to create a new change directory and initial configuration:

```
/opsx:new
```

This command creates the change directory and `.openspec.yaml` configuration file.

#### 2. Generate Artifacts

Use `/opsx:continue` to generate artifacts one by one:

```
/opsx:continue
```

Each call generates the next artifact in order:

| Order | Artifact | Description |
|-------|----------|-------------|
| 1 | `proposal.md` | Change proposal: Why, What, Impact |
| 2 | `design.md` | Technical design: solution details, interface definitions |
| 3 | `specs/*.md` | Delta specs: specification changes for this change |
| 4 | `tasks.md` | Task list: concrete implementation steps |

**Shortcut**: If requirements are clear, use `/opsx:propose` or `/opsx:ff` to generate all artifacts at once.

#### 3. Explore Mode (Optional)

When requirements are unclear, use `/opsx:explore` at any stage to enter explore mode:

```
/opsx:explore
```

Explore mode is used for:
- Understanding problems and requirements
- Investigating existing code
- Clarifying technical solutions
- Thinking before formally creating a change

#### 4. Implement Change

After artifacts are complete, use `/opsx:apply` to start implementation:

```
/opsx:apply
```

AI will execute implementation step by step following the task list in `tasks.md`. If issues are found during implementation, use `/opsx:continue` to update artifacts.

#### 5. Verify Implementation

After implementation, use `/opsx:verify` to verify:

```
/opsx:verify
```

Verification includes:
- Code consistency with design
- All tasks completed
- Specifications correctly implemented

#### 6. Sync Specs

After verification, use `/opsx:sync` to sync Delta specs to main specs directory:

```
/opsx:sync
```

This step merges specification changes from `changes/</>/specs/` to the `specs/` directory.

#### 7. Archive Change

Finally, use `/opsx:archive` to archive the change:

```
/opsx:archive
```

Archive operation moves the change directory to `archive/` with a date-based name (`YYYY-MM-DD-<name>`).

**Note**: `/opsx:archive` will automatically check if sync is needed before archiving and prompt the user if not synced.

### Command Reference

| Command | Description |
|---------|-------------|
| `/opsx:new` | Create new change |
| `/opsx:continue` | Generate next artifact |
| `/opsx:propose` | Quick proposal (generate all artifacts at once) |
| `/opsx:ff` | Fast-forward mode |
| `/opsx:explore` | Explore mode |
| `/opsx:apply` | Start implementation |
| `/opsx:verify` | Verify implementation |
| `/opsx:sync` | Sync Delta specs to main specs |
| `/opsx:archive` | Archive change |
| `/opsx:bulk-archive` | Bulk archive |

### Specs Writing Guide

Spec files are located at `openspec/specs/<capability>/spec.md`, use the following format:

```markdown
## Requirement: <requirement title>

<requirement description>

### Scenario: <scenario title>
- **WHEN** <trigger condition>
- **THEN** system SHALL <expected behavior>
- **AND** system SHALL <additional behavior>
```

**Delta Specs** (specs in change directory) use additional markers:

- `## NEW Requirements` - New requirements
- `## MODIFIED Requirements` - Modified requirements
- `## REMOVED Requirements` - Removed requirements

### Best Practices

1. **One change, one feature**: Keep change scope small and focused
2. **Design first, implement later**: Ensure proposal and design are complete before apply
3. **Appropriate task granularity**: Each task should be completable within 2 hours
4. **Archive timely**: Archive completed changes promptly to avoid accumulation
5. **Keep specs updated**: Ensure Delta specs are synced to main specs before archiving

---

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

---

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

---

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

---

## Related Documentation

- [README.md](../README.md) - Project documentation
- [OpenSpec Repository](https://github.com/Fission-AI/OpenSpec/blob/main/README.md) - OpenSpec official documentation