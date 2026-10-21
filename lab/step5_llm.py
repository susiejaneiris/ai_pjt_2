"""5단계 — LLM 연결. 에코 봇을 진짜 대화로 바꿔 봅니다.        ✏️ 실습용

준비:
    .env 에  GMS_KEY=발급받은_키

실행:
    streamlit run step5_llm.py

채팅 화면(4단계)은 이미 들어 있습니다. 지금 실행하면 에코 봇 그대로입니다.
바꾸는 것은 세 군데뿐입니다.
    [실습 1] get_model() 안에서 ChatOpenAI 객체를 만든다     (0단계와 같은 세 인자)
    [실습 2] get_model() 위에 @st.cache_resource 를 붙인다
    [실습 3] 에코 한 줄을 LLM 답으로 바꾼다
        answer = f"'{question}' 라고 하셨네요."      ← 이것을
        answer = get_model().invoke(question).content  ← 이것으로

비유      — @st.cache_resource 는 "전화기를 매번 새로 개통하지 않고, 한 번 개통한 것을 계속 쓰기"입니다.
한 걸음 더 — cache_resource로 만든 객체는 모든 사용자(세션)가 함께 쓰는 싱글턴입니다.
             사용자별 데이터는 여기에 넣지 말고 session_state에 둡니다. (값을 복사해 주는 것은 cache_data)

해 볼 것: 다 만든 뒤 @st.cache_resource 를 떼어 보고 무엇이 달라지는지 봅니다.
"""

import os

import streamlit as st
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()  # 같은 폴더의 .env 를 읽어 환경변수로 등록한다.

GMS_BASE_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/"


# [실습 2] 바로 아래 def 위에 @st.cache_resource 를 붙인다.
#          붙이지 않으면 화면이 바뀔 때마다 LLM 클라이언트를 새로 만든다. ("처음부터 다시 실행"이 여기에도 적용)
def get_model() -> ChatOpenAI:
    """LLM 클라이언트를 만들어 돌려준다."""
    key = os.environ.get("GMS_KEY")
    if not key:
        st.error("GMS_KEY가 없습니다. .env를 확인하세요.")
        st.stop()
    # [실습 1] 0단계와 같은 세 인자로 ChatOpenAI 객체를 만들어 return 한다.
    #          model="gpt-5.4-nano", api_key=key, base_url=GMS_BASE_URL
    return ChatOpenAI(model="gpt-5.4-nano", api_key=key, base_url=GMS_BASE_URL)



st.set_page_config(page_title="LLM 챗봇", page_icon="💬")
st.title("💬 LLM 챗봇")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

question = st.chat_input("무엇이든 물어보세요")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        # 응답이 오기까지 몇 초 걸린다. 아무것도 없으면 멈춘 것처럼 보인다.
        with st.spinner("생각하는 중..."):
            try:
                # [실습 3] 아래 에코 한 줄을 LLM 답으로 바꾼다.   get_model().invoke(question).content
                answer = get_model().invoke(question).content
            except Exception:
                answer = ""

        if answer:
            st.markdown(answer)
        else:
            # 오류 상세(트레이스백)는 화면에 보이지 않는다. 안내 문구만 보인다. (NF2004)
            st.error("답변을 받지 못했습니다. 키와 네트워크를 확인해 주세요.")

    if answer:
        st.session_state.messages.append({"role": "assistant", "content": answer})
