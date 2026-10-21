"""7단계 — 프로젝트 UI 골격. 여기서 3일 프로젝트가 시작됩니다.

실행:
    streamlit run step7_skeleton.py

6단계 챗봇에 프로젝트에 필요한 세 가지를 더합니다.

    ① 사이드바에서 질문할 항목을 고른다         st.selectbox
    ② 오래 걸리는 단계를 보여 준다             st.status
    ③ 답변 아래에 근거 목록을 붙인다            st.expander

**아직 RAG는 없습니다.** 문서 수집도 검색도 가짜입니다.
이 골격의 빈 칸을 진짜로 채워 나가는 것이 3일 프로젝트입니다.
이 파일을 오후부터 각자 프로젝트의 app.py로 이어 씁니다. 새로 만들지 않습니다.

비유 — st.status는 배달앱의 "조리 중 → 배달 중" 표시, 근거 목록은 보고서의 각주입니다.

놓치기 쉬운 두 가지
    1. 대화를 다시 그릴 때 근거 목록도 함께 그린다. 빠뜨리면 이전 답변의 근거가 사라진다.
    2. 검색된 문서를 전부 보여 주지 않는다. 답변이 실제로 인용한 [근거 N]만 보여 주고,
       인용이 하나도 없으면 그 사실을 안내한다. (요구사항 F2008)
"""

import os
import re
import time

import streamlit as st
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

GMS_BASE_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/"

# 실습용 임시 항목 목록 (예시 도메인: 영화).
DOMAIN = "영화"
ITEMS = ["기생충 (2019)", "명량 (2014)", "인터스텔라 (2014)", "올드보이 (2003)"]

# 답변 본문의 [근거 3], [근거 3, 5] 표기를 찾는다.
CITE_PATTERN = re.compile(r"\[근거\s*([\d,\s]+)\]")


@st.cache_resource
def get_model() -> ChatOpenAI:
    key = os.environ.get("GMS_KEY")
    if not key:
        st.error("GMS_KEY가 없습니다. .env를 확인하세요.")
        st.stop()
    return ChatOpenAI(model="gpt-5.4-nano", api_key=key, base_url=GMS_BASE_URL)


def collect_documents(item: str, question: str) -> list[dict]:
    """(가짜) 문서 수집. 프로젝트에서는 여기가 외부 문서 검색·선별·수집·색인이 된다. (RAG 2)

    첫 질문이 오래 걸리는 것을 흉내 내려고 일부러 멈춘다. 진행 표시가 왜 필요한지 보기 위한 것이다.
    """
    time.sleep(2)
    name = item.split(" (")[0]
    return [
        {
            "title": f"{name} (가짜 문서)",
            "url": "https://ko.wikipedia.org/",
            "text": f"{name}에 대한 외부 문서가 들어갈 자리입니다. 지금은 내용이 없습니다.",
        },
        {
            "title": "관련 배경 문서 (가짜 문서)",
            "url": "https://ko.wikipedia.org/",
            "text": "배경 지식 문서가 들어갈 자리입니다. 지금은 내용이 없습니다.",
        },
    ]


def cited_sources(answer: str, sources: list[dict]) -> list[tuple[int, dict]]:
    """답변이 실제로 인용한 근거만 (번호, 문서)로 돌려준다. 인용이 없으면 빈 목록. (F2008)"""
    numbers = {
        int(n) for group in CITE_PATTERN.findall(answer)
        for n in group.split(",") if n.strip().isdigit()
    }
    return [(i, s) for i, s in enumerate(sources, start=1) if i in numbers]


def render_sources(answer: str, sources: list[dict]) -> None:
    """답변 아래 근거 목록. 인용한 것만 보여 주고, 인용이 없으면 안내한다."""
    used = cited_sources(answer, sources)
    if not used:
        st.caption("ⓘ 답변에 인용된 근거가 없습니다.")
        return
    with st.expander(f"답변에 사용한 근거 {len(used)}건"):
        for number, source in used:
            st.markdown(f"**[근거 {number}]** {source['title']} · [원문]({source['url']})")


st.set_page_config(page_title="RAG 서비스 (골격)", page_icon="🎬")
st.title("🎬 Movie Lab")
st.caption("근거를 찾아 답하고 출처를 함께 보여 주는 지식 서비스 — UI 골격 (예시 도메인: 영화)")

with st.sidebar:
    st.header(f"{DOMAIN} 선택")
    item = st.selectbox(
        f"질문할 {DOMAIN}", ITEMS, index=None, key="item", placeholder=f"{DOMAIN}을(를) 고르세요"
    )
    if st.button("대화 지우기", width="stretch"):
        st.session_state.messages = []

if not item:
    st.info(f"왼쪽에서 질문할 {DOMAIN}을(를) 먼저 고르세요.")
    st.stop()

st.subheader(item)

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            render_sources(message["content"], message.get("sources", []))

question = st.chat_input(f"이 {DOMAIN}에 대해 궁금한 점을 물어보세요")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.status("관련 문서를 찾고 있습니다...", expanded=False) as status:
            sources = collect_documents(item, question)
            status.update(label=f"문서 {len(sources)}건 확보", state="complete")
            st.caption(" · ".join(s["title"] for s in sources))

        context = "\n\n".join(
            f"[근거 {i}] {s['title']}\n{s['text']}" for i, s in enumerate(sources, start=1)
        )
        prompt = (
            f"너는 {DOMAIN} 큐레이터다. 아래 [문서]에 있는 내용만 사용해 답한다.\n"
            "문서에 없으면 '문서에서 확인되지 않는다'고 답한다.\n"
            "문서에서 온 주장 뒤에는 [근거 N] 형태로 번호를 붙인다.\n\n"
            f"[문서]\n{context}\n\n[{DOMAIN}]\n{item}\n\n[질문]\n{question}"
        )

        with st.spinner("답변을 만드는 중..."):
            try:
                answer = get_model().invoke(prompt).content
            except Exception:
                answer = ""

        if answer:
            st.markdown(answer)
            render_sources(answer, sources)  # ③ 근거 목록
        else:
            st.error("답변을 만들지 못했습니다. 키와 네트워크를 확인해 주세요.")

    if answer:
        st.session_state.messages.append(
            {"role": "assistant", "content": answer, "sources": sources}
        )
