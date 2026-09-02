# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI 기반 소설 동영상 변환 플랫폼

## 프로젝트 개요

NovelFlow는 소설을 자동으로 동영상으로 변환하는 AI 플랫폼입니다.

**핵심 워크플로우:**

```
┌─────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│  소설   │ → │ AI 캐릭터 │ → │ AI 장면   │ → │ AI 소품   │ → │ 캐릭터    │
│         │    │  파싱     │    │  파싱     │    │  파싱     │    │ 이미지    │
└─────────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘
                                                                    ↓
┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│  동영상   │ ← │  오디오   │ ← │  샷       │ ← │ AI 샷    │ ← │ 장면      │
│  생성     │    │  생성     │    │  이미지   │    │  분할     │    │ 이미지    │
└───────────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘
                                                        ↑
                              ┌───────────┐    ┌───────────┐
                              │   장      │ ← │ 소품      │
                              │  편집     │    │ 이미지    │
                              └───────────┘    └───────────┘
```

**상세 단계:**
1. **소설 가져오기** - 신규 생성 또는 소설 텍스트 가져오기 (TXT, EPUB 지원)
2. **AI 캐릭터 파싱** - 캐릭터 정보 자동 추출 (이름, 설명, 외모)
3. **AI 장면 파싱** - 장면 정보 자동 추출 (장면 이름, 환경 설명)
4. **AI 소품 파싱** - 소품 정보 자동 추출 (소품 이름, 외모 설명)
5. **캐릭터 이미지 생성** - 각 캐릭터에 대해 AI 이미지 생성
6. **장면 이미지 생성** - 각 장면에 대한 참조 이미지 생성
7. **소품 이미지 생성** - 각 소품에 대한 참조 이미지 생성
8. **장 편집 / AI 샷 분할** - 장 내용 편집, AI가 자동으로 샷으로 분할
9. **샷 이미지 생성** - 샷 설명에 따라 장면 이미지 생성
10. **오디오 생성** - 샷의 내레이션/효과음 생성 (선택사항)
11. **동영상 생성** - Video Director로 단일 프레임, 시작/끝 프레임 또는 다중 키프레임 샷 동영상을 생성하고 완전한 동영상으로 합성

**주요 특징:**
- 장회체 소설 파싱 지원
- 캐릭터 일관성 (여러 장면에서 캐릭터 외모 유지)
- 장면 일관성 (여러 샷에서 장면 환경 유지)
- 자동 샷 생성 및 동영상 합성

## 인터페이스 미리보기

<img src="docs/index-en.png" alt="인터페이스 미리보기" width="800">

## 비디오 소개

📺 <a href="https://www.bilibili.com/video/BV1VdZbBDEXF" target="_blank">Bilibili: AI-NovelFlow 소설 동영상 변환 플랫폼 소개</a>

📺 <a href="https://www.youtube.com/watch?v=IlMbeDme2F8" target="_blank">YouTube: AI-NovelFlow 소설 동영상 변환 플랫폼 소개</a>

📺 <a href="https://www.youtube.com/watch?v=DybveicQ9eQ" target="_blank">YouTube: Windows에서 오픈소스 프로젝트 설치 방법</a>

## 커뮤니티

| Telegram 그룹 | QQ 그룹 |
|:---:|:---:|
| <a href="https://t.me/AI_NovelFlow" target="_blank">@AI_NovelFlow</a> | 1083469624 |
| <img src="docs/telegram_group.png" width="200" alt="Telegram 그룹 QR 코드"> | <img src="docs/qq_group.png" width="200" alt="QQ 그룹 QR 코드"> |

## 기술 스택

- **프론트엔드**: React + TypeScript + Tailwind CSS + Vite
- **상태 관리**: Zustand (전역 상태 + 국제화/타임존 상태)
- **백엔드**: FastAPI + SQLAlchemy + SQLite
- **AI**: DeepSeek API / OpenAI API / Gemini API + ComfyUI
- **동영상 생성**: MiniMax H3 이미지-동영상, 시작/끝 프레임 동영상, 다중 키프레임 동영상
- **국제화**: 커스텀 i18n 구현 (5개 언어 지원)

## 주요 기능

- **소설 관리**: 신규 생성, 편집, 삭제 지원, 자동 장회체 파싱
- **캐릭터 도감**: AI 자동 캐릭터 파싱, 캐릭터 이미지 생성 및 일관성 유지
- **장면 도감**: AI 자동 장면 파싱, 장면 참조 이미지 생성 및 환경 설정 지원
- **샷 생성**: AI 자동 장 분할, 일괄 이미지 생성, 구조화 편집, 상태 복구 지원
- **Video Director**: 단일 프레임, 시작/끝 프레임, 3키프레임, 4키프레임 동영상 계획을 지원하고 AI 호출 결과와 최종 Prompt를 보존
- **동영상 합성**: 샷 동영상과 다중 Clip 출력을 완전한 장 동영상으로 합성
- **워크플로우 관리**: 커스텀 ComfyUI 워크플로우, 노드 매핑 설정
- **작업 큐**: 백그라운드 비동기 작업 처리, 실시간 작업 모니터링
- **프리셋 테스트 케이스**: 「어린 말의 강 걷기」「빨간 모자」「벌거벗은 임금님」등 테스트 케이스 내장
- **다국어 지원**: 간체 중국어, 번체 중국어, 영어, 일본어, 한국어 인터페이스
- **타임존 지원**: 사용자가 타임존을 커스터마이즈 가능, 모든 시간 표시를 지정 타임존으로 변환

## 프로젝트 구조

```
AI-NovelFlow/
├── backend/              # FastAPI 백엔드
│   ├── app/
│   │   ├── api/         # API 라우트
│   │   ├── core/        # 코어 설정
│   │   ├── models/      # 데이터베이스 모델
│   │   ├── repositories/ # 데이터 리포지토리 계층
│   │   ├── schemas/     # Pydantic 모델
│   │   ├── services/    # 비즈니스 로직 (LLM, ComfyUI)
│   │   └── utils/       # 유틸리티 함수
│   ├── migrations/      # 데이터베이스 마이그레이션 스크립트
│   ├── prompt_templates/ # 프롬프트 템플릿 파일
│   ├── workflows/       # ComfyUI 워크플로우 설정
│   ├── user_workflows/  # 사용자 커스텀 워크플로우
│   ├── user_story/      # 생성된 이미지/동영상 저장 디렉토리
│   └── main.py
├── frontend/            # React 프론트엔드
│   └── my-app/
│       ├── src/
│       │   ├── components/  # 컴포넌트
│       │   ├── i18n/        # 국제화 번역 파일
│       │   ├── pages/       # 페이지
│       │   ├── stores/      # 상태 관리
│       │   └── types/       # TypeScript 타입
│       └── package.json
├── windows_gpu_monitor/ # Windows GPU 모니터링 서비스 (선택사항)
│   ├── gpu_monitor.py   # GPU 모니터링 서비스
│   ├── requirements.txt # 의존성
│   └── start.bat        # Windows 시작 스크립트
├── debug/workflows/     # 디버그용 워크플로우 예시, 시스템 기본값으로 로드하지 않음
└── README.md
```

## 빠른 시작

### 백엔드 시작

```bash
cd backend
source venv/bin/activate  # Windows: venv\Scripts\activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

백엔드 서비스는 http://localhost:8000 에서 실행

### 프론트엔드 시작

```bash
cd frontend/my-app
npm install
npm run dev
```

프론트엔드 서비스는 http://localhost:5173 에서 실행

## API 문서

백엔드 시작 후 접속: http://localhost:8000/docs

## 설정 설명

### 1. LLM API 설정

여러 LLM 제공자 지원:
- **DeepSeek** (기본): https://api.deepseek.com
- **OpenAI**: https://api.openai.com
- **Gemini**: https://generativelanguage.googleapis.com
- **Anthropic**: https://api.anthropic.com
- **Azure OpenAI**: 커스텀 Azure 엔드포인트

【시스템 설정】페이지에서 API Key와 프록시를 설정 (필요한 경우).

### 2. ComfyUI 설정

- **ComfyUI 주소**: 기본 http://localhost:8188
- **워크플로우 설정**: 커스텀 워크플로우 업로드 지원, 노드 매핑 필요
  - 캐릭터 생성: 프롬프트 노드 + 이미지 저장 노드
  - 장면 생성: 프롬프트 노드 + 이미지 저장 노드 + 너비/높이 노드
  - 샷 이미지: 프롬프트 노드 + 이미지 저장 노드 + 너비/높이 노드
  - 단일 프레임 동영상: 프롬프트 노드 + 동영상 저장 노드 + 참조 이미지 노드 + 길이 노드
  - 시작/끝 프레임 동영상: 프롬프트 노드 + 첫 이미지 노드 + 마지막 이미지 노드 + 동영상 저장 노드 + 길이 노드
  - 3/4키프레임 동영상: 프롬프트 노드 + 시작 참조 노드 + 키프레임 노드 + 동영상 저장 노드 + 길이 노드
  - 키프레임 이미지: 프롬프트 노드 + 이미지 저장 노드 + 참조 이미지 노드

시스템 워크플로우는 `backend/workflows/`에 저장되며 `backend/app/constants/workflow.py`에서 등록하고 기본값을 선택합니다. 사용자가 업로드한 워크플로우는 `backend/user_workflows/`에 저장됩니다. `debug/workflows/MiniMax H3/`는 디버그와 워크플로우 비교 전용이며 시스템 기본 워크플로우로 로드되지 않습니다.

#### 2.1 모델 파일

디렉토리는 `ComfyUI/models/...` 기준입니다; ComfyUI-Manager를 사용하는 경우에도 일반적으로 이러한 디렉토리를 스캔합니다.

| 모델 파일명 | 타입 | 주요 용도 | 사용되는 워크플로우 | 권장 디렉토리 |
|-----------|------|---------|------------------|-------------|
| `minimax_h3_ref2va_bf16.safetensors` | diffusion model | MiniMax H3 참조 이미지-동영상 메인 모델 | 단일 프레임, 시작/끝 프레임, 3키프레임, 4키프레임 동영상 워크플로우 | `models/diffusion_models/` |
| `qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | text encoder | MiniMax H3 텍스트/비전 인코딩 | MiniMax H3 동영상 워크플로우 | `models/text_encoders/` |
| `minimax_h3_video_vae_fp16.safetensors` | video VAE | MiniMax H3 동영상 VAE | MiniMax H3 동영상 워크플로우 | `models/vae/` |
| `minimax_h3_audio_vae_fp32.safetensors` | audio VAE | MiniMax H3 오디오 VAE | MiniMax H3 동영상 워크플로우 | `models/vae/` |
| `minimax_h3_fl2v_lightx2v_turbo_4step_v0.1_comfy.safetensors` | LoRA | MiniMax H3 가속 LoRA | MiniMax H3 가속 워크플로우 | `models/loras/` |
| `ae.safetensors` | VAE / AE | Z-image-turbo 및 일부 기본 캐릭터 워크플로우에서 VAE/AE로 사용 | Z-image-turbo 단일 생성 / 시스템 기본-캐릭터 생성 | `models/vae/` |
| `flux-2-klein-9b.safetensors` | UNet | Flux2-Klein 이미지 편집/샷 이미지 생성 | 샷 이미지, 키프레임 이미지, 기본 캐릭터 워크플로우 | `models/unet/` |
| `flux2-vae.safetensors` | VAE | Flux2 VAE | Flux2-Klein 이미지 편집/샷 이미지 워크플로우 | `models/vae/` |
| `qwen_3_8b.safetensors` / `qwen_3_8b_fp8mixed.safetensors` | text encoder | Flux2 텍스트 인코딩 | Flux2-Klein 이미지 편집/샷 이미지 워크플로우 | `models/clip/` |
| `qwen_image_edit_2511_fp8mixed.safetensors` | diffusion model | Qwen-Edit-2511 이미지 편집 | Qwen-Edit-2511 샷 참조 워크플로우 | `models/diffusion_models/` |
| `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors` | LoRA | Qwen-Edit-2511 4단계 가속 | Qwen-Edit-2511 샷 참조 워크플로우 | `models/loras/` |
| `qwen_image_vae.safetensors` | VAE | Qwen Image VAE | Qwen-Edit-2511 샷 참조 워크플로우 | `models/vae/` |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | text encoder | Qwen-Edit-2511 텍스트/비전 인코딩 | Qwen-Edit-2511 샷 참조 워크플로우 | `models/clip/` |
| `z_image_turbo_bf16.safetensors` | UNet | Z-image-turbo 단일 생성 UNet | Z-image-turbo 단일 생성 / 시스템 기본-캐릭터 생성 | `models/unet/` |
| `qwen_3_4b.safetensors` | text encoder | Z-image-turbo 텍스트 인코딩 | Z-image-turbo 단일 생성 / 시스템 기본-캐릭터 생성 | `models/clip/` |
| `Qwen3.8-27B-Q4_K_M.gguf` / `mmproj-F16.gguf` | LLM / projector | 디버그 워크플로우의 로컬 LLM Prompt 확장 | `debug/workflows/MiniMax H3/` LLM 디버그 워크플로우 | `models/LLM/` |

#### 2.2 서드파티 노드 패키지

| 서드파티 노드 패키지 | GitHub 저장소 | 워크플로우의 노드 class_type |
|-------------------|--------------|---------------------------|
| **MiniMax H3** | ComfyUI MiniMax H3 노드 | `MiniMaxH3ReferenceToVideo`, `MiniMaxH3SigmaShift`, `MiniMaxH3MemoryEfficientSageAttentionPatch`, `MiniMaxH3PromptEnhancerT8` |
| **Flux2 / Qwen Image Edit** | Flux2, Qwen-Edit 대응 ComfyUI 노드 | `Flux2Scheduler`, `EmptyFlux2LatentImage`, `TextEncodeQwenImageEditPlusAdvance_lrzjason` |
| **VideoHelperSuite / VHS** | [Kosinkadink/ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | `VHS_VideoCombine` |
| **Easy-Use** | [yolain/ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) | `easy int`, `easy cleanGpuUsed`, `easy showAnything` |
| **LayerStyle / LayerUtility** | [chflame163/ComfyUI_LayerStyle](https://github.com/chflame163/ComfyUI_LayerStyle) | `LayerUtility: ImageScaleByAspectRatio V2` |
| **Comfyroll** | [Suzie1/ComfyUI_Comfyroll_CustomNodes](https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes) | `CR Prompt Text`, `CR Text` |
| **FizzNodes / ConcatStringSingle** | [FizzleDorf/ComfyUI_FizzNodes](https://github.com/FizzleDorf/ComfyUI_FizzNodes) | `ConcatStringSingle` |
| **comfyui-various / JWInteger** | [jamesWalker55/comfyui-various](https://github.com/jamesWalker55/comfyui-various) | `JWInteger` |
| **ReservedVRAM** | [Windecay/ComfyUI-ReservedVRAM](https://github.com/Windecay/ComfyUI-ReservedVRAM) | `ReservedVRAMSetter` |
| **Qwen3-VL-Instruct / Qwen3_VQA** | [luvenisSapiens/ComfyUI_Qwen3-VL-Instruct](https://github.com/IuvenisSapiens/ComfyUI_Qwen3-VL-Instruct) | `Qwen3_VQA` |
| **Comfyui-zhenzhen** | [T8mars/Comfyui-zhenzhen](https://github.com/T8mars/Comfyui-zhenzhen) | `Zhenzhen_nano_banana`, `Zhenzhen API Settings` |

### 3. Windows GPU 모니터링 (선택사항)

ComfyUI가 원격 Windows 서버에서 실행되는 경우, `windows_gpu_monitor` 서비스를 배포하여 실시간 GPU 상태를 가져올 수 있습니다.

**기능**:
- 실시간 GPU 사용률, 온도, VRAM 모니터링
- 메모리 사용 상황 모니터링
- 큐 작업 수 표시

**배포 단계**:

```bash
cd windows_gpu_monitor

# 의존성 설치
pip install -r requirements.txt

# 서비스 시작
start.bat
```

서비스는 기본적으로 http://localhost:5000 에서 실행

**접속 테스트**:
- 홈: http://localhost:5000/
- GPU 상태: http://localhost:5000/gpu-stats

### 4. 프롬프트 템플릿 설정

커스터마이즈 지원:
- AI 캐릭터 파싱 시스템 프롬프트
- 캐릭터 생성 프롬프트 템플릿
- 장 분할 프롬프트 템플릿

### 5. 국제화 및 타임존 설정

**언어 설정**:
- 간체 중국어 (zh-CN)
- 번체 중국어 (zh-TW)
- English (en-US)
- 日本語 (ja-JP)
- 한국어 (ko-KR)

**타임존 설정**:
- 전 세계 주요 타임존 지원
- 모든 시간 표시 (작업 목록, LLM 로그 등)를 지정 타임존으로 변환
- 백엔드는 UTC 시간을 통일 저장, 프론트엔드는 사용자 설정에 따라 동적 변환

【시스템 설정】→【언어와 타임존】페이지에서 설정.

## 개발 로드맵

- [x] 프로젝트 초기화
- [x] 기본 페이지 (웰컴, 설정, 소설 목록)
- [x] 백엔드 API 프레임워크
- [x] DeepSeek API 통합 (텍스트 파싱)
- [x] ComfyUI API 통합 (이미지/동영상 생성)
- [x] 작업 큐 시스템
- [x] 캐릭터 도감 관리
- [x] 워크플로우 관리 시스템
- [x] JSON 파싱 로그
- [x] 프리셋 테스트 케이스
- [x] 다국어 지원 (중/영/일/한/번체)
- [x] 타임존 지원
- [x] Video Director (단일 프레임, 시작/끝 프레임, 3/4키프레임, 다중 Clip 순차 생성)
- [x] 영속화된 샷 이미지 일괄 큐 (서비스 재시작 복구 및 일괄 취소 지원)
- [x] 동영상 합성 기능 (샷 동영상, 다중 Clip 병합 지원)

## 사용 설명

### 1. 소설 신규 생성
- 【소설 생성】을 클릭하여 소설 생성
- 또는 프리셋 테스트 케이스를 선택하여 빠른 체험

### 2. AI 캐릭터, 장면 및 소품 파싱
- 소설 상세 페이지에서 【AI 캐릭터 분석】을 클릭하여 캐릭터 정보 추출
- 【AI 장면 분석】을 클릭하여 장면 정보 추출
- 【AI 소품 분석】을 클릭하여 소품 정보 추출
- 장 범위 지정 및 증분 업데이트 지원

### 3. 캐릭터, 장면 및 소품 이미지 생성
- 【캐릭터】페이지로 들어가 【AI로 모든 캐릭터 이미지 생성】을 클릭
- 【장면】페이지로 들어가 【모든 장면 이미지 생성】을 클릭
- 【소품】페이지로 들어가 【모든 소품 이미지 생성】을 클릭

### 4. 장 편집 및 AI 샷 분할
- 【장 생성】페이지로 들어가 【AI 샷 분할】을 클릭하여 자동으로 샷으로 분할
- 【장 편집】페이지로 들어가 장 내용 편집; 편집 중 캐릭터, 장면, 소품의 증분 파싱 지원

### 5. 샷 이미지 생성
- 【모든 샷 이미지 생성】을 클릭해 영속화된 일괄 작업 생성
- 미생성 샷만 선택하거나 기존 AI Prompt를 재사용해 LLM 호출을 건너뛸 수 있음

### 6. 오디오 생성 (선택사항)
- 【모든 오디오 생성】을 클릭하여 샷의 내레이션/효과음 생성

### 7. 동영상 생성
- 【동영상 생성】에서 Video Director로 동영상 모드를 계획
- 단일 프레임 모드는 기본 스토리보드 이미지를 재사용
- 시작/끝 프레임 모드는 기본 스토리보드를 START로 재사용하고 먼저 END 키프레임 이미지를 생성
- 다중 키프레임 모드는 최대 Clip 길이에 따라 execution windows를 나누며 각 Clip은 3개 또는 4개 키프레임으로 순차 생성
- 【동영상 병합】을 클릭하여 모든 클립을 완전한 동영상으로 합성

## 기여하기

프로젝트에 기여를 환영합니다! [기여 가이드](docs/CONTRIBUTE_GUIDE_EN.md)를 읽고 개발에 참여하는 방법을 알아보세요.

## License

이 프로젝트는 GNU General Public License v3.0에 따라 라이선스가 부여됩니다 - 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.
