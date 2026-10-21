"""외부 호출이 막힌 환경을 대비한 문서 묶음 만들기 (명세 F2004). 연결될 때 미리 한 번 실행합니다.

실행 (프로젝트 폴더에서):
    python -m scripts.export_fallback                 # 대표 항목만
    python -m scripts.export_fallback law_001 law_017 # 고른 항목만
    python -m scripts.export_fallback --all           # 108건 전부 (오래 걸림)

항목마다 data/fallback/{item_id}.json 에 수집 단계와 같은 모양의 문서(raw doc)를 저장합니다.
    - 법률 + 시행령 조문 전체
    - 같은 제목의 위키백과 문서 (있으면)
    - 연결된 법령해석례 (PDF 변환본)
수집 단계는 외부 호출이 실패하면 이 파일을 읽어 대신 색인합니다 (prep/collect.py).
"""

import json
import sys

from config import FALLBACK_DIR
from prep import casebook, wiki_api
from prep.collect import article_doc, expc_docs, get_law_articles, wiki_doc
from prep.item_text import load_items

# 데모 · 검증에 쓰는 대표 항목 (주거 · 근로 · 소비자 · 금융 · 교통)
DEFAULT_NAMES = ["주택임대차보호법", "근로기준법", "최저임금법", "전자상거래 등에서의 소비자보호에 관한 법률",
                 "전기통신금융사기 피해 방지 및 피해자산 환급에 관한 특별법", "공인중개사법", "도로교통법"]


def bundle_for(item: dict) -> list[dict]:
    docs = [article_doc(item, a, "저장된 문서 묶음") for a in get_law_articles(item)]
    if not item.get("article_range"):
        page = wiki_api.fetch_page(item["name"])
        if page:
            docs.append(wiki_doc(item, page, "저장된 문서 묶음"))
    for case in casebook.load_casebook():
        if item["item_id"] in case.get("item_ids", []):
            docs += expc_docs(item, case, "저장된 문서 묶음")
    return docs


def main() -> None:
    items = load_items()
    args = sys.argv[1:]
    if "--all" in args:
        targets = items
    elif args:
        targets = [i for i in items if i["item_id"] in args]
    else:
        targets = [i for i in items if i["name"] in DEFAULT_NAMES]

    FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    for item in targets:
        docs = bundle_for(item)
        with open(FALLBACK_DIR / f"{item['item_id']}.json", "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False)
        print(f"{item['item_id']} {item['label']}: 문서 {len(docs)}개")


if __name__ == "__main__":
    main()
