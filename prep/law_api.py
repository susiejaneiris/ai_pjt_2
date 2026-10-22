"""국가법령정보센터 Open API — 법령 검색 · 조문 · 판례. Streamlit 없이 터미널에서도 실행됩니다.

준비:
    .env 에  LAW_OC=신청한_이메일의_@_앞부분

실행 (프로젝트 폴더에서):
    python -m prep.law_api
    python -m prep.law_api "근로기준법" "최저임금"

step8_wiki_api.py 와 같은 자리입니다. 7단계 골격의 collect_documents() 를 채울 재료입니다.

    ① search_laws()    법령명으로 법령 목록과 메타데이터 (RAG 1 항목 메타데이터)
    ② fetch_articles() 법령 본문을 조(條) 단위로 펼친 목록 (RAG 2 외부 문서 — 청크 단위)
    ③ search_precs()   판례 검색 (사건명 기준 — 관련 없는 판례가 섞인다)
    ④ fetch_prec()     판례 본문 (판시사항 · 판결요지 · 참조조문)

응답에서 알게 된 것
    - 결과가 1건이면 목록이 아니라 dict 하나로 온다 → as_list() 로 맞춘다
    - 항이 있는 조문은 '조문내용'에 제목만 있고 본문은 항 · 호 아래에 있다 → 이어 붙인다
    - 판례 본문에는 <br/> 태그가 섞여 있다 → 지운다
    - 판례 검색은 사건명에서만 찾는다. '임대차보증금'으로 찾아도 상속 사건이 나온다
      → 참조조문으로 거르고 프롬프트 2로 선별하는 이유
"""

import re
import sys
import time

import requests

from config import env

SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
OC = env("LAW_OC")

MIN_INTERVAL = 0.3      # 호출 사이 최소 간격(초) — NF2006
MAX_RETRIES = 3
_last_call = 0.0


def request_law(url: str, params: dict) -> dict:
    """법령 API를 호출합니다. 간격을 지키고, 네트워크 오류 · 5xx 는 기다렸다가 다시 시도합니다."""
    global _last_call
    if not OC:
        raise RuntimeError("LAW_OC가 없습니다. .env 에 LAW_OC=이메일의_@_앞부분 을 넣어 주세요.")

    wait = 1.0
    for attempt in range(1, MAX_RETRIES + 1):
        time.sleep(max(0.0, _last_call + MIN_INTERVAL - time.monotonic()))
        _last_call = time.monotonic()
        try:
            response = requests.get(url, params={"OC": OC, "type": "JSON", **params}, timeout=30)
            if response.status_code < 500:
                break
        except requests.RequestException:
            if attempt == MAX_RETRIES:
                raise
        time.sleep(wait)
        wait *= 2

    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        # 인증 실패 · IP 미등록이면 JSON 대신 안내 문구가 온다.
        raise RuntimeError("법령 API가 JSON이 아닌 응답을 보냈습니다. LAW_OC 와 등록 IP를 확인하세요.")


def as_list(value) -> list:
    """결과가 1건이면 dict, 여러 건이면 list 로 오는 것을 list 로 맞춥니다."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def clean(text: str) -> str:
    """<br/> 같은 태그와 겹친 공백을 정리합니다."""
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def search_laws(query: str) -> list[dict]:
    """① 법령명으로 현행 법령을 찾습니다. 항목 메타데이터의 재료입니다."""
    # display 기본값은 20건 — "상법"처럼 이름이 다른 법령 이름에 많이 들어가면 정확히 같은 법이 밀려난다
    data = request_law(SEARCH_URL, {"target": "law", "query": query, "display": 100})
    return [
        {
            "law_id": item["법령ID"],
            "mst": item["법령일련번호"],          # 개정되면 바뀐다 → 재색인 기준
            "name": item["법령명한글"],
            "abbr": item.get("법령약칭명", ""),
            "kind": item.get("법령구분명", ""),
            "ministry": item.get("소관부처명", ""),
            "promulgation_date": item.get("공포일자", ""),
            "effective_date": item.get("시행일자", ""),
            "revision": item.get("제개정구분명", ""),
            "url": f"https://www.law.go.kr/법령/{item['법령명한글']}",
        }
        for item in as_list(data.get("LawSearch", {}).get("law"))
        if item.get("현행연혁코드") == "현행"
    ]


def article_label(unit: dict) -> str:
    """조문번호 3 + 가지번호 2 → '제3조의2'"""
    label = f"제{unit['조문번호']}조"
    if unit.get("조문가지번호"):
        label += f"의{unit['조문가지번호']}"
    return label


def joined(value) -> str:
    """내용 필드는 보통 문자열이지만 여러 줄이면 목록(중첩 포함)으로 온다."""
    if isinstance(value, list):
        return "\n".join(joined(v) for v in value)
    return value or ""


def article_text(unit: dict) -> str:
    """조문 제목줄 + 항 + 호 + 목을 한 덩어리 본문으로 이어 붙입니다."""
    lines = [joined(unit.get("조문내용"))]
    for para in as_list(unit.get("항")):
        lines.append(joined(para.get("항내용")))
        for item in as_list(para.get("호")):
            lines.append("  " + joined(item.get("호내용")))
            for sub in as_list(item.get("목")):
                lines.append("    " + joined(sub.get("목내용")))
    return clean("\n".join(line for line in lines if line.strip()))


def fetch_articles(mst: str) -> list[dict]:
    """② 법령 본문을 조 단위로 펼칩니다. 장 · 절 제목과 삭제된 조문은 뺍니다."""
    data = request_law(SERVICE_URL, {"target": "law", "MST": mst})
    law = data["법령"]
    name = law["기본정보"]["법령명_한글"]
    articles = []
    for unit in as_list(law.get("조문", {}).get("조문단위")):
        if unit.get("조문여부") != "조문":
            continue                              # 장 · 절 제목 행
        text = article_text(unit)
        if re.search(r"^제\d+조(의\d+)?\s*삭제", text):
            continue                              # "제5조 삭제 <2020.1.1>"
        label = article_label(unit)
        articles.append({
            "source": name,
            "mst": mst,
            "number": int(unit["조문번호"]),              # 민법(임대차)처럼 조문 범위를 자를 때 사용
            "article": label,
            "title": unit.get("조문제목", ""),
            "text": text,
            "effective_date": unit.get("조문시행일자", ""),
            "url": f"https://www.law.go.kr/법령/{name}/{label}",
        })
    return articles


def search_precs(query: str, limit: int = 20) -> list[dict]:
    """③ 판례를 사건명으로 찾습니다. 본문은 주지 않습니다."""
    data = request_law(SEARCH_URL, {"target": "prec", "query": query, "display": limit})
    return [
        {
            "prec_id": item["판례일련번호"],
            "case_no": item.get("사건번호", ""),
            "case_name": clean(item.get("사건명", "")),
            "court": item.get("법원명") or item.get("데이터출처명", ""),
            "date": item.get("선고일자", ""),
        }
        for item in as_list(data.get("PrecSearch", {}).get("prec"))
    ]


def fetch_prec(prec_id: str) -> dict | None:
    """④ 판례 본문. 판시사항 · 판결요지 · 참조조문만 씁니다 (판례내용 전문은 길어서 제외)."""
    data = request_law(SERVICE_URL, {"target": "prec", "ID": prec_id})
    body = data.get("PrecService")
    if not body:
        return None
    return {
        "prec_id": prec_id,
        "case_no": body.get("사건번호", ""),
        "case_name": clean(body.get("사건명", "")),
        "court": body.get("법원명", ""),
        "date": body.get("선고일자", ""),
        "holding": clean(body.get("판시사항", "")),       # 판시사항
        "summary": clean(body.get("판결요지", "")),       # 판결요지
        "ref_articles": clean(body.get("참조조문", "")),  # 참조조문 — 선별 규칙에 사용
        "url": f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={prec_id}",
    }


def main() -> None:
    law_query = sys.argv[1] if len(sys.argv) > 1 else "주택임대차보호법"
    prec_query = sys.argv[2] if len(sys.argv) > 2 else "임대차보증금"

    print(f"① 법령 검색 — \"{law_query}\"")
    laws = search_laws(law_query)
    for law in laws:
        print(f"   {law['name']} ({law['kind']}) · {law['ministry']} · 시행 {law['effective_date']} · MST {law['mst']}")
    if not laws:
        print("   검색 결과가 없습니다.")
        return
    time.sleep(0.5)

    law = laws[0]
    print(f"\n② 조문 — \"{law['name']}\"")
    articles = fetch_articles(law["mst"])
    lengths = [len(a["text"]) for a in articles]
    print(f"   조문 {len(articles)}개 · 길이 최소 {min(lengths)} / 최대 {max(lengths)}자")
    for article in articles[:3]:
        print(f"   [{article['source']} {article['article']}({article['title']})] {article['text'][:60]}...")
    time.sleep(0.5)

    print(f"\n③ 판례 검색 — \"{prec_query}\"")
    precs = search_precs(prec_query, limit=5)
    for number, prec in enumerate(precs, start=1):
        print(f"   {number}. {prec['court']} {prec['case_no']} ({prec['date']}) {prec['case_name'][:50]}...")
    if not precs:
        return
    time.sleep(0.5)

    print("\n④ 판례 본문 — 1번")
    prec = fetch_prec(precs[0]["prec_id"])
    print(f"   참조조문 : {prec['ref_articles'][:80]}")
    print(f"   판결요지 : {prec['summary'][:120]}...")
    print("   → 참조조문에 선택한 법령이 없으면 관련 없는 판례일 가능성이 크다. 선별 규칙의 근거.")


if __name__ == "__main__":
    main()
