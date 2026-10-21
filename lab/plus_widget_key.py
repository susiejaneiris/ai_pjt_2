"""도전 과제 (전공자·빠른 수강생) — 위젯의 정체성과 key.        ✏️ 실습용

실행:
    streamlit run plus_widget_key.py

프로젝트를 하다 보면 "추천 버튼을 누르면 사이드바의 선택도 그 항목으로 바뀌게" 하고 싶어집니다.
가장 먼저 떠오르는 방법은 selectbox의 index를 지금 선택값으로 계산하는 것인데, 여기에 함정이 있습니다.

    Streamlit은 key가 없는 위젯을 "인자값(라벨, 목록, index …)"으로 구분합니다.
    index가 바뀌면 다른 위젯으로 보고, 사용자가 방금 고른 값을 버린 채 기본값을 돌려줍니다.

실제로 참고 구현(Movie Lab) 검증에서 "영화 변경이 한 번 무시된다"는 결함으로 나왔던 문제입니다.

해 볼 것
    1. ① 함정 버전에서 목록으로 영화를 연달아 바꿔 보세요. 바꾼 직후 한 번은 무시됩니다.
    2. [도전] 자리에 ② 해결 버전을 직접 만들어 보세요. (힌트는 주석에)
    3. 같은 동작을 해 보고, 두 코드의 차이를 한 문장으로 설명해 보세요.
"""

import streamlit as st

MOVIES = ["기생충 (2019)", "명량 (2014)", "인터스텔라 (2014)", "올드보이 (2003)"]

st.title("도전 과제 — 위젯의 정체성(key)")
mode = st.radio("버전", ["① 함정 — index로 동기화", "② 해결 — key + 콜백"], horizontal=True)
st.divider()

if mode.startswith("①"):
    # ── 함정: key 없이, 직전 선택값으로 index를 계산한다 ──────────────────
    current = st.session_state.get("trap_movie")
    index = MOVIES.index(current) if current in MOVIES else None
    picked = st.selectbox("영화 (함정 버전)", MOVIES, index=index)
    st.session_state.trap_movie = picked

    if st.button("추천: 인터스텔라로 이동"):
        st.session_state.trap_movie = "인터스텔라 (2014)"
        st.rerun()

    st.write("지금 선택:", picked)
    st.warning(
        "목록에서 다른 영화를 고르면, 다음 실행에서 index가 달라져 **다른 위젯**으로 인식됩니다. "
        "그래서 방금 고른 값이 버려지고 이전 영화가 다시 나옵니다. 한 번 더 고르면 그제야 바뀝니다."
    )

else:
    # ── 해결: key로 값을 보관하고, 다른 곳에서 바꿀 때는 콜백에서 그 key를 고친다 ─────
    # [도전] 아래 안내 대신 해결 버전을 만든다. 세 가지면 됩니다.
    #        ① 콜백 함수 pick(movie): st.session_state.fix_movie = movie
    #           (콜백은 다음 실행이 시작되기 '전에' 돈다. 그래서 위젯 값을 바꿔도 된다.)
    #        ② selectbox 는 index=None 으로 고정하고 key="fix_movie" 로 값을 보관한다.
    #        ③ 추천 버튼은 on_click=pick, args=("인터스텔라 (2014)",) 로 콜백을 건다.
    #        주의: selectbox 를 그린 '뒤에' 본문에서 st.session_state.fix_movie = ... 를 하면 오류가 난다.
    st.info("해결 버전을 직접 만들어 보세요. 힌트는 코드의 [도전] 주석에 있습니다.")

with st.expander("한 걸음 더 — 왜 이런 일이 생기나"):
    st.markdown(
        "- 위젯 값은 브라우저가 아니라 서버의 세션에 **위젯 ID별로** 저장됩니다.\n"
        "- key가 없으면 ID를 위젯의 인자들로 만듭니다. 인자가 바뀌면 ID도 바뀝니다.\n"
        "- key를 주면 `st.session_state[key]`로 값을 읽고 쓸 수 있습니다. 단, 위젯을 그린 **뒤에는** 같은 실행 안에서 바꿀 수 없어 콜백(`on_click`, `on_change`)을 씁니다."
    )
