"""키워드(글자 조각) 검색 — 벡터 검색과 합치는 하이브리드 검색(3번)과, AI 한도 초과 때 원문 보여 주기가 같이 쓴다.

한국어는 띄어쓰기 · 조사가 달라 낱말 통째로는 잘 안 맞는다 → 낱말 안에서 두 글자씩 자른 조각(bigram)으로 본다.
여러 문서에 흔한 조각("하는 · 경우")일수록 낮게 친다(IDF). 임베딩 호출이 없다.

벡터 검색은 뜻이 비슷한 문서를 잘 찾지만 "해약금 · 갱신요구권 · 제565조" 같은 **정확한 용어**는 놓칠 때가 있다.
키워드 검색은 그 반대 — 그래서 두 순위를 RRF 로 합친다 (rag/retriever.py).
"""

import math
import re
from collections import Counter


def word_grams(text: str) -> set[str]:
    """낱말 안에서만 두 글자씩 — 띄어쓰기를 지우고 자르면 "는데 · 받아 · 아요" 같은 조각이 아무 문서에나 걸린다."""
    grams = set()
    for word in re.findall(r"[가-힣A-Za-z0-9]{2,}", text):
        grams |= {word[i:i + 2] for i in range(len(word) - 1)}
    return grams


class LexicalIndex:
    """문서 묶음 하나(한 법률의 청크들)에 대한 키워드 점수. 질의마다 다시 만들지 않게 한 번 만들어 쓴다."""

    def __init__(self, texts: list[str], titles: list[str] | None = None):
        self.grams = [word_grams(t) for t in texts]
        self.title_grams = [word_grams(t) for t in titles] if titles else [set() for _ in texts]
        self.df = Counter(g for grams in self.grams for g in grams)
        self.n = len(texts)

    def idf(self, gram: str) -> float:
        return math.log((self.n + 1) / (self.df.get(gram, 0) + 0.5))

    def scores(self, query: str, title_bonus: float = 0.3) -> list[float]:
        """문서마다 점수 — 겹친 조각의 IDF 합을 문서 길이(로그)로 나눈다. 제목에 맞으면 더 친다."""
        q = word_grams(query)
        weight = {g: self.idf(g) for g in q}
        out = []
        for grams, title in zip(self.grams, self.title_grams):
            body = sum(weight[g] for g in grams & q) / math.log(len(grams) + 10)
            out.append(body + title_bonus * sum(weight[g] for g in title & q))
        return out

    def ranking(self, query: str, depth: int) -> list[int]:
        """점수가 0 보다 큰 문서의 순번을 높은 순으로 depth 개."""
        scores = self.scores(query)
        ranked = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: scores[i], reverse=True)
        return ranked[:depth]
