"""8단계 — 위키백과 API 호출 샘플. Streamlit 없이 터미널에서 실행합니다.

준비:
    .env 에  WIKI_CONTACT=your-email@example.com   (없어도 실행은 됩니다)

실행:
    python step8_wiki_api.py
    python step8_wiki_api.py "인터스텔라"

7단계 골격의 collect_documents() 는 가짜였습니다.
이 파일의 search() 와 fetch_page() 가 그 자리를 채울 재료입니다.

    ① search()      검색어로 후보 문서의 제목을 찾습니다
    ② fetch_page()  고른 문서의 본문과 원문 URL을 받습니다

**어떤 문서를 고를지는 정해 두지 않았습니다.** 검색 결과에는 관련 없는 문서도 섞여 나옵니다.
무엇을 쓰고 무엇을 버릴지 판단하는 규칙을 만드는 것이 3일 과제의 일부입니다.
"""

import html
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://ko.wikipedia.org/w/api.php"

# 위키백과 API는 키가 없는 대신 User-Agent로 누가 보낸 요청인지 보고 한도를 나눕니다.
#   연락처 없음 → 분당 10회 (11번째 요청부터 429)
#   연락처 있음 → 분당 200회
# 연락처가 있으면 문제가 생겼을 때 운영자가 연락할 수 있어 한도를 넉넉히 줍니다.
# 형식: 앱이름/버전 (연락처) 라이브러리 — https://meta.wikimedia.org/wiki/User-Agent_policy
# 괄호 안에는 영문 이메일 또는 전체 URL이 들어가야 합니다. HTTP 헤더라 한글은 쓸 수 없습니다.
# 각자 자기 이메일을 넣으세요. 한 연락처를 여럿이 돌려 쓰면 한도를 함께 쓰게 되어 빨리 막힐 수 있습니다.
CONTACT = os.getenv("WIKI_CONTACT", "").strip()
USER_AGENT = f"MovieLab-Lab/0.1 ({CONTACT}) python-requests" if CONTACT \
    else "MovieLab-Lab/0.1 python-requests"


def check_user_agent() -> None:
    if not CONTACT:
        print("[안내] WIKI_CONTACT가 없어 분당 10회로 제한됩니다. 샘플 실행에는 충분합니다.")
        print("       과제에서 문서를 여러 개 모을 때는 .env 에 연락처를 꼭 넣으세요.\n")
    try:
        USER_AGENT.encode("latin-1")
    except UnicodeEncodeError:
        raise SystemExit("WIKI_CONTACT에 한글이 들어 있습니다. 영문 이메일이나 URL로 바꿔 주세요.")


def request_wikipedia(params: dict, max_retries: int = 4) -> dict:
    """위키백과 API를 호출합니다. 429(요청이 너무 많음)를 받으면 기다렸다가 다시 요청합니다."""
    wait = 2.0
    for attempt in range(1, max_retries + 1):
        response = requests.get(
            API_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=20
        )
        if response.status_code == 200:
            return response.json()
        if response.status_code == 429:
            # 서버가 알려 주는 대기 시간을 따르고, 없으면 점점 길게 기다립니다.
            retry_after = float(response.headers.get("Retry-After") or wait)
            print(f"[429] {retry_after:.0f}초 기다린 뒤 다시 요청합니다 ({attempt}/{max_retries})")
            time.sleep(retry_after)
            wait *= 2
            continue
        response.raise_for_status()
    raise RuntimeError("요청 제한이 계속되어 실패했습니다. 잠시 뒤 다시 실행해 주세요.")


def search(query: str, limit: int = 5) -> list[dict]:
    """① 검색어로 후보 문서를 찾습니다. 본문은 주지 않고 제목과 짧은 요약만 줍니다."""
    data = request_wikipedia({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "format": "json",
        "formatversion": 2,
    })
    return [
        {
            "page_id": item["pageid"],
            "title": item["title"],
            # 요약에는 <span class="searchmatch"> 같은 강조 태그가 섞여 있어 지웁니다.
            "snippet": html.unescape(re.sub(r"<[^>]+>", "", item.get("snippet", ""))),
        }
        for item in data["query"]["search"]
    ]


def fetch_page(title: str) -> dict | None:
    """② 문서 제목으로 본문과 원문 URL을 받습니다. 없는 문서면 None 을 돌려줍니다."""
    data = request_wikipedia({
        "action": "query",
        "prop": "extracts|info",
        "titles": title,
        "explaintext": 1,     # 태그 없는 본문 텍스트
        "inprop": "url",      # 원문 URL
        "redirects": 1,       # 넘겨주기 문서를 따라가 실제 문서를 받음
        "format": "json",
        "formatversion": 2,
    })
    page = data["query"]["pages"][0]
    if page.get("missing"):
        return None
    return {
        "page_id": page["pageid"],
        "title": page["title"],
        "url": page["fullurl"],
        "text": page.get("extract", ""),
    }


def main() -> None:
    check_user_agent()
    query = sys.argv[1] if len(sys.argv) > 1 else "명량 해전"

    print(f"① 검색 — \"{query}\"")
    results = search(query)
    for number, item in enumerate(results, start=1):
        print(f"   {number}. {item['title']}  ·  {item['snippet'][:40]}...")
    print("   → 관련 없는 문서도 섞여 있습니다. 무엇을 쓸지 고르는 규칙은 직접 만듭니다.\n")

    if not results:
        print("검색 결과가 없습니다. 다른 검색어로 실행해 보세요.")
        return

    # 호출 사이에 짧게 쉽니다. 여러 사람이 같은 교육장에서 호출하면 한도가 함께 줄어듭니다.
    time.sleep(0.5)

    title = results[0]["title"]
    print(f"② 본문 — \"{title}\"")
    page = fetch_page(title)
    print(f"   제목   : {page['title']}")
    print(f"   원문   : {page['url']}")
    print(f"   본문   : {len(page['text']):,}자")
    print(f"   앞부분 : {page['text'][:120].replace(chr(10), ' ')}...")
    print("   → 본문은 청킹해서 색인하고, 원문 URL은 근거 목록의 링크로 씁니다.\n")

    time.sleep(0.5)

    print("③ 없는 문서")
    print(f"   fetch_page('존재하지않는문서제목') → {fetch_page('존재하지않는문서제목')}")
    print("   → None 이면 건너뜁니다.")


if __name__ == "__main__":
    main()
