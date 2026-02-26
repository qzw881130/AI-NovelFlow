# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI 기반 소설 동영상 변환 플랫폼

## 프로젝트 개요

NovelFlow는 소설을 자동으로 동영상으로 변환하는 AI 플랫폼입니다.

**핵심 워크플로우:**

```
┌─────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐    ┌───────────┐
│  소설   │ → │ AI 캐릭터 │ → │ AI 장면   │ → │ 캐릭터    │ → │ 장면      │
│         │    │  파싱     │    │  파싱     │    │ 이미지    │    │ 이미지    │
└─────────┘    └───────────┘    └───────────┘    └───────────┘    └───────────┘
                                                            ↓
┌───────────┐    ┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  동영상   │ ← │  전환         │ ← │  샷           │ ← │  샷           │
│  합성     │    │  동영상 생성  │    │  동영상 생성  │    │  이미지 생성  │
└───────────┘    └───────────────┘    └───────────────┘    └───────┬───────┘
                                                                    ↑
                              ┌───────────────┐    ┌───────────┐    │
                              │ 통합 캐릭터   │ ← │  JSON     │ ← ┘
                              │ 이미지 생성   │    │ 구조      │
                              └───────────────┘    └───────────┘
                                                              ↑
                                              ┌───────────┐    │
                                              │   장      │ ← ┘
                                              │  편집     │
                                              │ AI 샷    │
                                              │  분할     │
                                              └───────────┘
```

**상세 단계:**
1. **소설 가져오기** - 신규 생성 또는 소설 텍스트 가져오기 (TXT, EPUB 지원)
2. **AI 캐릭터 파싱** - 캐릭터 정보 자동 추출 (이름, 설명, 외모)
3. **AI 장면 파싱** - 장면 정보 자동 추출 (장면 이름, 환경 설명)
4. **캐릭터 이미지 생성** - 각 캐릭터에 대해 AI 이미지 생성
5. **장면 이미지 생성** - 각 장면에 대한 참조 이미지 생성 (선택사항)
6. **장 편집 / AI 샷 분할** - 장 내용 편집, AI가 자동으로 샷으로 분할; 편집 중 캐릭터와 장면의 증분 파싱 지원
7. **JSON 구조** - 샷 데이터 생성 (캐릭터, 장면, 샷 설명)
8. **통합 캐릭터 이미지 생성** - 여러 캐릭터를 참조 이미지로 통합
9. **샷 이미지 생성** - 샷 설명에 따라 장면 이미지 생성
10. **샷 동영상 생성** - 샷 이미지를 동영상 클립으로 변환
11. **전환 동영상 생성** - 샷 사이에 전환 동영상 생성 (선택사항)
12. **동영상 합성** - 모든 클립을 완전한 동영상으로 합성

**주요 특징:**
- 장회체 소설 파싱 지원
- 캐릭터 일관성 (여러 장면에서 캐릭터 외모 유지)
- 장면 일관성 (여러 샷에서 장면 환경 유지)
- 자동 샷 생성 및 동영상 합성

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
- **동영상 생성**: LTX-2 동영상 생성 모델
- **국제화**: 커스텀 i18n 구현 (5개 언어 지원)

## 주요 기능

- **소설 관리**: 신규 생성, 편집, 삭제 지원, 자동 장회체 파싱
- **캐릭터 도감**: AI 자동 캐릭터 파싱, 캐릭터 이미지 생성 및 일관성 유지
- **장면 도감**: AI 자동 장면 파싱, 장면 참조 이미지 생성 및 환경 설정 지원
- **샷 생성**: AI 자동 장 분할, 일괄 이미지 및 동영상 생성 지원
- **전환 동영상**: 칵메라 전환, 라이팅 전환, 오클루전 전환 지원
- **동영상 합성**: 샷 동영상을 장 동영상으로 합성, 자동 전환 삽입
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
│   ├── user_story/      # 생성된 이미지/동영상 저장 디렉토리
│   ├── user_workflows/  # 사용자 커스텀 워크플로우
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
  - 샷 동영상: 프롬프트 노드 + 동영상 저장 노드 + 참조 이미지 노드
  - 전환 동영상: 첫 프레임 노드 + 마지막 프레임 노드 + 동영상 저장 노드

#### 2.1 모델 파일

디렉토리는 `ComfyUI/models/...` 기준입니다; ComfyUI-Manager를 사용하는 경우에도 일반적으로 이러한 디렉토리를 스캔합니다.

| 모델 파일명 | 타입 | 주요 용도 | 사용되는 워크플로우 | 권장 디렉토리 |
|-----------|------|---------|------------------|-------------|
| `ltx-2-19b-dev-fp8.safetensors` | checkpoint / 메인 모델 | LTX2 전환(가림/조명/카메라) 동영상 생성 | LTX2 가림 전환 / 조명 전환 / 카메라 전환 | `models/checkpoints/` |
| `ltx-2-19b-distilled-fp8.safetensors` | checkpoint / 메인 모델 | LTX2 동영상 생성(직접/확장) | LTX2 동영상 생성-직접 / 확장 | `models/checkpoints/` |
| `gemma_3_12B_it_fp8_e4m3fn.safetensors` | text encoder (LTX 텍스트 인코더) | LTX2 텍스트 인코딩 | 모든 LTX2 워크플로우(전환/동영상 생성) | `models/text_encoders/` |
| `ltx-2-19b-distilled-lora-384.safetensors` | LoRA | LTX2 증류 LoRA(향상/증류 프로세스 매칭) | 주로 전환 워크플로우 | `models/loras/` |
| `ltx-2-19b-lora-camera-control-dolly-left.safetensors` | LoRA | LTX2 카메라 제어 (dolly-left) | 주로 전환 워크플로우 | `models/loras/` |
| `ltx-2-spatial-upscaler-x2-1.0.safetensors` | upscale model (latent upscaler) | LTX2 latent 공간 업스케일 x2 | 주로 전환 워크플로우 | `models/upscale_models/` |
| `ae.safetensors` | VAE / AE | Z-image-turbo 및 일부 기본 캐릭터 워크플로우에서 VAE/AE로 사용 | Z-image-turbo 단일 생성 / 시스템 기본-캐릭터 생성 | `models/vae/` |
| `flux-2-klein-9b.safetensors` | UNet | Flux2-Klein 샷 이미지 생성 UNet | Flux2-Klein-9B 샷 이미지 / 시스템 기본-캐릭터 생성 | `models/unet/` |
| `flux2-vae.safetensors` | VAE | Flux2의 VAE | Flux2-Klein-9B 샷 이미지 / 시스템 기본-캐릭터 생성 | `models/vae/` |
| `qwen_3_8b.safetensors` | text encoder | Flux2 텍스트 인코딩 | Flux2-Klein-9B 샷 이미지 / 시스템 기본-캐릭터 생성 | `models/clip/` |
| `z_image_turbo_bf16.safetensors` | UNet | Z-image-turbo 단일 생성 UNet | Z-image-turbo 단일 생성 / 시스템 기본-캐릭터 생성 | `models/unet/` |
| `qwen_3_4b.safetensors` | text encoder | Z-image-turbo 텍스트 인코딩 | Z-image-turbo 단일 생성 / 시스템 기본-캐릭터 생성 | `models/clip/` |

#### 2.2 서드파티 노드 패키지

| 서드파티 노드 패키지 | GitHub 저장소 | 워크플로우의 노드 class_type |
|-------------------|--------------|---------------------------|
| **LTXVideo / LTXV** | [Lightricks/ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) | `LTXAVTextEncoderLoader`, `LTXVScheduler`, `LTXV*`, `LTXAV*`, `Painter*` |
| **VideoHelperSuite / VHS** | [Kosinkadink/ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | `VHS_VideoCombine` |
| **Easy-Use** | [yolain/ComfyUI-Easy-Use](https://github.com/yolain/ComfyUI-Easy-Use) | `easy int`, `easy cleanGpuUsed`, `easy showAnything` |
| **LayerStyle / LayerUtility** | [chflame163/ComfyUI_LayerStyle](https://github.com/chflame163/ComfyUI_LayerStyle) | `LayerUtility: ImageScaleByAspectRatio V2` |
| **Comfyroll** | [Suzie1/ComfyUI_Comfyroll_CustomNodes](https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes) | `CR Prompt Text`, `CR Text` |
| **FizzNodes / ConcatStringSingle** | [FizzleDorf/ComfyUI_FizzNodes](https://github.com/FizzleDorf/ComfyUI_FizzNodes) | `ConcatStringSingle` |
| **comfyui-various / JWInteger** | [jamesWalker55/comfyui-various](https://github.com/jamesWalker55/comfyui-various) | `JWInteger` |
| **ReservedVRAM** | [Windecay/ComfyUI-ReservedVRAM](https://github.com/Windecay/ComfyUI-ReservedVRAM) | `ReservedVRAMSetter` |
| **Qwen3-VL-Instruct / Qwen3_VQA** | [luvenisSapiens/ComfyUI_Qwen3-VL-Instruct](https://github.com/luvenisSapiens/ComfyUI_Qwen3-VL-Instruct) | `Qwen3_VQA` |
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
- [x] 동영상 합성 기능 (샷 동영상 병합, 전환 삽입 지원)

## 사용 설명

### 1. 소설 신규 생성
- 【소설 생성】을 클릭하여 소설 생성
- 또는 프리셋 테스트 케이스를 선택하여 빠른 체험

### 2. AI 캐릭터 및 장면 파싱
- 소설 상세 페이지에서 【AI 캐릭터 분석】을 클릭하여 캐릭터 정보 추출
- 【AI 장면 분석】을 클릭하여 장면 정보 추출
- 장 범위 지정 및 증분 업데이트 지원

### 3. 캐릭터 및 장면 이미지 생성
- 【캐릭터】페이지로 들어가 【AI로 모든 캐릭터 이미지 생성】을 클릭
- 【장면】페이지로 들어가 【모든 장면 이미지 생성】을 클릭 (선택사항)

### 4. 장 편집 및 AI 샷 분할
- 【장 생성】페이지로 들어가 【AI 샷 분할】을 클릭하여 자동으로 샷으로 분할
- 【장 편집】페이지로 들어가 장 내용 편집; 편집 중 캐릭터와 장면의 증분 파싱 지원

### 5. 샷 이미지 생성
- 【모든 샷 이미지 생성】을 클릭

### 6. 샷 동영상 생성
- 샷 이미지 생성이 완료된 후
- 【모든 샷 동영상 생성】을 클릭

### 7. 전환 동영상 생성 (선택사항)
- 샷 사이에 전환 동영상 생성

### 8. 동영상 병합
- 【동영상 병합】을 클릭하여 모든 클립을 완전한 동영상으로 합성

## 기여하기

프로젝트에 기여를 환영합니다! [기여 가이드](docs/CONTRIBUTE_GUIDE_EN.md)를 읽고 개발에 참여하는 방법을 알아보세요.

## License

MIT
