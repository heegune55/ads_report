import requests, csv, os

NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"

nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

# ── CSV 파싱 ──────────────────────────────────────────────────────────────────
CSV_PATH = os.environ.get("CSV_PATH", "hipup_data.csv")
rows = []
with open(CSV_PATH, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

ads = []
for r in rows:
    name = r.get("광고 이름", "").strip()
    if not name:
        continue
    spend    = float(r.get("지출 금액 (KRW)", "0") or 0)
    if spend == 0:
        continue
    impr     = float(r.get("노출", "0") or 0)
    purchases= float(r.get("결과", "0") or 0)
    roas     = float(r.get("웹사이트 구매 ROAS(광고 지출 대비 수익률)", "0") or 0)
    ctr      = float(r.get("CTR(전체)", "0") or 0)
    ob_ctr   = float(r.get("고유 아웃바운드 CTR(클릭률)", "0") or 0)
    cvr      = float(r.get("유입 대비 전환율", "0") or 0)
    cpc      = float(r.get("CPC(링크 클릭당 비용) (KRW)", "0") or 0)
    aov      = float(r.get("객단가", "0") or 0)
    conv_val = float(r.get("웹사이트 구매 전환값", "0") or 0)
    cpm      = spend / impr * 1000 if impr else 0
    short    = name[7:]  # 날짜 앞 7자리 제거
    ads.append(dict(name=name, short=short, spend=spend, impr=impr,
                    purchases=purchases, roas=roas, ctr=ctr, ob_ctr=ob_ctr,
                    cvr=cvr, cpc=cpc, aov=aov, conv_val=conv_val, cpm=cpm))

total_spend = sum(a["spend"] for a in ads)
total_cv    = sum(a["conv_val"] for a in ads)
total_pur   = sum(a["purchases"] for a in ads)
blend_roas  = total_cv / total_spend if total_spend else 0

converting  = [a for a in ads if a["roas"] > 0]
no_conv     = [a for a in ads if a["roas"] == 0]
high_cvr    = sorted([a for a in converting if a["cvr"] >= 0.06],  key=lambda x: x["cvr"], reverse=True)
mid_cvr     = sorted([a for a in converting if 0.03 <= a["cvr"] < 0.06], key=lambda x: x["cvr"], reverse=True)
low_cvr     = sorted([a for a in converting if a["cvr"] < 0.03],  key=lambda x: x["cvr"])

# ── 블록 헬퍼 ─────────────────────────────────────────────────────────────────
def h1(c):  return {"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h2(c):  return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h3(c):  return {"object":"block","type":"heading_3","heading_3":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def div():  return {"object":"block","type":"divider","divider":{}}
def co(text, emoji="💡"):
    return {"object":"block","type":"callout","callout":{
        "rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}],
        "icon":{"type":"emoji","emoji":emoji}
    }}
def bl(text):
    return {"object":"block","type":"bulleted_list_item","bulleted_list_item":{"rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}]}}
def p(text=""):
    return {"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}]}}

def tbl(headers, rows_data):
    def cell(t): return [{"type":"text","text":{"content":str(t)[:2000]}}]
    ch  = [{"type":"table_row","table_row":{"cells":[cell(h) for h in headers]}}]
    ch += [{"type":"table_row","table_row":{"cells":[cell(v) for v in row]}} for row in rows_data]
    return {"object":"block","type":"table",
            "table":{"table_width":len(headers),"has_column_header":True,"has_row_header":False,"children":ch}}

def fmt_roas(r): return f"{r*100:.1f}%" if r else "-"
def fmt_cvr(c):  return f"{c*100:.2f}%" if c else "-"

# ── 소재명 단축 (핵심 키워드만) ────────────────────────────────────────────────
def shorten(name):
    parts = name.split("_")
    # 날짜(260xxx) + 제품명 제거 후 핵심 키워드
    skip = {"아치스포츠", "이미지", "영상", "숏폼", "미용", "힙업", "후기형", "4대5", "9대16", "1대1"}
    keywords = [p for p in parts[2:] if p not in skip and not p.startswith("KB") and len(p) > 1]
    return "_".join(keywords[:3]) if keywords else name[-20:]

# ── 블록 구성 ─────────────────────────────────────────────────────────────────
blocks = [
    h1("🔍 힙업 소재 성과 분석 (4/28~5/27)"),
    co(
        f"총 소재: {len(ads)}개  |  총 지출: ₩{total_spend:,.0f}  |  총 구매: {total_pur:.0f}건  |  "
        f"블렌드 ROAS: {blend_roas*100:.1f}%\n"
        f"문제: 유입(CTR)은 오는데 전환(CVR)이 안 되는 소재 다수 → 광고-랜딩 메시지 불일치",
        "📌"
    ),
    div(),

    # ── 핵심 인사이트 ──────────────────────────────────────────────────────────
    h2("⚡ 핵심 발견: CTR이 높을수록 CVR이 낮아지는 역설"),
    co(
        "이 데이터셋에서 CTR 2% 이상 소재들의 평균 CVR은 1~2.5%에 불과\n"
        "반면 CTR 1.1~1.8% 소재들의 CVR은 6~7%로 4~5배 높음\n"
        "→ 높은 CTR = 호기심 클릭 / 적정 CTR = 구매 의도 클릭",
        "🚨"
    ),
    p(),
    tbl(
        ["소재명", "CTR", "CVR", "ROAS", "구매", "지출"],
        [
            ["놀란템_인트로2 ← 최악", "3.97%", "1.20%", "36.7%", "3건", f"₩{281699:,.0f}"],
            ["x힙업추천템_2안", "2.02%", "2.55%", "95.8%", "4건", f"₩{284541:,.0f}"],
            ["그냥이거에요", "1.45%", "2.98%", "103.6%", "7건", f"₩{300530:,.0f}"],
            ["━━━ 기준선 ━━━", "~1.8%", "~6%", "~130%", "—", "—"],
            ["엉밑살지흡_WE_2안 ← 베스트", "1.71%", "6.33%", "136.7%", "50건", f"₩{1572982:,.0f}"],
            ["힙업다걸었습니다_LO", "1.76%", "7.01%", "125.5%", "46건", f"₩{1436680:,.0f}"],
            ["숨막히는_인트로1", "1.25%", "6.77%", "132.2%", "21건", f"₩{799690:,.0f}"],
        ]
    ),
    div(),

    # ── 원인 분석 ──────────────────────────────────────────────────────────────
    h2("🧠 전환 실패 원인 분석"),

    h3("원인 1 — 호기심 클릭 vs 구매 의도 클릭"),
    bl("놀란템(CTR 3.97%, CVR 1.20%): '놀란템'이라는 키워드가 강한 호기심을 유발 → 클릭은 폭발적이지만 랜딩 도달 후 '이게 깔창이라고?' 인지 부조화로 즉시 이탈"),
    bl("추천템(CTR 2.02%, CVR 2.55%): '추천 제품 탐색' 목적 유저 유입 → 구매 결심 없는 상태로 들어와 구경만 하고 이탈"),
    bl("그냥이거에요(CTR 1.45%, CVR 2.98%): 카피의 느슨한 뉘앙스가 진지한 구매자를 사전에 걸러내지 못함"),
    p(),

    h3("원인 2 — 광고 메시지와 랜딩페이지 불연속"),
    bl("힙업 비주얼로 클릭을 유도했지만, 랜딩에서 '깔창이 힙업을 어떻게 만드는가'에 대한 설득 과정이 약하거나 없음"),
    bl("CTR이 높은 소재일수록 이 갭이 더 크게 발생 — 광고가 과대 기대를 만든 후 제품이 그 기대를 즉시 충족시키지 못함"),
    p(),

    h3("원인 3 — CPM 관점의 타겟 품질 차이"),
    bl(f"놀란템: CPM ₩49,430 (최고) → 가장 광범위한 타겟에 노출, 구매 의도 유저 비율 낮음"),
    bl(f"헬스2년째: CPM ₩15,248 (최저) → 좁고 적합한 타겟, CVR 5.49% 안정적"),
    bl("CPM이 낮다고 좋은 게 아니라, 소재가 적합한 유저를 걸러주는 역할을 해야 함"),
    p(),
    div(),

    # ── 고성과 소재 공통점 ──────────────────────────────────────────────────────
    h2("✅ 고성과 소재 (CVR 6%+) — 공통 패턴"),
    tbl(
        ["소재명", "CVR", "ROAS", "CTR", "구매", "지출", "특징"],
        [[shorten(a["name"]), fmt_cvr(a["cvr"]), fmt_roas(a["roas"]),
          f"{a['ctr']:.2f}%", f"{a['purchases']:.0f}건",
          f"₩{a['spend']:,.0f}",
          "후기형" if "후기형" in a["name"] else ("urgency" if "단종" in a["name"] or "다걸었" in a["name"] else "고민직접언급")]
         for a in high_cvr]
    ),
    p(),
    co(
        "공통점:\n"
        "① 구체적 고민/신체 부위를 직접 언급 (엉밑살, 숨막히는 힙업, 헬스 2년째)\n"
        "② 후기형 포맷으로 '이미 써본 사람'의 시점 → 구매 확신 상태로 유입\n"
        "③ urgency 카피 (다걸었습니다, 미친단종) → 구매 결정 가속\n"
        "④ CTR이 과도하게 높지 않음 (1.1~1.8%) → 적합한 유저만 걸러서 유입",
        "💡"
    ),
    div(),

    # ── 저성과 소재 ─────────────────────────────────────────────────────────────
    h2("❌ 저성과 소재 (CVR <3%) — 문제 소재"),
    tbl(
        ["소재명", "CVR", "ROAS", "CTR", "CPM", "지출", "문제"],
        [
            ["놀란템_인트로2", "1.20%", "36.7%", "3.97%", "₩49,430", "₩281,699", "호기심 클릭 → 구매의도 無"],
            ["x힙업추천템_2안", "2.55%", "95.8%", "2.02%", "₩35,510", "₩284,541", "탐색형 클릭 → 전환 약"],
            ["그냥이거에요", "2.98%", "103.6%", "1.45%", "₩18,722", "₩300,530", "느슨한 카피 → 구매자 필터 無"],
        ]
    ),
    co(
        "3개 소재 합산 지출: ₩866,770 → 구매 14건 → 평균 CPA ₩61,912\n"
        "반면 엉밑살지흡 WE_2안은 ₩1,572,982 → 50건 → CPA ₩31,460\n"
        "→ 저성과 3개 소재 예산을 베스트 소재로 이동했다면 약 27건 추가 구매 가능했을 것",
        "⚠️"
    ),
    div(),

    # ── 전환 없는 소재 ──────────────────────────────────────────────────────────
    h2("🚫 전환 0 소재"),
    tbl(
        ["소재명", "지출", "노출", "CTR", "OB-CTR"],
        [[shorten(a["name"]), f"₩{a['spend']:,.0f}", f"{a['impr']:,.0f}",
          f"{a['ctr']:.2f}%", f"{a['ob_ctr']:.2f}%"] for a in no_conv]
    ),
    co("힙테스트 인트로1,2: CTR 0.5~0.6%로 유입 자체가 극히 적음 → 소재 초반 훅 실패\n뉴컬러디벨롭: CTR 0.79%로 낮고 구매 전환도 0 → 소재 컨셉 자체를 재검토 필요", "🔕"),
    div(),

    # ── 전체 소재 성과표 ─────────────────────────────────────────────────────────
    h2("📋 전체 소재 성과표 (지출 높은 순)"),
    tbl(
        ["소재명", "지출", "ROAS", "CTR", "CVR", "구매", "CPM", "AOV"],
        [[shorten(a["name"]),
          f"₩{a['spend']:,.0f}",
          fmt_roas(a["roas"]),
          f"{a['ctr']:.2f}%",
          fmt_cvr(a["cvr"]),
          f"{a['purchases']:.0f}건",
          f"₩{a['cpm']:,.0f}",
          f"₩{a['aov']:,.0f}" if a["aov"] else "-"]
         for a in sorted(ads, key=lambda x: x["spend"], reverse=True)]
    ),
    div(),

    # ── 액션 플랜 ────────────────────────────────────────────────────────────────
    h2("🎯 액션 플랜"),

    h3("즉시 실행"),
    bl("놀란템 인트로2 즉시 중단 — CTR 3.97%는 허수, ROAS 36.7%로 예산 낭비 명확"),
    bl("엉밑살지흡 WE_2안 + 숨막히는 인트로1 예산 집중 증액 (CVR 6~7%, ROAS 130%+, 볼륨도 가장 큼)"),
    p(),

    h3("소재 방향 전환"),
    bl("카피 방향: '호기심 자극형' → '고민 직접 언급형'으로 전환"),
    bl("예시: '놀란템' → '엉밑살 때문에 힙업 안 된다면' / '추천템' → '헬스 2년째인데 힙업이 안 만들어진다면'"),
    bl("후기형 포맷 비중 늘리기 — 이번 데이터에서 후기형 소재들이 가장 일관되게 높은 CVR 기록"),
    p(),

    h3("CTR 목표치 재설정"),
    bl("CTR 목표: 2% 이상이 목표가 아님 — 이 제품군의 최적 CTR은 1.1~1.8%"),
    bl("CTR이 2% 넘으면 오히려 소재를 의심할 것 (호기심 클릭 가능성 높음)"),
    bl("'CTR 높은데 ROAS 낮음' 패턴 발견 즉시 → 소재 일시정지 후 랜딩 연속성 점검"),
    p(),

    co(
        "요약\n"
        "베스트 소재: 엉밑살지흡 WE_2안 (ROAS 136.7%, CVR 6.33%, 50건)\n"
        "즉시 중단: 놀란템 인트로2 (ROAS 36.7%, 지출 ₩282K 낭비)\n"
        "핵심 인사이트: 높은 CTR ≠ 좋은 소재. 구매 의도 있는 유저를 걸러주는 소재가 진짜 성과를 만든다",
        "🏆"
    ),
]

# ── Notion 업로드 ─────────────────────────────────────────────────────────────
print("[1/2] Notion 페이지 생성...")
page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": "🔍 힙업 소재 성과 분석 (4/28~5/27) — CTR vs CVR 역설"}}]}},
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
    if block.get("type") == "table":
        flush(page_id, pending)
        pending = []
        flush(page_id, [block])
    else:
        pending.append(block)
        if len(pending) >= 90:
            flush(page_id, pending)
            pending = []
flush(page_id, pending)
print(f"\n✅ 완료! {page.get('url')}")
