import requests, json, datetime, os, time, urllib.parse
from collections import defaultdict

META_TOKEN    = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = os.environ.get("META_ACCOUNT", "act_3431020723842735")
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"

SINCE     = os.environ.get("RETRO_SINCE", "2026-05-01")
UNTIL     = os.environ.get("RETRO_UNTIL", str(datetime.date.today() - datetime.timedelta(days=1)))
KEYWORD   = os.environ.get("PERSON_FILTER", "KB")
SPEND_MIN = 100_000

FIELDS_FULL  = "ad_id,ad_name,spend,impressions,cpm,outbound_clicks_ctr,actions,action_values,purchase_roas,video_play_actions,video_p25_watched_actions"
FIELDS_DAILY = "ad_name,spend,impressions,outbound_clicks_ctr,actions,action_values"
BASE_URL = f"https://graph.facebook.com/v20.0/{META_ACCOUNT}/insights"
DAYS_KO  = ["월", "화", "수", "목", "금", "토", "일"]

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

def fv(lst):
    return float(lst[0].get("value", 0)) if lst else 0.0

tr = json.dumps({"since": SINCE, "until": UNTIL})

# ── 1. 소재별 전체 데이터 ─────────────────────────────────────────────────────
print(f"[1/4] 소재별 전체 데이터 수집 ({SINCE} ~ {UNTIL})...")
raw = fetch_all({
    "level": "ad",
    "time_range": tr,
    "fields": FIELDS_FULL,
    "access_token": META_TOKEN,
    "limit": 500,
})

ads = []
for ad in raw:
    name = ad.get("ad_name", "")
    if KEYWORD not in name:
        continue
    spd  = float(ad.get("spend", 0) or 0)
    if spd < SPEND_MIN:
        continue
    impr  = float(ad.get("impressions", 0) or 0)
    obl   = ad.get("outbound_clicks_ctr", [])
    rl    = ad.get("purchase_roas", [])
    avl   = ad.get("action_values", [])
    al    = ad.get("actions", [])
    plays = fv(ad.get("video_play_actions", []))
    p25   = fv(ad.get("video_p25_watched_actions", []))
    pv    = ga(avl, "purchase")
    pur   = ga(al,  "purchase")
    roas  = float(rl[0].get("value", 0)) if rl else None

    ads.append({
        "name":      name,
        "spend":     spd,
        "impr":      impr,
        "roas":      roas,
        "ob_ctr":    float(obl[0].get("value", 0)) if obl else 0.0,
        "cpm":       float(ad.get("cpm", 0) or 0),
        "pur":       pur,
        "pv":        pv,
        "hook_rate": plays / impr * 100 if plays and impr else None,
        "hold_rate": p25  / plays * 100 if p25  and plays else None,
    })

print(f"  -> KB 소재 (₩{SPEND_MIN:,} 이상): {len(ads)}개")
if not ads:
    raise SystemExit("해당 조건의 소재 없음")

# ── 2. 일자별 데이터 ──────────────────────────────────────────────────────────
print("[2/4] 일자별 데이터 수집...")
raw_daily = fetch_all({
    "level": "ad",
    "time_range": tr,
    "fields": FIELDS_DAILY,
    "time_increment": "1",
    "access_token": META_TOKEN,
    "limit": 500,
})

daily = defaultdict(lambda: {"spend": 0.0, "impr": 0.0, "pv": 0.0, "pur": 0.0, "w_ctr": 0.0})
for row in raw_daily:
    name = row.get("ad_name", "")
    if KEYWORD not in name:
        continue
    date  = row.get("date_start", "")
    spd   = float(row.get("spend", 0) or 0)
    impr  = float(row.get("impressions", 0) or 0)
    pv    = ga(row.get("action_values", []), "purchase")
    pur   = ga(row.get("actions", []),       "purchase")
    obl   = row.get("outbound_clicks_ctr", [])
    ctr   = float(obl[0].get("value", 0)) if obl else 0.0
    daily[date]["spend"] += spd
    daily[date]["impr"]  += impr
    daily[date]["pv"]    += pv
    daily[date]["pur"]   += pur
    daily[date]["w_ctr"] += ctr * impr

dates_sorted = sorted(daily.keys())

# ── 3. 집계 ───────────────────────────────────────────────────────────────────
ads_by_roas = sorted(ads, key=lambda a: a["roas"] if a["roas"] else -1, reverse=True)
top_ads     = [a for a in ads_by_roas if a["roas"] and a["roas"] >= 1.8]
mid_ads     = [a for a in ads_by_roas if a["roas"] and 1.0 <= a["roas"] < 1.8]
low_ads     = [a for a in ads_by_roas if not a["roas"] or a["roas"] < 1.0]

total_spend  = sum(a["spend"] for a in ads)
total_pv     = sum(a["pv"]    for a in ads)
total_pur    = sum(a["pur"]   for a in ads)
blend_roas   = total_pv / total_spend if total_spend else 0
avg_cpm      = sum(a["cpm"] * a["impr"] for a in ads) / sum(a["impr"] for a in ads) if sum(a["impr"] for a in ads) else 0
total_impr   = sum(a["impr"] for a in ads)
avg_ctr_w    = sum(a["ob_ctr"] * a["impr"] for a in ads) / total_impr if total_impr else 0

# 요일 패턴
dow = defaultdict(lambda: {"spend": 0.0, "pv": 0.0, "pur": 0.0, "impr": 0.0, "count": 0})
for date in dates_sorted:
    d   = daily[date]
    day = DAYS_KO[datetime.date.fromisoformat(date).weekday()]
    dow[day]["spend"] += d["spend"]
    dow[day]["pv"]    += d["pv"]
    dow[day]["pur"]   += d["pur"]
    dow[day]["impr"]  += d["impr"]
    dow[day]["count"] += 1

def dow_roas(day):
    d = dow[day]
    return d["pv"] / d["spend"] if d["spend"] else 0

days_present = [d for d in DAYS_KO if d in dow]
best_day  = max(days_present, key=dow_roas) if days_present else None
worst_day = min(days_present, key=dow_roas) if days_present else None

# 추세: 전반/후반
half = len(dates_sorted) // 2
early_pv    = sum(daily[d]["pv"]    for d in dates_sorted[:half])
early_spend = sum(daily[d]["spend"] for d in dates_sorted[:half])
late_pv     = sum(daily[d]["pv"]    for d in dates_sorted[half:])
late_spend  = sum(daily[d]["spend"] for d in dates_sorted[half:])
early_roas  = early_pv / early_spend if early_spend else 0
late_roas   = late_pv  / late_spend  if late_spend  else 0

# ── Notion 블록 헬퍼 ──────────────────────────────────────────────────────────
def h1(c):  return {"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h2(c):  return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h3(c):  return {"object":"block","type":"heading_3","heading_3":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def p(c):   return {"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def div():  return {"object":"block","type":"divider","divider":{}}
def co(text, emoji="💡"):
    return {"object":"block","type":"callout","callout":{
        "rich_text":[{"type":"text","text":{"content":str(text)[:2000]}}],
        "icon":{"type":"emoji","emoji":emoji}
    }}

def tbl(headers, rows):
    def cell(t): return [{"type":"text","text":{"content":str(t)[:2000]}}]
    ch  = [{"type":"table_row","table_row":{"cells":[cell(h) for h in headers]}}]
    ch += [{"type":"table_row","table_row":{"cells":[cell(v) for v in row]}} for row in rows]
    return {"object":"block","type":"table",
            "table":{"table_width":len(headers),"has_column_header":True,"has_row_header":False,
                     "children": ch}}

def img_block(url):
    return {"object":"block","type":"image","image":{"type":"external","external":{"url":url}}}

def qc(cfg, w=680, h=360):
    url = "https://quickchart.io/chart?c=" + urllib.parse.quote(json.dumps(cfg, ensure_ascii=False)) + f"&w={w}&h={h}"
    return img_block(url)

def ad_row(a):
    hook = f"{a['hook_rate']:.1f}%" if a["hook_rate"] else "-"
    hold = f"{a['hold_rate']:.1f}%" if a["hold_rate"] else "-"
    return [
        a["name"],
        f"₩{a['spend']:,.0f}",
        f"{a['roas']:.2f}x" if a["roas"] else "전환없음",
        f"{a['ob_ctr']:.2f}%",
        f"₩{a['cpm']:,.0f}",
        hook,
        hold,
        f"{a['pur']:.0f}건",
    ]

AD_HDR = ["소재명", "지출", "ROAS", "OB-CTR", "CPM", "훅률", "홀드율", "구매수"]
period = f"{SINCE.replace('-','.')} ~ {UNTIL.replace('-','.')}"
month_label = datetime.date.fromisoformat(SINCE).strftime("%Y년 %m월")

# ── 블록 조립 ─────────────────────────────────────────────────────────────────
print("[3/4] 블록 조립...")
blocks = [
    h1(f"📝 {month_label} KB 소재 월말 회고"),
    co(
        f"분석 기간: {period}  |  소재: {len(ads)}개  |  "
        f"합산 지출: ₩{total_spend:,.0f}  |  블렌드 ROAS: {blend_roas:.2f}x  |  "
        f"총 구매: {total_pur:.0f}건  |  ROAS 180%+: {len(top_ads)}개",
        "📌"
    ),
    div(),
]

# ── 핵심 지표 요약 ─────────────────────────────────────────────────────────────
blocks.append(h2("📊 핵심 지표 요약"))
blocks.append(tbl(
    ["지표", "값"],
    [
        ["합산 지출",      f"₩{total_spend:,.0f}"],
        ["블렌드 ROAS",    f"{blend_roas:.2f}x"],
        ["총 구매건수",    f"{total_pur:.0f}건"],
        ["총 노출",        f"{total_impr:,.0f}회"],
        ["평균 CPM",       f"₩{avg_cpm:,.0f}"],
        ["평균 OB-CTR",    f"{avg_ctr_w:.2f}%"],
        ["활성 소재 수",   f"{len(ads)}개"],
        ["ROAS 180%+ 소재", f"{len(top_ads)}개 ({len(top_ads)/len(ads)*100:.0f}%)"],
    ]
))
blocks.append(div())

# ── 전체 소재 성과 ─────────────────────────────────────────────────────────────
blocks.append(h2(f"📋 소재별 성과 전체 ({len(ads)}개) — ROAS 높은 순"))
blocks.append(tbl(AD_HDR, [ad_row(a) for a in ads_by_roas]))
blocks.append(div())

# ── 우수 소재 ──────────────────────────────────────────────────────────────────
if top_ads:
    blocks.append(h2(f"✅ 우수 소재 — ROAS 180% 이상 ({len(top_ads)}개)"))
    for a in top_ads[:5]:
        lines = [f"ROAS {a['roas']:.2f}x  |  지출 ₩{a['spend']:,.0f}  |  구매 {a['pur']:.0f}건  |  CPM ₩{a['cpm']:,.0f}"]
        if a["hook_rate"]: lines.append(f"훅률 {a['hook_rate']:.1f}% {'✅ 기준 초과' if a['hook_rate'] >= 8 else '⚠️ 기준 미달 (8%↑)'}")
        if a["hold_rate"]: lines.append(f"홀드율 {a['hold_rate']:.1f}% {'✅ 기준 초과' if a['hold_rate'] >= 60 else '⚠️ 기준 미달 (60%↑)'}")
        blocks.append(h3(a["name"]))
        blocks.append(co("\n".join(lines), "✅"))
    blocks.append(div())

# ── 개선 필요 소재 ─────────────────────────────────────────────────────────────
low_high_spend = sorted([a for a in low_ads if a["spend"] >= 500_000],
                        key=lambda a: a["spend"], reverse=True)
if low_high_spend:
    blocks.append(h2(f"⚠️ 개선 필요 소재 — 지출 50만↑ + ROAS 100% 미만 ({len(low_high_spend)}개)"))
    blocks.append(tbl(AD_HDR, [ad_row(a) for a in low_high_spend]))
    blocks.append(div())

# ── 일별 추이 ──────────────────────────────────────────────────────────────────
blocks.append(h2("📅 일별 추이"))

date_labels = [d[5:].replace("-", "/") for d in dates_sorted]
daily_roas  = [round(daily[d]["pv"] / daily[d]["spend"], 2) if daily[d]["spend"] else 0 for d in dates_sorted]
daily_spend = [round(daily[d]["spend"] / 10000, 1) for d in dates_sorted]

blocks.append(qc({
    "type": "line",
    "data": {"labels": date_labels,
             "datasets": [{"label": "ROAS",
                           "data": daily_roas,
                           "borderColor": "rgb(75,192,192)",
                           "backgroundColor": "rgba(75,192,192,0.08)",
                           "tension": 0.2, "fill": False}]},
    "options": {"title": {"display": True, "text": f"{month_label} 일별 ROAS 추이"},
                "scales": {"yAxes": [{"ticks": {"beginAtZero": True}}]}}
}))

blocks.append(qc({
    "type": "bar",
    "data": {"labels": date_labels,
             "datasets": [{"label": "지출 (만원)",
                           "data": daily_spend,
                           "backgroundColor": "rgba(54,162,235,0.6)"}]},
    "options": {"title": {"display": True, "text": f"{month_label} 일별 지출 (만원)"},
                "scales": {"yAxes": [{"ticks": {"beginAtZero": True}}]}}
}))
blocks.append(div())

# ── 요일 패턴 ──────────────────────────────────────────────────────────────────
blocks.append(h2("📆 요일별 패턴"))

dow_table = []
for day in DAYS_KO:
    if day not in dow: continue
    d    = dow[day]
    roas = d["pv"] / d["spend"] if d["spend"] else 0
    cpm  = d["spend"] / d["impr"] * 1000 if d["impr"] else 0
    tag  = " ★" if day == best_day else (" ▼" if day == worst_day else "")
    dow_table.append([
        day + tag,
        f"{d['count']}일",
        f"₩{d['spend']:,.0f}",
        f"{roas:.2f}x",
        f"₩{cpm:,.0f}",
        f"{d['pur']:.0f}건",
    ])

blocks.append(tbl(["요일", "집계일수", "지출합계", "ROAS", "CPM", "구매수"], dow_table))

dow_labels = [d for d in DAYS_KO if d in dow]
dow_roas_v = [round(dow_roas(d), 2) for d in dow_labels]
max_v = max(dow_roas_v) if dow_roas_v else 1
min_v = min(dow_roas_v) if dow_roas_v else 0

blocks.append(qc({
    "type": "bar",
    "data": {"labels": dow_labels,
             "datasets": [{"label": "ROAS",
                           "data": dow_roas_v,
                           "backgroundColor": [
                               "rgba(75,192,75,0.7)" if v == max_v
                               else ("rgba(255,99,132,0.7)" if v == min_v
                               else "rgba(54,162,235,0.6)") for v in dow_roas_v
                           ]}]},
    "options": {"title": {"display": True, "text": "요일별 ROAS (초록=최고, 빨강=최저)"},
                "scales": {"yAxes": [{"ticks": {"beginAtZero": True}}]}}
}))
blocks.append(div())

# ── 회고 인사이트 ──────────────────────────────────────────────────────────────
blocks.append(h2("💡 회고 인사이트"))

trend_dir = "개선 📈" if late_roas > early_roas else "하락 📉"
hit_rate  = len(top_ads) / len(ads) * 100

insight = []
insight.append(f"[성과 추세]  전반부 ROAS {early_roas:.2f}x → 후반부 ROAS {late_roas:.2f}x  ({trend_dir})")
insight.append(f"[소재 효율]  전체 {len(ads)}개 중 ROAS 180%+ {len(top_ads)}개 ({hit_rate:.0f}%) / 전환없음·미달 {len(low_ads)}개")

if best_day:
    insight.append(f"[요일 패턴]  최고 요일 {best_day}요일 (ROAS {dow_roas(best_day):.2f}x)  /  최저 요일 {worst_day}요일 (ROAS {dow_roas(worst_day):.2f}x)")

wd_roas = (sum(dow[d]["pv"] for d in ["월","화","수","목","금"] if d in dow) /
           sum(dow[d]["spend"] for d in ["월","화","수","목","금"] if d in dow)
           if sum(dow[d]["spend"] for d in ["월","화","수","목","금"] if d in dow) else 0)
we_roas = (sum(dow[d]["pv"] for d in ["토","일"] if d in dow) /
           sum(dow[d]["spend"] for d in ["토","일"] if d in dow)
           if sum(dow[d]["spend"] for d in ["토","일"] if d in dow) else 0)
insight.append(f"[평일 vs 주말]  평일 ROAS {wd_roas:.2f}x  vs  주말 ROAS {we_roas:.2f}x")

if top_ads:
    insight.append(f"[이달 베스트]  {top_ads[0]['name']} (ROAS {top_ads[0]['roas']:.2f}x, 지출 ₩{top_ads[0]['spend']:,.0f})")

if low_high_spend:
    insight.append(f"[이달 아쉬운]  {low_high_spend[0]['name']} (지출 ₩{low_high_spend[0]['spend']:,.0f}, {'ROAS ' + str(round(low_high_spend[0]['roas'],2)) + 'x' if low_high_spend[0]['roas'] else '전환없음'})")

blocks.append(co("\n".join(insight), "📌"))
blocks.append(div())

# ── Notion 업로드 ─────────────────────────────────────────────────────────────
print("[4/4] Notion 페이지 생성...")
nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": f"📝 {month_label} KB 소재 월말 회고 ({period})"}}]}},
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

pending = []
for block in blocks:
    if block.get("type") in ("table", "image"):
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
