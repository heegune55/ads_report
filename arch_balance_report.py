import requests, json, datetime, os, time

META_TOKEN    = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = "act_3431020723842735"
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"
KEYWORD       = "아치밸런스"

today = datetime.date.today()
since = today - datetime.timedelta(days=30)
until = today - datetime.timedelta(days=1)

BASE_FIELDS = "ad_name,spend,impressions,outbound_clicks_ctr,actions,action_values"
BASE_URL    = f"https://graph.facebook.com/v20.0/{META_ACCOUNT}/insights"

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

def fetch_all(extra_params):
    rows, nxt = [], None
    params = {
        "level": "ad",
        "time_range": json.dumps({"since": str(since), "until": str(until)}),
        "fields": BASE_FIELDS,
        "access_token": META_TOKEN,
        "limit": 500,
        **extra_params,
    }
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

def parse(row, breakdown_key=None):
    name = row.get("ad_name", "")
    if KEYWORD not in name:
        return None
    spend = float(row.get("spend", 0) or 0)
    impr  = float(row.get("impressions", 0) or 0)
    obl   = row.get("outbound_clicks_ctr", [])
    pv    = ga(row.get("action_values", []), "purchase")
    return {
        "name":   name,
        "spend":  spend,
        "impr":   impr,
        "pv":     pv,
        "ob_ctr": float(obl[0].get("value", 0)) if obl else 0.0,
        "roas":   pv / spend if spend else None,
        "cpm":    spend / impr * 1000 if impr else 0.0,
        "key":    row.get(breakdown_key) if breakdown_key else None,
    }

print(f"[1/4] 소재별 데이터 수집 ({since} ~ {until})...")
raw_ad = [r for r in (parse(x) for x in fetch_all({})) if r]
print(f"  -> {KEYWORD} 소재: {len(raw_ad)}개")

if not raw_ad:
    raise SystemExit("해당 기간 내 아치밸런스 소재 없음")

print("[2/4] 성별 데이터 수집...")
raw_gender = [r for r in (parse(x, "gender") for x in fetch_all({"breakdowns": "gender"})) if r]

print("[3/4] 연령별 데이터 수집...")
raw_age = [r for r in (parse(x, "age") for x in fetch_all({"breakdowns": "age"})) if r]

def aggregate(rows):
    groups = {}
    for r in rows:
        k = r["key"] or "unknown"
        if k not in groups:
            groups[k] = {"spend": 0, "impr": 0, "pv": 0, "w_ctr": 0}
        groups[k]["spend"] += r["spend"]
        groups[k]["impr"]  += r["impr"]
        groups[k]["pv"]    += r["pv"]
        groups[k]["w_ctr"] += r["ob_ctr"] * r["impr"]
    result = []
    for k, g in groups.items():
        result.append({
            "key":    k,
            "spend":  g["spend"],
            "roas":   g["pv"] / g["spend"] if g["spend"] else None,
            "ob_ctr": g["w_ctr"] / g["impr"] if g["impr"] else 0,
            "cpm":    g["spend"] / g["impr"] * 1000 if g["impr"] else 0,
        })
    return sorted(result, key=lambda x: x["spend"], reverse=True)

GENDER_MAP = {"male": "남성", "female": "여성", "unknown": "미확인"}
gender_agg = aggregate(raw_gender)
age_agg    = sorted(aggregate(raw_age), key=lambda x: x["key"])

# ── Notion 블록 빌더 ──────────────────────────────────────────────────────────
def h1(c):  return {"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h2(c):  return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
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

def fmt_row(label, g):
    return [label,
            f"₩{g['spend']:,.0f}",
            f"{g['roas']:.2f}x" if g["roas"] else "전환없음",
            f"{g['ob_ctr']:.2f}%",
            f"₩{g['cpm']:,.0f}"]

period = f"{since.strftime('%Y.%m.%d')} ~ {until.strftime('%Y.%m.%d')}"
total_spend = sum(a["spend"] for a in raw_ad)
total_pv    = sum(a["pv"] for a in raw_ad)
blend_roas  = total_pv / total_spend if total_spend else 0

blocks = [
    h1("🏋 아치밸런스 소재 분석"),
    co(f"분석 기간: {period}  |  소재: {len(raw_ad)}개  |  합산 지출: ₩{total_spend:,.0f}  |  블렌드 ROAS: {blend_roas:.2f}x", "📌"),
    div(),
    h2("📋 소재별 성과"),
    tbl(
        ["소재명", "지출", "ROAS", "OB-CTR", "CPM"],
        [[a["name"], f"₩{a['spend']:,.0f}",
          f"{a['roas']:.2f}x" if a["roas"] else "전환없음",
          f"{a['ob_ctr']:.2f}%", f"₩{a['cpm']:,.0f}"]
         for a in sorted(raw_ad, key=lambda x: x["spend"], reverse=True)]
    ),
    div(),
    h2("👥 성별 성과"),
    tbl(
        ["성별", "지출", "ROAS", "OB-CTR", "CPM"],
        [fmt_row(GENDER_MAP.get(g["key"], g["key"]), g) for g in gender_agg]
    ),
    div(),
    h2("📊 연령별 성과"),
    tbl(
        ["연령대", "지출", "ROAS", "OB-CTR", "CPM"],
        [fmt_row(g["key"], g) for g in age_agg]
    ),
    div(),
]

# ── Notion 업로드 ─────────────────────────────────────────────────────────────
print("[4/4] Notion 페이지 생성...")
nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": f"🏋 아치밸런스 소재 분석 ({period})"}}]}},
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
