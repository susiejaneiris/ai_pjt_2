"""근거 표시 (F2008) — 답변이 실제로 인용한 근거만 골라내고, 이상한 인용을 찾아냅니다."""

import re

CITE_PATTERN = re.compile(r"\[근거\s*([\d,\s]+)\]")
ARTICLE_PATTERN = re.compile(r"제\s?(\d+)조(?:의\s?(\d+))?")


def cited_numbers(answer: str) -> list[int]:
    numbers = []
    for group in CITE_PATTERN.findall(answer):
        numbers += [int(n) for n in group.split(",") if n.strip().isdigit()]
    return list(dict.fromkeys(numbers))


def cited_sources(answer: str, sources: list[dict]) -> list[dict]:
    """답변에 [근거 N] 으로 나온 근거만. 없으면 빈 목록 → 화면에서 '인용 없음' 안내."""
    numbers = set(cited_numbers(answer))
    return [s for s in sources if s["n"] in numbers]


def citation_warnings(answer: str, sources: list[dict]) -> list[str]:
    """없는 근거 번호 인용, 근거에 없는 조문 번호 언급을 찾는다 (조문 번호 지어내기 방지)."""
    warnings = []
    valid = {s["n"] for s in sources}
    unknown = [n for n in cited_numbers(answer) if n not in valid]
    if unknown:
        warnings.append(f"근거 목록에 없는 번호를 인용했습니다: {unknown}")

    known = set()
    for s in sources:
        known.update(article_labels(s["text"]))
    invented = sorted(article_labels(answer) - known)
    if invented:
        warnings.append("근거 문서에서 찾을 수 없는 조문 번호가 있습니다: " + ", ".join(invented))
    return warnings


def article_labels(text: str) -> set[str]:
    """'제3조의2', '제 6 조' → {'제3조의2', '제6조'}"""
    return {f"제{a}조" + (f"의{b}" if b else "") for a, b in ARTICLE_PATTERN.findall(text)}
