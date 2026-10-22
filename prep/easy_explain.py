"""법률마다 '법을 몰라도 알 수 있는 한두 문장 설명' 만들기 — 검색 결과에서 법률 이름에 마우스를 올리면 보여 준다.

실행 (프로젝트 폴더에서, 법률 목록을 바꿨을 때 한 번):
    python -m prep.easy_explain            # 없는 것만 만든다
    python -m prep.easy_explain --all      # 전부 다시

data/items.json 의 제1조(목적) · 주요 조문 제목 → LLM → data/law_easy.json {item_id: 설명}

규칙 (프롬프트에 그대로)
    - 목적 조문과 조문 제목에 있는 내용만 쉬운 말로 — 금액 · 기간 · 처벌 같은 구체 내용은 쓰지 않는다
      (근거 없이 단정하면 틀릴 수 있다. 자세한 내용은 대화에서 조문을 근거로 답한다)
    - 해요체, 1~2문장, 생활 속 예시 상황 하나
"""

import argparse
import json

from config import DATA_DIR
from prep.item_text import load_items
from rag.llm import get_chat_model, parse_json

EASY_JSON = DATA_DIR / "law_easy.json"
BATCH = 12

PROMPT = """너는 법을 전혀 모르는 사람에게 법률을 소개하는 안내자다. 아래 [법률]마다 한두 문장 설명을 쓴다.

규칙
- 해요체. 1~2문장, 80자 안팎. 중학생도 바로 이해하는 말만 쓴다.
- 법률 용어(대항력 · 채무불이행 · 법정대리인 · 특례 · 공정화 …)는 쓰지 않는다. 꼭 필요하면 쉬운 말로 바꾼다
  (임대차 → 집을 빌리고 빌려주는 일, 법정대리인 → 부모님).
- 무엇을 다루는 법인지는 목적보다 **주요 조문 제목**을 보고 판단한다 (목적 조문이 추상적인 법이 많다).
- 끝에 "예를 들어 ~할 때 봐요." 처럼 생활 속 상황 하나를 든다.
- 목적 · 조문 제목에 있는 내용만 쓴다. 금액 · 기간 · 처벌 수위 같은 구체적인 내용은 쓰지 않는다.
- JSON 만 출력한다. 형식: {{"law_001": "설명", ...}}

[법률]
{laws}"""


def load_easy() -> dict:
    if EASY_JSON.exists():
        return json.loads(EASY_JSON.read_text(encoding="utf-8"))
    return {}


def describe(item: dict) -> str:
    titles = " · ".join(t for t in item.get("article_titles", []) if t not in ("목적", "정의"))[:400]
    purpose = item.get("purpose", "").split(")", 1)[-1].strip()[:300]
    return f"- {item['item_id']} | {item['label']} | 목적: {purpose} | 주요 조문: {titles}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="이미 만든 것도 다시")
    args = parser.parse_args()

    easy = {} if args.all else load_easy()
    todo = [i for i in load_items() if i["item_id"] not in easy]
    llm = get_chat_model()
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        answer = parse_json(llm.invoke(PROMPT.format(laws="\n".join(describe(i) for i in batch))).content, default={})
        for item in batch:
            text = answer.get(item["item_id"]) if isinstance(answer, dict) else None
            if isinstance(text, str) and text.strip():
                easy[item["item_id"]] = text.strip()
        EASY_JSON.write_text(json.dumps(easy, ensure_ascii=False, indent=1), encoding="utf-8")   # 끊겨도 이어서
        print(f"{min(start + BATCH, len(todo))}/{len(todo)}")
    missing = [i["label"] for i in load_items() if i["item_id"] not in easy]
    print(f"설명 {len(easy)}건 → {EASY_JSON.name}" + (f" · 빠진 것 {missing}" if missing else ""))


if __name__ == "__main__":
    main()
