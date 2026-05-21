import requests, json, datetime, os, time

META_TOKEN    = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = os.environ.get("META_ACCOUNT", "act_3431020723842735")
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"
KEYWORD       = "프로모션"
SPEND_MIN     = 1_000_000
ROAS_MIN      = 2.0

today = datetime.date.today()
since = today - datetime.timedelta(days=180)
until = today - datetime.timedelta(days=1)

FIELDS = ",".join([
    "ad_name", "spend", "impressions", "cpm",
    "outbound_clicks_ctr", "purchase_roas", "actions", "action_values",
])
BASE_URL = f"https://graph.facebook.com/v20.0/{META_ACCOUNT}/insights"

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
print(f"[1/3] Meta Ads 수집 ({since} ~ {until})...")
raw = fetch_all({
    "level": "ad",
    "time_range": json.dumps({"since": str(since), "until": str(until)}),
    "fields": FIELDS,
    "access_token": META_TOKEN,
    "limit": 500,
})
print(f"  -> 전체 {len(raw)}개 소재")

# ── 파싱 + 필터 ───────────────────────────────────────────────────────────────
ads = []
for ad in raw:
    name = ad.get("ad_name", "")
    if KEYWORD not in name:
        continue
    spd  = float(ad.get("spend", 0) or 0)
    if spd < SPEND_MIN:
        continue
    impr = float(ad.get("impressions", 0) or 0)
    obl  = ad.get("outbound_clicks_ctr", [])
    rl   = ad.get("purchase_roas", [])
    avl  = ad.get("action_values", [])
    pv   = ga(avl, "purchase")
    pur  = ga(ad.get("actions", []), "purchase")
    roas = float(rl[0].get("value", 0)) if rl else None

    ads.append({
        "name":    name,
        "spend":   spd,
        "impr":    impr,
        "roas":    roas,
        "ob_ctr":  float(obl[0].get("value", 0)) if obl else 0.0,
        "cpm":     float(ad.get("cpm", 0) or 0),
        "pur":     pur,
        "pv":      pv,
    })

print(f"  -> 프로모션 소재 (₩{SPEND_MIN:,} 이상): {len(ads)}개")
if not ads:
    raise SystemExit("해당 조건의 소재 없음")

# ── 정렬 및 분류 ──────────────────────────────────────────────────────────────
ads_sorted = sorted(ads, key=lambda a: a["roas"] if a["roas"] else -1, reverse=True)
qualified  = [a for a in ads_sorted if a["roas"] and a["roas"] >= ROAS_MIN]

total_spend = sum(a["spend"] for a in ads)
total_pv    = sum(a["pv"] for a in ads)
total_pur   = sum(a["pur"] for a in ads)
blend_roas  = total_pv / total_spend if total_spend else 0

print(f"  -> ROAS {ROAS_MIN*100:.0f}%+ 해당 소재: {len(qualified)}개")

# ── Notion 블록 ───────────────────────────────────────────────────────────────
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

def make_rows(lst):
    return [[a["name"],
             f"₩{a['spend']:,.0f}",
             f"{a['roas']:.2f}x" if a["roas"] else "전환없음",
             f"{a['ob_ctr']:.2f}%",
             f"₩{a['cpm']:,.0f}",
             f"{a['pur']:.0f}건"] for a in lst]

HEADERS = ["소재명", "지출", "ROAS", "OB-CTR", "CPM", "구매수"]
period  = f"{since.strftime('%Y.%m.%d')} ~ {until.strftime('%Y.%m.%d')}"

blocks = [
    h1("🎯 KB 프로모션 소재 — ROAS 200%+ / 지출 100만↑"),
    co(
        f"분석 기간: {period}  |  조건: 지출 ₩1,000,000↑ + ROAS 200%↑  |  "
        f"해당 소재: {len(qualified)}개  |  블렌드 ROAS: {blend_roas:.2f}x  |  총 구매: {total_pur:.0f}건",
        "📌"
    ),
    div(),
]

if qualified:
    blocks.append(h2(f"✅ ROAS 200% 이상 소재 ({len(qualified)}개) — ROAS 높은 순"))
    blocks.append(tbl(HEADERS, make_rows(qualified)))
    blocks.append(div())
else:
    blocks.append({"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":"해당 조건의 소재가 없습니다."}}]}})

# ── Notion 업로드 ─────────────────────────────────────────────────────────────
print("[2/3] Notion 페이지 생성...")
nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": f"🎯 KB 프로모션 소재 성과 리스트 ({period})"}}]}},
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

print("[3/3] 블록 추가...")
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
