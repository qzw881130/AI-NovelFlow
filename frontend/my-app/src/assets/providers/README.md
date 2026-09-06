# Provider Logos

Local, vendored SVG brand artwork used by `src/components/ProviderLogo.tsx`.
Fetched on 2026-09-06. The URLs below are provenance only: the application
imports local files through Vite and never requests a remote logo at runtime.
Artwork is copied without changing paths or colors (only a trailing newline).

| Provider key | Local file | Catalog SVG source | Catalog license |
| --- | --- | --- | --- |
| `deepseek` | `deepseek.svg` | [Lobe Icons 1.95.0, DeepSeek](https://unpkg.com/@lobehub/icons-static-svg@1.95.0/icons/deepseek-color.svg) | MIT |
| `openai` | `openai.svg` | [Simple Icons 13.0.0, OpenAI](https://cdn.jsdelivr.net/npm/simple-icons@13.0.0/icons/openai.svg) | CC0-1.0 |
| `gemini` | `gemini.svg` | [Simple Icons 13.0.0, Google Gemini](https://cdn.jsdelivr.net/npm/simple-icons@13.0.0/icons/googlegemini.svg) | CC0-1.0 |
| `anthropic` | `anthropic.svg` | [Simple Icons 13.0.0, Anthropic](https://cdn.jsdelivr.net/npm/simple-icons@13.0.0/icons/anthropic.svg) | CC0-1.0 |
| `azure` | `azure.svg` | [Simple Icons 11.0.0, Microsoft Azure](https://cdn.jsdelivr.net/npm/simple-icons@11.0.0/icons/microsoftazure.svg) | CC0-1.0 |
| `aliyun-bailian` | `aliyun-bailian.svg` | [Lobe Icons 1.95.0, BaiLian](https://unpkg.com/@lobehub/icons-static-svg@1.95.0/icons/bailian-color.svg) | MIT |
| `ollama` | `ollama.svg` | [Simple Icons 15.0.0, Ollama](https://cdn.jsdelivr.net/npm/simple-icons@15.0.0/icons/ollama.svg) | CC0-1.0 |
| `custom` | None | Not a brand; rendered as a neutral `</>` text placeholder | Not applicable |

## Provenance And Limits

- [Simple Icons](https://github.com/simple-icons/simple-icons) is a standard brand vector catalog, not a claim of vendor endorsement. Its [CC0 license](https://cdn.jsdelivr.net/npm/simple-icons@13.0.0/LICENSE.md) and [CC0 legal terms](https://creativecommons.org/publicdomain/zero/1.0/legalcode) do not grant trademark rights.
- [Lobe Icons](https://github.com/lobehub/lobe-icons) is a third-party AI brand vector catalog. Its [published package metadata](https://unpkg.com/@lobehub/icons-static-svg@1.95.0/package.json) declares MIT; the [upstream license](https://cdn.jsdelivr.net/gh/lobehub/lobe-icons@master/LICENSE) is reproduced in `LICENSE-LobeHub.txt`.
- The [DeepSeek official site](https://www.deepseek.com/) was inspected and contains the whale mark in its inline header artwork. The vendored file is the catalog's compact standalone whale, not a direct export of that header.
- The [official Bailian console](https://bailian.console.aliyun.com/) was inspected but did not expose a standalone SVG brand download in its HTML. The catalog's BaiLian vector is used, not an invented logo, Alibaba Cloud parent logo, or Qwen model logo. A first-party downloadable SVG/license was not established for Bailian.
- All seven branded providers have catalog artwork. These are pinned catalog snapshots, not a guarantee of the latest brand redesign or first-party distribution. Anthropic uses the company mark, Azure OpenAI uses the Azure mark, and Gemini uses the monochrome catalog sparkle.
- Selection uses provider keys from `LLMProvider`/`LLM_PROVIDER_PRESETS`, never model-name inference: a DeepSeek model served by Bailian still displays Bailian.
- Unknown provider keys have a neutral `?` placeholder with the caller's accessible label and tooltip. No fictitious brand artwork or generic Lucide substitute is used for known brands.
- Log labels include the exact provider and model ID via native `title` and `aria-label`. Native hover tooltips are browser-dependent on touch/keyboard; the existing log details action still exposes the model as text.
- Brand names and marks remain the property of their respective owners. Catalog licensing does not waive brand usage rules or imply endorsement.
