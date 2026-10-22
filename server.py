"""내일의 법 — 웹 서버 (F2013 · 화면과 서버 분리). Streamlit 과 같은 service/ 모듈을 씁니다.

실행 (프로젝트 폴더에서):
    uvicorn server:app --port 8000
    → http://localhost:8000

요청 · 응답 형식
    GET  /api/items                              → [{item_id, label, name, category, ministry, effective_date, url, risks}]
    GET  /api/status                             → {ok, message, meta_count}
    GET  /api/items/{item_id}                    → {item, notices, docs_count, collected_titles}
    GET  /api/items/{item_id}/articles           → [{index, label}]
    POST /api/chat       {item_id, question, history:[{role, content}]}
    POST /api/factcheck  {item_id, claim}
    POST /api/explain    {item_id, article_index}
         ↳ 세 요청은 NDJSON 스트림: {"type":"step","message"}… → {"type":"result", ...} 또는 {"type":"error","message"}
    POST /api/find-laws  {condition}             → {results:[{item_id, label, category, reason}]}

화면에는 쉬운 안내만 내보내고 키 · 프롬프트 · 오류 추적 정보는 보내지 않습니다 (NF2004).
"""

import json
import logging
import queue
import threading
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, AuthenticationError
from pydantic import BaseModel, Field

from config import ROOT
from prep.casebook import KOGL_NOTICE
from prep.disclaimer import notices_for, risk_types
from prep.easy_explain import load_easy
from prep.item_text import load_items
from service.chat import Result
from service.features import article_choices, explain, factcheck
from service.find_laws import find_laws
from service.offline import QUOTA_MESSAGE, ask_or_offline, is_quota_error
from service.runtime import Runtime, build_runtime
from store.vectorstore import MissingKeyError

log = logging.getLogger("naeil_law.server")
app = FastAPI(title="내일의 법 API")
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
app.mount("/mascot", StaticFiles(directory=ROOT / "assets" / "mascot"), name="mascot")

EASY = load_easy()          # 법을 몰라도 알 수 있는 한두 문장 (prep/easy_explain.py)
ITEMS = [{**i, "easy": EASY.get(i["item_id"], "")} for i in load_items()]
ITEMS_BY_ID = {i["item_id"]: i for i in ITEMS}


class ChatRequest(BaseModel):
    item_id: str
    question: str = Field(min_length=1, max_length=1000)
    history: list[dict] = []


class FactRequest(BaseModel):
    item_id: str
    claim: str = Field(min_length=1, max_length=1000)


class ExplainRequest(BaseModel):
    item_id: str
    article_index: int


class FindRequest(BaseModel):
    condition: str = Field(min_length=1, max_length=500)


# ── 공통 ─────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def runtime() -> Runtime:
    return build_runtime()


def friendly_error(error: Exception) -> str:
    if isinstance(error, MissingKeyError):
        return "GMS_KEY가 설정되지 않았어요. .env 파일에 키를 넣고 서버를 다시 켜 주세요."
    if is_quota_error(error):
        return QUOTA_MESSAGE
    if isinstance(error, AuthenticationError):
        return "GMS 키가 만료되었거나 올바르지 않아요. 키를 다시 발급받아 .env에 넣어 주세요."
    if isinstance(error, APIConnectionError):
        return "AI 서버에 연결하지 못했어요. 네트워크를 확인하고 잠시 뒤 다시 시도해 주세요."
    return "처리하는 중에 문제가 생겼어요. 잠시 뒤 다시 시도해 주세요."


def get_item(item_id: str) -> dict:
    item = ITEMS_BY_ID.get(item_id)
    if not item:
        raise HTTPException(404, "없는 법률이에요.")
    return item


def public_item(item: dict) -> dict:
    keys = ("item_id", "label", "name", "category", "ministry", "effective_date", "url", "easy")
    return {**{k: item[k] for k in keys}, "risks": risk_types(item)}


def result_json(result: Result) -> dict:
    """화면에 필요한 것만 — 인용된 근거만 보낸다 (F2008)."""
    cited = [{
        "n": s["n"], "type": s["type"], "type_label": s["type_label"], "title": s["title"],
        "url": s["url"], "citation": s["citation"], "excerpt": s["text"].split("\n", 1)[-1][:400],
    } for s in result.cited]
    report = result.report
    return {
        "answer": result.answer, "cited": cited, "warnings": result.warnings, "notices": result.notices,
        "kogl": KOGL_NOTICE if any(c["type"] == "expc" for c in cited) else "",
        "elapsed": round(result.elapsed, 1),
        "offline": result.offline,            # AI 사용 한도가 끝나 원문만 보여 준 결과
        "report": None if report is None else {
            "queries": report.queries, "new_queries": report.new_queries, "selected": report.selected,
            "dropped": report.dropped[:10], "reused": report.reused_docs, "fallback": report.fallback,
        },
    }


def stream(task, to_json) -> StreamingResponse:
    """오래 걸리는 작업을 스레드에서 돌리며 진행 단계를 한 줄씩 흘려보낸다 (F2012)."""
    events: queue.Queue = queue.Queue()

    def worker():
        try:
            outcome = task(lambda message: events.put({"type": "step", "message": message}))
            events.put({"type": "result", **to_json(outcome)})
        except Exception as error:
            log.exception("task failed")
            events.put({"type": "error", "message": friendly_error(error)})
        events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        while (event := events.get()) is not None:
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


def ready_runtime() -> Runtime:
    try:
        rt = runtime()
    except Exception as error:
        raise HTTPException(503, friendly_error(error))
    if rt.meta_count() == 0:
        raise HTTPException(503, "아직 법률 색인이 없어요. 터미널에서 python -m scripts.build_index 를 실행해 주세요.")
    return rt


# ── 라우트 ───────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/items")
def items():
    return [public_item(i) for i in ITEMS]


@app.get("/api/status")
def status():
    try:
        rt = runtime()
        count = rt.meta_count()
    except Exception as error:
        return {"ok": False, "message": friendly_error(error), "meta_count": 0}
    if count == 0:
        return {"ok": False, "meta_count": 0,
                "message": "아직 법률 색인이 없어요. 터미널에서 python -m scripts.build_index 를 실행해 주세요."}
    return {"ok": True, "message": "", "meta_count": count}


@app.get("/api/items/{item_id}")
def item_detail(item_id: str):
    item = get_item(item_id)
    detail = {"item": public_item(item), "notices": notices_for(item), "docs_count": 0, "collected_titles": []}
    try:
        rt = runtime()
        detail["docs_count"] = rt.docs_count(item_id)
        detail["collected_titles"] = rt.collected_titles(item_id)
    except Exception:
        pass
    return detail


@app.get("/api/items/{item_id}/articles")
def articles(item_id: str):
    item = get_item(item_id)
    try:
        choices = article_choices(item)
    except Exception as error:
        log.exception("articles")
        raise HTTPException(502, friendly_error(error))
    return [{"index": n, "label": f"{a['source']} {a['article']}({a['title']})"} for n, a in enumerate(choices)]


@app.post("/api/chat")
def chat(request: ChatRequest):
    item, rt = get_item(request.item_id), ready_runtime()
    history = [{"role": m.get("role"), "content": str(m.get("content", ""))} for m in request.history
               if m.get("role") in ("user", "assistant")]
    return stream(lambda step: ask_or_offline(rt, item, request.question, history, on_step=step), result_json)


@app.post("/api/factcheck")
def fact(request: FactRequest):
    item, rt = get_item(request.item_id), ready_runtime()

    def to_json(outcome):
        verdict, result = outcome
        body = result.answer.split("\n", 1)[-1].strip() if result.answer.startswith("판정") else result.answer
        result.answer = body
        return {"verdict": verdict, **result_json(result)}

    return stream(lambda step: factcheck(rt, item, request.claim, on_step=step), to_json)


@app.post("/api/explain")
def explain_article(request: ExplainRequest):
    item, rt = get_item(request.item_id), ready_runtime()
    choices = article_choices(item)
    if not 0 <= request.article_index < len(choices):
        raise HTTPException(404, "없는 조문이에요.")
    article = choices[request.article_index]

    def to_json(result):
        return {**result_json(result), "original": {
            "title": f"{article['source']} {article['article']}({article['title']})",
            "text": article["text"], "url": article["url"]}}

    return stream(lambda step: explain(rt, item, article, on_step=step), to_json)


@app.post("/api/find-laws")
def find(request: FindRequest):
    rt = ready_runtime()
    try:
        results = find_laws(rt, request.condition, ITEMS_BY_ID)
    except Exception as error:
        log.exception("find_laws")
        raise HTTPException(502, friendly_error(error))
    return {"results": [{**public_item(r["item"]), "reason": r["reason"]} for r in results]}
