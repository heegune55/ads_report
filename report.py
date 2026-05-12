import requests, json, datetime, os
import anthropic

META_TOKEN = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT = "act_3431020723842735"
NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

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
    al = ad.get("actions", [])
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

# ── 3. Claude API로 분석 생성 ─────────────────────────────────────────────────
print("[2/3] Claude API로 분석 생성...")
client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

prompt = f"""{yesterday} 기준 Meta 광고 소재(Ad) 레벨 성과 데이터입니다.

전체 소재:
{json.dumps([{"name":a["name"],"spend":a["spend"],"cpm":a["cpm"],"ob_ctr":a["ob_ctr"],"roas":a["roas"],"v3s":a["v3s"],"cvr":a["cvr"]} for a in parsed], ensure_ascii=False)}

상위 5개 소재:
{json.dumps([{"name":a["name"],"cpm":a["cpm"],"ob_ctr":a["ob_ctr"],"roas":a["roas"],"v3s":a["v3s"]} for a in top5], ensure_ascii=False)}

하위 5개 소재:
{json.dumps([{"name":a["name"],"cpm":a["cpm"],"ob_ctr":a["ob_ctr"],"roas":a["roas"],"v3s":a["v3s"]} for a in bot5], ensure_ascii=False)}

아래 형식 그대로 작성하세요. 구체적인 수치를 근거로 사용하세요.

[회고]
소재 전반 성과 패턴과 인사이트를 3~5문장으로 서술.

[To-Do]
- 즉시 조치 항목 (하위 소재 중단, 예산 재배분 등)

[Next Action]
- 중장기 소재 전략 액션 아이템
"""

msg = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": prompt}],
)
analysis = msg.content[0].text

retro, todo, next_act, cur = [], [], [], None
for line in analysis.split("\n"):
    if "[회고]" in line:         cur = "retro"
    elif "[To-Do]" in line:     cur = "todo"
    elif "[Next Action]" in line: cur = "next"
    elif cur == "retro" and line.strip(): retro.append(line.strip())
    elif cur == "todo"  and line.strip(): todo.append(line.strip().lstrip("-• "))
    elif cur == "next"  and line.strip(): next_act.append(line.strip().lstrip("-• "))

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
for line in retro: blocks.append(p(line))

blocks.append(h2("✅ To-Do"))
for line in todo: blocks.append(blt(line))

blocks.append(h2("🚀 Next Action"))
for line in next_act: blocks.append(blt(line))

# ── 5. Notion 페이지 생성 ─────────────────────────────────────────────────────
print("[3/3] Notion 페이지 생성...")
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
    res = requests.patch(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        headers=nh, json={"children": blocks[i:i+90]}
    ).json()
    if "error" in res:
        print(f"  -> 블록 추가 실패 (chunk {i}): {res}")
    else:
        print(f"  -> 블록 {i}~{i+len(blocks[i:i+90])} 추가 완료")

print(f"\n✅ 완료! {page.get('url')}")
