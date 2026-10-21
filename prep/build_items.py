"""항목 메타데이터 만들기 (F2001 의 재료). 색인 전에 한 번 실행합니다.

실행 (프로젝트 폴더에서):
    python -m prep.build_items

data/item_list.csv (우리가 고른 법률 목록) → 법령 API → data/items.json

    1. 법령명으로 검색해 이름이 정확히 같은 '법률'을 찾는다 (시행령 · 시행규칙은 항목이 아니라 외부 문서)
    2. 본문에서 제1조(목적)와 조문 제목 목록을 꺼낸다 → 항목 텍스트에서 상황 검색이 걸리게 하는 재료
    3. 민법처럼 부분 항목이면 조문 범위 안의 제목만 남긴다
    4. 찾지 못한 이름은 따로 알려 준다 → item_list.csv 를 고친다
"""

import csv
import json
from datetime import date

from config import ITEM_LIST_CSV, ITEMS_JSON
from prep.law_api import fetch_articles, search_laws

SOURCE = "국가법령정보센터 Open API (https://open.law.go.kr)"


def find_law(name: str) -> dict | None:
    """이름이 정확히 같은 법률 하나. 공백 · 가운뎃점 차이는 무시한다."""
    def norm(text: str) -> str:
        return text.replace(" ", "").replace("ㆍ", "").replace("·", "")

    for law in search_laws(name):
        if law["kind"] == "법률" and norm(law["name"]) == norm(name):
            return law
    return None


def parse_range(text: str) -> tuple[int, int] | None:
    """'618-654' → (618, 654). 비어 있으면 None(전체)."""
    if not text:
        return None
    start, end = text.split("-")
    return int(start), int(end)


def summarize_articles(articles: list[dict], article_range: tuple[int, int] | None) -> dict:
    """제1조(목적), 범위 안의 조문 제목 목록, 조문 수."""
    first = next((a for a in articles if a["article"] == "제1조"), None)
    if article_range:
        start, end = article_range
        articles = [a for a in articles if start <= a["number"] <= end]
    titles = []
    for article in articles:
        if article["title"] and article["title"] not in titles:
            titles.append(article["title"])
    return {
        "purpose": first["text"] if first else "",
        "article_titles": titles,
        "article_count": len(articles),
    }


def main() -> None:
    with open(ITEM_LIST_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    items, missing = [], []
    cache: dict[str, list[dict]] = {}   # 민법처럼 여러 항목이 같은 법을 쓰면 본문은 한 번만 받는다
    for number, row in enumerate(rows, start=1):
        name = row["name"].strip()
        label = row["label"].strip() or name
        article_range = parse_range(row["article_range"].strip())
        try:
            law = find_law(name)
            if law and law["mst"] not in cache:
                cache[law["mst"]] = fetch_articles(law["mst"])
            summary = summarize_articles(cache[law["mst"]], article_range) if law else None
        except Exception as error:
            print(f"[{number:3}] 오류  {label}: {error}")
            missing.append(label)
            continue
        if not law:
            print(f"[{number:3}] 없음  {label}")
            missing.append(label)
            continue

        items.append({
            "item_id": f"law_{len(items) + 1:03}",
            "label": label,                                  # 화면에 보이는 이름
            "category": row["category"].strip(),
            "article_range": row["article_range"].strip() or None,
            **law,                                           # law_id, mst, name, abbr, kind, ministry, 날짜들, url
            **summary,                                       # purpose, article_titles, article_count
            "source": SOURCE,
            "collected_at": date.today().isoformat(),
        })
        print(f"[{number:3}] 확인  {label} · 조문 {summary['article_count']}개 · 시행 {law['effective_date']}")

    with open(ITEMS_JSON, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)

    print(f"\n항목 {len(items)}건 → {ITEMS_JSON.name}")
    if missing:
        print(f"찾지 못한 {len(missing)}건 — item_list.csv 의 이름을 확인하세요: {missing}")


if __name__ == "__main__":
    main()
