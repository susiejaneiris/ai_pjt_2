"""법제처 「찾기쉬운 생활법령정보」 Open API (공공데이터포털) — 생활법령 백문백답 · 생활법령정보.

실행 (연결 확인 — 프로젝트 폴더에서):
    python -m prep.easylaw_api

준비:
    .env 에  DATA_GO_KR_KEY=공공데이터포털_일반_인증키(Decoding)

두 서비스 모두 SOAP 방식이다. XML 봉투(Envelope)의 머리(Header)에 인증키를 넣어 POST 로 보낸다.
    - http 주소는 https 로 넘어가며(301) POST 가 GET 으로 바뀌어 "No such operation" 이 난다 → https 로 직접 보낸다
    - 키가 아직 등록되지 않았으면 HTTP 200 에 returnCode 30 "SERVICE KEY IS NOT REGISTERED ERROR."
    - 초당 최대 10건 (가이드) → 호출 사이 최소 0.15초

백문백답 조회 순서
    분류목록(getMaskMAnswerClassList) → 분류별 목록(getMaskMAnswerAreaList: 질문 · 답 본문)
    → 항목(getMaskMAnswerAreaItem: 관련 법령 · 판례 · 관심규정해설 링크)
"""

import html
import re
import time
import xml.etree.ElementTree as ET

import requests

from config import env

BASE = "https://www.easylaw.go.kr/OPENAPI/soap"
QA_SERVICE = f"{BASE}/ManyAskManyAnswerService"
LIFE_SERVICE = f"{BASE}/LifeLawInfoService"
QA_PAGE = "https://www.easylaw.go.kr/CSP/OnhunqueansInfoRetrieve.laf?onhunqnaAstSeq={ast}&onhunqueSeq={seq}"

MIN_INTERVAL = 0.15          # 초당 최대 10건
MAX_RETRIES = 3
_last_call = 0.0

ENVELOPE = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" \
xmlns:head="http://apache.org/headers" xmlns:open="http://openapi.affis.go.kr">
<soapenv:Header><head:ComMsgHeader><ServiceKey>{key}</ServiceKey></head:ComMsgHeader></soapenv:Header>
<soapenv:Body>{body}</soapenv:Body></soapenv:Envelope>"""

# 가이드의 에러코드 — 화면 · 로그에 쉬운 말로
ERRORS = {"01": "제공기관 서비스 오류", "02": "제공기관 DB 오류", "03": "데이터 없음", "04": "HTTP 오류",
          "05": "서비스 연결 실패", "10": "잘못된 요청 파라미터", "12": "서비스가 없거나 폐기됨",
          "20": "서비스 접근 거부", "22": "요청 한도 초과", "30": "등록되지 않은 인증키(활성화 대기 중일 수 있음)",
          "31": "기한이 만료된 인증키", "32": "등록되지 않은 IP", "99": "기타 오류"}


class EasylawError(RuntimeError):
    """API 가 오류 코드를 돌려줬을 때. 수집 단계의 EXTERNAL_ERRORS(RuntimeError)로 잡힌다."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {ERRORS.get(code, message)}")


def soap_call(url: str, body: str) -> ET.Element:
    """SOAP 요청을 보내고 응답 Body 의 첫 요소를 돌려준다. 간격 · 재시도 · 오류 코드를 처리한다."""
    global _last_call
    key = env("DATA_GO_KR_KEY")
    if not key:
        raise EasylawError("30", "DATA_GO_KR_KEY 가 없습니다")
    payload = ENVELOPE.format(key=html.escape(key), body=body).encode("utf-8")

    wait = 1.0
    for attempt in range(1, MAX_RETRIES + 1):
        time.sleep(max(0.0, _last_call + MIN_INTERVAL - time.monotonic()))
        _last_call = time.monotonic()
        try:
            response = requests.post(url, data=payload, timeout=30,
                                     headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""})
            if response.status_code < 500 or attempt == MAX_RETRIES:
                break
        except requests.RequestException:
            if attempt == MAX_RETRIES:
                raise
        time.sleep(wait)
        wait *= 2
    return parse_envelope(response.text)


def parse_envelope(text: str) -> ET.Element:
    """SOAP 응답 → Body 의 첫 요소. 오류 코드나 Fault 면 EasylawError."""
    root = ET.fromstring(text)
    body = next(el for el in root.iter() if el.tag.endswith("}Body"))
    first = list(body)[0]
    if first.tag.endswith("}Fault"):
        raise EasylawError("04", first.findtext("faultstring") or "SOAP Fault")
    code = first.findtext(".//returnCode")
    if code and code not in ("00", "0"):
        raise EasylawError(code.zfill(2), first.findtext(".//errMsg") or "")
    return first


def clean(text: str | None) -> str:
    """<br/> · HTML 엔티티 · 태그를 정리한다 (CDATA · 이스케이프 둘 다 온다)."""
    text = html.unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


# ── 생활법령 백문백답 ─────────────────────────────────────────────────────────────

def qa_classes() -> list[dict]:
    """분류 목록 — 대분류(onhunqnaAstSeq) · 중분류(onhunqueAstSeq)."""
    return parse_qa_classes(soap_call(QA_SERVICE, "<open:getMaskMAnswerClassList/>"))


def parse_qa_classes(el: ET.Element) -> list[dict]:
    return [{
        "level": item.findtext("cls"),
        "ast_seq": item.findtext("onhunqnaAstSeq"),
        "ast_name": item.findtext("onhunqnaAstNm"),
        "cat_seq": item.findtext("onhunqueAstSeq"),
        "cat_name": item.findtext("onhunqueCatNm") or "",
    } for item in el.iter("MaskMAnswerClassListItem")]


def qa_list(ast_seq: str, cat_seq: str) -> list[dict]:
    """분류별 질문 · 답 목록 (본문 포함)."""
    body = (f"<open:getMaskMAnswerAreaList><MaskMAnswerAreaListRequest><onhunqnaAstSeq>{ast_seq}</onhunqnaAstSeq>"
            f"<onhunqueAstSeq>{cat_seq}</onhunqueAstSeq></MaskMAnswerAreaListRequest></open:getMaskMAnswerAreaList>")
    return parse_qa_list(soap_call(QA_SERVICE, body))


def parse_qa_list(el: ET.Element) -> list[dict]:
    return [{
        "ast_seq": item.findtext("onhunqnaAstSeq"),
        "ast_name": item.findtext("onhunqnaAstNm"),
        "cat_name": item.findtext("onhunqueCatNm") or "",
        "que_seq": item.findtext("onhunqueSeq"),
        "subject": clean(item.findtext("onhunqueSubjNm")),
        "question": clean(item.findtext("onhunqueCts")),
        "answer": clean(item.findtext("onhunansCts")),
        "service_date": (item.findtext("onhunansServiceDt") or "")[:10],
    } for item in el.iter("MaskMAnswerAreaListItem")]


def qa_item(ast_seq: str, que_seq: str) -> dict:
    """질문 하나 — 관련 법령 · 관련 판례 등 · 관심규정해설 링크."""
    body = (f"<open:getMaskMAnswerAreaItem><MaskMAnswerAreaItemRequest><onhunqnaAstSeq>{ast_seq}</onhunqnaAstSeq>"
            f"<onhunqueSeq>{que_seq}</onhunqueSeq></MaskMAnswerAreaItemRequest></open:getMaskMAnswerAreaItem>")
    return parse_qa_item(soap_call(QA_SERVICE, body))


def parse_qa_item(el: ET.Element) -> dict:
    return {
        "laws": [clean(x.findtext("onhunqueConLsiNm")) for x in el.iter("MaskMAnswerAreaLawListItem")],
        "references": [{"kind": clean(x.findtext("onhunqueConEtcCdNm")), "name": clean(x.findtext("onhunqueConEtcNm"))}
                       for x in el.iter("MaskMAnswerAreaFileListItem")],
        "guides": [{"title": clean(x.findtext("cnpClsNm")), "url": html.unescape(x.findtext("linkUrl") or "")}
                   for x in el.iter("MaskMAnswerAreaInfoListItem")],
        "views": int(el.findtext(".//onhunqueRetriCnt") or 0),
    }


def qa_page_url(ast_seq: str, que_seq: str) -> str:
    return QA_PAGE.format(ast=ast_seq, seq=que_seq)


if __name__ == "__main__":
    try:
        classes = qa_classes()
    except EasylawError as error:
        raise SystemExit(f"백문백답 API 연결 실패 {error}")
    big = [c for c in classes if c["level"] == "대분류"]
    print(f"백문백답 분류: 대분류 {len(big)}개 · 중분류 {len(classes) - len(big)}개")
    print(" · ".join(c["ast_name"] for c in big))
