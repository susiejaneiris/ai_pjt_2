"""4단계 — 채팅 화면 만들기 (에코 봇).        ✏️ 실습용

실행:
    streamlit run step4_echo.py

새로 쓰는 것은 두 개뿐입니다.
    st.chat_input(...)      화면 아래 고정된 입력창. 입력하면 그 문자열을, 없으면 None을 돌려줍니다.
    st.chat_message(role)   말풍선. role은 "user" 또는 "assistant".

핵심은 **매번 대화 전체를 다시 그린다**는 점입니다.
새 메시지만 덧붙이는 게 아니라, 기록을 처음부터 끝까지 다시 그립니다.
2·3단계에서 본 "처음부터 다시 실행"이 그대로 적용됩니다.

비유      — 카톡방을 열면 앱이 지난 대화를 처음부터 다시 그려 보여 줍니다.
한 걸음 더 — 화면을 직접 고치지 않고 상태(messages 목록)만 고칩니다. 화면은 매번 상태로부터 그립니다.

해 볼 것: 다 만든 뒤 [실습 2] 반복문을 주석 처리하고 두 번 입력해 보세요. 직전 한 쌍만 남습니다.
"""

import streamlit as st

st.set_page_config(page_title="에코 봇", page_icon="💬")
st.title("💬 에코 봇")

# [실습 1] 대화 기록을 담을 st.session_state.messages 를 빈 목록으로 준비한다. (첫 실행에만 — 3단계와 같은 모양)
#          한 칸의 모양: {"role": "user" 또는 "assistant", "content": "..."}  ← 0단계에서 본 LLM 대화 형식과 같다.
if "messages" not in st.session_state:
    st.session_state.messages = []

# [실습 2] 지금까지의 대화를 처음부터 다시 그린다.
#          for message in st.session_state.messages:
#              with st.chat_message(message["role"]):  안에서  st.markdown(message["content"])
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# [실습 3] question = st.chat_input("아무 말이나 입력해 보세요")
#          입력이 없으면 None 이라 아래 if question: 이 실행되지 않는다.
question = st.chat_input("아무 말이나 입력해 보세요")

# [실습 4] if question: 이면
#          ① 사용자 메시지 {"role": "user", "content": question} 를 messages 에 넣고, user 말풍선으로 그린다.
#          ② answer = f"'{question}' 라고 하셨네요."          ← 5단계에서 바뀌는 한 줄
#          ③ 답변 {"role": "assistant", "content": answer} 도 messages 에 넣고, assistant 말풍선으로 그린다.

if question:
    st.session_state.messages.append({"role": "assistant", "content": answer})
    with st.chat_message("user"):
        st.markdown(question)

    answer = f"'{question}' 라고 하셨네요."

    st.session_state.messages.append({"role": "assistant", "content": answer})
    with st.chat_message("assistant"):
        st.markdown(answer)
