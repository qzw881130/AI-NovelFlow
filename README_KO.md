# AI-NovelFlow

**[简体中文](README.md) | [繁體中文](README_TW.md) | [English](README_EN.md) | [日本語](README_JA.md) | [한국어](README_KO.md)**

AI 기반 소설 동영상 변환 플랫폼

## 프로젝트 개요

NovelFlow는 소설 본문, 인물과 장면 설정, 샷 이미지, 오디오, 동영상 작업을 편집 가능한 제작 흐름으로 연결합니다. 각 단계를 확인하며 진행하거나 장과 샷을 일괄 처리할 수 있습니다.

**제작 흐름:** TXT/EPUB 또는 예제 소설 가져오기 → AI로 인물·장면·소품 추출 → 참조 이미지와 음색 준비 → 장 편집 및 샷 분할 → 샷 이미지 생성·평가 → Video Director로 Clip 계획·생성 → 장/소설 동영상 병합 → 표지 제작 및 선택적으로 YouTube 업로드.

Video Director는 다중 참조 이미지 생성, 동영상 이어 만들기, 시간 앵커 기반 확장을 지원합니다. 프롬프트, 작업, 키프레임, 결과를 저장하여 검토하고 다시 시도할 수 있습니다.

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

- **프론트엔드**: React, TypeScript, Tailwind CSS, Vite, Zustand
- **백엔드**: FastAPI, SQLAlchemy, SQLite, 백그라운드 작업과 파일 저장
- **AI 및 미디어**: 설정 가능한 LLM, ComfyUI, FFmpeg. 이미지 프리셋은 Moss Image와 Qwen Image 2.1, 동영상은 MiniMax H3, 오디오는 Qwen3-TTS 사용
- **화면**: 중국어 간체/번체, 영어, 일본어, 한국어와 시간대 설정

## 주요 기능

- **소설과 장**: TXT/EPUB 생성·편집·삭제·가져오기, 장 분석 및 일괄 가져오기/분할, 예제 소설.
- **소재 라이브러리**: 인물, 장면, 소품 추출과 참조 이미지 생성·관리, 인물 음색 및 참조 오디오 관리.
- **샷과 이미지**: AI 분할, 수동 편집, 이미지 일괄 생성, 참조 이미지 연결, 키프레임, 단일/다중 이미지 편집, AI 품질 평가와 고해상도 재생성.
- **Video Director**: 다중 참조, 이어 만들기, 시간 앵커를 이용한 샷/Clip 계획. 프롬프트, LLM 로그, 작업 및 결과 보관.
- **Clip 실행 검사**: 타임라인과 프레임별 생성 근거, 참조 소재, 관찰 기록 확인.
- **오디오와 배포**: 선택적 음색 설계·음성 생성, Clip/장/소설 동영상 병합, 첫 등장 이름표 미리보기, 표지 생성 및 YouTube 업로드.
- **워크플로와 프롬프트**: ComfyUI 시스템/사용자 워크플로, 노드 매핑, 가져오기/내보내기, 프롬프트 템플릿 관리.
- **작업과 알림**: 백그라운드 처리, 재시도·복구, 이벤트, 페이지 알림음, Feishu/Telegram 알림.
- **다국어와 시간대**: 5개 화면 언어와 사용자 지정 시간대.

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
│   └── run_server.py
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

시스템 설정에는 DeepSeek, OpenAI, Gemini, Anthropic, Azure OpenAI, Alibaba Cloud Bailian, Ollama 및 OpenAI API 호환 사용자 지정 서비스의 프리셋이 있습니다. 서비스에 맞는 주소, 모델, API 키를 설정하세요. 필요하면 프록시를 설정하고 프롬프트 설정에서 제작 단계별 템플릿을 관리할 수 있습니다.

### 2. ComfyUI 설정

- 기본 주소는 `http://localhost:8188`이며 시스템 설정에서 변경할 수 있습니다.
- 시스템 프리셋 JSON은 `backend/workflows/`, 등록 규칙과 노드 매핑은 `backend/app/constants/workflow.py`에 있습니다. 업로드한 워크플로는 `backend/user_workflows/`에 저장됩니다. 화면에서 가져오기, 내보내기, 선택, 노드 매핑을 할 수 있습니다.
- 이미지 프리셋에는 Moss Image T2I의 인물 4면도/장면/소품과 Qwen Image 2.1의 샷/키프레임/단일·다중 이미지 편집이 있습니다. 동영상 프리셋에는 MiniMax H3 다중 참조, 이어 만들기, 시간축 확장, 2차 샘플링, 3D latent 업스케일링이 있습니다. 오디오 워크플로에는 Qwen3-TTS도 포함됩니다.
- 실제 활성 워크플로는 데이터베이스 선택에 따릅니다. `debug/workflows/`는 디버깅 예제로 시스템 프리셋에 자동 등록되지 않습니다.

**모델과 노드 다운로드**: [Quark 링크](https://pan.quark.cn/s/2a630b7755ed). 선택한 워크플로 JSON이 참조하는 모델과 노드만 설치하세요. 2026-10-23 조사에는 Moss Image, Qwen Image 2.1, 로컬 Qwen PE 재작성 모델, H3 본체/VAE/LoRA/업스케일러와 플러그인이 포함됩니다. 정확한 경로, 플러그인 저장소, 활성 상태는 [ComfyUI 의존성 목록](docs/COMFYUI_DEPENDENCIES.md)을 참고하세요.

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

프롬프트 설정에서 시스템 템플릿을 보고 사용자 템플릿을 생성·복사·편집·내보내거나 소설에 연결할 수 있습니다. 소재 추출, 샷, 동영상 계획, 이미지 품질 평가 등을 다루며 LLM 로그로 실제 호출을 추적할 수 있습니다.

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

## 구현된 제작 기능

- [x] 소설/장 관리와 인물/장면/소품 라이브러리
- [x] 샷 분할, 이미지 일괄 생성, 이미지 평가 및 고해상도 재생성
- [x] Video Director, 다중 참조/이어 만들기/시간축 확장과 Clip 검사
- [x] 오디오 생성, 장/소설 동영상 병합, 이름표 미리보기와 표지
- [x] 워크플로/프롬프트 관리, 작업 복구, 이벤트 알림, YouTube 업로드
- [x] 5개 언어 화면과 시간대 설정

## 사용 방법

1. **환경 준비**: 백엔드와 프론트엔드를 시작하고 시스템 설정에서 LLM과 ComfyUI를 설정합니다. 선택한 워크플로의 모델과 노드를 설치합니다.
2. **소설 가져오기**: TXT/EPUB를 가져오거나 예제를 선택하고 필요하면 장을 일괄 가져오기·분할합니다.
3. **소재 구축**: 인물, 장면, 소품을 추출하고 참조 이미지를 생성합니다. 인물 음색을 설계하거나 참조 오디오를 등록할 수 있습니다.
4. **샷 제작**: 장을 편집하고 AI 분할 결과를 수정한 뒤 샷 이미지와 키프레임을 생성합니다. 이미지 품질을 확인하고 필요하면 고해상도로 재생성합니다.
5. **오디오·동영상 생성**: 필요한 오디오를 만들고 Video Director에서 워크플로와 참조 이미지를 선택하여 Clip을 계획하고 동영상을 생성·연장합니다.
6. **검토 및 병합**: 작업 목록과 Clip 실행 검사 화면에서 상태, 프레임, 근거를 확인하고 Clip과 장을 병합합니다. 이름표 미리보기를 사용할 수 있습니다.
7. **배포**: 소설 동영상을 병합하고 표지를 생성·다운로드합니다. YouTube를 연결한 뒤 결과를 업로드할 수 있습니다.

## 기여하기

프로젝트에 기여를 환영합니다! [기여 가이드](docs/CONTRIBUTE_GUIDE_EN.md)를 읽고 개발에 참여하는 방법을 알아보세요.

## License

이 프로젝트는 GNU General Public License v3.0에 따라 라이선스가 부여됩니다 - 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.
