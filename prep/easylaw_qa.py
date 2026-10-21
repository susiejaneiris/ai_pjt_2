"""생활법령 백문백답 → 질문 단위 JSON (RAG 2 의 다섯 번째 출처 💬).

실행 (키가 활성화된 뒤, 프로젝트 폴더에서 한 번):
    python -m prep.easylaw_qa              # 전체 받기 (중간에 끊겨도 다시 실행하면 이어서 받는다)
    python -m prep.easylaw_qa --relink     # 받은 것은 그대로 두고 우리 법률과의 연결만 다시 계산

data/qa.json — 질문마다
    qa_id · 분류 · 주제 · 질문 · 답 · 관련 법령 문자열 · 관련 판례 등 · 원문 URL
    item_ids          관련 법령으로 연결한 우리 항목(법률)
    articles          항목별 관련 조문  예) {"law_001": ["제3조", "제3조의2"]}

왜 백문백답인가 — 평가에서 끝까지 못 찾은 질문(Q01 전입신고 당일 대출, Q20 음주 킥보드)은 일상어 질문과
조문 사이 의미 거리가 먼 경우였다. 백문백답은 "실제 사람들이 묻는 말 ↔ 법제처의 쉬운 답 ↔ 관련 조문"이
한 묶음이라 그 거리를 이어 준다.
"""

import argparse
import json
import re
import sys

from config import DATA_DIR
from prep import easylaw_api
from prep.item_text import load_items

QA_JSON = DATA_DIR / "qa.json"
SOURCE = "법제처 「찾기쉬운 생활법령정보」 생활법령 백문백답 (공공데이터포털 Open API)"
LAW_NAME = re.compile(r"「?([가-힣A-Za-z0-9ㆍ·\s]+?(?:법률|법|령|규칙))」?\s*(?=제\s*\d+\s*조)")
ARTICLE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")
# 백문백답은 2010년부터 쌓인 자료라 바뀌기 전 법 이름으로 적힌 것이 있다 (공백 뺀 이름 → 지금 이름)
ALIASES = {"전기통신금융사기피해방지및피해금환급에관한특별법": "전기통신금융사기피해방지및피해자산환급에관한특별법"}


# ── 관련 법령 문자열 → (법령명, 조문 목록) ────────────────────────────────────────

def parse_law_refs(text: str) -> list[tuple[str, list[str]]]:
    """'민법 제476조, 제477조 및 「주택임대차보호법」 제3조제1항' → [("민법", ["제476조", "제477조"]), ("주택임대차보호법", ["제3조"])]

    법령명이 다시 나오기 전까지의 조문은 앞 법령의 조문으로 본다.
    "제3조제1항"의 항 · 호는 버리고 조(條) 단위로만 남긴다 — 근거 단위가 조문이므로.
    """
    refs: list[tuple[str, list[str]]] = []
    names = list(LAW_NAME.finditer(text))
    for n, match in enumerate(names):
        end = names[n + 1].start() if n + 1 < len(names) else len(text)
        segment = text[match.end():end]
        articles = []
        for a, b in ARTICLE.findall(segment):
            label = f"제{a}조" + (f"의{b}" if b else "")
            if label not in articles:
                articles.append(label)
        refs.append((match.group(1).strip(), articles))
    return refs


def link_items(law_texts: list[str], items: list[dict]) -> tuple[list[str], dict[str, list[str]]]:
    """관련 법령 → 우리 항목. 시행령 · 시행규칙은 모법(법률) 항목으로, 민법은 조문 번호로 부분 항목에."""
    whole = {i["name"].replace(" ", ""): i for i in items if not i.get("article_range")}
    ranged = [i for i in items if i.get("article_range")]
    item_ids: list[str] = []
    articles: dict[str, list[str]] = {}

    def add(item_id: str, labels: list[str]) -> None:
        if item_id not in item_ids:
            item_ids.append(item_id)
        bucket = articles.setdefault(item_id, [])
        bucket += [l for l in labels if l not in bucket]

    for text in law_texts:
        for name, labels in parse_law_refs(text):
            base = re.sub(r"\s*(시행령|시행규칙)$", "", name).replace(" ", "")
            base = ALIASES.get(base, base)
            is_decree = bool(re.search(r"(시행령|시행규칙)$", name))
            if base in whole:
                add(whole[base]["item_id"], [] if is_decree else labels)   # 시행령 조문 번호는 법률 조문과 다르다
            for item in ranged:                                           # 민법(임대차) 같은 부분 항목
                if item["name"].replace(" ", "") != base:
                    continue
                start, end = map(int, item["article_range"].split("-"))
                inside = [l for l in labels if start <= int(re.match(r"제(\d+)", l).group(1)) <= end]
                if inside:
                    add(item["item_id"], inside)
    return item_ids, articles


# ── 받기 · 저장 ───────────────────────────────────────────────────────────────────

def load_qa() -> list[dict]:
    if not QA_JSON.exists():
        return []
    return json.loads(QA_JSON.read_text(encoding="utf-8"))


def save_qa(rows: list[dict]) -> None:
    QA_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def build(relink_only: bool = False) -> None:
    items = load_items()
    rows = load_qa()
    done = {r["qa_id"] for r in rows}

    if not relink_only:
        classes = [c for c in easylaw_api.qa_classes() if c["level"] == "중분류"]
        print(f"중분류 {len(classes)}개 — 이미 받은 질문 {len(done)}건은 건너뜀")
        for n, cls in enumerate(classes, start=1):
            listing = easylaw_api.qa_list(cls["ast_seq"], cls["cat_seq"])
            new = 0
            for qa in listing:
                qa_id = f"qa-{qa['ast_seq']}-{qa['que_seq']}"
                if qa_id in done:
                    continue
                try:
                    detail = easylaw_api.qa_item(qa["ast_seq"], qa["que_seq"])
                except easylaw_api.EasylawError as error:
                    print(f"  항목 실패 {qa_id}: {error}")
                    detail = {"laws": [], "references": [], "guides": [], "views": 0}
                rows.append({"qa_id": qa_id, **qa, **detail,
                             "url": easylaw_api.qa_page_url(qa["ast_seq"], qa["que_seq"]), "source": SOURCE})
                done.add(qa_id)
                new += 1
            print(f"[{n:3}/{len(classes)}] {cls['ast_name']} > {cls['cat_name']}: 목록 {len(listing)} · 새로 {new}")
            if new:
                save_qa(rows)                       # 분류마다 저장 — 끊겨도 이어서 받는다

    linked = 0
    for row in rows:
        row["item_ids"], row["articles"] = link_items(row.get("laws", []), items)
        linked += bool(row["item_ids"])
    save_qa(rows)
    print(f"\n백문백답 {len(rows)}건 → {QA_JSON.name} · 우리 법률과 연결된 질문 {linked}건 "
          f"({len({i for r in rows for i in r['item_ids']})}개 법률)")


# ── RAG 2 후보 찾기 ───────────────────────────────────────────────────────────────

def bigrams(text: str) -> set[str]:
    text = re.sub(r"\s+", "", text)
    return {text[i:i + 2] for i in range(len(text) - 1)}


def search_qa(item: dict, texts: list[str], limit: int) -> list[dict]:
    """선택한 법률과 연결된 백문백답 중, 질문 · 검색어와 글자 2개씩 겹치는 정도가 큰 순으로.

    한국어는 띄어쓰기 · 조사가 달라 낱말 단위로는 잘 안 맞는다 → 두 글자 조각(bigram) 겹침으로 본다.
    로컬 파일이라 외부 호출이 없다.
    """
    query_grams = set().union(*(bigrams(t) for t in texts)) if texts else set()
    linked = [r for r in load_qa() if item["item_id"] in r.get("item_ids", [])]

    def score(row: dict) -> float:
        grams = bigrams(row["subject"] + row["question"])
        return len(grams & query_grams) / (len(grams) ** 0.5 or 1)

    return sorted(linked, key=score, reverse=True)[:limit]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--relink", action="store_true", help="받기 없이 법률 연결만 다시 계산")
    args = parser.parse_args()
    try:
        build(relink_only=args.relink)
    except easylaw_api.EasylawError as error:
        sys.exit(f"백문백답 API 오류 {error}")
