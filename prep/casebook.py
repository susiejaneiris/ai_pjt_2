"""법제처 「2024 법령해석 사례집」 PDF → 사례 단위 JSON (F2016 · PDF 출처).

실행 (프로젝트 폴더에서, 한 번만):
    python -m prep.casebook

data/pdf/법제처_2024_법령해석사례집_(상|하).pdf → data/casebook.json

PDF 한 사례의 모양
    질의제목 1 ▶ 안건번호 23-0932
    민원인 – (제목) (「소득세법 시행령」 제155조제8항 등 관련)
    질의요지 … 회답 … 이유 … (법령정비 권고사항 …)
    쪽 아래에는 각주 "1) …" 가 붙는다

변환 규칙
    - 쪽 머리글(사례집 제목) · 쪽 번호 · 절 제목은 본문에서 뺀다 (절 이름은 메타데이터로)
    - 각주는 본문에 표시("중개546)")가 나온 번호로 시작하는 줄만 각주로 본다 → 본문의 "1)" 나열과 구분
      (하권은 각주 번호가 사례마다 1로 돌아가지 않고 장 단위로 이어진다)
    - 본문 속 각주 표시("경우1)")는 지운다. 각주 본문은 footnotes 로 따로 보관
    - 제목의 「법령명」에서 시행령 · 시행규칙을 떼어 항목(법률)과 연결한다

알려진 한계
    - PDF 텍스트 추출 순서가 꼬인 쪽에서는 각주가 본문 중간에 섞인다 (312건 중 4건: 23-1022, 24-0033,
      24-0696, 24-0848). 원문 쪽 번호를 근거에 함께 표시하므로 사용자가 원문으로 대조할 수 있다.

수집 단계(prep/collect.py)는 search_cases() 로 후보를 받아 프롬프트 2 로 선별한다.
"""

import json
import re
from pathlib import Path

from pypdf import PdfReader

from config import DATA_DIR
from prep.item_text import load_items

PDF_DIR = DATA_DIR / "pdf"
CASEBOOK_JSON = DATA_DIR / "casebook.json"
VOLUMES = {"상": "법제처_2024_법령해석사례집_(상).pdf", "하": "법제처_2024_법령해석사례집_(하).pdf"}
PUBLISHER = "법제처, 「2024 법령해석 사례집」"
# 공공누리 제4유형(출처표시 · 상업적 이용금지 · 변경금지) — 근거로 쓸 때마다 화면에 함께 표시 (NF2007)
KOGL_NOTICE = ("이 서비스는 공공누리 제4유형으로 개방한 '법제처, 「2024 법령해석 사례집」'을 이용하였으며, "
               "해당 저작물은 공공데이터포털(www.data.go.kr)에서 무료로 내려받을 수 있습니다.")

SECTION_NAMES = {"질의요지": "question", "회답": "answer", "이유": "reason",
                 "법령정비 권고사항": "recommendation", "법령정비 권고의견": "recommendation"}
CASE_HEAD = re.compile(r"^질의제목\s*(\d+)\s*▶\s*안건번호\s*(.+)$")
FOOTNOTE = re.compile(r"^(\d{1,4})\)\s*(.*)$")
INLINE_MARK = re.compile(r"(?<=[가-힣’”」\)a-zA-Z,])\s?(\d{1,4})\)")
SECTION_HEAD = re.compile(r"^제\s*\d+\s*절$")
CHAPTER_HEAD = re.compile(r"^제\s*\d+\s*장\s*(.*)$")
LAW_NAME = re.compile(r"「([^」]+)」")


def is_running_header(line: str) -> bool:
    return line.startswith("2024 법령해석 사례집") or line.isdigit()


def join_lines(lines: list[str]) -> str:
    """PDF 줄바꿈은 낱말 사이에서 일어난다 → 공백으로 잇고, 문장이 끝난 줄에서만 문단을 나눈다."""
    text = ""
    for line in lines:
        text += line.strip()
        text += "\n" if re.search(r"(다\.|\?|함\.|음\.)$", line.strip()) else " "
    text = INLINE_MARK.sub("", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def toc_key(text: str) -> str:
    """목차의 '제 1 절  공 무 원 ····· 389' 와 본문의 '공무원' 을 같은 키로."""
    text = re.sub(r"^제\s*\d+\s*[장절]", "", text)
    return re.sub(r"[^가-힣A-Za-z]", "", text)      # 띄어 쓴 글자 · 점선 · 쪽 번호(3 8 9)를 모두 지운다


def parse_volume(volume: str) -> list[dict]:
    reader = PdfReader(PDF_DIR / VOLUMES[volume])
    cases, case = [], None
    chapter = section = ""
    expect_section_name = False
    section_to_chapter: dict[str, str] = {}     # 목차에서 만든 '절 → 장' 대응

    for page_index, page in enumerate(reader.pages):
        printed = None
        in_footnotes = False
        for raw in (page.extract_text() or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.isdigit() and printed is None:
                printed = int(line)
            if is_running_header(line):
                continue
            if expect_section_name:
                section, expect_section_name = line, False
                continue
            if SECTION_HEAD.match(line):
                expect_section_name = True
                continue
            if case is None:            # 목차 — 장 · 절 이름만 모은다
                chapter_match = CHAPTER_HEAD.match(line)
                if chapter_match:
                    chapter = chapter_match.group(1).strip()
                elif re.match(r"^제\s*\d+\s*절", line):
                    # 처음 나온 목차 값만 쓴다 (뒤쪽 장 표지 쪽이 덮어쓰지 않게)
                    section_to_chapter.setdefault(toc_key(line), chapter)

            head = CASE_HEAD.match(line)
            if head:
                case = {
                    "volume": volume, "seq": int(head.group(1)),
                    "case_no": head.group(2).replace(" ", ""),
                    "chapter": section_to_chapter.get(toc_key(section), ""), "section": section,
                    "pdf_page_start": page_index + 1, "pdf_page_end": page_index + 1,
                    "page_start": printed, "page_end": printed,
                    "parts": {"title": [], "question": [], "answer": [], "reason": [], "recommendation": []},
                    "current": "title", "footnotes": [], "markers": set(),
                }
                cases.append(case)
                in_footnotes = False
                continue
            if case is None:
                continue                    # 목차 · 머리말

            case["pdf_page_end"] = page_index + 1
            if printed:
                case["page_end"] = printed
                case["page_start"] = case["page_start"] or printed

            footnote = FOOTNOTE.match(line)
            if footnote and footnote.group(1) in case["markers"]:
                case["markers"].discard(footnote.group(1))
                case["footnotes"].append(footnote.group(2))
                in_footnotes = True
                continue
            if in_footnotes:
                case["footnotes"][-1] += " " + line     # 각주가 다음 줄로 이어진 것
                continue
            if line in SECTION_NAMES:
                case["current"] = SECTION_NAMES[line]
                continue
            case["markers"].update(INLINE_MARK.findall(line))
            case["parts"][case["current"]].append(line)

    return [finish(c) for c in cases]


def finish(case: dict) -> dict:
    parts = {k: join_lines(v) for k, v in case.pop("parts").items()}
    case.pop("current")
    case.pop("markers")
    title = parts.pop("title")
    requester, _, title_text = title.partition(" – ") if " – " in title else ("", "", title)
    laws = list(dict.fromkeys(LAW_NAME.findall(title)))
    return {
        "doc_id": f"expc-{case['case_no'].split(',')[0]}",
        "title": title_text.strip(),
        "requester": requester.strip(),
        "laws": laws,
        **case,
        **parts,
        "source": f"{PUBLISHER}({case['volume']}), {case['page_start']}~{case['page_end']}쪽",
        "file": VOLUMES[case["volume"]],
    }


def link_items(cases: list[dict]) -> None:
    """제목에 나온 법령(시행령 · 시행규칙 포함)을 우리 항목(법률)과 연결한다."""
    by_name = {}
    for item in load_items():
        if not item.get("article_range"):
            by_name[item["name"].replace(" ", "")] = item["item_id"]
    for case in cases:
        ids = []
        for law in case["laws"]:
            base = re.sub(r"\s*(시행령|시행규칙)$", "", law).replace(" ", "")
            if base in by_name:
                ids.append(by_name[base])
        case["item_ids"] = list(dict.fromkeys(ids))


def load_casebook() -> list[dict]:
    if not CASEBOOK_JSON.exists():
        return []
    with open(CASEBOOK_JSON, encoding="utf-8") as f:
        return json.load(f)


def search_cases(item: dict, queries: list[str], limit: int) -> list[dict]:
    """후보 법령해석례 — 선택한 법률과 연결된 사례를, 검색어와 겹치는 낱말이 많은 순으로.

    로컬 파일이라 외부 호출이 없다. 연결된 사례가 없는 법률이면 빈 목록.
    """
    words = {w for q in queries for w in q.split() if len(w) >= 2}
    linked = [c for c in load_casebook() if item["item_id"] in c.get("item_ids", [])]

    def score(case: dict) -> int:
        text = case["title"] + case["question"][:500]
        return sum(text.count(w) for w in words)

    return sorted(linked, key=score, reverse=True)[:limit]


def main() -> None:
    cases = []
    for volume in VOLUMES:
        found = parse_volume(volume)
        print(f"({volume}) 사례 {len(found)}건")
        cases += found
    link_items(cases)

    with open(CASEBOOK_JSON, "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=1)

    empty = [c["case_no"] for c in cases if not (c["question"] and c["answer"] and c["reason"])]
    linked = [c for c in cases if c["item_ids"]]
    print(f"전체 {len(cases)}건 → {CASEBOOK_JSON.name}")
    print(f"질의요지 · 회답 · 이유 중 빈 칸이 있는 사례: {len(empty)}건 {empty[:5]}")
    print(f"우리 항목(법률)과 연결된 사례: {len(linked)}건")


if __name__ == "__main__":
    main()
