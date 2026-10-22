"""쟁점 나누기 모드 평가 — 복합 질문에서 쟁점별 정답 조문을 몇 개나 근거로 찾고(검색) 인용했는지.

실행:
    python -m scripts.eval_complex

data/eval_complex.json — 질문마다 정답 조문 목록 [[법률명, 조문], ...]
    쟁점 적중률(검색) = 근거에 들어온 정답 조문 / 전체 정답 조문
    쟁점 적중률(인용) = 답변이 인용한 정답 조문 / 전체 정답 조문
"""

import json
import time

from config import DATA_DIR, ROOT
from prep.item_text import load_items
from service.complex import answer_complex, decompose
from service.runtime import build_runtime

QUESTIONS = DATA_DIR / "eval_complex.json"
OUT = ROOT / "docs" / "eval" / "complex.md"


def hit(sources: list[dict], law: str, article: str) -> bool:
    return any(s["title"].startswith(f"{law} {article}(") for s in sources)


def main() -> None:
    rt, items = build_runtime(), load_items()
    lines = ["# 쟁점 나누기 모드 평가", "", "| # | 쟁점 수 | 정답 조문 | 검색 | 인용 | 시간 | 놓친 조문 |", "|---|---|---|---|---|---|---|"]
    total = found_all = cited_all = 0
    for q in json.loads(QUESTIONS.read_text(encoding="utf-8")):
        started = time.perf_counter()
        plan = decompose(rt, q["question"], items)
        if not plan:
            print(f"[{q['id']}] 쟁점 1개 이하로 판단 — 쟁점 나누기 모드로 가지 않음")
            lines.append(f"| {q['id']} | 1 이하 | {len(q['expect'])} | - | - | - | (모드 진입 실패) |")
            total += len(q["expect"])
            continue
        result = answer_complex(rt, q["question"], plan)
        found = [e for e in q["expect"] if hit(result.sources, *e)]
        cited = [e for e in q["expect"] if hit(result.cited, *e)]
        missed = [f"{l} {a}" for l, a in q["expect"] if [l, a] not in found]
        elapsed = time.perf_counter() - started
        total, found_all, cited_all = total + len(q["expect"]), found_all + len(found), cited_all + len(cited)
        print(f"[{q['id']}] 쟁점 {len(plan['issues'])} · 검색 {len(found)}/{len(q['expect'])} · "
              f"인용 {len(cited)}/{len(q['expect'])} · {elapsed:.0f}초 · 놓침 {missed}")
        lines.append(f"| {q['id']} | {len(plan['issues'])} | {len(q['expect'])} | {len(found)} | {len(cited)} | "
                     f"{elapsed:.0f}초 | {', '.join(missed) or '-'} |")
    summary = f"쟁점 적중률 — 검색 {100 * found_all / total:.1f}% · 인용 {100 * cited_all / total:.1f}% ({total}개 조문)"
    print("\n" + summary)
    OUT.write_text("\n".join(lines + ["", summary, ""]), encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
