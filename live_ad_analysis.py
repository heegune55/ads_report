import requests, json, datetime, os, time, urllib.parse
from collections import defaultdict

META_TOKEN    = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = os.environ.get("META_ACCOUNT", "act_607986688972375")
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"

SINCE = "2026-05-01"
UNTIL = "2026-05-20"

FIELDS   = "ad_id,ad_name,spend,impressions,outbound_clicks_ctr,outbound_clicks,actions,action_values,cpm"
BASE_URL = f"https://graph.facebook.com/v20.0/{META_ACCOUNT}/insights"
DAYS_KO  = ["월", "화", "수", "목", "금", "토", "일"]
GENDER_MAP = {"male": "남성", "female": "여성", "unknown": "미확인"}

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

def zero():
    return {"spend": 0.0, "impr": 0.0, "pv": 0.0, "pur": 0.0, "clicks": 0.0, "w_ctr": 0.0}

def parse_row(row):
    spend  = float(row.get("spend", 0) or 0)
    impr   = float(row.get("impressions", 0) or 0)
    obl    = row.get("outbound_clicks_ctr", [])
    ctr    = float(obl[0].get("value", 0)) if obl else 0.0
    return {
        "spend":  spend,
        "impr":   impr,
        "pv":     ga(row.get("action_values", []), "purchase"),
        "pur":    ga(row.get("actions", []), "purchase"),
        "clicks": ga(row.get("outbound_clicks", []), "outbound_click"),
        "w_ctr":  ctr * impr,
    }

def accum(dest, p):
    for k in dest:
        dest[k] += p.get(k, 0)

def calc(d):
    spend, impr, pv, pur, clicks, w_ctr = (
        d["spend"], d["impr"], d["pv"], d["pur"], d["clicks"], d["w_ctr"]
    )
    return {
        "spend":  spend,
        "roas":   pv / spend if spend else None,
        "ob_ctr": w_ctr / impr if impr else 0,
        "cpm":    spend / impr * 1000 if impr else 0,
        "cvr":    pur / clicks * 100 if clicks else None,
        "pur":    pur,
    }

# ── 1. 지출 상위 2개 소재 식별 ────────────────────────────────────────────────
print(f"[1/5] 지출 상위 소재 식별 ({SINCE} ~ {UNTIL})...")
total_rows = fetch_all({
    "level": "ad",
    "time_range": json.dumps({"since": SINCE, "until": UNTIL}),
    "fields": "ad_id,ad_name,spend",
    "access_token": META_TOKEN,
    "limit": 500,
})
total_rows.sort(key=lambda x: float(x.get("spend", 0) or 0), reverse=True)
top2       = total_rows[:2]
top2_ids   = [a["ad_id"] for a in top2]
top2_names = {a["ad_id"]: a["ad_name"] for a in top2}

print(f"  -> 상위 2개:")
for a in top2:
    print(f"     ₩{float(a.get('spend',0)):,.0f} | {a['ad_name']}")

fil = json.dumps([{"field": "ad.id", "operator": "IN", "value": top2_ids}])
tr  = json.dumps({"since": SINCE, "until": UNTIL})
base_params = {"level": "ad", "time_range": tr, "fields": FIELDS,
               "filtering": fil, "access_token": META_TOKEN, "limit": 500}

# ── 2. 일자별 데이터 ───────────────────────────────────────────────────────────
print("[2/5] 일자별 데이터 수집...")
raw_daily = fetch_all({**base_params, "time_increment": "1"})

# ── 3. 성별 breakdown ──────────────────────────────────────────────────────────
print("[3/5] 성별 데이터 수집...")
raw_gender = fetch_all({**base_params, "breakdowns": "gender"})

# ── 4. 연령별 breakdown ────────────────────────────────────────────────────────
print("[4/5] 연령별 데이터 수집...")
raw_age = fetch_all({**base_params, "breakdowns": "age"})

# ── 파싱 ──────────────────────────────────────────────────────────────────────

# 일자별 합산 + 소재별 일별 ROAS (차트용)
daily      = defaultdict(zero)
ad_daily   = {aid: {} for aid in top2_ids}
ad_summary = {aid: zero() for aid in top2_ids}

for row in raw_daily:
    date = row.get("date_start", "")
    aid  = row.get("ad_id", "")
    p    = parse_row(row)
    accum(daily[date], p)
    if aid in ad_summary:
        accum(ad_summary[aid], p)
        ad_daily[aid][date] = p["pv"] / p["spend"] if p["spend"] else 0

# 성별
gender = defaultdict(zero)
for row in raw_gender:
    accum(gender[row.get("gender", "unknown")], parse_row(row))

# 연령별
age = defaultdict(zero)
for row in raw_age:
    accum(age[row.get("age", "unknown")], parse_row(row))

# 요일별
dow = defaultdict(lambda: {**zero(), "count": 0})
for date in sorted(daily.keys()):
    day = DAYS_KO[datetime.date.fromisoformat(date).weekday()]
    for k in ["spend", "impr", "pv", "pur", "clicks", "w_ctr"]:
        dow[day][k] += daily[date][k]
    dow[day]["count"] += 1

# ── 요일 패턴 분석 ────────────────────────────────────────────────────────────
dates_sorted = sorted(daily.keys())
dow_m = {d: calc(dow[d]) for d in dow}

days_roas = [(d, m["roas"]) for d, m in dow_m.items() if m["roas"]]
best_day  = max(days_roas, key=lambda x: x[1])[0] if days_roas else None
worst_day = min(days_roas, key=lambda x: x[1])[0] if days_roas else None

def group_roas(day_list):
    pv = sum(dow[d]["pv"] for d in day_list if d in dow)
    sp = sum(dow[d]["spend"] for d in day_list if d in dow)
    return pv / sp if sp else 0

wd_roas  = group_roas(["월","화","수","목","금"])
we_roas  = group_roas(["토","일"])

# 추세: 전반부(1~10일) vs 후반부(11~20일)
half = len(dates_sorted) // 2
first_half  = dates_sorted[:half]
second_half = dates_sorted[half:]

def period_roas(ds):
    pv = sum(daily[d]["pv"] for d in ds)
    sp = sum(daily[d]["spend"] for d in ds)
    return pv / sp if sp else 0

trend_early = period_roas(first_half)
trend_late  = period_roas(second_half)

# ── Notion 블록 헬퍼 ──────────────────────────────────────────────────────────
def h1(c):  return {"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h2(c):  return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
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

def fmt_m(label, m):
    return [
        label,
        f"₩{m['spend']:,.0f}",
        f"{m['roas']:.2f}x" if m["roas"] else "전환없음",
        f"{m['ob_ctr']:.2f}%",
        f"₩{m['cpm']:,.0f}",
        f"{m['cvr']:.1f}%" if m["cvr"] else "N/A",
        f"{m['pur']:.0f}건",
    ]

# ── 블록 조립 ─────────────────────────────────────────────────────────────────
total_spend = sum(daily[d]["spend"] for d in dates_sorted)
total_pv    = sum(daily[d]["pv"] for d in dates_sorted)
total_pur   = sum(daily[d]["pur"] for d in dates_sorted)
blend_roas  = total_pv / total_spend if total_spend else 0
period      = "2026.05.01 ~ 2026.05.20"

blocks = [
    h1("📊 Baruner3 라이브 소재 분석"),
    co(
        f"분석 기간: {period}  |  분석 소재: {len(top2)}개  |  "
        f"합산 지출: ₩{total_spend:,.0f}  |  블렌드 ROAS: {blend_roas:.2f}x  |  총 구매: {total_pur:.0f}건",
        "📌"
    ),
    div(),
]

# ── 소재별 요약 ───────────────────────────────────────────────────────────────
blocks.append(h2("📋 소재별 성과 요약"))
blocks.append(tbl(
    ["소재명", "지출", "ROAS", "OB-CTR", "CPM", "CVR", "구매수"],
    [fmt_m(top2_names[aid], calc(ad_summary[aid])) for aid in top2_ids]
))
blocks.append(div())

# ── 일자별 성과 ───────────────────────────────────────────────────────────────
blocks.append(h2("📅 일자별 성과"))

daily_rows = []
for date in dates_sorted:
    m   = calc(daily[date])
    dt  = datetime.date.fromisoformat(date)
    dow_label = DAYS_KO[dt.weekday()]
    daily_rows.append([
        date[5:].replace("-", "/"),
        dow_label,
        f"₩{m['spend']:,.0f}",
        f"{m['roas']:.2f}x" if m["roas"] else "전환없음",
        f"{m['ob_ctr']:.2f}%",
        f"₩{m['cpm']:,.0f}",
        f"{m['cvr']:.1f}%" if m["cvr"] else "N/A",
        f"{m['pur']:.0f}건",
    ])

blocks.append(tbl(
    ["날짜", "요일", "지출", "ROAS", "OB-CTR", "CPM", "CVR", "구매수"],
    daily_rows
))

# 차트 1: 일별 ROAS 라인 차트 (소재별 2개 선)
date_labels = [d[5:].replace("-", "/") for d in dates_sorted]
colors = ["rgb(75,192,192)", "rgb(255,99,132)"]
datasets = []
for i, aid in enumerate(top2_ids):
    datasets.append({
        "label": top2_names[aid][:25],
        "data":  [round(ad_daily[aid].get(d, 0), 2) for d in dates_sorted],
        "borderColor": colors[i],
        "backgroundColor": colors[i].replace("rgb(", "rgba(").replace(")", ",0.08)"),
        "tension": 0.2, "fill": False,
    })

blocks.append(qc({
    "type": "line",
    "data": {"labels": date_labels, "datasets": datasets},
    "options": {
        "title": {"display": True, "text": "일별 ROAS 추이 (소재별)"},
        "scales": {"yAxes": [{"ticks": {"beginAtZero": True}}]}
    }
}))

# 차트 2: 일별 지출 바 차트
blocks.append(qc({
    "type": "bar",
    "data": {
        "labels": date_labels,
        "datasets": [{"label": "일별 지출 (만원)",
                      "data": [round(daily[d]["spend"] / 10000, 1) for d in dates_sorted],
                      "backgroundColor": "rgba(54,162,235,0.6)"}]
    },
    "options": {
        "title": {"display": True, "text": "일별 지출 (만원)"},
        "scales": {"yAxes": [{"ticks": {"beginAtZero": True}}]}
    }
}))
blocks.append(div())

# ── 요일별 패턴 ───────────────────────────────────────────────────────────────
blocks.append(h2("📆 요일별 패턴 분석"))

dow_table = []
for day in DAYS_KO:
    if day not in dow:
        continue
    m   = dow_m[day]
    cnt = dow[day]["count"]
    tag = " ★" if day == best_day else (" ▼" if day == worst_day else "")
    dow_table.append([
        day + tag,
        f"{cnt}일",
        f"₩{m['spend']:,.0f}",
        f"{m['roas']:.2f}x" if m["roas"] else "전환없음",
        f"₩{m['cpm']:,.0f}",
        f"{m['pur']:.0f}건",
    ])

blocks.append(tbl(
    ["요일", "집계일수", "지출합계", "ROAS", "CPM", "구매수"],
    dow_table
))

# 차트 3: 요일별 ROAS 바 차트
dow_labels = [d for d in DAYS_KO if d in dow_m]
dow_roas_v = [round(dow_m[d]["roas"], 2) if dow_m[d]["roas"] else 0 for d in dow_labels]
max_v = max(dow_roas_v) if dow_roas_v else 1
min_v = min(dow_roas_v) if dow_roas_v else 0

blocks.append(qc({
    "type": "bar",
    "data": {
        "labels": dow_labels,
        "datasets": [{"label": "ROAS",
                      "data": dow_roas_v,
                      "backgroundColor": [
                          "rgba(75,192,75,0.7)" if v == max_v
                          else ("rgba(255,99,132,0.7)" if v == min_v
                          else "rgba(54,162,235,0.6)") for v in dow_roas_v
                      ]}]
    },
    "options": {
        "title": {"display": True, "text": "요일별 ROAS (초록=최고, 빨강=최저)"},
        "scales": {"yAxes": [{"ticks": {"beginAtZero": True}}]}
    }
}))

# 패턴 인사이트
trend_dir = "개선 추세 📈" if trend_late > trend_early else "하락 추세 📉"
insight_lines = []
if best_day:
    insight_lines.append(f"★ 최고 성과 요일: {best_day}요일 (ROAS {dow_m[best_day]['roas']:.2f}x)")
if worst_day:
    insight_lines.append(f"▼ 최저 성과 요일: {worst_day}요일 (ROAS {dow_m[worst_day]['roas']:.2f}x)")
insight_lines.append(f"평일 ROAS {wd_roas:.2f}x  vs  주말 ROAS {we_roas:.2f}x")
insight_lines.append(f"전반부(1~{half}일) ROAS {trend_early:.2f}x → 후반부({half+1}~{len(dates_sorted)}일) ROAS {trend_late:.2f}x  ({trend_dir})")

blocks.append(co("\n".join(insight_lines), "📌"))
blocks.append(div())

# ── 성별 분석 ─────────────────────────────────────────────────────────────────
blocks.append(h2("👥 성별 성과"))
gender_sorted = sorted(gender.items(), key=lambda x: x[1]["spend"], reverse=True)
blocks.append(tbl(
    ["성별", "지출", "ROAS", "OB-CTR", "CPM", "CVR", "구매수"],
    [fmt_m(GENDER_MAP.get(g, g), calc(d)) for g, d in gender_sorted]
))

g_labels = [GENDER_MAP.get(g, g) for g, _ in gender_sorted]
g_spend  = [round(d["spend"] / 10000, 1) for _, d in gender_sorted]
g_roas   = [round(calc(d)["roas"], 2) if calc(d)["roas"] else 0 for _, d in gender_sorted]

blocks.append(qc({
    "type": "bar",
    "data": {
        "labels": g_labels,
        "datasets": [
            {"label": "지출 (만원)", "data": g_spend, "backgroundColor": "rgba(54,162,235,0.6)", "yAxisID": "A"},
            {"label": "ROAS",        "data": g_roas,  "backgroundColor": "rgba(255,99,132,0.6)", "yAxisID": "B"},
        ]
    },
    "options": {
        "title": {"display": True, "text": "성별 지출 & ROAS"},
        "scales": {
            "yAxes": [
                {"id": "A", "position": "left",  "scaleLabel": {"display": True, "labelString": "지출(만원)"}, "ticks": {"beginAtZero": True}},
                {"id": "B", "position": "right", "scaleLabel": {"display": True, "labelString": "ROAS"},       "ticks": {"beginAtZero": True}},
            ]
        }
    }
}))
blocks.append(div())

# ── 연령별 분석 ───────────────────────────────────────────────────────────────
blocks.append(h2("📊 연령별 성과"))
age_sorted = sorted(age.items(), key=lambda x: x[0])
blocks.append(tbl(
    ["연령대", "지출", "ROAS", "OB-CTR", "CPM", "CVR", "구매수"],
    [fmt_m(a, calc(d)) for a, d in age_sorted]
))

a_labels = [a for a, _ in age_sorted]
a_spend  = [round(d["spend"] / 10000, 1) for _, d in age_sorted]
a_roas   = [round(calc(d)["roas"], 2) if calc(d)["roas"] else 0 for _, d in age_sorted]

blocks.append(qc({
    "type": "bar",
    "data": {
        "labels": a_labels,
        "datasets": [
            {"label": "지출 (만원)", "data": a_spend, "backgroundColor": "rgba(54,162,235,0.6)", "yAxisID": "A"},
            {"label": "ROAS",        "data": a_roas,  "backgroundColor": "rgba(255,99,132,0.6)", "yAxisID": "B"},
        ]
    },
    "options": {
        "title": {"display": True, "text": "연령별 지출 & ROAS"},
        "scales": {
            "yAxes": [
                {"id": "A", "position": "left",  "ticks": {"beginAtZero": True}},
                {"id": "B", "position": "right", "ticks": {"beginAtZero": True}},
            ]
        }
    }
}))
blocks.append(div())

# ── Notion 업로드 ─────────────────────────────────────────────────────────────
print("[5/5] Notion 페이지 생성...")
nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": f"📊 Baruner3 라이브 소재 분석 ({period})"}}]}},
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
