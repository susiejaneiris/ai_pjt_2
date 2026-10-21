"""3단계 — session_state: 다시 실행돼도 살아남는 곳.        ✏️ 실습용

실행:
    streamlit run step3_state.py

2단계의 count가 왜 안 올라갔는지 봤으니, 이제 살아남게 만들어 봅니다.

비유      — 브라우저 탭마다 하나씩 있는 사물함. 칠판은 매번 지워져도 사물함 안의 물건은 남습니다.
한 걸음 더 — 자바의 HttpSession과 비슷합니다. 탭(세션)마다 따로이고, 서버를 다시 켜면 사라집니다.
             오래 남겨야 하는 데이터(색인, 수집 이력)는 파일이나 DB에 둡니다.

가장 흔한 실수: 첫 실행인지 확인하지 않고 매번 초기값으로 덮어쓰는 것.
"""

import streamlit as st

st.title("3단계 — session_state에 담기")

# [실습 1] 첫 실행일 때만 st.session_state.count 에 0을 넣는다. 이미 있으면 건드리지 않는다.
#          힌트: if "count" not in st.session_state:

if "count" not in st.session_state:
    st.session_state.count = 0

# [실습 2] st.button("눌러 보세요") 가 눌렸으면 st.session_state.count 를 1 올린다.
if st.button("눌러 보세요"):
    st.session_state.count += 1

# [실습 3] st.write("count =", ...) 로 session_state 의 count 를 화면에 쓴다.
st.write("count =", st.session_state.count)

st.divider()
st.caption("지금 session_state에 들어 있는 것")
st.write(dict(st.session_state))

st.info(
    "이제 숫자가 쌓입니다.\n\n"
    "**기억해야 할 것 :** 화면에 남아야 하는 값은 session_state에 넣는다.\n\n"
    "해 볼 것: `if \"count\" not in st.session_state:` 줄을 지우고 다시 눌러 보세요. 왜 0으로 돌아갈까요?\n\n"
    "대화 기록도 마찬가지입니다. 다음 단계에서 여기에 메시지를 쌓습니다."
)
