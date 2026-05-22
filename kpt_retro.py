import requests, os

NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"

nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

# ── 블록 헬퍼 ─────────────────────────────────────────────────────────────────
def h1(c):
    return {"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}

def h2(c):
    return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}

def h3(c):
    return {"object":"block","type":"heading_3","heading_3":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}

def div():
    return {"object":"block","type":"divider","divider":{}}

def co(text, emoji="💡"):
    return {"object":"block","type":"callout","callout":{
        "rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}],
        "icon":{"type":"emoji","emoji":emoji}
    }}

def p(text):
    return {"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}]}}

def bl(text):
    return {"object":"block","type":"bulleted_list_item","bulleted_list_item":{"rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}]}}

# ── 블록 구성 ─────────────────────────────────────────────────────────────────
blocks = [
    h1("5월 KPT 회고"),
    co("팀/파트: 라이프본부 마케팅팀  |  닉네임: koby  |  기간: 2026년 5월", "📋"),
    div(),

    # ── 1~2주차 ────────────────────────────────────────────────────────────────
    h2("📅 1~2주차 (5/1 ~ 5/14)"),

    h3("📌 수행 업무 Recap"),
    bl("KB 이니셜 소재 집행 운영 및 일별 성과 모니터링"),
    bl("프로모션 소재 중심으로 지출 집중 및 ROAS 관리"),
    bl("신규 소재 세팅 및 A/B 소재 라이브 대응"),
    p(""),

    h3("✅ Keep"),
    bl("ROAS 180% 이상 달성 소재 비중을 일정 수준 유지 — 고성과 소재 식별 후 예산 집중 전략이 효과적이었음"),
    bl("주중(화~목) 성과가 주말 대비 우수한 패턴 확인 → 예산 집행 스케줄링에 반영 가능"),
    bl("프로모션 소재 중 ROAS 200% 이상 소재가 다수 발굴됨 (프로모션 리스트 기준 32개)"),
    p(""),

    h3("❌ Problem"),
    bl("지출 규모 대비 전환이 낮은 소재(ROAS 100% 미만, 지출 50만원+)가 병행 집행되어 전체 블렌드 ROAS를 끌어내림"),
    bl("소재별 성과 편차가 크고, 저성과 소재 조기 중단 기준이 명확하지 않아 낭비 지출 발생"),
    bl("OB-CTR이 특정 소재에 편중되어 있어 클릭 유입 다양성 부족"),
    p(""),

    h3("💡 Try"),
    bl("ROAS 100% 미만 + 지출 50만원 초과 소재는 D+3 기준으로 일시정지 규칙 적용"),
    bl("주중 집중 운영 전략 실험: 토/일 예산을 화~목으로 재배분하여 ROAS 개선 테스트"),
    bl("소재 라이브 후 72시간 성과 체크리스트 운영으로 빠른 의사결정 체계 구축"),
    p(""),

    co("건의사항: 소재 중단 기준(ROAS, 지출, 기간) 팀 내 공식 가이드라인 수립 필요", "📣"),
    div(),

    # ── 3~4주차 ────────────────────────────────────────────────────────────────
    h2("📅 3~4주차 (5/15 ~ 5/21)"),

    h3("📌 수행 업무 Recap"),
    bl("월말 회고 데이터 분석 (KB 소재 36개, 5/1~5/21 기준)"),
    bl("아치밸런스 키워드 소재 성별/연령별 타겟 분석 수행"),
    bl("Baruner3 계정 라이브 소재 2개 일자별/요일별 패턴 분석 및 노션 리포트 전달"),
    bl("프로모션 소재 전수 리스트업 (25~26년 기준, 지출 100만원+ / ROAS 기준 분류)"),
    p(""),

    h3("✅ Keep"),
    bl("다계정(KB / Baruner3) 소재를 계정별로 구분해 분석하는 체계가 잡힘"),
    bl("월말 회고 리포트 자동화로 수작업 시간 대폭 감소 — 데이터 기반 의사결정 속도 향상"),
    bl("라이브 소재 요일별 패턴 분석이 다음 달 운영 방향 설정에 직접 활용 가능한 수준으로 정리됨"),
    p(""),

    h3("❌ Problem"),
    bl("분석 기간(5/1~5/21)이 월말이 포함되지 않아 완전한 월 단위 성과 측정에 제약"),
    bl("일부 소재는 소재명 이니셜 기준 필터링이 누락될 가능성 있음 (이니셜 미기재 소재)"),
    bl("ROAS가 집계되지 않는 소재(전환없음)의 비중 파악 및 원인 분석이 부족"),
    p(""),

    h3("💡 Try"),
    bl("소재명 네이밍 룰 정립: 이니셜 + 소재유형 + 날짜 형식으로 통일하여 필터링 정확도 향상"),
    bl("매월 1일 자동으로 전월 회고 리포트가 생성되는 스케줄 자동화 설정"),
    bl("전환없음 소재의 랜딩페이지, 타겟, 입찰 전략 점검 프로세스 추가"),
    p(""),

    co("건의사항 1: 소재 네이밍 컨벤션 팀 내 공식화 요청 (담당자 이니셜 + 제품명 + 소재유형 필수 포함)\n건의사항 2: 월말 회고 공유 시 팀 전체 리뷰 세션 정례화 검토 부탁드립니다", "📣"),
]

# ── Notion 페이지 생성 ─────────────────────────────────────────────────────────
print("[1/2] Notion 페이지 생성...")
page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": "5월 KPT 회고 - koby (라이프본부 마케팅팀)"}}]}},
}).json()

if page.get("object") != "page":
    raise SystemExit(f"페이지 생성 실패: {page}")

page_id = page["id"]
print(f"  -> {page.get('url')}")

def flush(pid, chunk):
    if not chunk: return
    res = requests.patch(
        f"https://api.notion.com/v1/blocks/{pid}/children",
        headers=nh, json={"children": chunk}
    ).json()
    if "error" in res or res.get("object") == "error":
        print(f"  -> 실패: {res.get('message', res)}")
    else:
        print(f"  -> {len(chunk)}개 블록 추가 완료")

print("[2/2] 블록 추가...")
pending = []
for block in blocks:
    pending.append(block)
    if len(pending) >= 90:
        flush(page_id, pending)
        pending = []
flush(page_id, pending)

print(f"\n✅ 완료! {page.get('url')}")
