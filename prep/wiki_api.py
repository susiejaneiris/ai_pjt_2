"""한국어 위키백과 API — 검색 · 본문. step8_wiki_api.py 를 프로젝트용으로 옮긴 것입니다.

실행 (프로젝트 폴더에서):
    python -m prep.wiki_api "주택임대차보호법"

외부 API 예절 (NF2006)
    - User-Agent 에 연락처(WIKI_CONTACT)를 넣는다. 없으면 분당 10회, 있으면 200회
    - 호출 사이 최소 간격을 지키고, 429 를 받으면 Retry-After 만큼 기다렸다 다시 요청한다
"""

import html
import re
import sys
import time

import requests

from config import env

API_URL = "https://ko.wikipedia.org/w/api.php"
CONTACT = env("WIKI_CONTACT")
USER_AGENT = (f"LawGuide/0.1 ({CONTACT}) python-requests" if CONTACT
              else "LawGuide/0.1 python-requests")
LICENSE = "CC BY-SA 4.0"

MIN_INTERVAL = 0.35 if CONTACT else 6.0
MAX_RETRIES = 4
_last_call = 0.0


def request_wikipedia(params: dict) -> dict:
    """간격을 지켜 호출하고, 429 면 기다렸다가 다시 요청합니다."""
    global _last_call
    wait = 2.0
    for _ in range(MAX_RETRIES):
        time.sleep(max(0.0, _last_call + MIN_INTERVAL - time.monotonic()))
        _last_call = time.monotonic()
        response = requests.get(
            API_URL, params={"format": "json", "formatversion": 2, **params},
            headers={"User-Agent": USER_AGENT}, timeout=20,
        )
        if response.status_code == 200:
            return response.json()
        if response.status_code == 429 or response.status_code >= 500:
            time.sleep(float(response.headers.get("Retry-After") or wait))
            wait *= 2
            continue
        response.raise_for_status()
    raise RuntimeError("위키백과 요청 제한이 계속되어 실패했습니다.")


def search(query: str, limit: int = 5) -> list[dict]:
    """검색어로 후보 문서의 제목과 요약을 찾습니다. 본문은 주지 않습니다."""
    data = request_wikipedia({"action": "query", "list": "search", "srsearch": query, "srlimit": limit})
    return [
        {
            "page_id": item["pageid"],
            "title": item["title"],
            "snippet": html.unescape(re.sub(r"<[^>]+>", "", item.get("snippet", ""))),
        }
        for item in data.get("query", {}).get("search", [])
    ]


def fetch_page(title: str) -> dict | None:
    """문서 제목으로 본문 · 원문 URL · 최종 수정일. 없는 문서면 None."""
    data = request_wikipedia({
        "action": "query", "prop": "extracts|info", "titles": title,
        "explaintext": 1, "inprop": "url", "redirects": 1,
    })
    page = data["query"]["pages"][0]
    if page.get("missing") or not page.get("extract"):
        return None
    return {
        "page_id": page["pageid"],
        "title": page["title"],
        "url": page["fullurl"],
        "text": page["extract"],
        "touched": page.get("touched", "")[:10].replace("-", ""),
    }


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "주택임대차보호법"
    for hit in search(query):
        print(f"- {hit['title']} · {hit['snippet'][:50]}")
    page = fetch_page(query)
    print(f"\n같은 제목 문서: {page['title']} · {len(page['text']):,}자 · {page['url']}" if page
          else "\n같은 제목 문서 없음")
