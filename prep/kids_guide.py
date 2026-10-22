"""법제처 「함께 만들고 함께 지키는 어린이 생활법령」(2012) PDF → 주제 단위 JSON (RAG 2 · 💬 생활법령 Q&A).

실행 (프로젝트 폴더에서, 한 번만):
    python -m prep.kids_guide

data/pdf/함께_만들고_함께_지키는_어린이_생활법령.pdf → data/kids_guide.json

쓰는 부분은 PART 2 "어린이 생활법령" 27개 주제뿐이다 (책 12~39쪽).
    - 한 주제 = 상황 이야기 → 쉬운 설명 → 관련 조문 「법령명」 제N조 (1~2쪽)
    - 백문백답과 같은 "일상의 말 ↔ 조문" 다리라서 같은 후보 묶음(qa)에 넣는다 — 근거 표시는 따로
    - PART 1(소개) · 만화는 법 내용이 없고, PART 3(어린이법제관 법령개선 의견)은 개선 제안이라
      현행법 근거가 아니므로 뺀다

변환 규칙
    - 주제 경계는 목차(책 4~5쪽)의 쪽 번호로 정한다. PDF 쪽 = 책 쪽 + 2
    - 쪽 머리글(▪함께 만들고 함께 지키는NN · 어린이 생활법령▪ NN · PART 2 …) · 장 이름 · "더 궁금해요~?"
      장식 · 큰 제목 조각은 본문에서 뺀다. 문장은 고치지 않는다 (출처를 밝히고 원문 그대로 인용)
    - PDF 줄바꿈은 낱말 중간에서도 일어난다 ("「근로\\n기준법」") → 빈칸 없이 잇는다.
      줄 끝에 빈칸이 있거나 문장 · 소제목이 끝난 줄에서만 띄우거나 문단을 나눈다
    - 「법령명」 제N조 를 백문백답과 같은 규칙으로 우리 항목(법률)과 연결한다 (easylaw_qa.link_items)
    - 우리 108개 법률에 없는 법(민법 총칙 · 형법 · 저작권법 …)만 인용한 주제는 연결이 비어 있다
      → 검색어와 많이 겹칠 때만 어느 법률에서든 후보로 올린다 (easylaw_qa.search_qa)

알려진 한계
    - 낱말 사이에서 끊긴 줄 끝에 빈칸이 없으면 띄어쓰기가 하나 빠진다 ("매달한 번"). 글자는 그대로다.
    - 2012년 발행이라 금액 · 기간이 지금과 다를 수 있다 → 근거에 발행 연도를 표시하고,
      답변 프롬프트가 조문으로 확인되는 것만 단정하게 한다 (백문백답과 같은 규칙)
"""

import json
import re

from config import DATA_DIR
from prep.easylaw_qa import link_items
from prep.item_text import load_items

PDF_PATH = DATA_DIR / "pdf" / "함께_만들고_함께_지키는_어린이_생활법령.pdf"
GUIDE_JSON = DATA_DIR / "kids_guide.json"
PUBLISHER = "법제처, 「함께 만들고 함께 지키는 어린이 생활법령」(2012)"
PAGE_OFFSET = 2                      # PDF 쪽 번호(0부터) = 책 쪽 + 2
TOC_PAGES = (4, 5)                   # PART 2 목차가 있는 PDF 쪽
PART2_END = 39                       # PART 2 마지막 책 쪽 (40쪽부터 PART 3)

TOC_CHAPTER = re.compile(r"^(\d)\.\s*(\S+생활과 법)\s*$")
TOC_TOPIC = re.compile(r"^∙(.+?)\s*(\d{2})\s*$")
RUNNING = re.compile(r"^(▪함께 만들고 함께 지키는\s*\d+|어린이 생활법령▪\s*\d+|PART 2\. 어린이 생활법령|더|궁금해요~\?)$")
CHAPTER_LABEL = re.compile(r"^\d\.\s*\S+생활과 법$")
MORE = re.compile(r"^★")
SENTENCE_END = re.compile(r"([.?!~)」』”]|요|다)$")
LAW_REF = re.compile(r"「[^」]+」\s*제\s*\d+\s*조(?:의\s*\d+)?(?:\s*제\s*\d+\s*항)?(?:\s*제\s*\d+\s*호)?")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def read_toc(reader) -> list[dict]:
    """목차 → [{chapter, title, page}] (PART 2 만)."""
    topics, chapter = [], ""
    for p in TOC_PAGES:
        for line in (reader.pages[p].extract_text() or "").splitlines():
            line = line.strip()
            if m := TOC_CHAPTER.match(line):
                chapter = m.group(2)
            elif chapter and (m := TOC_TOPIC.match(line)) and int(m.group(2)) >= 12:
                topics.append({"chapter": chapter, "title": m.group(1).strip(), "page": int(m.group(2))})
    return topics


def join_lines(lines: list[str]) -> str:
    text = ""
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("※", "- ", "∙", "[")) and text and not text.endswith("\n"):
            text = text.rstrip() + "\n"        # 참고 · 목록 줄은 새 문단에서 시작
        text += stripped
        open_bracket = text.count("「") > text.count("」") or text.count("(") > text.count(")")
        if SENTENCE_END.search(stripped) or (len(stripped) < 25 and not open_bracket):
            text += "\n"               # 문장 · 소제목 · 짧은 줄(문단 끝) → 문단 나눔
        elif line != line.rstrip():
            text += " "                # 줄 끝 빈칸 = 낱말 사이
        # 그 밖에는 낱말 중간에서 끊긴 줄 → 빈칸 없이 잇는다
    return re.sub(r"\n{2,}", "\n", text).strip()


def parse_topic(reader, topic: dict, end_page: int) -> dict:
    title_key = compact(topic["title"])
    story, body, more = [], [], []
    seen_title = False
    for page in range(topic["page"], end_page + 1):
        for line in (reader.pages[page + PAGE_OFFSET].extract_text() or "").splitlines():
            key = compact(line)
            if not key or RUNNING.match(line.strip()) or CHAPTER_LABEL.match(line.strip()):
                continue
            if len(key) >= 2 and key in title_key:          # 큰 제목 조각 — 여기까지가 상황 이야기
                seen_title = True
                continue
            if MORE.match(key):
                more.append(line.strip().lstrip("★ "))
                continue
            (body if seen_title else story).append(line)
    if len(join_lines(body)) < len(join_lines(story)):      # 큰 제목이 쪽 아래에 있는 주제 — 나누지 않는다
        story, body = [], story + body
    return {
        "qa_id": f"kids-{topic['page']}",
        "kind": "kids",
        "chapter": topic["chapter"],
        "subject": topic["title"],
        "story": join_lines(story),
        "answer": join_lines(body),
        "more": more,
        "page_start": topic["page"],
        "page_end": end_page,
        "citation": f"{PUBLISHER}, {topic['page']}" + (f"~{end_page}쪽" if end_page > topic["page"] else "쪽"),
        "url": "",
        "service_date": "2012-12",
    }


def load_guide() -> list[dict]:
    if not GUIDE_JSON.exists():
        return []
    return json.loads(GUIDE_JSON.read_text(encoding="utf-8"))


def main() -> None:
    from pypdf import PdfReader     # 변환 때만 필요 — 앱은 kids_guide.json 만 읽는다
    reader = PdfReader(PDF_PATH)
    toc = read_toc(reader)
    items = load_items()
    rows = []
    for n, topic in enumerate(toc):
        end = toc[n + 1]["page"] - 1 if n + 1 < len(toc) else PART2_END
        row = parse_topic(reader, topic, end)
        row["laws"] = list(dict.fromkeys(LAW_REF.findall(row["story"] + "\n" + row["answer"])))
        row["item_ids"], row["articles"] = link_items([row["answer"]], items)
        rows.append(row)
    GUIDE_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")

    linked = [r for r in rows if r["item_ids"]]
    print(f"주제 {len(rows)}건 → {GUIDE_JSON.name} · 우리 법률과 연결된 주제 {len(linked)}건 "
          f"({len({i for r in rows for i in r['item_ids']})}개 법률)")
    for r in rows:
        print(f"  {r['page_start']:>2}~{r['page_end']:<2} [{r['chapter']}] {r['subject'][:28]:<30} "
              f"본문 {len(r['answer']):>4}자 · 연결 {r['item_ids']}")


if __name__ == "__main__":
    main()
