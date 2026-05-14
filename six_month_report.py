import requests, json, datetime, os, time

META_TOKEN    = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = "act_3431020723842735"
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"
SPEND_MIN     = 1_000_000

today = datetime.date.today()
since = today - datetime.timedelta(days=180)
until = today - datetime.timedelta(days=1)

FIELDS = ",".join([
    "ad_id","ad_name","impressions","spend","cpm","ctr",
    "outbound_clicks_ctr","cpc","actions","action_values","purchase_roas",
    "video_avg_time_watched_actions","video_play_actions","video_p25_watched_actions",
])

# ── 1. 데이터 수집 ────────────────────────────────────────────────────────────
def api_get(url, params=None, retries=5):
    for attempt in range(retries):
        r = requests.get(url, params=params, timeout=60)
        d = r.json()
        if "error" in d:
            code = d["error"].get("code", 0)
            if code in (4, 17, 32, 613):
                wait = 2 ** (attempt + 3)
                print(f"  -> Rate limit (code {code}), {wait}초 대기 후 재시도...")
                time.sleep(wait)
                continue
            raise SystemExit(f"Meta API 오류: {d['error']['message']}")
        return d
    raise SystemExit("Rate limit 반복 — 나중에 다시 시도해주세요.")

print(f"[1/3] Meta Ads 수집 ({since} ~ {until})...")
ads_raw, nxt = [], None
params = {
    "level": "ad",
    "time_range": json.dumps({"since": str(since), "until": str(until)}),
    "fields": FIELDS, "access_token": META_TOKEN, "limit": 500,
}
url = f"https://graph.facebook.com/v20.0/{META_ACCOUNT}/insights"
while True:
    d = api_get(nxt or url, params=(None if nxt else params))
    ads_raw.extend(d.get("data", []))
    nxt = d.get("paging", {}).get("next")
    if not nxt:
        break
print(f"  -> 전체 {len(ads_raw)}개 소재 수집")

# ── 2. 파싱 + 필터 ────────────────────────────────────────────────────────────
def ga(lst, t):
    for a in (lst or []):
        if a.get("action_type") == t:
            return float(a.get("value", 0))
    return None

def fv(lst):
    return float(lst[0].get("value", 0)) if lst else 0.0

ads = []
for ad in ads_raw:
    name = ad.get("ad_name", "")
    if "KB" not in name:
        continue

    al   = ad.get("actions", [])
    obl  = ad.get("outbound_clicks_ctr", [])
    rl   = ad.get("purchase_roas", [])
    avl  = ad.get("action_values", [])
    pur  = ga(al, "purchase") or 0
    spd  = float(ad.get("spend", 0) or 0)
    impr = float(ad.get("impressions", 0) or 0)
    roas = float(rl[0].get("value", 0)) if rl else None
    plays = fv(ad.get("video_play_actions", [])) or None
    p25   = fv(ad.get("video_p25_watched_actions", [])) or None

    if spd < SPEND_MIN:
        continue

    ads.append({
        "name":      name,
        "spend":     spd,
        "impressions": impr,
        "cpm":       float(ad.get("cpm", 0) or 0),
        "ob_ctr":    float(obl[0].get("value", 0)) if obl else 0.0,
        "cpc":       float(ad.get("cpc", 0) or 0),
        "roas":      roas,
        "pv":        ga(avl, "purchase") or 0,
        "purchases": pur,
        "vavg":      fv(ad.get("video_avg_time_watched_actions", [])) or None,
        "hook_rate": plays / impr * 100 if plays and impr else None,
        "hold_rate": p25 / plays * 100 if p25 and plays else None,
    })

print(f"  -> KB 소재 (₩{SPEND_MIN:,} 이상): {len(ads)}개")

if not ads:
    raise SystemExit("해당 조건의 소재 없음")

# ── 3. 정렬 (ROAS 높은 순, 전환 없는 소재는 맨 뒤) ──────────────────────────
ads_sorted = sorted(ads, key=lambda a: a["roas"] if a["roas"] else -1, reverse=True)

qualified   = [a for a in ads_sorted if a["roas"] and a["roas"] >= 1.8]
rest        = [a for a in ads_sorted if not a["roas"] or a["roas"] < 1.8]

print(f"  -> ROAS 180% 이상: {len(qualified)}개 / 나머지: {len(rest)}개")

# 집계
total_spend = sum(a["spend"] for a in ads)
total_pv    = sum(a["pv"] for a in ads)
total_pur   = sum(a["purchases"] for a in ads)
blend_roas  = total_pv / total_spend if total_spend else 0

# ── Notion 블록 빌더 ──────────────────────────────────────────────────────────
def h1(c):  return {"object":"block","type":"heading_1","heading_1":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h2(c):  return {"object":"block","type":"heading_2","heading_2":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def h3(c):  return {"object":"block","type":"heading_3","heading_3":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def p(c):   return {"object":"block","type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
def blt(c): return {"object":"block","type":"bulleted_list_item","bulleted_list_item":{"rich_text":[{"type":"text","text":{"content":str(c)[:2000]}}]}}
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
            "table":{"table_width":len(headers),"has_column_header":True,"has_row_header":False},
            "children": ch}

# ── 블록 조립 ─────────────────────────────────────────────────────────────────
blocks = []
period = f"{since.strftime('%Y.%m.%d')} ~ {until.strftime('%Y.%m.%d')}"

blocks += [
    h1(f"📋 KB 소재 성과 리스트 — 최근 6개월 지출 100만↑"),
    co(
        f"분석 기간: {period}  |  전체 소재: {len(ads)}개  |  "
        f"합산 지출: ₩{total_spend:,.0f}  |  블렌드 ROAS: {blend_roas:.2f}x  |  "
        f"총 구매: {total_pur:.0f}건  |  ROAS 180% 이상: {len(qualified)}개",
        "📌"
    ),
    div(),
]

# ── ROAS 180% 이상 ────────────────────────────────────────────────────────────
blocks.append(h2(f"✅ ROAS 180% 이상 소재 ({len(qualified)}개)"))
blocks.append(tbl(
    ["#", "소재명", "지출", "ROAS", "OB-CTR", "CPM", "훅률", "홀드율", "구매수"],
    [[str(i),
      a["name"],
      f"₩{a['spend']:,.0f}",
      f"{a['roas']:.2f}x",
      f"{a['ob_ctr']:.2f}%",
      f"₩{a['cpm']:,.0f}",
      f"{a['hook_rate']:.1f}%" if a["hook_rate"] else "N/A",
      f"{a['hold_rate']:.1f}%" if a["hold_rate"] else "N/A",
      f"{a['purchases']:.0f}건"]
     for i, a in enumerate(qualified, 1)]
))
blocks.append(div())

# ── 나머지 소재 (ROAS 180% 미만) ─────────────────────────────────────────────
blocks.append(h2(f"📊 ROAS 180% 미만 소재 ({len(rest)}개)"))
blocks.append(tbl(
    ["#", "소재명", "지출", "ROAS", "OB-CTR", "CPM", "훅률", "홀드율", "구매수"],
    [[str(i),
      a["name"],
      f"₩{a['spend']:,.0f}",
      f"{a['roas']:.2f}x" if a["roas"] else "전환 없음",
      f"{a['ob_ctr']:.2f}%",
      f"₩{a['cpm']:,.0f}",
      f"{a['hook_rate']:.1f}%" if a["hook_rate"] else "N/A",
      f"{a['hold_rate']:.1f}%" if a["hold_rate"] else "N/A",
      f"{a['purchases']:.0f}건"]
     for i, a in enumerate(rest, 1)]
))
blocks.append(div())

# ── Notion 업로드 ─────────────────────────────────────────────────────────────
print("[2/3] Notion 페이지 생성...")
nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": f"📋 KB 소재 성과 리스트 — 최근 6개월 지출 100만↑ ({period})"}}]}},
}).json()

if page.get("object") != "page":
    raise SystemExit(f"페이지 생성 실패: {page}")

page_id = page["id"]
print(f"  -> {page.get('url')}")

print("[3/3] 블록 추가...")

def flush(pid, chunk):
    if not chunk: return
    res = requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children",
                         headers=nh, json={"children": chunk}).json()
    if "error" in res:
        print(f"  -> 실패: {res.get('message')}")
    else:
        print(f"  -> {len(chunk)}개 추가")

def flush_table(pid, table_block):
    # 1단계: 테이블 골격만 생성 (행 제외)
    skeleton = {k: v for k, v in table_block.items() if k != "children"}
    res = requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children",
                         headers=nh, json={"children": [skeleton]}).json()
    results = res.get("results", [])
    if not results or res.get("object") == "error":
        print(f"  -> 테이블 생성 실패: {res.get('message', res)}")
        return
    table_id = results[0]["id"]
    print(f"  -> 테이블 생성 완료 (id: {table_id[:8]}...)")

    # 2단계: 행을 테이블에 추가
    rows = table_block["children"]
    for i in range(0, len(rows), 50):
        chunk = rows[i:i+50]
        row_res = requests.patch(f"https://api.notion.com/v1/blocks/{table_id}/children",
                                 headers=nh, json={"children": chunk}).json()
        if row_res.get("object") == "error":
            print(f"  -> 행 추가 실패: {row_res.get('message')}")
        else:
            print(f"  -> {len(chunk)}개 행 추가")

pending = []
for block in blocks:
    if block.get("type") == "table":
        flush(page_id, pending); pending = []
        flush_table(page_id, block)
    else:
        pending.append(block)
        if len(pending) >= 90:
            flush(page_id, pending); pending = []
flush(page_id, pending)

print(f"\n✅ 완료! {page.get('url')}")
