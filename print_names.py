import requests, json, datetime, os, time

META_TOKEN   = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = os.environ.get("META_ACCOUNT", "act_3431020723842735")
SPEND_MIN    = 0

since = datetime.date(2026, 5, 1)
until = datetime.date(2026, 5, 27)

FIELDS = "ad_name,spend"

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

names = sorted(set(
    r["ad_name"] for r in ads_raw
    if "KB" in r.get("ad_name", "") and float(r.get("spend", 0) or 0) > 0
))

print(f"\nKB 소재명 전체 ({len(names)}개):")
print("=" * 80)
for n in names:
    print(n)
print("=" * 80)
