import requests, json, datetime, os, time

META_TOKEN   = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = os.environ.get("META_ACCOUNT", "act_3431020723842735")
SPEND_MIN    = 1_000_000

today = datetime.date.today()
since = today - datetime.timedelta(days=180)
until = today - datetime.timedelta(days=1)

FIELDS = "ad_name,spend,purchase_roas"

def api_get(url, params=None, retries=5):
    for attempt in range(retries):
        r = requests.get(url, params=params, timeout=60)
        d = r.json()
        if "error" in d:
            code = d["error"].get("code", 0)
            if code in (4, 17, 32, 613):
                wait = 2 ** (attempt + 3)
                time.sleep(wait)
                continue
            raise SystemExit(f"Meta API 오류: {d['error']['message']}")
        return d
    raise SystemExit("Rate limit 반복 실패")

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

ads = []
for ad in ads_raw:
    name = ad.get("ad_name", "")
    if "KB" not in name:
        continue
    spd  = float(ad.get("spend", 0) or 0)
    if spd < SPEND_MIN:
        continue
    rl   = ad.get("purchase_roas", [])
    roas = float(rl[0].get("value", 0)) if rl else None
    ads.append({"name": name, "spend": spd, "roas": roas})

ads_sorted = sorted(ads, key=lambda a: a["roas"] if a["roas"] else -1, reverse=True)

print(f"\n{'='*80}")
print(f"KB 소재 (지출 ₩100만↑) 전체 {len(ads_sorted)}개 — ROAS 높은 순")
print(f"{'='*80}")
for i, a in enumerate(ads_sorted, 1):
    roas_str = f"ROAS {a['roas']:.2f}x" if a["roas"] else "전환없음"
    marker = " ★" if a["roas"] and a["roas"] >= 1.8 else ""
    print(f"{i:2d}. [{roas_str}] ₩{a['spend']:>12,.0f}  |  {a['name']}{marker}")
print(f"{'='*80}")
print(f"★ = ROAS 180% 이상")
