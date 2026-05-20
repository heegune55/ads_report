import requests, json, datetime, os
from collections import Counter

META_TOKEN    = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = os.environ.get("META_ACCOUNT", "act_3431020723842735")
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"
SPEND_MIN     = 10_000
PERSON_FILTER = os.environ.get("PERSON_FILTER", "KB")

_target = os.environ.get("TARGET_DATE", "")
yesterday = _target if _target else (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

# ── 1. Meta 데이터 수집 ──────────────────────────────────────────────────────
print(f"[1/3] Meta Ads 데이터 수집 ({yesterday})...")
fields = ",".join([
    "ad_id","ad_name","impressions","spend","cpm","ctr",
    "outbound_clicks_ctr","cpc","actions","action_values",
    "purchase_roas","video_avg_time_watched_actions",
    "video_play_actions","video_p25_watched_actions","post_engagement",
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

# ── 2. 파싱 + 지출 필터 ──────────────────────────────────────────────────────
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
    vl   = ad.get("video_avg_time_watched_actions", [])
    pl   = ad.get("video_play_actions", [])
    p25l = ad.get("video_p25_watched_actions", [])
    pur  = ga(al, "purchase") or 0
    clk  = ga(al, "link_click") or 1
    impr = float(ad.get("impressions", 0) or 0)
    plays = float(pl[0].get("value", 0)) if pl else None
    p25   = float(p25l[0].get("value", 0)) if p25l else None
    all_ads.append({
        "name":        ad.get("ad_name", ""),
        "impressions": impr,
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
        "plays":       plays,
        "p25":         p25,
        "hook_rate":   round(plays / impr * 100, 1) if plays and impr else None,
        "hold_rate":   round(p25 / plays * 100, 1) if p25 and plays else None,
    })

parsed = [a for a in all_ads if a["spend"] >= SPEND_MIN and PERSON_FILTER in a["name"]]
print(f"  -> {PERSON_FILTER} 소재 중 지출 ₩{SPEND_MIN:,} 이상: {len(parsed)}개")

# ── 3. 상위 / 하위 선정 ──────────────────────────────────────────────────────
def top_score(a):
    return (a["roas"] or 0) * 10 + a["ob_ctr"]

def bot_score(a):
    return -(a["spend"] * (1 - (a["roas"] or 0)))  # 손실액 기준

top5 = sorted(parsed, key=top_score, reverse=True)[:5]
bot5 = sorted(parsed, key=bot_score)[:5]

# ── 4. 집계 ──────────────────────────────────────────────────────────────────
total_spend = sum(a["spend"] for a in parsed)
total_pv    = sum(a["pv"] for a in parsed if a["pv"])
total_pur   = sum(a["purchases"] for a in parsed)
blend_roas  = total_pv / total_spend if total_spend else 0
avg_cpm     = sum(a["cpm"] for a in parsed) / len(parsed) if parsed else 0
avg_ob_ctr  = sum(a["ob_ctr"] for a in parsed) / len(parsed) if parsed else 0
high_burn   = [a for a in parsed if a["spend"] > 50_000 and (not a["roas"] or a["roas"] < 1)]

# ── 5. 포맷 · 브랜드별 성과 집계 ─────────────────────────────────────────────
def parse_name(name):
    parts = name.split("_")
    brand = parts[1] if len(parts) > 1 else "기타"
    fmt   = parts[2] if len(parts) > 2 else "기타"
    return brand, fmt

def grp(lst):
    rl = [a["roas"] for a in lst if a["roas"]]
    return {
        "n": len(lst),
        "avg_roas":       sum(rl) / len(rl) if rl else 0,
        "roas_coverage":  len(rl) / len(lst) * 100 if lst else 0,
        "total_spend":    sum(a["spend"] for a in lst),
        "avg_ob_ctr":     sum(a["ob_ctr"] for a in lst) / len(lst) if lst else 0,
        "avg_cpm":        sum(a["cpm"] for a in lst) / len(lst) if lst else 0,
    }

fmt_data, brand_data = {}, {}
for a in parsed:
    brand, fmt = parse_name(a["name"])
    fmt_data.setdefault(fmt, []).append(a)
    brand_data.setdefault(brand, []).append(a)

fmt_stats   = {f: grp(v) for f, v in fmt_data.items() if len(v) >= 2}
brand_stats = {b: grp(v) for b, v in brand_data.items() if len(v) >= 2}
fmt_sorted   = sorted(fmt_stats.items(),   key=lambda x: x[1]["avg_roas"], reverse=True)
brand_sorted = sorted(brand_stats.items(), key=lambda x: x[1]["avg_roas"], reverse=True)

# 상위/하위 공통 속성
top5_fmts    = [parse_name(a["name"])[1] for a in top5]
top5_brands  = [parse_name(a["name"])[0] for a in top5]
bot5_fmts    = [parse_name(a["name"])[1] for a in bot5]
bot5_brands  = [parse_name(a["name"])[0] for a in bot5]

# ── 6. 소재 회고 (데이터 기반 분석) ──────────────────────────────────────────
retro = []

# (1) 전체 효율 진단
roas_label = ("수익 구조 양호" if blend_roas >= 1.5
               else "손익 분기점 수준" if blend_roas >= 1.0
               else "전반적 손실 구간")
retro.append(
    f"블렌드 ROAS {blend_roas:.2f}x — {roas_label}. "
    f"지출 ₩{total_spend:,.0f} 대비 전환값 ₩{total_pv:,.0f} 회수, 구매 {total_pur:.0f}건 발생."
)

# (2) 포맷별 효율 비교
if len(fmt_sorted) >= 2:
    bf, bs = fmt_sorted[0]
    wf, ws = fmt_sorted[-1]
    retro.append(
        f"포맷 효율 격차: '{bf}' 평균 ROAS {bs['avg_roas']:.2f}x({bs['n']}개, ₩{bs['total_spend']:,.0f}) vs "
        f"'{wf}' {ws['avg_roas']:.2f}x({ws['n']}개) — "
        f"동일 예산 투입 시 {bf}가 {bs['avg_roas']/max(ws['avg_roas'], 0.01):.1f}배 효율적. "
        f"{bf} 포맷으로의 예산 재배분 검토 필요."
    )

# (3) 파트너십 전용 분석
if "파트너십" in fmt_stats:
    ps = fmt_stats["파트너십"]
    verdict = ("ROAS 1x 미만 — 현재 파트너 계약·소재 방식으로는 수익 회수 불가. "
               "단가 협상 또는 파트너 교체 검토 필요"
               if ps["avg_roas"] < 1 else "수익 구조 양호")
    retro.append(
        f"파트너십 소재 {ps['n']}개: 평균 ROAS {ps['avg_roas']:.2f}x, "
        f"전환 발생률 {ps['roas_coverage']:.0f}%, 총 집행 ₩{ps['total_spend']:,.0f} — {verdict}."
    )

# (4) 상위 소재 공통점 분석
top_fmt_cnt = Counter(top5_fmts)
dom_top_fmt, dom_top_cnt = top_fmt_cnt.most_common(1)[0]
top_avg_cpm  = sum(a["cpm"] for a in top5) / len(top5) if top5 else 0
top_roas_ads = [a for a in top5 if a["roas"]]
top_avg_roas = sum(a["roas"] for a in top_roas_ads) / len(top_roas_ads) if top_roas_ads else 0
cpm_vs_avg   = "낮아 노출 효율 우수" if top_avg_cpm < avg_cpm else "높음"
retro.append(
    f"상위 소재 패턴: {dom_top_cnt}/5개 '{dom_top_fmt}' 포맷 집중, "
    f"평균 CPM ₩{top_avg_cpm:,.0f}(전체 평균 ₩{avg_cpm:,.0f} 대비 {cpm_vs_avg}), "
    f"평균 ROAS {top_avg_roas:.2f}x — "
    f"이 포맷·테마 기반 신규 소재 제작이 가장 빠른 성과 개선 경로."
)

# (5) 하위 소재 공통점 분석
bot_fmt_cnt = Counter(bot5_fmts)
dom_bot_fmt, dom_bot_cnt = bot_fmt_cnt.most_common(1)[0]
bot_no_roas     = [a for a in bot5 if not a["roas"]]
total_bot_loss  = sum(a["spend"] * (1 - (a["roas"] or 0)) for a in bot5)
bot_avg_cpm     = sum(a["cpm"] for a in bot5) / len(bot5) if bot5 else 0
if bot_no_roas:
    retro.append(
        f"하위 소재 문제: {len(bot_no_roas)}/5개 전환 미발생, "
        f"'{dom_bot_fmt}' 포맷 {dom_bot_cnt}개 집중, "
        f"5개 합산 추정 손실 ₩{total_bot_loss:,.0f}. "
        f"평균 CPM ₩{bot_avg_cpm:,.0f} — "
        f"크리에이티브 소구점 재설계 없이는 비용 회수 불가."
    )
else:
    bot_roas_ads = [a for a in bot5 if a["roas"]]
    bot_avg_roas = sum(a["roas"] for a in bot_roas_ads) / len(bot_roas_ads) if bot_roas_ads else 0
    retro.append(
        f"하위 소재: 전환은 발생하나 평균 ROAS {bot_avg_roas:.2f}x — "
        f"손실 합계 ₩{total_bot_loss:,.0f}. "
        f"단가·마진 구조 점검 또는 CPC 절감 방안 필요."
    )

# ── 7. To-Do + Next Action ────────────────────────────────────────────────────
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
    f"상위 소재 포맷({dom_top_fmt}) 기반 신규 소재 제작 — 컨셉·훅·비율 그대로 복제 후 소구점만 변형",
    f"'{dom_bot_fmt}' 하위 소재 공통 원인 분석 후 타겟팅 또는 랜딩 페이지 점검",
    "OB-CTR 상위 소재 위주 예산 재배분 (클릭 품질 확보 우선)",
]
if "파트너십" in fmt_stats and fmt_stats["파트너십"]["avg_roas"] < 1:
    next_actions.append("파트너십 소재 전체 ROAS 1x 미만 — 신규 계약 전 성과 기준 명문화 필요")

# ── 8. Notion 블록 빌더 ───────────────────────────────────────────────────────
def h1(c):  return {"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h2(c):  return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h3(c):  return {"object":"block","type":"heading_3","heading_3":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def p(c):   return {"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def blt(c): return {"object":"block","type":"bulleted_list_item","bulleted_list_item":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def divider(): return {"object":"block","type":"divider","divider":{}}

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

# ── 10. 블록 조립 ─────────────────────────────────────────────────────────────
blocks = []

# 헤더
blocks += [
    h1(f"📊 광고 소재 성과 보고서 — {yesterday}"),
    callout(
        f"총 지출 ₩{total_spend:,.0f}  |  구매 {total_pur:.0f}건  |  전환값 ₩{total_pv:,.0f}  |  "
        f"블렌드 ROAS {blend_roas:.2f}x  |  평균 CPM ₩{avg_cpm:,.0f}  |  평균 OB-CTR {avg_ob_ctr:.2f}%  |  "
        f"분석 소재 {len(parsed)}개 ({PERSON_FILTER} 소재 / ₩{SPEND_MIN:,} 이상)",
        "📌"
    ),
    divider(),
]

# 핵심지표: 전체 소재 성과 표 (지출 순)
all_sorted = sorted(parsed, key=lambda x: x["spend"], reverse=True)
blocks.append(h2("📋 전체 소재 성과"))
blocks.append(notion_table(
    ["소재명", "지출", "ROAS", "OB-CTR", "CPM", "훅률", "홀드율", "구매수"],
    [[a["name"][:35],
      f"₩{a['spend']:,.0f}",
      f"{a['roas']:.2f}x" if a["roas"] else "N/A",
      f"{a['ob_ctr']:.2f}%",
      f"₩{a['cpm']:,.0f}",
      f"{a['hook_rate']:.1f}%" if a["hook_rate"] else "N/A",
      f"{a['hold_rate']:.1f}%" if a["hold_rate"] else "N/A",
      f"{a['purchases']:.0f}건"]
     for a in all_sorted]
))
blocks.append(divider())

# 상위 5개
blocks.append(h2("🏆 상위 5개 소재"))
for i, a in enumerate(top5, 1):
    blocks.append(p(f"소재{i}: {a['name']}"))
blocks.append(notion_table(
    ["#", "소재명", "지출", "CPM", "OB-CTR", "ROAS", "훅률", "홀드율"],
    [[str(i), a["name"][:30], f"₩{a['spend']:,.0f}", f"₩{a['cpm']:,.0f}",
      f"{a['ob_ctr']:.2f}%",
      f"{a['roas']:.2f}x" if a["roas"] else "N/A",
      f"{a['hook_rate']:.1f}%" if a["hook_rate"] else "N/A",
      f"{a['hold_rate']:.1f}%" if a["hold_rate"] else "N/A"]
     for i, a in enumerate(top5, 1)]
))

for i, a in enumerate(top5, 1):
    diagnoses = []
    if avg_cpm > 0 and a["cpm"] < avg_cpm * 0.8:
        diagnoses.append(f"CPM ₩{a['cpm']:,.0f}으로 전체 평균(₩{avg_cpm:,.0f}) 대비 {(1-a['cpm']/avg_cpm)*100:.0f}% 저렴 — 노출 경쟁력 확보")
    elif avg_cpm > 0 and a["cpm"] > avg_cpm * 1.2:
        diagnoses.append(f"CPM ₩{a['cpm']:,.0f}으로 평균 대비 {(a['cpm']/avg_cpm-1)*100:.0f}% 비싸지만 ROAS로 커버")
    if avg_ob_ctr > 0 and a["ob_ctr"] > avg_ob_ctr * 1.3:
        diagnoses.append(f"OB-CTR {a['ob_ctr']:.2f}%(평균 {avg_ob_ctr:.2f}% 대비 {a['ob_ctr']/avg_ob_ctr:.1f}배) — 소재 반응 및 랜딩 연결성 우수")
    if a["roas"] and a["roas"] > blend_roas * 1.5:
        diagnoses.append(f"ROAS {a['roas']:.2f}x로 블렌드 ROAS({blend_roas:.2f}x)의 {a['roas']/blend_roas:.1f}배 — 전환 효율 탁월")
    if a["hook_rate"] is not None:
        bench = "우수 (기준 8% 이상)" if a["hook_rate"] >= 8 else "주의 (기준 8% 미만)"
        diagnoses.append(f"훅률 {a['hook_rate']:.1f}% — {bench}")
    if a["hold_rate"] is not None:
        bench = "우수 (기준 60% 이상)" if a["hold_rate"] >= 60 else "개선 필요 (기준 60% 미만)"
        diagnoses.append(f"홀드율 {a['hold_rate']:.1f}% — {bench}")
    if a["v3s"] and a["v3s"] >= 3:
        diagnoses.append(f"3초 재생 {a['v3s']:.1f}초 — 도입부 훅이 이탈 없이 시청 유도")
    low_spend_note = " ※ 지출 적어 통계적 신뢰도 낮음 — 예산 증액 후 재검증 필요" if a["spend"] < 50_000 else ""
    tip = "예산 증액 검토" if a["roas"] and a["roas"] >= 1.5 else "현 예산 유지 모니터링"
    roas_str = f"{a['roas']:.2f}x" if a["roas"] else "N/A"
    body = " / ".join(diagnoses) if diagnoses else f"지출 ₩{a['spend']:,.0f}, ROAS {roas_str}"
    blocks.append(h3(f"소재{i}. {a['name'][:50]}"))
    blocks.append(callout(body + low_spend_note + f"\n→ {tip}", "✅"))

blocks.append(divider())

# 하위 5개
blocks.append(h2("⚠️ 하위 5개 소재 (손실액 기준)"))
for i, a in enumerate(bot5, 1):
    blocks.append(p(f"하위{i}: {a['name']}"))
blocks.append(notion_table(
    ["#", "소재명", "지출", "ROAS", "추정 손실액", "OB-CTR", "CPM"],
    [[str(i), a["name"][:30], f"₩{a['spend']:,.0f}",
      f"{a['roas']:.2f}x" if a["roas"] else "N/A",
      f"₩{a['spend']*(1-(a['roas'] or 0)):,.0f}",
      f"{a['ob_ctr']:.2f}%", f"₩{a['cpm']:,.0f}"]
     for i, a in enumerate(bot5, 1)]
))

for i, a in enumerate(bot5, 1):
    loss = a["spend"] * (1 - (a["roas"] or 0))
    diagnoses = [f"추정 손실 ₩{loss:,.0f} (지출 ₩{a['spend']:,.0f}, ROAS {'%s' % (str(round(a['roas'],2))+'x') if a['roas'] else '전환 없음'})"]
    if not a["roas"]:
        diagnoses.append("전환 데이터 없음 — 픽셀 이벤트 누락이거나 크리에이티브가 구매 의도를 유발하지 못하는 상태")
    elif a["roas"] < 0.5:
        diagnoses.append(f"ROAS {a['roas']:.2f}x — 지출의 절반도 회수 못 함. 소재 교체 없이 운영 지속 시 손실 누적")
    elif a["roas"] < 1:
        diagnoses.append(f"ROAS {a['roas']:.2f}x — 손실 구간이나 귀인 지연 가능성 있음. 7일 window 데이터로 재확인 필요")
    if avg_cpm > 0 and a["cpm"] > avg_cpm * 1.5:
        diagnoses.append(f"CPM ₩{a['cpm']:,.0f}으로 평균 대비 {a['cpm']/avg_cpm:.1f}배 — 오디언스 경쟁 과열 또는 관련성 낮음")
    if avg_ob_ctr > 0 and a["ob_ctr"] < avg_ob_ctr * 0.5:
        diagnoses.append(f"OB-CTR {a['ob_ctr']:.2f}%(평균 {avg_ob_ctr:.2f}%) — 소재 반응 자체가 낮아 클릭 유도 실패")
    if a["hook_rate"] is not None and a["hook_rate"] < 8:
        diagnoses.append(f"훅률 {a['hook_rate']:.1f}% — 기준(8%) 미달, 도입부 훅 재설계 필요")
    if a["hold_rate"] is not None and a["hold_rate"] < 60:
        diagnoses.append(f"홀드율 {a['hold_rate']:.1f}% — 기준(60%) 미달, 영상 초반 이탈 과다")
    action = "즉시 중단" if a["spend"] > 50_000 and (not a["roas"] or a["roas"] < 0.5) else "예산 축소 후 관찰"
    blocks.append(h3(f"하위{i}. {a['name'][:50]}"))
    blocks.append(callout(" / ".join(diagnoses) + f"\n→ {action}", "🔴"))

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

# ── 11. Notion 페이지 생성 ────────────────────────────────────────────────────
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

# ── 12. 블록 추가 (테이블 단독 전송) ─────────────────────────────────────────
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
