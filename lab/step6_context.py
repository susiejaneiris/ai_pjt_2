"""6단계 — 대화 맥락. 이어지는 대화를 만들어 봅니다.        ✏️ 실습용

실행:
    streamlit run step6_context.py

5단계 완성본이 들어 있습니다. 먼저 그대로 실행해서 이렇게 물어보세요.
    "대한민국의 수도는?"  →  "서울입니다"
    "거기 인구는?"        →  "어디를 말씀하시는지..."

**LLM은 이전 대화를 기억하지 않습니다.** 매번 전체를 다시 보내야 합니다.
Streamlit이 매번 처음부터 다시 실행되는 것과 똑같습니다. 기억은 우리가 들고 있어야 합니다.

화면은 5단계와 같습니다. 바뀌는 것은 LLM에 넘기는 값뿐입니다.
    get_model().invoke(question)     ← 질문 하나만 넘기던 것을
    get_model().invoke(payload)      ← system + 지금까지의 대화 전체로

비유      — 영화 〈메멘토〉의 주인공. 메모(대화 기록)를 함께 건네야 방금 무슨 일이 있었는지 압니다.
한 걸음 더 — 대화가 길어질수록 매번 보내는 토큰이 늘어 느려지고 비용이 듭니다. 모델이 한 번에 받을 수 있는
             양(컨텍스트 창)에도 한계가 있습니다. 최근 N개만 보내기, 앞부분 요약하기가 흔한 해법입니다.
             RAG가 문서를 통째로 넣지 않고 관련 있는 몇 조각(Top-k)만 넣는 이유도 같습니다.
"""

import os

import streamlit as st
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

GMS_BASE_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/"
# 배우에게 주는 배역 설명서. 말투를 바꿔 보면 차이가 잘 보인다.
SYSTEM_PROMPT = "너는 친절한 한국어 비서다. 간결하게 답한다."


@st.cache_resource
def get_model() -> ChatOpenAI:
    key = os.environ.get("GMS_KEY")
    if not key:
        st.error("GMS_KEY가 없습니다. .env를 확인하세요.")
        st.stop()
    return ChatOpenAI(model="gpt-5.4-nano", api_key=key, base_url=GMS_BASE_URL)


st.set_page_config(page_title="LLM 챗봇", page_icon="💬")
st.title("💬 LLM 챗봇 — 이어지는 대화")

with st.sidebar:
    if st.button("대화 지우기", width="stretch"):
        st.session_state.messages = []

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

    # [실습 1] 질문 하나 대신 넘길 payload 를 만든다.
    #          payload = [{"role": "system", "content": SYSTEM_PROMPT}] + (지금까지의 대화 목록)
    #          방금 넣은 질문도 messages 안에 이미 들어 있다. 이것이 '기억'의 정체다.

    payload = [{"role": "system", "content": SYSTEM_PROMPT}] + st.session_state.messages
    
    with st.chat_message("assistant"):
        with st.spinner("생각하는 중..."):
            try:
                # [실습 2] question 대신 payload 를 넘기도록 바꾼다.
                answer = get_model().invoke(question).content
            except Exception:
                answer = ""

        if answer:
            st.markdown(answer)
        else:
            st.error("답변을 받지 못했습니다. 키와 네트워크를 확인해 주세요.")

    if answer:
        st.session_state.messages.append({"role": "assistant", "content": answer})
