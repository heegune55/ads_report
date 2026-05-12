import requests, json, datetime, os

META_TOKEN = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT = "act_3431020723842735"
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"

yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

# ── 1. Meta Ads 데이터 수집 ──────────────────────────────────────────────────
print(f"[1/3] Meta Ads 데이터 수집 ({yesterday})...")
fields = ",".join([
    "ad_id", "ad_name", "impressions", "spend", "cpm", "ctr",
    "outbound_clicks_ctr", "cpc", "actions", "action_values",
    "purchase_roas", "video_avg_time_watched_actions", "post_engagement",
])
ads, next_url = [], None
params = {"level": "ad", "date_preset": "yesterday", "fields": fields,
          "access_token": META_TOKEN, "limit": 100}
url = f"https://graph.facebook.com/v20.0/{META_ACCOUNT}/insights"
while True:
    resp = requests.get(next_url or url, params=(None if next_url else params))
    data = resp.json()
    if "error" in data:
        raise SystemExit(f"Meta API 오류: {data['error']['message']}")
    ads.extend(data.get("data", []))
    next_url = data.get("paging", {}).get("next")
    if not next_url:
        break
print(f"  -> {len(ads)}개 소재 수집")

# ── 2. 지표 파싱 ─────────────────────────────────────────────────────────────
def ga(lst, t):
    for a in (lst or []):
        if a.get("action_type") == t:
            return float(a.get("value", 0))
    return None

parsed = []
for ad in ads:
    al  = ad.get("actions", [])
    obl = ad.get("outbound_clicks_ctr", [])
    rl  = ad.get("purchase_roas", [])
    avl = ad.get("action_values", [])
    vl  = ad.get("video_avg_time_watched_actions", [])
    pur = ga(al, "purchase") or 0
    clk = ga(al, "link_click") or 1
    parsed.append({
        "name":        ad.get("ad_name", ""),
        "impressions": float(ad.get("impressions", 0) or 0),
        "spend":       float(ad.get("spend", 0) or 0),
        "cpm":         float(ad.get("cpm", 0) or 0),
        "ctr":         float(ad.get("ctr", 0) or 0),
        "ob_ctr":      float(obl[0].get("value", 0)) if obl else 0.0,
        "cpc":         float(ad.get("cpc", 0) or 0),
        "cvr":         pur / clk * 100,
        "roas":        float(rl[0].get("value", 0)) if rl else None,
        "pv":          ga(avl, "purchase"),
        "v3s":         float(vl[0].get("value", 0)) if vl else None,
        "pe":          ga(al, "post_engagement") or float(ad.get("post_engagement", 0) or 0),
    })

def score(a):
    s = (1 / a["cpm"]) if a["cpm"] > 0 else 0
    s += a["ob_ctr"] * 10
    if a["v3s"]:  s += a["v3s"]
    if a["roas"]: s += a["roas"]
    return s

ranked = sorted(parsed, key=score, reverse=True)
top5, bot5 = ranked[:5], ranked[-5:]

# ── 3. 규칙 기반 분석 생성 ───────────────────────────────────────────────────
total_spend = sum(a["spend"] for a in parsed)
total_roas  = [a["roas"] for a in parsed if a["roas"]]
avg_roas    = sum(total_roas) / len(total_roas) if total_roas else 0
avg_cpm     = sum(a["cpm"] for a in parsed) / len(parsed) if parsed else 0
avg_ob_ctr  = sum(a["ob_ctr"] for a in parsed) / len(parsed) if parsed else 0
zero_roas   = [a for a in parsed if not a["roas"] or a["roas"] == 0]
high_spend_no_roas = [a for a in parsed if a["spend"] > 10000 and (not a["roas"] or a["roas"] < 1)]

retro_lines = [
    f"총 {len(parsed)}개 소재 분석 | 전체 지출 ₩{total_spend:,.0f} | 평균 CPM ₩{avg_cpm:,.0f} | 평균 아웃바운드CTR {avg_ob_ctr:.2f}%",
    f"평균 ROAS {avg_roas:.2f}x — " + ("전반적으로 양호한 수준입니다." if avg_roas >= 2 else "개선이 필요한 수준입니다."),
]
if top5:
    t = top5[0]
    roas_str = f", ROAS {t['roas']:.2f}x" if t['roas'] else ""
    retro_lines.append(f"최고 성과 소재: {t['name'][:40]} (CPM ₩{t['cpm']:,.0f}, OBC {t['ob_ctr']:.2f}%{roas_str})")
if zero_roas:
    retro_lines.append(f"ROAS 미발생 소재 {len(zero_roas)}개 — 크리에이티브 또는 타겟팅 재검토 필요.")
if any(a["v3s"] for a in parsed):
    avg_v3s = sum(a["v3s"] for a in parsed if a["v3s"]) / len([a for a in parsed if a["v3s"]])
    retro_lines.append(f"동영상 소재 평균 3초 재생시간 {avg_v3s:.1f}초 — {'도입부 훅이 효과적입니다.' if avg_v3s >= 3 else '도입부 훅 강화가 필요합니다.'}")

todo_lines = []
for a in bot5:
    if a["spend"] > 5000 and (not a["roas"] or a["roas"] < 0.5):
        todo_lines.append(f"중단 검토: {a['name'][:40]} (지출 ₩{a['spend']:,.0f}, ROAS {'N/A' if not a['roas'] else f'{a[\"roas\"]:.2f}x'})")
if high_spend_no_roas:
    todo_lines.append(f"ROAS 1x 미만 고지출 소재 {len(high_spend_no_roas)}개 예산 축소 또는 중단 검토")
if top5 and top5[0]["roas"] and top5[0]["roas"] >= 2:
    todo_lines.append(f"상위 소재 예산 증액 검토: {top5[0]['name'][:40]}")
if not todo_lines:
    todo_lines.append("현재 즉시 조치가 필요한 소재 없음 — 지속 모니터링")

next_lines = [
    f"상위 소재({top5[0]['name'][:30] if top5 else ''}) 컨셉·포맷 기반 신규 소재 1~2개 제작",
    "CPM 낮고 아웃바운드CTR 높은 소재 위주로 예산 집중 운영",
    "하위 소재 공통 패턴 분석 후 크리에이티브 방향 개선",
]
if any(a["v3s"] for a in parsed):
    next_lines.append("3초 재생시간 높은 동영상 소재의 훅 패턴을 다른 소재에 적용")

# ── 4. Notion 블록 구성 ───────────────────────────────────────────────────────
def h2(c):  return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":str(c)[:1999]}}]}}
def h3(c):  return {"object":"block","type":"heading_3","heading_3":{"rich_text":[{"type":"text","text":{"content":str(c)[:1999]}}]}}
def p(c):   return {"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":str(c)[:1999]}}]}}
def blt(c): return {"object":"block","type":"bulleted_list_item","bulleted_list_item":{"rich_text":[{"type":"text","text":{"content":str(c)[:1999]}}]}}

blocks = [
    h2(f"기준일: {yesterday} | 분석 소재 수: {len(parsed)}개"),
    h2("전체 소재 성과"),
    p("소재명 | 노출 수 | 지출 | CPM | CTR | 아웃바운드CTR | CPC | CVR | ROAS | 구매전환값 | 3초재생시간 | 게시물참여"),
    p("-" * 80),
]
for a in parsed:
    rs = f"{a['roas']:.2f}x" if a["roas"] is not None else "N/A"
    ps = f"₩{a['pv']:,.0f}"  if a["pv"]   is not None else "N/A"
    vs = f"{a['v3s']:.1f}초"  if a["v3s"]  is not None else "N/A"
    blocks.append(p(
        f"{a['name'][:28]} | {int(a['impressions']):,} | ₩{a['spend']:,.0f} | "
        f"₩{a['cpm']:,.0f} | {a['ctr']:.2f}% | {a['ob_ctr']:.2f}% | "
        f"₩{a['cpc']:,.0f} | {a['cvr']:.2f}% | {rs} | {ps} | {vs} | {int(a['pe']):,}"
    ))

blocks.append(h2("🏆 상위 5개 소재"))
for i, a in enumerate(top5, 1):
    rs = f"{a['roas']:.2f}x" if a["roas"] is not None else "N/A"
    blocks.append(h3(f"{i}. {a['name'][:50]}"))
    blocks.append(blt(f"CPM: ₩{a['cpm']:,.0f} | 아웃바운드CTR: {a['ob_ctr']:.2f}% | ROAS: {rs}"))
    if a["v3s"]: blocks.append(blt(f"3초 재생시간: {a['v3s']:.1f}초"))

blocks.append(h2("⚠️ 하위 5개 소재"))
for i, a in enumerate(bot5, 1):
    rs = f"{a['roas']:.2f}x" if a["roas"] is not None else "N/A"
    blocks.append(h3(f"{i}. {a['name'][:50]}"))
    blocks.append(blt(f"CPM: ₩{a['cpm']:,.0f} | 아웃바운드CTR: {a['ob_ctr']:.2f}% | ROAS: {rs}"))

blocks.append(h2("💡 소재 전반 회고"))
for line in retro_lines: blocks.append(p(line))

blocks.append(h2("✅ To-Do"))
for line in todo_lines: blocks.append(blt(line))

blocks.append(h2("🚀 Next Action"))
for line in next_lines: blocks.append(blt(line))

# ── 5. Notion 페이지 생성 ─────────────────────────────────────────────────────
print("[2/3] Notion 페이지 생성...")
nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": f"📊 광고 소재 성과 보고서 - {yesterday}"}}]}},
}).json()

if page.get("object") != "page":
    raise SystemExit(f"페이지 생성 실패: {page}")

page_id = page["id"]
print(f"  -> 페이지 생성: {page.get('url')}")

for i in range(0, len(blocks), 90):
    chunk = blocks[i:i+90]
    res = requests.patch(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        headers=nh, json={"children": chunk}
    ).json()
    if "error" in res:
        print(f"  -> 블록 추가 실패 (chunk {i}): {res}")
    else:
        print(f"  -> 블록 {i}~{i+len(chunk)} 추가 완료")

print(f"\n✅ 완료! {page.get('url')}")
