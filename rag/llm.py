"""채팅 모델과 JSON 응답 파싱. UI 와 무관한 모듈입니다."""

import json
import re

from langchain_openai import ChatOpenAI

from config import GMS_BASE_URL, env, load_settings
from store.vectorstore import MissingKeyError


def get_chat_model() -> ChatOpenAI:
    key = env("GMS_KEY")
    if not key:
        raise MissingKeyError("GMS_KEY가 없습니다. .env 를 확인하세요.")
    settings = load_settings()
    # 온도를 낮춰 같은 근거 · 같은 질문에 같은 답이 나오게 한다 — 평가에서 실행마다 인용 · 거절이 흔들렸다
    return ChatOpenAI(model=settings["chat_model"], api_key=key, base_url=GMS_BASE_URL,
                      temperature=settings.get("temperature", 0))


def parse_json(text: str, default):
    """```json ... ``` 으로 감싸 오거나 앞뒤에 말이 붙어도 JSON 부분만 꺼낸다. 실패하면 default."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"(\{.*\}|\[.*\])", text, flags=re.DOTALL)
    if not match:
        return default
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return default
