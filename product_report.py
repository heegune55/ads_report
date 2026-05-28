import requests, json, datetime, os, time, re
from collections import defaultdict

META_TOKEN    = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = os.environ.get("META_ACCOUNT", "act_3431020723842735")
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"

PERSON_FILTER = os.environ.get("PERSON_FILTER", "KB")
SINCE = datetime.date.fromisoformat(os.environ.get("REPORT_SINCE", "2026-05-01"))
UNTIL = datetime.date.fromisoformat(os.environ.get("REPORT_UNTIL", "2026-05-27"))

BASE_URL = f"https://graph.facebook.com/v20.0/{META_ACCOUNT}/insights"
FIELDS = ",".join([
    "ad_name", "spend", "impressions", "cpm",
    "outbound_clicks_ctr", "actions", "action_values",
])

# ── 제품명 추출 ────────────────────────────────────────────────────────────────
# 소재명 규칙: YYMMDD_제품명_소재유형_..._KB_버전
# → 첫 토큰이 6자리 날짜면 두 번째 토큰이 제품명
DATE6_PAT = re.compile(r"^\d{6}$")

def extract_product(name: str) -> str:
    parts = name.split("_")
    if len(parts) >= 2 and DATE6_PAT.match(parts[0]):
        return parts[1]   # YYMMDD_제품명_...
    # 날짜 없는 구형 네이밍: KB 앞 토큰에서 추출
    for i, p in enumerate(parts):
        if p.upper() == "KB" and i >= 1:
            return parts[i - 1]
    return "기타"

# ── API 호출 ──────────────────────────────────────────────────────────────────
def api_get(url, params=None, retries=5):
    for attempt in range(retries):
        r = requests.get(url, params=params, timeout=60)
        d = r.json()
        if "error" in d:
            code = d["error"].get("code", 0)
            if code in (4, 17, 32, 613):
                wait = 2 ** (attempt + 3)
                print(f"  -> Rate limit (code {code}), {wait}초 대기...")
                time.sleep(wait)
                continue
            raise SystemExit(f"Meta API 오류: {d['error']['message']}")
        return d
    raise SystemExit("Rate limit 반복 실패")

def fetch_all(params):
    rows, nxt = [], None
    while True:
        d = api_get(nxt or BASE_URL, params=(None if nxt else params))
        rows.extend(d.get("data", []))
        nxt = d.get("paging", {}).get("next")
        if not nxt:
            break
    return rows

def ga(lst, t):
    for a in (lst or []):
        if a.get("action_type") == t:
            return float(a.get("value", 0))
    return 0.0

# ── 데이터 수집 ───────────────────────────────────────────────────────────────
print(f"[1/4] Meta 데이터 수집 ({SINCE} ~ {UNTIL})...")
raw = fetch_all({
    "level": "ad",
    "time_range": json.dumps({"since": str(SINCE), "until": str(UNTIL)}),
    "fields": FIELDS,
    "access_token": META_TOKEN,
    "limit": 500,
})
print(f"  -> 전체 {len(raw)}개 소재")

# ── 파싱 ─────────────────────────────────────────────────────────────────────
ads = []
for ad in raw:
    name = ad.get("ad_name", "")
    if PERSON_FILTER not in name:
        continue
    spd  = float(ad.get("spend", 0) or 0)
    impr = float(ad.get("impressions", 0) or 0)
    obl  = ad.get("outbound_clicks_ctr", [])
    avl  = ad.get("action_values", [])
    pv   = ga(avl, "purchase")
    pur  = ga(ad.get("actions", []), "purchase")
    clk  = ga(ad.get("actions", []), "outbound_click")
    roas = pv / spd if spd else None
    ads.append({
        "name":    name,
        "product": extract_product(name),
        "spend":   spd,
        "impr":    impr,
        "pv":      pv,
        "pur":     pur,
        "clk":     clk,
        "roas":    roas,
        "ob_ctr":  float(obl[0].get("value", 0)) if obl else 0.0,
        "cpm":     float(ad.get("cpm", 0) or 0),
    })

print(f"  -> KB 소재: {len(ads)}개")
if not ads:
    raise SystemExit("KB 소재 없음")

# ── 제품별 집계 ───────────────────────────────────────────────────────────────
products = defaultdict(lambda: {"spend":0,"pv":0,"pur":0,"clk":0,"impr":0,"w_ctr":0,"ads":[]})
for a in ads:
    p = a["product"]
    products[p]["spend"] += a["spend"]
    products[p]["pv"]    += a["pv"]
    products[p]["pur"]   += a["pur"]
    products[p]["clk"]   += a["clk"]
    products[p]["impr"]  += a["impr"]
    products[p]["w_ctr"] += a["ob_ctr"] * a["impr"]
    products[p]["ads"].append(a)

def prod_roas(p):
    d = products[p]
    return d["pv"] / d["spend"] if d["spend"] else 0

products_sorted = sorted(products.keys(), key=lambda p: products[p]["spend"], reverse=True)

total_spend = sum(a["spend"] for a in ads)
total_pv    = sum(a["pv"] for a in ads)
total_pur   = sum(a["pur"] for a in ads)
total_clk   = sum(a["clk"] for a in ads)
blend_roas  = total_pv / total_spend if total_spend else 0
avg_cpm     = (sum(a["cpm"]*a["impr"] for a in ads) / sum(a["impr"] for a in ads)) if ads else 0
avg_ctr     = (sum(a["ob_ctr"]*a["impr"] for a in ads) / sum(a["impr"] for a in ads)) if ads else 0
cvr         = total_pur / total_clk * 100 if total_clk else 0
hit_180     = len([a for a in ads if a["roas"] and a["roas"] >= 1.8])
hit_100     = len([a for a in ads if a["roas"] and a["roas"] >= 1.0])

print(f"  -> 제품 카테고리: {len(products)}개 / KB 소재: {len(ads)}개")
print(f"  -> 블렌드 ROAS: {blend_roas*100:.1f}%  |  ROAS 180%+: {hit_180}개")

# ── KPT 인사이트 자동 생성 ────────────────────────────────────────────────────
ads_by_roas = sorted([a for a in ads if a["roas"]], key=lambda a: a["roas"], reverse=True)
best_ad  = ads_by_roas[0] if ads_by_roas else None
worst_hi = sorted([a for a in ads if a["spend"] >= 500_000 and (not a["roas"] or a["roas"] < 1.0)],
                  key=lambda a: a["spend"], reverse=True)

best_prod  = max(products_sorted, key=prod_roas)
worst_prod = min(products_sorted, key=lambda p: prod_roas(p) if products[p]["spend"] > 0 else 999)

bp = products[best_prod]
wp = products[worst_prod]

trend_word = "개선" if blend_roas >= 1.8 else ("유지" if blend_roas >= 1.5 else "하락")

insights = [
    f"분석 기간: {SINCE.strftime('%m/%d')}~{UNTIL.strftime('%m/%d')}  |  KB 소재 {len(ads)}개  |  총 지출 ₩{total_spend:,.0f}",
    f"블렌드 ROAS {blend_roas*100:.1f}% → {trend_word} 추세  |  ROAS 180%+ 소재 {hit_180}/{len(ads)}개 ({hit_180/len(ads)*100:.0f}%)",
    f"베스트 제품: {best_prod} (ROAS {prod_roas(best_prod)*100:.1f}%, 지출 ₩{bp['spend']:,.0f})",
    f"주목 필요: {worst_prod} (ROAS {prod_roas(worst_prod)*100:.1f}%, 지출 ₩{wp['spend']:,.0f})",
]
if best_ad:
    insights.append(f"최고 소재: {best_ad['name'][:40]} (ROAS {best_ad['roas']*100:.1f}%)")

keep_points = [
    f"블렌드 ROAS {blend_roas*100:.1f}% 달성 — {'목표치 상회' if blend_roas >= 1.8 else '운영 기조 유지'}",
    f"ROAS 180% 이상 소재 {hit_180}개({hit_180/len(ads)*100:.0f}%) 확보로 고성과 소재 포트폴리오 형성",
    f"{best_prod} 제품 ROAS {prod_roas(best_prod)*100:.1f}% 기록 — 해당 소재 유형 및 구성 방식 벤치마킹 가능",
    f"CVR {cvr:.2f}% 수준 유지 — 클릭 이후 전환 흐름 안정적",
]

problem_points = [
    f"저성과 소재(ROAS 100% 미만) 지속 집행으로 예산 비효율 발생 — {len(worst_hi)}개 소재 집중 관리 필요",
    f"제품별 ROAS 편차 큼: {best_prod}({prod_roas(best_prod)*100:.1f}%) vs {worst_prod}({prod_roas(worst_prod)*100:.1f}%)",
    f"평균 CPM ₩{avg_cpm:,.0f} — 특정 제품 CPM 과다 구간 존재 시 타겟 세그먼트 재검토 필요",
    "소재 유형(이미지/영상/숏폼)별 성과 차이 분석 미실시 → 다음 달 A/B 비교 필요",
]

try_points = [
    f"저성과 소재 기준 명확화: 지출 50만원 초과 + ROAS 100% 미만 → D+3 일시정지 규칙 적용",
    f"{best_prod} 고성과 패턴(소재 구성, 카피, 비주얼)을 타 제품에 이식 테스트",
    f"{worst_prod} 소재 전면 리뉴얼 또는 타겟 세그먼트 변경으로 반등 시도",
    "제품별 ROAS 목표치 설정 후 일별 모니터링 체계 구축 (현재: 통합 블렌드 기준만 관리)",
]

# ── Notion 블록 빌더 ──────────────────────────────────────────────────────────
def h1(c): return {"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h2(c): return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h3(c): return {"object":"block","type":"heading_3","heading_3":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def div(): return {"object":"block","type":"divider","divider":{}}
def co(text, emoji="💡"):
    return {"object":"block","type":"callout","callout":{
        "rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}],
        "icon":{"type":"emoji","emoji":emoji}
    }}
def bl(text):
    return {"object":"block","type":"bulleted_list_item","bulleted_list_item":{"rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}]}}
def p(text=""):
    return {"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}]}}

def tbl(headers, rows):
    def cell(t): return [{"type":"text","text":{"content":str(t)[:2000]}}]
    ch  = [{"type":"table_row","table_row":{"cells":[cell(h) for h in headers]}}]
    ch += [{"type":"table_row","table_row":{"cells":[cell(v) for v in row]}} for row in rows]
    return {"object":"block","type":"table",
            "table":{"table_width":len(headers),"has_column_header":True,"has_row_header":False,"children":ch}}

def fmt_roas(r): return f"{r*100:.1f}%" if r else "전환없음"

period = f"{SINCE.strftime('%Y.%m.%d')} ~ {UNTIL.strftime('%Y.%m.%d')}"

print("[2/4] Notion 블록 구성...")
blocks = [
    h1(f"📊 KB 소재 전체 성과 보고서 ({SINCE.strftime('%m/%d')}~{UNTIL.strftime('%m/%d')})"),
    co(
        f"총 소재: {len(ads)}개  |  총 지출: ₩{total_spend:,.0f}  |  블렌드 ROAS: {blend_roas*100:.1f}%  |  "
        f"총 구매: {total_pur:.0f}건  |  평균 CPM: ₩{avg_cpm:,.0f}  |  평균 OB-CTR: {avg_ctr:.2f}%  |  CVR: {cvr:.2f}%",
        "📌"
    ),
    div(),

    # 제품별 요약 비교표
    h2("📋 제품별 성과 요약"),
    tbl(
        ["제품", "소재수", "지출", "ROAS", "OB-CTR", "CPM", "구매수"],
        [[
            prod,
            str(len(products[prod]["ads"])),
            f"₩{products[prod]['spend']:,.0f}",
            fmt_roas(prod_roas(prod)),
            f"{products[prod]['w_ctr']/products[prod]['impr']:.2f}%" if products[prod]["impr"] else "0.00%",
            f"₩{products[prod]['spend']/products[prod]['impr']*1000:,.0f}" if products[prod]["impr"] else "-",
            f"{products[prod]['pur']:.0f}건",
        ] for prod in products_sorted]
    ),
    div(),
]

# 제품별 상세
h2_blocks_count = 0
for prod in products_sorted:
    d  = products[prod]
    pr = prod_roas(prod)
    avg_p_ctr = d["w_ctr"] / d["impr"] if d["impr"] else 0
    avg_p_cpm = d["spend"] / d["impr"] * 1000 if d["impr"] else 0
    cvr_p     = d["pur"] / d["clk"] * 100 if d["clk"] else 0

    blocks.append(h2(f"▸ {prod}"))
    blocks.append(co(
        f"소재 {len(d['ads'])}개  |  지출 ₩{d['spend']:,.0f}  |  ROAS {fmt_roas(pr)}  |  "
        f"OB-CTR {avg_p_ctr:.2f}%  |  CPM ₩{avg_p_cpm:,.0f}  |  구매 {d['pur']:.0f}건  |  CVR {cvr_p:.2f}%",
        "📦"
    ))

    ads_in_prod = sorted(d["ads"], key=lambda a: a["spend"], reverse=True)
    blocks.append(tbl(
        ["소재명", "지출", "ROAS", "OB-CTR", "CPM", "구매수"],
        [[
            a["name"],
            f"₩{a['spend']:,.0f}",
            fmt_roas(a["roas"]),
            f"{a['ob_ctr']:.2f}%",
            f"₩{a['cpm']:,.0f}",
            f"{a['pur']:.0f}건",
        ] for a in ads_in_prod]
    ))
    blocks.append(div())
    h2_blocks_count += 1

# KPT + 인사이트
blocks += [
    h2("🔍 인사이트 & 회고 (KPT)"),
    co("\n".join(insights), "📊"),
    p(),

    h3("✅ Keep — 잘 된 것"),
] + [bl(pt) for pt in keep_points] + [
    p(),
    h3("❌ Problem — 문제점"),
] + [bl(pt) for pt in problem_points] + [
    p(),
    h3("💡 Try — 다음 달 시도"),
] + [bl(pt) for pt in try_points] + [
    p(),
    co(
        f"베스트 소재: {best_ad['name'][:60] if best_ad else '-'} (ROAS {best_ad['roas']*100:.1f}%)\n"
        f"저성과 집중 관리 소재: {worst_hi[0]['name'][:60] if worst_hi else '없음'}\n"
        f"다음 달 핵심 과제: {best_prod} 성공 패턴 확장 + {worst_prod} 소재 리뉴얼",
        "🎯"
    ),
]

# ── Notion 업로드 ─────────────────────────────────────────────────────────────
print("[3/4] Notion 페이지 생성...")
nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": f"📊 KB 소재 전체 성과 보고서 ({period})"}}]}},
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

print("[4/4] 블록 추가...")
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
print(f"\n[요약]")
print(f"  KB 소재 {len(ads)}개 / 제품 {len(products)}개 카테고리")
print(f"  총 지출 ₩{total_spend:,.0f}  |  블렌드 ROAS {blend_roas*100:.1f}%")
for prod in products_sorted:
    d = products[prod]
    print(f"  - {prod}: {len(d['ads'])}개  ₩{d['spend']:,.0f}  ROAS {prod_roas(prod)*100:.1f}%")
