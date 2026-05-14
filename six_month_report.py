import requests, json, datetime, os

META_TOKEN    = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = "act_3431020723842735"
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"
SPEND_MIN     = 10_000

today = datetime.date.today()
since = today - datetime.timedelta(days=180)
until = today - datetime.timedelta(days=1)

FIELDS = ",".join([
    "ad_id","ad_name","impressions","spend","cpm","ctr",
    "outbound_clicks_ctr","cpc","actions","action_values","purchase_roas",
    "video_avg_time_watched_actions","video_play_actions","video_p25_watched_actions",
])

# ── 1. 데이터 수집 ────────────────────────────────────────────────────────────
print(f"[1/3] Meta Ads 수집 ({since} ~ {until})...")
ads_raw, nxt = [], None
params = {
    "level": "ad",
    "time_range": json.dumps({"since": str(since), "until": str(until)}),
    "fields": FIELDS, "access_token": META_TOKEN, "limit": 500,
}
url = f"https://graph.facebook.com/v20.0/{META_ACCOUNT}/insights"
while True:
    r = requests.get(nxt or url, params=(None if nxt else params))
    d = r.json()
    if "error" in d:
        raise SystemExit(f"Meta API 오류: {d['error']['message']}")
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
    if "아치스본 스포츠" not in name and "아치스포츠" not in name:
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

print(f"  -> 아치스포츠 소재 (₩{SPEND_MIN:,} 이상): {len(ads)}개")

if not ads:
    raise SystemExit("해당 조건의 소재 없음")

# ── 3. 정렬 (ROAS + OB-CTR 종합 점수) ────────────────────────────────────────
def score(a):
    return (a["roas"] or 0) * 10 + a["ob_ctr"]

ads_sorted = sorted(ads, key=score, reverse=True)

# 집계
total_spend = sum(a["spend"] for a in ads)
total_pv    = sum(a["pv"] for a in ads)
total_pur   = sum(a["purchases"] for a in ads)
blend_roas  = total_pv / total_spend if total_spend else 0
roas_ads    = [a for a in ads if a["roas"] and a["roas"] >= 1.0]

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
    h1(f"🏅 아치스포츠 소재 성과 리스트 — 최근 6개월"),
    co(
        f"분석 기간: {period}  |  소재 수: {len(ads)}개  |  "
        f"총 지출: ₩{total_spend:,.0f}  |  블렌드 ROAS: {blend_roas:.2f}x  |  "
        f"총 구매: {total_pur:.0f}건  |  ROAS 1x 이상 소재: {len(roas_ads)}개",
        "📌"
    ),
    div(),
]

# ── ROAS 1x 이상 (수익 구간) ─────────────────────────────────────────────────
good = [a for a in ads_sorted if a["roas"] and a["roas"] >= 1.0]
if good:
    blocks.append(h2("✅ ROAS 1x 이상 소재 (수익 구간)"))
    blocks.append(tbl(
        ["#", "소재명", "지출", "ROAS", "OB-CTR", "CPM", "훅률", "홀드율", "구매수"],
        [[str(i),
          a["name"][:40],
          f"₩{a['spend']:,.0f}",
          f"{a['roas']:.2f}x",
          f"{a['ob_ctr']:.2f}%",
          f"₩{a['cpm']:,.0f}",
          f"{a['hook_rate']:.1f}%" if a["hook_rate"] else "N/A",
          f"{a['hold_rate']:.1f}%" if a["hold_rate"] else "N/A",
          f"{a['purchases']:.0f}건"]
         for i, a in enumerate(good, 1)]
    ))

    # 베스트 소재 코멘트
    best = good[0]
    blocks.append(co(
        f"최고 성과: {best['name'][:45]}\n"
        f"ROAS {best['roas']:.2f}x / OB-CTR {best['ob_ctr']:.2f}% / 지출 ₩{best['spend']:,.0f} / 구매 {best['purchases']:.0f}건\n"
        f"→ 이 소재의 훅·메시지 구조를 신규 소재 제작 시 레퍼런스로 활용 권장",
        "🥇"
    ))
    blocks.append(div())

# ── ROAS 없거나 1x 미만 (참고용) ─────────────────────────────────────────────
rest = [a for a in ads_sorted if not a["roas"] or a["roas"] < 1.0]
if rest:
    blocks.append(h2("⚠️ ROAS 1x 미만 또는 전환 미발생 소재 (참고용)"))
    blocks.append(tbl(
        ["#", "소재명", "지출", "ROAS", "OB-CTR", "CPM", "훅률", "홀드율", "구매수"],
        [[str(i),
          a["name"][:40],
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

# ── 인사이트 요약 ─────────────────────────────────────────────────────────────
blocks.append(h2("💡 인사이트 요약"))

if good:
    avg_roas_good = sum(a["roas"] for a in good) / len(good)
    avg_ob_ctr_good = sum(a["ob_ctr"] for a in good) / len(good)
    blocks.append(blt(f"수익 소재 {len(good)}개 평균 ROAS {avg_roas_good:.2f}x, 평균 OB-CTR {avg_ob_ctr_good:.2f}%"))

if len(good) > 0 and len(rest) > 0:
    ratio = len(good) / len(ads) * 100
    blocks.append(blt(f"전체 소재 중 수익 달성 비율 {ratio:.0f}% ({len(good)}/{len(ads)}개)"))

hook_ads = [a for a in ads if a["hook_rate"] and a["hook_rate"] >= 8]
if hook_ads:
    blocks.append(blt(f"훅률 8% 이상 우수 소재 {len(hook_ads)}개 — 도입부 소구력 검증 완료"))

hold_ads = [a for a in ads if a["hold_rate"] and a["hold_rate"] >= 60]
if hold_ads:
    blocks.append(blt(f"홀드율 60% 이상 우수 소재 {len(hold_ads)}개 — 영상 몰입도 우수"))

# ── Notion 업로드 ─────────────────────────────────────────────────────────────
print("[2/3] Notion 페이지 생성...")
nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": f"🏅 아치스포츠 소재 성과 리스트 — 최근 6개월 ({period})"}}]}},
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

pending = []
for block in blocks:
    if block.get("type") == "table":
        flush(page_id, pending); pending = []
        flush(page_id, [block])
    else:
        pending.append(block)
        if len(pending) >= 90:
            flush(page_id, pending); pending = []
flush(page_id, pending)

print(f"\n✅ 완료! {page.get('url')}")
