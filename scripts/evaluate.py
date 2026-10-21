"""평가 질문 세트 자동 채점 (명세 4장 검증 · 설계문서의 "값을 바꿨을 때의 차이").

실행 (프로젝트 폴더에서):
    python -m scripts.evaluate                              # settings.json 그대로
    python -m scripts.evaluate --label topk3 --set top_k=3  # 설정을 바꿔 비교
    python -m scripts.evaluate --only Q01 Q09 T01           # 일부 질문만

data/eval_questions.json — 질문 25개 (정상 21 · 함정 4), 질문마다 정답 조문
결과
    docs/eval/<label>.md      질문별 결과표
    docs/eval/<label>.json    같은 내용 (비교용)
    docs/eval/summary.md      실행마다 한 줄씩 쌓이는 요약표

지표
    검색 적중률   정상 질문에서 정답 조문이 근거 목록(retrieve 결과)에 들어온 비율
    인용 적중률   정상 질문에서 답변이 정답 조문을 실제로 [근거 N] 으로 인용한 비율
    잘못된 거절   정상 질문인데 "확인되지 않습니다"로 답한 비율 (낮을수록 좋다)
    거절 정확도   함정 질문에 "확인되지 않습니다"로 답한 비율 (높을수록 좋다)
    인용 경고     없는 번호 · 근거에 없는 조문 번호를 쓴 횟수 (G2 · G3)
"""

import argparse
import json
import time
from datetime import datetime

from config import DATA_DIR, ROOT
from prep.item_text import load_items
from rag.prompts import NOT_FOUND
from service.chat import ask
from service.runtime import Runtime, build_runtime

QUESTIONS = DATA_DIR / "eval_questions.json"
OUT_DIR = ROOT / "docs" / "eval"


def has_article(sources: list[dict], law: str, labels: list[str]) -> bool:
    """근거 제목에 '법률명 제N조(' 가 있으면 일치. '(' 까지 봐서 제3조와 제3조의2 를 구분한다."""
    return any(f"{law} {label}(" in s["title"] for s in sources for label in labels)


def parse_value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text


def evaluate(rt: Runtime, questions: list[dict], on_row=print) -> list[dict]:
    items = {i["name"]: i for i in load_items()}
    rows = []
    for q in questions:
        item = items[q["law"]]
        started = time.perf_counter()
        try:
            result = ask(rt, item, q["question"], history=[])
        except Exception as error:          # 한 질문이 실패해도 나머지는 계속 채점
            rows.append({**q, "error": str(error)[:200]})
            on_row(f"[{q['id']}] 오류: {str(error)[:80]}")
            continue
        refused = result.answer.startswith(NOT_FOUND)
        row = {
            **q,
            "retrieved": has_article(result.sources, q["law"], q["expect"]) if not q["trap"] else None,
            "cited": has_article(result.cited, q["law"], q["expect"]) if not q["trap"] else None,
            "refused": refused,
            "warnings": len(result.warnings),
            "n_sources": len(result.sources),
            "sources": [s["title"] for s in result.sources],
            "cited_titles": [s["title"] for s in result.cited],
            "answer": result.answer,
            "elapsed": round(time.perf_counter() - started, 1),
        }
        rows.append(row)
        mark = (("거절 O" if refused else "거절 X") if q["trap"]
                else f"검색 {'O' if row['retrieved'] else 'X'} · 인용 {'O' if row['cited'] else 'X'}"
                     + (" · 잘못된 거절" if refused else ""))
        on_row(f"[{q['id']}] {mark} · {row['elapsed']}초 — {q['question'][:40]}")
    return rows


def metrics(rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]
    normal = [r for r in ok if not r["trap"]]
    traps = [r for r in ok if r["trap"]]
    rate = lambda xs: round(100 * sum(xs) / len(xs), 1) if xs else None
    return {
        "검색 적중률": rate([r["retrieved"] for r in normal]),
        "인용 적중률": rate([r["cited"] for r in normal]),
        "잘못된 거절": rate([r["refused"] for r in normal]),
        "거절 정확도": rate([r["refused"] for r in traps]),
        "인용 경고": sum(r["warnings"] for r in ok),
        "평균 근거 수": round(sum(r["n_sources"] for r in ok) / len(ok), 1) if ok else None,
        "평균 시간(초)": round(sum(r["elapsed"] for r in ok) / len(ok), 1) if ok else None,
        "오류": len(rows) - len(ok),
    }


def report(label: str, overrides: dict, rows: list[dict], m: dict) -> str:
    lines = [f"# 평가 결과 — {label}", "",
             f"- 실행: {datetime.now():%Y-%m-%d %H:%M}",
             f"- 설정 변경: {json.dumps(overrides, ensure_ascii=False) if overrides else '없음 (settings.json 그대로)'}",
             f"- 질문: {len(rows)}개 (정상 {sum(not r['trap'] for r in rows)} · 함정 {sum(r['trap'] for r in rows)})", "",
             "## 지표", "", "| 지표 | 값 |", "|---|---|"]
    lines += [f"| {k} | {v}{'%' if k in ('검색 적중률', '인용 적중률', '잘못된 거절', '거절 정확도') and v is not None else ''} |"
              for k, v in m.items()]
    lines += ["", "## 질문별", "",
              "| # | 법률 | 질문 | 정답 조문 | 검색 | 인용 | 거절 | 경고 | 근거 수 |", "|---|---|---|---|---|---|---|---|---|"]
    ox = lambda v: "-" if v is None else ("O" if v else "X")
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['id']} | {r['law'][:10]} | {r['question']} | {', '.join(r['expect']) or '(함정)'} | 오류 | | | | |")
            continue
        refused = ("O" if r["refused"] else "X") if r["trap"] else ("잘못 거절" if r["refused"] else "-")
        lines.append(f"| {r['id']} | {r['law'][:10]} | {r['question']} | {', '.join(r['expect']) or '(함정)'} | "
                     f"{ox(r['retrieved'])} | {ox(r['cited'])} | {refused} | {r['warnings']} | {r['n_sources']} |")
    misses = [r for r in rows if "error" not in r and not r["trap"] and not r["retrieved"]]
    if misses:
        lines += ["", "## 정답 조문을 못 찾은 질문 — 검색된 근거", ""]
        for r in misses:
            lines.append(f"- **{r['id']}** {r['question']} (정답 {', '.join(r['expect'])}) → {' · '.join(r['sources'])}")
    return "\n".join(lines) + "\n"


def append_summary(label: str, overrides: dict, m: dict) -> None:
    path = OUT_DIR / "summary.md"
    if not path.exists():
        path.write_text("# 평가 요약 — 실행마다 한 줄\n\n| 실행 | 라벨 | 설정 변경 | " + " | ".join(m) + " |\n|"
                        + "---|" * (len(m) + 3) + "\n", encoding="utf-8")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"| {datetime.now():%m-%d %H:%M} | {label} | {json.dumps(overrides, ensure_ascii=False) if overrides else '-'} | "
                + " | ".join(str(v) for v in m.values()) + " |\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="평가 질문 세트 자동 채점")
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE", help="settings.json 값 바꾸기")
    parser.add_argument("--only", nargs="*", default=[], metavar="ID")
    args = parser.parse_args()

    overrides = {k: parse_value(v) for k, v in (s.split("=", 1) for s in args.set)}
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    if args.only:
        questions = [q for q in questions if q["id"] in args.only]

    rt = build_runtime()
    rt.overrides = overrides
    rows = evaluate(rt, questions)
    m = metrics(rows)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{args.label}.md").write_text(report(args.label, overrides, rows, m), encoding="utf-8")
    (OUT_DIR / f"{args.label}.json").write_text(
        json.dumps({"overrides": overrides, "metrics": m, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    append_summary(args.label, overrides, m)
    print("\n" + "\n".join(f"{k}: {v}" for k, v in m.items()))
    print(f"→ docs/eval/{args.label}.md")


if __name__ == "__main__":
    main()
