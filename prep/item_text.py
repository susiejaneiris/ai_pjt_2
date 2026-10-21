"""항목 1건 → 색인 텍스트 1개 (F2001). 도메인에 묶인 규칙이라 데이터 준비 영역에 둡니다.

사용자는 법률을 '이름 · 분야 · 상황 · 담당 부처'로 찾는다.
상황 검색(F2011)이 걸리려면 "무엇을 다루는 법인지"가 텍스트에 있어야 하므로
제1조(목적)와 조문 제목 목록을 함께 넣는다. 빠진 속성으로는 검색이 걸리지 않는다.

실행 (항목 텍스트 확인 — 명세 4.1):
    python -m prep.item_text law_001
"""

import json
import sys

from config import ITEMS_JSON

MAX_TITLES_CHARS = 1500     # 조문이 수백 개인 법은 제목 목록이 1만 자에 가깝다 → 앞부분만


def load_items() -> list[dict]:
    with open(ITEMS_JSON, encoding="utf-8") as f:
        return json.load(f)


def format_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}" if len(yyyymmdd) == 8 else yyyymmdd


def build_item_text(item: dict) -> str:
    """법률 1건을 검색용 텍스트 하나로 묶는다."""
    name = item["label"]
    if item.get("abbr"):
        name += f" (약칭 {item['abbr']})"

    titles = ""
    for title in item.get("article_titles", []):
        if len(titles) + len(title) + 3 > MAX_TITLES_CHARS:
            titles += " …"
            break
        titles += (" · " if titles else "") + title

    lines = [
        f"법률명: {name}",
        f"분야: {item['category']} | 소관부처: {item['ministry']} | 시행일: {format_date(item['effective_date'])}",
    ]
    if item.get("article_range"):
        start, end = item["article_range"].split("-")
        lines.append(f"범위: {item['name']} 제{start}조~제{end}조")
    else:
        # 부분 항목(민법)의 제1조는 민법 전체의 목적이라 항목 설명이 되지 않는다.
        lines.append(f"목적: {item['purpose'].split(')', 1)[-1].strip()}")
    lines.append(f"주요 조문: {titles}")
    return "\n".join(lines)


def item_metadata(item: dict) -> dict:
    """law_meta 청크에 함께 저장할 메타데이터. Chroma 는 문자열 · 숫자만 받는다."""
    return {
        "item_id": item["item_id"],
        "label": item["label"],
        "name": item["name"],
        "abbr": item.get("abbr", ""),
        "category": item["category"],
        "ministry": item["ministry"],
        "effective_date": item["effective_date"],
        "url": item["url"],
        "source_type": "meta",
    }


if __name__ == "__main__":
    items = load_items()
    target = sys.argv[1] if len(sys.argv) > 1 else items[0]["item_id"]
    item = next(i for i in items if i["item_id"] == target)
    print(build_item_text(item))
    print(f"\n({len(build_item_text(item))}자)")
