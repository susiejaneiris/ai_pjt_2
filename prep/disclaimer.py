"""위험 도메인 면책 안내 (F2012). 어떤 항목이 위험한지는 도메인 규칙이라 데이터 준비 영역에 둡니다.

    법률   모든 항목 — 법령 정보 안내일 뿐 법률 자문이 아니다
    금융   금융·신용 · 세금 분야 + 연금 · 기금 법률 — 대출 · 투자 · 세무 결정을 대신하지 않는다
    건강   의료·건강 분야 + 의료 · 응급 · 건강보험 · 식품위생 법률 — 진단 · 치료 판단을 대신하지 않는다

화면(Streamlit · 웹)은 notices_for() 결과를 답변과 함께 그대로 보여 줍니다.
"""

LEGAL = ("⚖️ 이 서비스는 법령 정보를 안내할 뿐 법률 자문을 대신하지 않습니다. "
         "구체적인 사안은 대한법률구조공단(☎132) 등 법률 전문가와 상담하세요.")
FINANCE = ("💰 금융 · 세금 관련 안내는 대출 · 투자 · 보험 · 세무 결정을 대신하지 않습니다. "
           "실제 거래나 신고 전에는 금융감독원(☎1332), 국세청(☎126) 또는 세무 전문가에게 확인하세요.")
HEALTH = ("🏥 건강 · 의료 관련 안내는 진단이나 치료 판단을 대신하지 않습니다. "
          "증상이 있거나 응급 상황이면 의료기관 또는 119에 먼저 연락하세요.")

FINANCE_CATEGORIES = {"금융·신용", "세금"}
FINANCE_LAWS = {"국민연금법", "주택도시기금법", "기초연금법", "장애인연금법", "복권 및 복권기금법"}
HEALTH_CATEGORIES = {"의료·건강"}
HEALTH_LAWS = {"의료법", "응급의료에 관한 법률", "국민건강보험법", "식품위생법", "의료급여법",
               "노인장기요양보험법", "어린이 식생활안전관리 특별법"}


def risk_types(item: dict) -> list[str]:
    """항목의 위험 유형. 법률은 항상 포함."""
    risks = ["legal"]
    if item.get("category") in FINANCE_CATEGORIES or item.get("name") in FINANCE_LAWS:
        risks.append("finance")
    if item.get("category") in HEALTH_CATEGORIES or item.get("name") in HEALTH_LAWS:
        risks.append("health")
    return risks


def notices_for(item: dict | None) -> list[str]:
    """화면에 띄울 면책 문구 목록. 항목을 고르기 전에는 법률 안내만."""
    texts = {"legal": LEGAL, "finance": FINANCE, "health": HEALTH}
    return [texts[r] for r in risk_types(item or {})]


def prompt_rules(item: dict) -> str:
    """답변 프롬프트에 덧붙일 규칙 — 개인의 결정을 권하지 않게 한다."""
    rules = ["- 개인의 소송 · 계약 결정을 대신 내려 주지 않는다. 필요하면 전문가 상담을 권한다."]
    risks = risk_types(item)
    if "finance" in risks:
        rules.append("- 특정 금융상품 · 대출 · 투자 · 절세 방법을 추천하지 않는다. 금액 · 세율은 근거에 있는 것만 쓴다.")
    if "health" in risks:
        rules.append("- 진단 · 치료 · 복약을 권하지 않는다. 응급 상황이면 119 · 의료기관을 먼저 안내한다.")
    return "\n".join(rules)
