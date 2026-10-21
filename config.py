"""경로 · 설정 · 환경변수를 한곳에서 읽습니다.

청킹 · 검색 값은 코드가 아니라 settings.json 에서 바꿉니다. (F2005 · F2006 · F2014)
키는 .env 에서만 읽고 코드에 쓰지 않습니다. (NF2003)
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
ITEM_LIST_CSV = DATA_DIR / "item_list.csv"
ITEMS_JSON = DATA_DIR / "items.json"
COLLECTED_JSON = DATA_DIR / "collected.json"      # 이미 수집한 검색어 (NF2002)
FALLBACK_DIR = DATA_DIR / "fallback"              # 외부 호출이 막힌 환경용 문서 묶음 (F2004)
VECTOR_DIR = ROOT / "vectorstore"                 # Chroma 저장 폴더

META_COLLECTION = "law_meta"                      # RAG 1 — 항목 메타데이터
DOCS_COLLECTION = "law_docs"                      # RAG 2 — 외부 문서

GMS_BASE_URL = "https://gms.ssafy.io/gmsapi/api.openai.com/v1/"


def load_settings(**overrides) -> dict:
    """settings.json 을 읽습니다. 비교 실험에서는 overrides 로 값만 바꿔 씁니다."""
    with open(ROOT / "settings.json", encoding="utf-8") as f:
        settings = json.load(f)
    settings.update(overrides)
    return settings


def env(name: str) -> str:
    return os.getenv(name, "").strip()
