import requests, json, datetime, os, urllib.parse

META_TOKEN    = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = "act_3431020723842735"
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"
SPEND_MIN     = 10_000  # ₩10,000 이상 소재만 분석

yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

# ── 1. Meta Ads 데이터 수집 ──────────────────────────────────────────────────
print(f"[1/3] Meta Ads 데이터 수집 ({yesterday})...")
fields = ",".join([
    "ad_id","ad_name","impressions","spend","cpm","ctr",
    "outbound_clicks_ctr","cpc","actions","action_values",
    "purchase_roas","video_avg_time_watched_actions","post_engagement",
])
ads, next_url = [], None
params = {"level":"ad","date_preset":"yesterday","fields":fields,
          "access_token":META_TOKEN,"limit":100}
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

# ── 2. 지표 파싱 + 지출 필터 ─────────────────────────────────────────────────
def ga(lst, t):
    for a in (lst or []):
        if a.get("action_type") == t:
            return float(a.get("value", 0))
    return None

all_ads = []
for ad in ads:
    al  = ad.get("actions", [])
    obl = ad.get("outbound_clicks_ctr", [])
    rl  = ad.get("purchase_roas", [])
    avl = ad.get("action_values", [])
    vl  = ad.get("video_avg_time_watched_actions", [])
    pur = ga(al, "purchase") or 0
    clk = ga(al, "link_click") or 1
    all_ads.append({
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
        "purchases":   pur,
    })

parsed = [a for a in all_ads if a["spend"] >= SPEND_MIN]
print(f"  -> 지출 ₩{SPEND_MIN:,} 이상 소재: {len(parsed)}개")

# ── 3. 상위 / 하위 소재 선정 ─────────────────────────────────────────────────
def top_score(a):
    return (a["roas"] or 0) * 10 + a["ob_ctr"]

def bot_score(a):
    roas = a["roas"] or 0
    return -(a["spend"] * (1 - roas))  # 손실액 = 지출 × (1 - ROAS), 클수록 하위

top5 = sorted(parsed, key=top_score, reverse=True)[:5]
bot5 = sorted(parsed, key=bot_score)[:5]

# ── 4. 집계 지표 ─────────────────────────────────────────────────────────────
total_spend = sum(a["spend"] for a in parsed)
total_pv    = sum(a["pv"] for a in parsed if a["pv"])
total_pur   = sum(a["purchases"] for a in parsed)
blend_roas  = total_pv / total_spend if total_spend else 0
avg_cpm     = sum(a["cpm"] for a in parsed) / len(parsed) if parsed else 0
avg_ob_ctr  = sum(a["ob_ctr"] for a in parsed) / len(parsed) if parsed else 0
high_burn   = [a for a in parsed if a["spend"] > 50_000 and (not a["roas"] or a["roas"] < 1)]
top10_spend = sorted(parsed, key=lambda x: x["spend"], reverse=True)[:10]

# ── 5. 차트 URL (QuickChart.io) ───────────────────────────────────────────────
def qc(cfg, w=720, h=380):
    return "https://quickchart.io/chart?w={}&h={}&c={}".format(
        w, h, urllib.parse.quote(json.dumps(cfg, ensure_ascii=False))
    )

# 차트 1: 상위 5 ROAS 바 차트
t_labels = [f"소재{i+1}" for i in range(len(top5))]
roas_chart = qc({
    "type": "bar",
    "data": {
        "labels": t_labels,
        "datasets": [{
            "label": "ROAS",
            "backgroundColor": ["rgba(59,130,246,0.85)", "rgba(16,185,129,0.85)",
                                 "rgba(245,158,11,0.85)", "rgba(139,92,246,0.85)",
                                 "rgba(236,72,153,0.85)"],
            "data": [round(a["roas"], 2) if a["roas"] else 0 for a in top5]
        }]
    },
    "options": {
        "plugins": {"title": {"display": True, "text": "상위 5개 소재 ROAS", "font": {"size": 14}}},
        "scales": {"y": {"beginAtZero": True}}
    }
})

# 차트 2: 하위 5 지출(만원) + ROAS 복합 차트
b_labels = [f"하위{i+1}" for i in range(len(bot5))]
bot_chart = qc({
    "type": "bar",
    "data": {
        "labels": b_labels,
        "datasets": [
            {"label": "지출(만원)", "backgroundColor": "rgba(239,68,68,0.75)",
             "data": [round(a["spend"] / 10000, 1) for a in bot5], "yAxisID": "y"},
            {"label": "ROAS", "type": "line", "borderColor": "rgba(16,185,129,1)",
             "borderWidth": 2, "pointRadius": 5, "fill": False,
             "data": [round(a["roas"], 2) if a["roas"] else 0 for a in bot5], "yAxisID": "y1"}
        ]
    },
    "options": {
        "plugins": {"title": {"display": True, "text": "하위 5개 소재: 지출 vs ROAS"}},
        "scales": {
            "y":  {"position": "left",  "title": {"display": True, "text": "지출 (만원)"}},
            "y1": {"position": "right", "title": {"display": True, "text": "ROAS"},
                   "grid": {"drawOnChartArea": False}}
        }
    }
})

# 차트 3: 지출 TOP10 수평 바
spend_chart = qc({
    "type": "horizontalBar",
    "data": {
        "labels": [a["name"][:22] for a in top10_spend],
        "datasets": [{
            "label": "지출 (₩)",
            "backgroundColor": "rgba(139,92,246,0.75)",
            "data": [int(a["spend"]) for a in top10_spend]
        }]
    },
    "options": {
        "plugins": {"title": {"display": True, "text": "지출 TOP 10 소재"}},
        "scales": {"xAxes": [{"ticks": {"beginAtZero": True}}]}
    }
}, w=720, h=440)

# ── 6. 분석 텍스트 ────────────────────────────────────────────────────────────
retro = [
    f"지출 발생 소재 {len(parsed)}개 | 총 지출 ₩{total_spend:,.0f} | 총 구매 {total_pur:.0f}건 | 총 전환값 ₩{total_pv:,.0f}",
    f"블렌드 ROAS {blend_roas:.2f}x — {'수익 구조 양호' if blend_roas >= 1.5 else '수익 구조 개선 필요'}",
    f"평균 CPM ₩{avg_cpm:,.0f} | 평균 아웃바운드CTR {avg_ob_ctr:.2f}%",
]
top_video = [a for a in top5 if a["v3s"]]
if top_video:
    avg_v3s = sum(a["v3s"] for a in top_video) / len(top_video)
    retro.append(f"상위 소재 평균 3초 재생 {avg_v3s:.1f}초 — {'도입부 훅 효과적' if avg_v3s >= 3 else '도입부 개선 여지 있음'}")
if high_burn:
    total_burn = sum(a["spend"] for a in high_burn)
    retro.append(f"고지출 저효율 소재 {len(high_burn)}개 총 ₩{total_burn:,.0f} 소진 — 즉각 점검 필요")

todo = []
for a in bot5:
    if a["spend"] > 50_000 and (not a["roas"] or a["roas"] < 0.5):
        rs = f"{a['roas']:.2f}x" if a["roas"] else "N/A"
        todo.append(f"[즉시 중단] {a['name'][:38]} — 지출 ₩{a['spend']:,.0f} / ROAS {rs}")
for a in sorted(high_burn, key=lambda x: x["spend"], reverse=True)[:5]:
    if a not in bot5:
        rs = f"{a['roas']:.2f}x" if a["roas"] else "N/A"
        todo.append(f"[예산 축소] {a['name'][:38]} — 지출 ₩{a['spend']:,.0f} / ROAS {rs}")
if top5 and top5[0]["roas"] and top5[0]["roas"] >= 1.5:
    todo.append(f"[예산 증액] {top5[0]['name'][:40]} — ROAS {top5[0]['roas']:.2f}x")
if not todo:
    todo.append("즉시 조치 필요 소재 없음 — 지속 모니터링")

next_actions = [
    f"상위 소재 '{top5[0]['name'][:25] if top5 else ''}' 컨셉·포맷 기반 신규 소재 1~2개 제작",
    "OB-CTR 상위 소재 위주로 예산 재배분",
    f"하위 {len(bot5)}개 소재 공통 패턴(고CPM/저전환) 분석 후 크리에이티브 방향 교정",
]
if any(a["v3s"] and a["v3s"] >= 3 for a in top5):
    next_actions.append("3초 재생 우수 동영상의 도입부 훅 패턴을 저성과 소재에 적용")

# ── 7. Notion 블록 빌더 ───────────────────────────────────────────────────────
def h1(c):  return {"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h2(c):  return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h3(c):  return {"object":"block","type":"heading_3","heading_3":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def p(c):   return {"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def blt(c): return {"object":"block","type":"bulleted_list_item","bulleted_list_item":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def divider(): return {"object":"block","type":"divider","divider":{}}
def img(url): return {"object":"block","type":"image","image":{"type":"external","external":{"url":url}}}

def callout(text, emoji="💡"):
    return {"object":"block","type":"callout","callout":{
        "rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}],
        "icon":{"type":"emoji","emoji":emoji}
    }}

def notion_table(headers, rows):
    def cell(text): return [{"type":"text","text":{"content":str(text)[:2000]}}]
    children  = [{"type":"table_row","table_row":{"cells":[cell(h) for h in headers]}}]
    children += [{"type":"table_row","table_row":{"cells":[cell(v) for v in row]}} for row in rows]
    return {
        "object":"block","type":"table",
        "table":{"table_width":len(headers),"has_column_header":True,"has_row_header":False},
        "children": children
    }

# ── 8. 블록 조립 ─────────────────────────────────────────────────────────────
blocks = []

# 헤더
blocks += [
    h1(f"📊 광고 소재 성과 보고서 — {yesterday}"),
    callout(f"전체 {len(all_ads)}개 소재 중 지출 ₩{SPEND_MIN:,} 이상 {len(parsed)}개만 분석", "📌"),
    divider(),
]

# KPI 요약 테이블
blocks.append(h2("📈 핵심 지표"))
blocks.append(notion_table(
    ["항목", "수치"],
    [
        ["총 지출",           f"₩{total_spend:,.0f}"],
        ["총 구매 수",        f"{total_pur:.0f}건"],
        ["총 구매전환값",     f"₩{total_pv:,.0f}"],
        ["블렌드 ROAS",       f"{blend_roas:.2f}x"],
        ["평균 CPM",          f"₩{avg_cpm:,.0f}"],
        ["평균 아웃바운드CTR", f"{avg_ob_ctr:.2f}%"],
        ["고지출 저효율 소재", f"{len(high_burn)}개 (지출 5만↑, ROAS 1x↓)"],
    ]
))
blocks.append(divider())

# 지출 TOP10
blocks.append(h2("💰 지출 TOP 10 소재"))
blocks.append(img(spend_chart))
blocks.append(notion_table(
    ["#", "소재명", "지출", "ROAS", "OB-CTR", "구매수"],
    [[str(i+1), a["name"][:35], f"₩{a['spend']:,.0f}",
      f"{a['roas']:.2f}x" if a["roas"] else "N/A",
      f"{a['ob_ctr']:.2f}%", f"{a['purchases']:.0f}건"]
     for i, a in enumerate(top10_spend)]
))
blocks.append(divider())

# 상위 5개
blocks.append(h2("🏆 상위 5개 소재"))
blocks.append(img(roas_chart))
for i, a in enumerate(top5, 1):
    blocks.append(p(f"소재{i}: {a['name']}"))
blocks.append(notion_table(
    ["#", "소재명", "지출", "CPM", "OB-CTR", "ROAS", "구매수", "3초재생"],
    [[str(i), a["name"][:30], f"₩{a['spend']:,.0f}", f"₩{a['cpm']:,.0f}",
      f"{a['ob_ctr']:.2f}%",
      f"{a['roas']:.2f}x" if a["roas"] else "N/A",
      f"{a['purchases']:.0f}건",
      f"{a['v3s']:.1f}초" if a["v3s"] else "N/A"]
     for i, a in enumerate(top5, 1)]
))

for i, a in enumerate(top5, 1):
    strengths = []
    if avg_ob_ctr > 0 and a["ob_ctr"] > avg_ob_ctr * 1.3:
        strengths.append(f"OB-CTR {a['ob_ctr']:.2f}% (평균 {avg_ob_ctr:.2f}% 대비 {a['ob_ctr']/avg_ob_ctr:.1f}배)")
    if a["roas"] and a["roas"] > blend_roas:
        strengths.append(f"ROAS {a['roas']:.2f}x (블렌드 {blend_roas:.2f}x 초과)")
    if avg_cpm > 0 and a["cpm"] < avg_cpm * 0.8:
        strengths.append(f"CPM ₩{a['cpm']:,.0f} (평균 대비 저렴 — 노출 효율 우수)")
    if a["v3s"] and a["v3s"] >= 3:
        strengths.append(f"3초 재생 {a['v3s']:.1f}초 — 도입부 훅 효과적")
    tip = "예산 증액 검토" if a["roas"] and a["roas"] >= 1.5 else "현 예산 유지 모니터링"
    roas_str = f"{a['roas']:.2f}x" if a["roas"] else "N/A"
    body = ("강점: " + " / ".join(strengths)) if strengths else f"지출 ₩{a['spend']:,.0f}, ROAS {roas_str}"
    blocks.append(h3(f"소재{i}. {a['name'][:50]}"))
    blocks.append(callout(body + f"\n→ {tip}", "✅"))

blocks.append(divider())

# 하위 5개
blocks.append(h2("⚠️ 하위 5개 소재"))
blocks.append(img(bot_chart))
for i, a in enumerate(bot5, 1):
    blocks.append(p(f"하위{i}: {a['name']}"))
blocks.append(notion_table(
    ["#", "소재명", "지출", "CPM", "OB-CTR", "ROAS", "구매수"],
    [[str(i), a["name"][:30], f"₩{a['spend']:,.0f}", f"₩{a['cpm']:,.0f}",
      f"{a['ob_ctr']:.2f}%",
      f"{a['roas']:.2f}x" if a["roas"] else "N/A",
      f"{a['purchases']:.0f}건"]
     for i, a in enumerate(bot5, 1)]
))

for i, a in enumerate(bot5, 1):
    roas_val = a["roas"] or 0
    loss = a["spend"] * (1 - roas_val)
    issues = [f"추정 손실액 ₩{loss:,.0f} (지출 ₩{a['spend']:,.0f}, ROAS {a['roas']:.2f}x 기준)" if a["roas"] else f"추정 손실액 ₩{loss:,.0f} (지출 ₩{a['spend']:,.0f}, 전환 미발생)"]
    if avg_cpm > 0 and a["cpm"] > avg_cpm * 1.5:
        issues.append(f"CPM ₩{a['cpm']:,.0f} (평균 ₩{avg_cpm:,.0f} 대비 고비용)")
    if avg_ob_ctr > 0 and a["ob_ctr"] < avg_ob_ctr * 0.5:
        issues.append(f"OB-CTR {a['ob_ctr']:.2f}% (평균 미달 — 소재 반응 낮음)")
    if not a["roas"]:
        issues.append("전환 미발생 — 크리에이티브 or 타겟팅 재검토")
    elif a["roas"] < 1:
        issues.append(f"ROAS {a['roas']:.2f}x — 손실 구간")
    action = "즉시 중단" if a["spend"] > 50_000 and (not a["roas"] or a["roas"] < 0.5) else "예산 축소 후 관찰"
    blocks.append(h3(f"하위{i}. {a['name'][:50]}"))
    blocks.append(callout(" / ".join(issues) + f"\n→ {action}", "🔴"))

blocks.append(divider())

# 소재 회고
blocks.append(h2("💡 소재 회고"))
for line in retro:
    blocks.append(blt(line))
blocks.append(divider())

# To-Do
blocks.append(h2("✅ To-Do"))
for line in todo:
    blocks.append(blt(line))
blocks.append(divider())

# Next Action
blocks.append(h2("🚀 Next Action"))
for line in next_actions:
    blocks.append(blt(line))

# ── 9. Notion 페이지 생성 ─────────────────────────────────────────────────────
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

# ── 10. 블록 추가 (테이블은 단독 전송) ────────────────────────────────────────
print("[3/3] 블록 추가...")

def flush(page_id, chunk, nh):
    if not chunk:
        return
    res = requests.patch(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        headers=nh, json={"children": chunk}
    ).json()
    if "error" in res:
        print(f"  -> 블록 추가 실패: {res.get('message', res)}")
    else:
        print(f"  -> {len(chunk)}개 블록 추가 완료")

pending = []
for block in blocks:
    if block.get("type") == "table":
        flush(page_id, pending, nh)
        pending = []
        flush(page_id, [block], nh)
    else:
        pending.append(block)
        if len(pending) >= 90:
            flush(page_id, pending, nh)
            pending = []
flush(page_id, pending, nh)

print(f"\n✅ 완료! {page.get('url')}")
