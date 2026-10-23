# ⚖️ 내일의 법 — 청년을 위한 생활법령 RAG 지식 서비스

> **내 일에 필요한 법, 내일을 위한 지식.**
> 법을 잘 모르는 청년이 집 · 일 · 계약 · 돈 · 가족 · 건강 · 사고처럼 생활 다방면에서 부딪히는 법을 가볍게 물어보면,
> 실제 **법 조문 · 판례 · 법령해석례**를 찾아 **근거 번호와 원문 출처를 붙여** 답하는 서비스입니다.
> 마스코트는 법복 입은 동글이 **로우(law)** 입니다.

- 서비스명 "내일의 법" = **내 일**(내 일상)에 필요한 법 + 미래의 **내일**을 준비하는 지식
- AI 코어 프로젝트 2회차 — RAG 기반 도메인 지식 서비스 (필수 F2001~F2012 · 심화 F2013~F2016)
- ⚠️ 이 서비스는 법령 정보를 안내할 뿐 **법률 자문을 대신하지 않습니다.**
- 검색 결과 카드의 법률 이름에 마우스를 올리면 **법을 몰라도 알 수 있는 한두 문장 설명**이 떠요 (`prep/easy_explain.py` → `data/law_easy.json`).
- 요구사항별 확인 결과는 [`docs/검증_체크리스트.md`](docs/검증_체크리스트.md) 에 정리했어요.

---

## 1. 실행 방법

### 준비
```bash
python -m venv venv
source venv/Scripts/activate            # Windows Git Bash (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env                    # 아래 세 값을 채운다
```
| 환경변수 | 내용 |
|---|---|
| `GMS_KEY` | SSAFY GMS 키 (LLM · 임베딩) |
| `LAW_OC` | 국가법령정보센터 Open API 인증값 (신청 이메일의 `@` 앞부분) |
| `WIKI_CONTACT` | 위키백과 API User-Agent 연락처 (영문 이메일) |

### 데이터 준비 · 색인 (처음 한 번)
```bash
python -m prep.build_items        # 법률 276건(20개 분야) 메타데이터 수집 → data/items.json   (이미 포함됨)
python -m prep.casebook           # 법령해석 사례집 PDF → data/casebook.json (312건) (이미 포함됨)
python -m prep.kids_guide         # 어린이 생활법령 PDF → data/kids_guide.json (26개 주제) (이미 포함됨)
python -m scripts.build_index     # RAG 1: 항목 메타데이터 임베딩 → law_meta 컬렉션
python -m scripts.export_fallback # (선택) 외부 호출이 막힐 때 쓸 문서 묶음 → data/fallback/
```

### 실행
```bash
streamlit run app.py              # Streamlit 화면
uvicorn server:app --port 8000    # 웹 화면 (F2013) → http://localhost:8000
```

### 검증 · 비교 스크립트
```bash
python -m prep.item_text law_001      # 항목 1건의 색인 텍스트 확인 (명세 4.1)
python -m rag.graph                   # LangGraph 구조 출력 (명세 4.3)
python -m scripts.compare_search      # 유사도 vs MMR, Top-k 3/6/10 → docs/compare_search.md (F2014)
python -m scripts.compare_rag         # RAG 사용 전후 답변 비교 → docs/RAG_전후_비교.md (F2015)
```

---

## 2. 기능

### 필수
| 번호 | 기능 | 구현 |
|---|---|---|
| F2001 | 항목 메타데이터 적재 | 법률 276건 · 20개 분야, 1건 = 법률명 · 분야 · 부처 · 시행일 · 목적 · 조문 제목 목록 텍스트 (`prep/item_text.py`) |
| F2002 | 메타데이터 색인 (RAG 1) | `law_meta` 컬렉션, id = item_id 로 다시 색인해도 덮어쓰기 (`scripts/build_index.py`) |
| F2003 | 검색어 추출 (프롬프트 1) | 생활법령 전문가 역할, 일상어 → 법률 용어, JSON 배열 (`rag/prompts.py`) |
| F2004 | 외부 문서 수집 (프롬프트 2) | 조문 · 판례 · 법령해석례 · 위키 후보를 제목 · 요약만 보고 선별 → 본문 + 원문 출처. 법률 자체 문서는 항상 수집. 외부 호출이 막히면 저장된 문서 묶음 사용 (`prep/collect.py`) |
| F2005 | 외부 문서 색인 (RAG 2) | 출처별 문서 단위 → `settings.json` 의 청크 크기 · 중복 길이로 분할 → `law_docs`, id = `항목ID:문서ID:순번` |
| F2006 | 근거 검색 · 병합 | 메타 청크는 항상 [근거 1], 외부 문서는 item_id 필터 + Top-k, 중복 제거 3단계 (`rag/retriever.py`). 프롬프트 1 이 조문 목록에서 정답 조문을 지목해 근거에 고정 (평가 25문항 90.5 → 100%) |
| F2007 | 근거 기반 답변 (프롬프트 3) | LangGraph `retrieve → generate`, 근거 없으면 LLM 을 부르지 않고 "확인되지 않습니다" (`rag/graph.py`) |
| F2008 | 근거 표시 | 답변이 인용한 `[근거 N]` 만 제목 · 원문 출처와 표시, 없는 번호 · 근거에 없는 조문 번호는 경고 (`rag/citations.py`) |
| F2009 | 항목 선택 · 질의응답 | 분야 → 법률 선택, 법률별 대화 기록 |
| F2010 | 도메인 특화 기능 | ① **사실일까?** 법률 상식 팩트체크 (사실 / 사실 아님 / 확인 불가) ② **조문 쉽게 읽기** 쉬운 말 풀이 + 원문 나란히 (`service/features.py`) ③ **쟁점 나누기** 여러 법이 얽힌 긴 상황을 쟁점별 법률 · 조문으로 나눠 답변 (`service/complex.py`, 정답 조문 적중 44 → 83%) |
| F2011 | 조건 기반 항목 탐색 | "알바하다 다쳤어요" → 메타 색인 후보 → LLM 선별 → 카드 → 그 법률 대화로 (`service/find_laws.py`) |
| F2012 | 진행 상태 · 안내 | 수집 · 색인 · 생성 단계 표시, 색인 없음 · 키 누락 · 결과 없음 안내, 법률 · 금융 · 건강 면책 (`prep/disclaimer.py`). AI 사용 한도(GMS 토큰)가 끝나면 원인을 안내하고 API 없이 원문만 보여 줌 (`service/offline.py`) |

### 심화
| 번호 | 기능 | 구현 |
|---|---|---|
| F2013 | 프론트엔드 직접 구현 | FastAPI(`server.py`) + HTML/CSS/JS(`web/`), 진행 단계는 NDJSON 스트림. Streamlit 과 같은 `service/` 사용 |
| F2014 | MMR 검색 | `settings.json` 의 `search_type: "mmr"` (fetch_k 30, lambda 0.5), 비교 스크립트 |
| F2015 | RAG 전후 품질 비교 | 대표 질문 7개(함정 1개)를 RAG 없이 / RAG 로 → 사실 정확성 · 근거 제시 · 모른다고 답함 |
| F2016 | 여러 문서 출처 결합 | 법령 API(JSON) · 법령해석 사례집(PDF) · 위키백과 — 근거에 📜조문 / ⚖️판례 / 📘법령해석례 / 📖위키 / 🗂️메타 구분 |

### 비기능
NF2002 수집 캐시(`data/collected.json`) · NF2003 키는 `.env` · NF2004 화면에 키 · 프롬프트 · 오류 추적 미노출 · NF2005 모듈 분리 · NF2006 호출 간격 · 재시도 · User-Agent · NF2007 출처 기록(`data/SOURCES.md`)

---

## 3. 데이터 준비 · 색인 절차

```
⓪ 실행 전 (RAG 1)
   data/item_list.csv(우리가 고른 법률 276개) ─► 법령 API ─► data/items.json ─► 항목 텍스트 ─► 임베딩 ─► [law_meta]
   법령해석 사례집 PDF(1,402쪽) ─► 사례 312건 JSON (data/casebook.json)

① 질문마다 (RAG 2)
   항목 + 질문 ─► 프롬프트1 검색어 ─► 새 검색어만 ─► 조문 목록 · 판례 · 법령해석례 · 위키 후보
              ─► 프롬프트2 선별 ─► 본문 수집 ─► 출처별 청킹 ─► 임베딩 ─► [law_docs]

② 답변 (LangGraph)
   retrieve: 메타 청크(항상) + law_docs(item_id 필터, similarity|MMR) → 병합 · 중복 제거 · 근거 번호
   generate: 프롬프트3 (근거만 사용 · [근거 N] · 없으면 "확인되지 않습니다") → 인용 검증
```

| 설정 (`settings.json`) | 값 | 이유 |
|---|---|---|
| `chunk_size` / `chunk_overlap` | 1000 / 200 | 실측 조문 1,886개 중 85%가 1,000자 이하 → 근거 1개 = 조문 1개 |
| `top_k` | 6 | 메타 1 + 외부 6. 선별 상한보다 작게 |
| `search_type` | similarity (mmr 선택) | 이웃 청크가 몰리면 MMR |

자세한 설계는 `docs/RAG_파이프라인_설계문서.md`.

---

## 4. 데이터 · 문서 출처와 이용 조건

| 출처 | 이용 조건 |
|---|---|
| 국가법령정보센터 Open API — 법률 메타데이터 · 조문 · 판례 | 활용 신청(OC) 후 사용. 법령 · 판결은 저작권법 제7조 비보호 저작물. 출처 표시 |
| 법제처 「2024 법령해석 사례집」(상 · 하) — 공공데이터포털 | **공공누리 제4유형** (출처표시 · 상업적 이용금지 · 변경금지). 원문 무수정 발췌 + 쪽 번호 표시 |
| 한국어 위키백과 API | CC BY-SA 4.0, 문서 URL 표시, User-Agent 연락처 |

> 이 서비스는 공공누리 제4유형으로 개방한 '법제처, 「2024 법령해석 사례집」'을 이용하였으며, 해당 저작물은 공공데이터포털(www.data.go.kr)에서 무료로 내려받을 수 있습니다.

전체 내용은 [`data/SOURCES.md`](data/SOURCES.md).

---

## 5. 폴더 구조

```
app.py                  Streamlit 화면 (step7 골격을 이어 씀)
server.py · web/        FastAPI 서버 + HTML/CSS/JS 화면 (F2013)
config.py · settings.json   경로 · 키 · 청킹/검색 설정
prep/                   데이터 준비 — 도메인에 묶인 코드는 여기만 (NF2005)
  law_api.py wiki_api.py   외부 출처 호출
  build_items.py item_text.py   항목 메타데이터 · 색인 텍스트
  casebook.py              법령해석 사례집 PDF → JSON
  kids_guide.py            어린이 생활법령 PDF → JSON (생활법령 Q&A 후보)
  collect.py               프롬프트1 → 검색 → 프롬프트2 → 본문 (RAG 2 수집)
  disclaimer.py            법률 · 금융 · 건강 면책
store/                  Vector Store — 컬렉션 · upsert · 청킹
rag/                    프롬프트 · 검색 · 병합 · LangGraph · 인용 검증
service/                화면이 부르는 기능 (질의응답 · 팩트체크 · 조문 풀이 · 법 찾기)
scripts/                색인 · 비교 · 마스코트 자르기 · 문서 묶음 만들기
data/                   items.json · casebook.json · pdf/ · fallback/ · SOURCES.md
assets/mascot/          로우 8자세 + 아바타
docs/                   요구사항 정의서 · 설계문서 · 비교 결과 · 검증 결과
lab/                    2회차 라이브 실습 파일 (step0~8)
```
