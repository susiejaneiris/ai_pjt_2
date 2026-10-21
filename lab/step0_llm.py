"""0단계 — LLM 연결 기초 (Streamlit 없이 LLM 호출만 확인)        ✏️ 실습용

    python step0_llm.py

[실습 N] 주석 자리를 위에서부터 차례로 채우고, 하나 채울 때마다 실행해 봅니다.
채우지 않은 구간은 제목만 출력되고 넘어갑니다.

확인할 것
  1. 키가 제대로 읽히는가                (1번 구간은 이미 채워져 있습니다)
  2. LLM을 부르면 무엇이 돌아오는가
  3. 대화는 어떤 형식으로 주고받는가
  4. LLM은 이전 대화를 기억하는가      ← 오늘 가장 중요한 장면

비유      LLM은 영화 〈메멘토〉의 주인공 — 메모(대화 기록)를 함께 건네야 방금 무슨 일이 있었는지 압니다.
한 걸음 더 GMS는 OpenAI와 같은 모양의 HTTP API입니다. invoke() 한 번이 HTTP 요청 한 번이고,
          서버는 이전 요청을 기억하지 않습니다(stateless).

준비      .env.example 을 복사해 이 폴더에 .env 를 만들고 GMS_KEY=발급받은_키 를 넣습니다.
          키 값은 코드에 쓰지 않고, 화면에 출력하지도 않습니다.
"""
import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

GMS_BASE_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/"
MODEL_NAME = "gpt-5.4-nano"


def title(text):
    print()
    print("=" * 64)
    print(text)
    print("=" * 64)


def input_tokens(response):
    return (response.usage_metadata or {}).get("input_tokens", "?")


# ── 1. 키 읽기 ──────────────────────────────────────────────────────
title("1. 키 읽기")

load_dotenv()                           # 이 파일과 같은 폴더의 .env → 환경변수
key = os.environ.get("GMS_KEY")

if not key:
    print("GMS_KEY를 찾지 못했습니다.")
    print("  - 이 파일과 같은 폴더에 .env 파일이 있는지")
    print("  - 그 안에 GMS_KEY=... 가 있는지 (.env.examp le 이 아니라 .env)")
    sys.exit(1)

print(f"키를 찾았습니다. (길이 {len(key)})   ← 키 값 자체는 출력하지 않습니다")


# ── 2. 첫 호출 ──────────────────────────────────────────────────────
title("2. 첫 호출 — 주소(base_url)만 GMS로 바꾼다")

# [실습 2] ① ChatOpenAI 객체를 만들어 model 에 담는다.
#             인자 세 개: model=MODEL_NAME, api_key=key, base_url=GMS_BASE_URL
#             OpenAI용 라이브러리를 그대로 쓰고 주소(base_url)만 GMS로 바꾼다.
#          ② model.invoke("안녕? 한 문장으로 자기소개해줘.") 의 결과를 response 에 담는다.
#          ③ 답은 response.content — print 로 출력한다.
#          막히면  401 → 키 문제(오타 · 만료)   404 → base_url 오타   (응답에 몇 초 걸리는 것은 정상)
model = ChatOpenAI(
    model=MODEL_NAME,
    api_key=key,
    base_url=GMS_BASE_URL,
)

response = model.invoke("안녕하세요")
print(response.content)


# ── 3. 돌아온 것의 정체 ─────────────────────────────────────────────
title("3. 돌아온 것은 문자열이 아니라 메시지 객체")

# [실습 3] response 를 들여다본다. 세 줄을 출력해 보세요.
#          type(response).__name__     → 무슨 객체인가
#          response.content            → 답 (우리가 쓰는 것은 이것 하나)
#          response.usage_metadata     → 토큰 사용량 (요금과 직결)
print(type(response).__name__)
print(response.usage_metadata)


# ── 4. 대화의 형식 ──────────────────────────────────────────────────
title("4. 대화는 역할이 붙은 메시지 목록")

# [실습 4] 문자열 하나 대신 '역할이 붙은 메시지 목록'으로 묻는다.
#          messages = [ {"role": "system", "content": "너는 친절한 한국어 비서다. 간결하게 답한다."},
#                       {"role": "user",   "content": "대한민국의 수도는?"} ]
#          first_answer = model.invoke(messages).content  → 출력
#          system = 지시(배우에게 주는 배역 설명서) · user = 사용자 질문 · assistant = LLM의 답변
#          이 모양을 기억해 두세요. Streamlit 4단계에서 대화 기록을 똑같은 모양으로 쌓습니다.

messages = [ {"role": "system", "content": "너는 친절한 한국어 비서다. 간결하게 답한다."},
                      {"role": "user",   "content": "대한민국의 수도는?"} ]

first_answer = model.invoke(messages).content
print(first_answer)


# ── 5. LLM은 기억하지 않는다 ────────────────────────────────────────
title("5. LLM은 이전 대화를 기억하지 않는다")

# [실습 5] ① 질문만 보내기 : [{"role": "user", "content": "거기 인구는 대략 얼마야?"}] 하나만 invoke → 출력
#                            "거기"가 어디인지 알까요?
#          ② 대화 전체 보내기: history = messages + [ {"role": "assistant", "content": first_answer},
#                                                     {"role": "user", "content": "거기 인구는 대략 얼마야?"} ]
#                            full = model.invoke(history) → full.content 출력
#          → 기억은 모델이 아니라 우리가 들고 있다. 매번 대화 전체를 다시 보낸다.

answer1 = model.invoke([{"role": "user", "content": content}])
print(answer1.content)

history = messages + [  {"role": "assistant", "content": first_answer},
                        {"role": "user", "content": "거기 인구는 대략 얼마야?"} ]
answer2 = model.invoke(history)
print(answer2.content)

title("연결 끝 — 이제 화면을 만들러 갑니다:  streamlit run step1_widgets.py")
