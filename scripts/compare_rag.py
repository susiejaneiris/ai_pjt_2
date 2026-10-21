"""RAG 사용 전후 답변 비교 (F2015 · 명세 4.6) — 대표 질문을 RAG 없이 / RAG 로 답하게 해 나란히 기록.

실행 (프로젝트 폴더에서):
    python -m scripts.compare_rag

비교 기준 (명세 4.6)
    ① 사실 정확성 — 기대 핵심어가 답에 있는지 자동 표시 + 사람이 최종 판정
    ② 근거 제시   — 인용한 근거가 있는지 (RAG 없이는 출처를 댈 수 없다)
    ③ 모르면 모른다고 — 함정 질문에 "확인되지 않습니다"로 답하는지
결과는 docs/RAG_전후_비교.md 에 저장합니다.
"""

from datetime import datetime

from config import ROOT
from prep.item_text import load_items
from rag.prompts import NO_RAG_PROMPT, NOT_FOUND
from service.chat import ask
from service.runtime import Runtime, build_runtime

OUT = ROOT / "docs" / "RAG_전후_비교.md"

# (법률, 질문, 기대 핵심어, 함정 여부) — 근거 없이 답하면 틀리기 쉬운 질문 (기획서 1장)
QUESTIONS = [
    ("주택임대차보호법", "전입신고한 날 집주인이 대출을 받으면 내 보증금이 먼저인가요?", ["다음 날"], False),
    ("주택임대차보호법", "계약갱신요구권은 몇 번, 몇 년까지 쓸 수 있나요?", ["1회", "2년"], False),
    ("주택임대차보호법", "서울에서 보증금 1억 원 원룸에 살면 최우선변제를 받을 수 있나요?", ["시행령"], False),
    ("근로기준법", "상시 5명 미만 가게에서 일하는 알바도 연차유급휴가를 받을 수 있나요?", ["5명 미만"], False),
    ("전기통신금융사기 피해 방지 및 피해자산 환급에 관한 특별법",
     "보이스피싱으로 송금한 돈을 돌려받으려면 어떤 법에 따라 무엇을 신청하나요?", ["피해자산", "지급정지"], False),
    ("전자상거래 등에서의 소비자보호에 관한 법률", "온라인 쇼핑몰에서 산 물건 포장을 뜯으면 청약철회를 못 하나요?",
     ["내용을 확인|내용 확인"], False),
    ("주택임대차보호법", "부동산 중개보수 상한은 얼마인가요?", [], True),        # 함정 — 이 법에는 없다
]


def mark(answer: str, expect: list[str]) -> str:
    """기대 핵심어 일치 수. "A|B" 는 둘 중 하나만 있어도 일치."""
    if not expect:
        return "-"
    hits = [w for w in expect if any(alt in answer for alt in w.split("|"))]
    return f"{len(hits)}/{len(expect)} ({', '.join(hits) or '없음'})"


def one_line(text: str, limit: int = 1500) -> str:
    text = text.replace("\n", " ").replace("|", "／")
    return text[:limit] + ("…" if len(text) > limit else "")


def compare(rt: Runtime) -> str:
    items = {i["name"]: i for i in load_items()}
    rows, details = [], []
    for n, (law, question, expect, trap) in enumerate(QUESTIONS, start=1):
        item = items[law]
        print(f"[{n}] {question}")
        # RAG 없이는 일반 챗봇처럼 질문만 준다 — 법률 이름을 붙이면 답(예: 바뀐 법 이름)을 미리 알려 주게 된다
        plain = rt.llm.invoke([{"role": "system", "content": NO_RAG_PROMPT},
                               {"role": "user", "content": question}]).content
        rag = ask(rt, item, question, history=[])
        # 정해진 문장이 아니어도, 인용 없이 "확인되지 않/확인할 수 없"으로 시작하면 모른다고 답한 것으로 본다
        refused = rag.answer.startswith(NOT_FOUND) or (not rag.cited and any(
            k in rag.answer[:120] for k in ("확인되지 않", "확인할 수 없")))
        plain_refused = "확인되지" in plain or "알 수 없" in plain
        rows.append(
            f"| {n} | {question}{' (함정)' if trap else ''} | {mark(plain, expect)} | {mark(rag.answer, expect)} | "
            f"없음 | {len(rag.cited)}건 | "
            f"{('O' if plain_refused else 'X') if trap else '-'} | {('O' if refused else 'X') if trap else '-'} |"
        )
        cited = "<br>".join(f"[근거 {s['n']}] {s['type_label']} · {s['title']}" for s in rag.cited) or "인용 없음"
        details += [f"### {n}. {question}", f"- 법률: {item['label']}",
                    f"- 기대 핵심어: {', '.join(expect) or '(함정 — 확인되지 않는다고 답해야 함)'}", "",
                    "| RAG 없이 | RAG 사용 |", "|---|---|",
                    f"| {one_line(plain)} | {one_line(rag.answer)}<br><br>{cited} |",
                    "", "- 판정 (직접 작성): ", ""]

    return "\n".join([
        "# RAG 사용 전후 답변 비교 (F2015)", "",
        f"- 실행: {datetime.now():%Y-%m-%d %H:%M}",
        "- 같은 모델에 같은 질문을 ① 근거 없이(질문만, 법률 이름도 주지 않음) ② 법률을 고르고 근거를 붙여 물었다.",
        "- 핵심어 일치는 자동 표시이며, 사실 정확성의 최종 판정은 원문을 보고 직접 적는다.", "",
        "## 요약", "",
        "| # | 질문 | 핵심어 (RAG 없이) | 핵심어 (RAG) | 근거 제시 (RAG 없이) | 근거 제시 (RAG) | 모른다고 답함 (RAG 없이) | 모른다고 답함 (RAG) |",
        "|---|---|---|---|---|---|---|---|", *rows, "",
        "## 질문별 답변", "", *details,
    ])


def main(rt: Runtime | None = None) -> None:
    rt = rt or build_runtime()
    report = compare(rt)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(report, encoding="utf-8")
    print(f"→ docs/{OUT.name}")


if __name__ == "__main__":
    main()
