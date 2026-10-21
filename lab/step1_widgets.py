"""1단계 — 위젯은 값을 돌려준다.        ✏️ 실습용

실행:
    streamlit run step1_widgets.py

[실습 N] 자리를 채우고 저장한 뒤, 브라우저 오른쪽 위 Rerun(또는 R 키)을 누릅니다.

Streamlit의 위젯(화면에 놓는 입력 부품)은 함수입니다.
부르면 화면에 그려지고, 지금 들어 있는 값을 돌려줍니다.
    name = st.text_input(...)      입력한 글자 (비어 있으면 "")
    genre = st.selectbox(...)      고른 항목
    clicked = st.button(...)       방금 눌렸으면 True, 아니면 False

비유  — 위젯은 "기다리지 않는 input()" 입니다. 입력칸을 그리고, 지금 적혀 있는 값을 바로 돌려줍니다.
        버튼은 초인종입니다. 누른 그 순간에만 울립니다(True).

마지막으로 해 볼 것: 인사하기를 누른 뒤 이름을 바꿔 보세요. 인사말이 사라집니다.
왜 사라지는지는 2단계에서 알아봅니다.
"""

import streamlit as st

st.title("1단계 — 위젯은 값을 돌려준다")
st.write("화면에 글자를 쓰는 가장 쉬운 방법은 `st.write` 입니다. **마크다운**도 됩니다.")

# [실습 1] 위젯 세 개를 부르고, 돌려준 값을 변수에 담는다.
#          name    ← st.text_input   라벨 "이름"   (placeholder="이름을 입력하세요" 도 넣어 보세요)
#          genre   ← st.selectbox    라벨 "좋아하는 장르", 목록 ["SF", "드라마", "액션", "애니메이션"]
#          clicked ← st.button       라벨 "인사하기"
name = st.text_input("이름", placeholder="이름을 입력하세요.")
genre = st.selectbox("좋아하는 장르", ["SF", "드라마", "액션", "애니메이션"])
clicked = st.button("인사하기")

# [실습 2] clicked 가 True 일 때만 인사한다.
#          이름이 있으면 st.success(f"{name}님, {genre} 좋아하시는군요!")
#          이름이 비어 있으면 st.warning("이름을 먼저 입력하세요.")
if clicked:
    if name:
        st.success(f"{name}님, {genre} 좋아하시는군요!")
    else:
        st.warning("이름을 먼저 입력하세요.")


# [실습 3] 접었다 펴는 영역 st.expander("위젯이 돌려준 값 들여다보기") 안에서
#          세 값을 st.write({"name": name, "genre": genre, "clicked": clicked}) 로 보여 준다.

btn = st.expander("위젯이 돌려준 값 들여다보기"):
btn.write({"name": name, "genre": genre, "clicked": clicked})

st.info(
    "인사하기를 누른 뒤 **이름을 바꿔 보세요.** 인사말이 사라지고 `clicked`가 `False`로 돌아갑니다.\n\n"
    "버튼은 **누른 그 순간에만** `True`입니다. 왜 그런지는 다음 단계에서 봅니다."
)
