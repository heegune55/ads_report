import requests, json, datetime, os
from collections import Counter

META_TOKEN    = os.environ["META_ACCESS_TOKEN"]
META_ACCOUNT  = "act_3431020723842735"
NOTION_TOKEN  = os.environ["NOTION_TOKEN"]
NOTION_PARENT = "12fb99f5082080e5a78ac8591f0fbae4"
SPEND_MIN     = 10_000

# ── 날짜: 이번 주 월~어제 vs 전주 같은 기간 ──────────────────────────────────
today     = datetime.date.today()
yesterday = today - datetime.timedelta(days=1)

if today.weekday() == 0:          # 오늘이 월요일 → 지난 주 전체(월~일)
    curr_end   = yesterday
    curr_start = curr_end - datetime.timedelta(days=6)
else:
    curr_end   = yesterday
    curr_start = yesterday - datetime.timedelta(days=yesterday.weekday())

prev_start = curr_start - datetime.timedelta(days=7)
prev_end   = curr_end   - datetime.timedelta(days=7)

CW = f"{curr_start.strftime('%m/%d')}~{curr_end.strftime('%m/%d')}"
PW = f"{prev_start.strftime('%m/%d')}~{prev_end.strftime('%m/%d')}"

# ── Meta API 필드 ─────────────────────────────────────────────────────────────
FIELDS = ",".join([
    "ad_id","ad_name","impressions","reach","frequency",
    "spend","cpm","ctr","outbound_clicks_ctr","cpc",
    "actions","action_values","purchase_roas","post_engagement",
    "video_avg_time_watched_actions",
])

def fetch(d_since, d_until):
    ads, nxt = [], None
    params = {
        "level": "ad",
        "time_range": json.dumps({"since": str(d_since), "until": str(d_until)}),
        "fields": FIELDS, "access_token": META_TOKEN, "limit": 100,
    }
    url = f"https://graph.facebook.com/v20.0/{META_ACCOUNT}/insights"
    while True:
        r = requests.get(nxt or url, params=(None if nxt else params))
        d = r.json()
        if "error" in d:
            raise SystemExit(f"Meta API 오류: {d['error']['message']}")
        ads.extend(d.get("data", []))
        nxt = d.get("paging", {}).get("next")
        if not nxt:
            break
    return ads

print(f"[1/3] 데이터 수집 ({CW} vs {PW})...")
curr_raw = fetch(curr_start, curr_end)
prev_raw = fetch(prev_start, prev_end)
print(f"  현재 {len(curr_raw)}개 | 이전 {len(prev_raw)}개")

# ── 파싱 ─────────────────────────────────────────────────────────────────────
def ga(lst, t):
    for a in (lst or []):
        if a.get("action_type") == t:
            return float(a.get("value", 0))
    return None

def fv(lst):
    return float(lst[0].get("value", 0)) if lst else 0.0

def parse(ad):
    al   = ad.get("actions", [])
    obl  = ad.get("outbound_clicks_ctr", [])
    rl   = ad.get("purchase_roas", [])
    avl  = ad.get("action_values", [])
    pur  = ga(al, "purchase") or 0
    spd  = float(ad.get("spend", 0) or 0)
    vavg_raw = fv(ad.get("video_avg_time_watched_actions", []))
    vavg = vavg_raw if vavg_raw > 0 else None
    return {
        "name":       ad.get("ad_name", ""),
        "impressions":float(ad.get("impressions", 0) or 0),
        "reach":      float(ad.get("reach", 0) or 0),
        "frequency":  float(ad.get("frequency", 0) or 0),
        "spend":      spd,
        "cpm":        float(ad.get("cpm", 0) or 0),
        "ctr":        float(ad.get("ctr", 0) or 0),
        "ob_ctr":     float(obl[0].get("value", 0)) if obl else 0.0,
        "roas":       float(rl[0].get("value", 0)) if rl else None,
        "pv":         ga(avl, "purchase"),
        "purchases":  pur,
        "cpa":        spd / pur if pur > 0 else None,
        "vavg":       vavg,
        "is_video":   vavg is not None,
    }

curr = [a for a in (parse(r) for r in curr_raw) if a["spend"] >= SPEND_MIN]
prev = [a for a in (parse(r) for r in prev_raw) if a["spend"] >= SPEND_MIN]

# ── 집계 ─────────────────────────────────────────────────────────────────────
def agg(ads):
    if not ads:
        return dict(n=0, spend=0, pv=0, purchases=0, blend_roas=0,
                    cpa=None, avg_ob_ctr=0, avg_cpm=0, avg_vavg=None, n_fatigue=0)
    spd  = sum(a["spend"] for a in ads)
    pv   = sum(a["pv"] for a in ads if a["pv"])
    pur  = sum(a["purchases"] for a in ads)
    vid  = [a for a in ads if a["is_video"]]
    vavg_l = [a["vavg"] for a in vid if a["vavg"] is not None]
    return {
        "n":           len(ads),
        "spend":       spd,
        "pv":          pv,
        "purchases":   pur,
        "blend_roas":  pv / spd if spd else 0,
        "cpa":         spd / pur if pur else None,
        "avg_ob_ctr":  sum(a["ob_ctr"] for a in ads) / len(ads),
        "avg_cpm":     sum(a["cpm"] for a in ads) / len(ads),
        "avg_vavg":    sum(vavg_l) / len(vavg_l) if vavg_l else None,
        "n_fatigue":   sum(1 for a in ads if a["frequency"] >= 3),
    }

C = agg(curr)
P = agg(prev)

def chg(cv, pv, hi=True):
    if not cv or not pv: return "–"
    d = (cv - pv) / pv * 100
    arrow = "▲" if d > 0 else "▼"
    sign  = "+" if d > 0 else ""
    return f"{arrow}{sign}{d:.1f}%"

# ── 포맷별 집계 ───────────────────────────────────────────────────────────────
def pname(name):
    p = name.split("_")
    return (p[1] if len(p) > 1 else "기타", p[2] if len(p) > 2 else "기타")

fmt_map = {}
for a in curr:
    _, fmt = pname(a["name"])
    fmt_map.setdefault(fmt, []).append(a)

def fagg(lst):
    if not lst: return None
    spd = sum(a["spend"] for a in lst)
    pv  = sum(a["pv"] for a in lst if a["pv"])
    pur = sum(a["purchases"] for a in lst)
    return {
        "n": len(lst), "spend": spd,
        "blend_roas": pv / spd if spd else 0,
        "avg_ob_ctr": sum(a["ob_ctr"] for a in lst) / len(lst),
        "avg_cpm":    sum(a["cpm"] for a in lst) / len(lst),
        "purchases":  pur,
    }

fmt_stats  = {f: fagg(v) for f, v in fmt_map.items()}
fmt_sorted = sorted(fmt_stats.items(), key=lambda x: x[1]["blend_roas"], reverse=True)

# ── 동영상 훅 분석 (평균 시청 시간 기준) ──────────────────────────────────────
vid_curr    = [a for a in curr if a["is_video"]]
vid_with_vavg = sorted([a for a in vid_curr if a["vavg"] is not None], key=lambda x: x["vavg"], reverse=True)
hook_strong = vid_with_vavg[:3]
hook_weak   = list(reversed(vid_with_vavg[-3:])) if len(vid_with_vavg) >= 3 else []

# ── 피로도 ───────────────────────────────────────────────────────────────────
fatigue_ads  = sorted([a for a in curr if a["frequency"] >= 3],
                      key=lambda x: x["frequency"], reverse=True)
replace_list = [a for a in fatigue_ads if not a["roas"] or a["roas"] < 1]

# ── 내러티브 생성 ─────────────────────────────────────────────────────────────
def interp_roas():
    if not P["blend_roas"]: return ""
    delta = C["blend_roas"] - P["blend_roas"]
    dir_  = "상승" if delta > 0 else "하락"
    pct   = abs(delta / P["blend_roas"] * 100)
    cause = []
    if P["avg_cpm"] and abs(C["avg_cpm"] - P["avg_cpm"]) / P["avg_cpm"] > 0.1:
        cd = "상승" if C["avg_cpm"] > P["avg_cpm"] else "하락"
        cause.append(f"CPM {cd}({C['avg_cpm']:,.0f}원 → {P['avg_cpm']:,.0f}원)으로 노출 비용 변화")
    if P["avg_ob_ctr"] and abs(C["avg_ob_ctr"] - P["avg_ob_ctr"]) / max(P["avg_ob_ctr"], 0.01) > 0.1:
        cd = "개선" if C["avg_ob_ctr"] > P["avg_ob_ctr"] else "저하"
        cause.append(f"OB-CTR {cd}({P['avg_ob_ctr']:.2f}% → {C['avg_ob_ctr']:.2f}%)")
    reason = " / ".join(cause) + "이 주요 원인." if cause else "소재별 세부 분석 참조."
    return f"블렌드 ROAS {P['blend_roas']:.2f}x → {C['blend_roas']:.2f}x ({dir_}, {pct:.0f}%). {reason}"

def interp_cpa():
    if not C["cpa"] or not P["cpa"]: return ""
    delta = C["cpa"] - P["cpa"]
    dir_  = "상승" if delta > 0 else "하락"
    note  = "단가 또는 전환율 악화. 랜딩·오퍼 점검 필요." if delta > 0 else "전환 효율 개선. 현 구조 유지 권장."
    return f"CPA ₩{P['cpa']:,.0f} → ₩{C['cpa']:,.0f} ({dir_}). {note}"

def interp_vavg():
    if not C["avg_vavg"] or not P["avg_vavg"]: return ""
    delta = C["avg_vavg"] - P["avg_vavg"]
    dir_  = "개선" if delta > 0 else "하락"
    note  = "훅 및 초반 메시지 소구력 강화 효과." if delta > 0 else "도입부 훅 구조 점검 필요."
    return f"동영상 평균 시청 시간 {P['avg_vavg']:.1f}초 → {C['avg_vavg']:.1f}초 ({dir_}). {note}"

summary_narrative = " ".join(filter(None, [interp_roas(), interp_cpa(), interp_vavg()])) or "전주 대비 주요 지표 변화 제한적."

def fmt_narrative():
    if len(fmt_sorted) < 2: return "포맷 다양성 부족으로 비교 불가."
    bf, bs = fmt_sorted[0]
    wf, ws = fmt_sorted[-1]
    ratio  = bs["blend_roas"] / max(ws["blend_roas"], 0.01)
    bpct   = bs["spend"] / max(C["spend"], 1) * 100
    return (
        f"'{bf}'이 ROAS {bs['blend_roas']:.2f}x로 이번 주 최고 효율 달성 ({bs['n']}개, 예산 {bpct:.0f}% 집중). "
        f"'{wf}' 대비 {ratio:.1f}배 효율 차이. "
        f"OB-CTR 격차 {bs['avg_ob_ctr']:.2f}% vs {ws['avg_ob_ctr']:.2f}%가 클릭 품질 차이를 설명."
    )

def fatigue_narrative():
    n   = C["n_fatigue"]
    pct = n / max(C["n"], 1) * 100
    if n == 0: return "빈도 3 이상 소재 없음 — 피로 위험 낮음."
    sig = "포화 신호 감지 — 즉각 소재 교체 권장." if pct > 40 else "주의 수준 — 성과 추이 집중 모니터링."
    return f"빈도 3 이상 소재 {n}개 ({pct:.0f}%) — {sig}"

# ── 인사이트 ─────────────────────────────────────────────────────────────────
insights = []

top_ad = sorted(curr, key=lambda x: (x["roas"] or 0) * 10 + x["ob_ctr"], reverse=True)
if top_ad and top_ad[0]["roas"]:
    a = top_ad[0]
    _, fmt = pname(a["name"])
    insights.append(
        f"최고 성과 소재: '{a['name'][:38]}' (ROAS {a['roas']:.2f}x, OB-CTR {a['ob_ctr']:.2f}%, 지출 ₩{a['spend']:,.0f}). "
        f"'{fmt}' 포맷 전환 효율 우위 실증 — 컨셉 복제 우선 검토."
    )

if len(fmt_sorted) >= 2:
    bf, bs = fmt_sorted[0]
    wf, ws = fmt_sorted[-1]
    dir_budget = "성과 상위 포맷에 예산 집중 (올바른 방향)." if bs["spend"] > ws["spend"] else "성과 대비 예산 역배분 — 즉시 재배분 필요."
    insights.append(
        f"'{bf}' vs '{wf}' ROAS 격차 {bs['blend_roas']/max(ws['blend_roas'],0.01):.1f}배. "
        f"예산 비중 {bs['spend']/max(C['spend'],1)*100:.0f}% vs {ws['spend']/max(C['spend'],1)*100:.0f}% — {dir_budget}"
    )

if hook_strong and hook_weak:
    avg_s = sum(a["vavg"] for a in hook_strong) / len(hook_strong)
    avg_w = sum(a["vavg"] for a in hook_weak) / len(hook_weak)
    _, sfmt = pname(hook_strong[0]["name"])
    insights.append(
        f"훅 강도 양극화: 고시청 평균 {avg_s:.1f}초 vs 저시청 {avg_w:.1f}초. "
        f"고시청 소재 '{sfmt}' 포맷 집중 — 해당 포맷의 도입부 구성 방식을 저시청 소재에 이식 필요."
    )

if replace_list:
    a = replace_list[0]
    rs = f"{a['roas']:.2f}x" if a["roas"] else "전환 없음"
    insights.append(
        f"빈도 {a['frequency']:.1f} 도달 '{a['name'][:30]}' (ROAS {rs}) — "
        f"피로 누적으로 CPM 추가 상승 및 ROAS 추가 하락 예상. 즉시 교체 필요."
    )

if C["avg_vavg"] and P["avg_vavg"]:
    delta_vavg = C["avg_vavg"] - P["avg_vavg"]
    if abs(delta_vavg) > 1:
        dir_v = "증가" if delta_vavg > 0 else "감소"
        note_v = "훅 소구력 강화 — 현 도입부 구조 유지 권장." if delta_vavg > 0 else "도입부 훅 교체 실험 필요."
        insights.append(
            f"동영상 평균 시청 시간 {delta_vavg:+.1f}초 {dir_v} ({P['avg_vavg']:.1f}초 → {C['avg_vavg']:.1f}초). {note_v}"
        )

# ── 잘한 / 아쉬운 점 ─────────────────────────────────────────────────────────
well_done, missed = [], []

if C["blend_roas"] >= P["blend_roas"] and P["blend_roas"] > 0:
    well_done.append(f"블렌드 ROAS 전주 대비 유지·개선 ({P['blend_roas']:.2f}x → {C['blend_roas']:.2f}x)")
else:
    missed.append(f"ROAS 전주 대비 하락 ({P['blend_roas']:.2f}x → {C['blend_roas']:.2f}x) — 소재 성과 하락 선제 대응 미흡")

if fmt_sorted and fmt_sorted[0][1]["blend_roas"] >= 1.5:
    bf, bs = fmt_sorted[0]
    well_done.append(f"'{bf}' 포맷 집중 운영으로 ROAS {bs['blend_roas']:.2f}x 달성")

if not replace_list:
    well_done.append("빈도 3 이상 저효율 소재 없음 — 소재 순환 관리 양호")
else:
    missed.append(f"피로도 임계치 초과 소재 {len(replace_list)}개 선제 교체 미진행")

if len(fmt_sorted) >= 2 and fmt_sorted[-1][1]["blend_roas"] < 1 and fmt_sorted[-1][1]["spend"] > fmt_sorted[0][1]["spend"]:
    missed.append(f"저효율 '{fmt_sorted[-1][0]}' 포맷에 예산 과집중 — 재배분 필요했음")

# ── To-Do & 가설 ─────────────────────────────────────────────────────────────
todo = []

for a in replace_list[:3]:
    rs = f"{a['roas']:.2f}x" if a["roas"] else "N/A"
    todo.append(f"[중단] {a['name'][:38]} — 빈도 {a['frequency']:.1f}, ROAS {rs}")

high_burn = [a for a in curr if a["spend"] > 100_000 and (not a["roas"] or a["roas"] < 0.8)]
for a in sorted(high_burn, key=lambda x: x["spend"], reverse=True)[:3]:
    rs = f"{a['roas']:.2f}x" if a["roas"] else "N/A"
    todo.append(f"[예산 50% 축소] {a['name'][:38]} — ₩{a['spend']:,.0f}, ROAS {rs}")

for a in sorted([a for a in curr if a["roas"] and a["roas"] >= 1.5], key=lambda x: x["roas"], reverse=True)[:2]:
    todo.append(f"[예산 30% 증액] {a['name'][:38]} — ROAS {a['roas']:.2f}x")

if not todo:
    todo.append("즉시 조치 필요 소재 없음 — 다음 주 신규 소재 테스트 집중")

hypotheses = []
if fmt_sorted:
    bf, bs = fmt_sorted[0]
    hypotheses.append(
        f"가설: '{bf}' 포맷 상위 소재 훅·메시지를 저성과 포맷에 이식 시 OB-CTR {bs['avg_ob_ctr']*1.2:.2f}% 이상 달성 가능. "
        f"실험: 동일 오디언스·예산, 훅 첫 3초만 교체한 A/B. 기대 기간: 3~5일, 예산 각 5만원."
    )
if hook_weak:
    hw = hook_weak[-1]
    vavg_str = f"{hw['vavg']:.1f}초" if hw["vavg"] else "N/A"
    hypotheses.append(
        f"가설: 평균 시청 {vavg_str}인 '{hw['name'][:28]}' 도입부를 "
        f"직접 소구 + 즉각 혜택 제시 구조로 교체 시 시청 시간 50% 이상 증가 → CVR 15% 이상 개선 기대."
    )

# ── Notion 블록 ───────────────────────────────────────────────────────────────
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
    ch = [{"type":"table_row","table_row":{"cells":[cell(h) for h in headers]}}]
    ch += [{"type":"table_row","table_row":{"cells":[cell(v) for v in row]}} for row in rows]
    return {"object":"block","type":"table",
            "table":{"table_width":len(headers),"has_column_header":True,"has_row_header":False},
            "children": ch}

blocks = []

# 헤더
blocks += [
    h1(f"📊 위클리 성과 보고서 — {CW}  (전주: {PW})"),
    co(f"총 지출 ₩{C['spend']:,.0f} {chg(C['spend'],P['spend'])}  |  "
       f"블렌드 ROAS {C['blend_roas']:.2f}x {chg(C['blend_roas'],P['blend_roas'])}  |  "
       f"구매 {C['purchases']:.0f}건 {chg(C['purchases'],P['purchases'])}  |  "
       f"분석 소재 {C['n']}개 (전주 {P['n']}개)", "📌"),
    div(),
]

# ── 1. 주간 성과 요약 ─────────────────────────────────────────────────────────
blocks.append(h2("1️⃣ 주간 성과 요약 (전주 대비)"))
blocks.append(tbl(
    ["지표", f"이번 주 ({CW})", f"전주 ({PW})", "변화"],
    [
        ["블렌드 ROAS",     f"{C['blend_roas']:.2f}x", f"{P['blend_roas']:.2f}x",   chg(C["blend_roas"], P["blend_roas"])],
        ["CPA",            f"₩{C['cpa']:,.0f}" if C["cpa"] else "N/A",
                           f"₩{P['cpa']:,.0f}" if P["cpa"] else "N/A",
                           chg(C["cpa"], P["cpa"], False) if C["cpa"] and P["cpa"] else "–"],
        ["아웃바운드 CTR", f"{C['avg_ob_ctr']:.2f}%",  f"{P['avg_ob_ctr']:.2f}%",   chg(C["avg_ob_ctr"], P["avg_ob_ctr"])],
        ["동영상 평균 시청", f"{C['avg_vavg']:.1f}초" if C["avg_vavg"] else "N/A",
                            f"{P['avg_vavg']:.1f}초" if P["avg_vavg"] else "N/A",
                            chg(C["avg_vavg"], P["avg_vavg"]) if C["avg_vavg"] and P["avg_vavg"] else "–"],
        ["평균 CPM",        f"₩{C['avg_cpm']:,.0f}",   f"₩{P['avg_cpm']:,.0f}",     chg(C["avg_cpm"], P["avg_cpm"], False)],
        ["총 지출",         f"₩{C['spend']:,.0f}",      f"₩{P['spend']:,.0f}",       chg(C["spend"], P["spend"])],
        ["구매 건수",       f"{C['purchases']:.0f}건",  f"{P['purchases']:.0f}건",    chg(C["purchases"], P["purchases"])],
    ]
))
blocks.append(co(summary_narrative, "📝"))
blocks.append(div())

# ── 2. 소재 유형별 패턴 ───────────────────────────────────────────────────────
blocks.append(h2("2️⃣ 소재 유형별 패턴 분석"))
if fmt_stats:
    blocks.append(tbl(
        ["포맷", "소재수", "총 지출", "블렌드 ROAS", "OB-CTR", "평균 CPM", "구매수"],
        [[fmt, f"{s['n']}개", f"₩{s['spend']:,.0f}", f"{s['blend_roas']:.2f}x",
          f"{s['avg_ob_ctr']:.2f}%", f"₩{s['avg_cpm']:,.0f}", f"{s['purchases']:.0f}건"]
         for fmt, s in fmt_sorted]
    ))
blocks.append(co(fmt_narrative(), "📊"))
blocks.append(p(fatigue_narrative()))
blocks.append(div())

# ── 3. 훅 분석 심화 ───────────────────────────────────────────────────────────
blocks.append(h2("3️⃣ 훅 분석 심화 (평균 시청 시간 기준)"))
if vid_with_vavg:
    if hook_strong:
        blocks.append(h3("훅 강한 소재 TOP 3 (평균 시청 시간 높음 = 초반 소구 성공)"))
        blocks.append(tbl(
            ["소재명", "평균 시청(초)", "ROAS", "OB-CTR", "지출"],
            [[a["name"][:38], f"{a['vavg']:.1f}초",
              f"{a['roas']:.2f}x" if a["roas"] else "N/A",
              f"{a['ob_ctr']:.2f}%", f"₩{a['spend']:,.0f}"] for a in hook_strong]
        ))
    if hook_weak:
        blocks.append(h3("훅 약한 소재 TOP 3 (평균 시청 시간 낮음 = 도입부 개선 필요)"))
        blocks.append(tbl(
            ["소재명", "평균 시청(초)", "ROAS", "OB-CTR", "지출"],
            [[a["name"][:38], f"{a['vavg']:.1f}초",
              f"{a['roas']:.2f}x" if a["roas"] else "N/A",
              f"{a['ob_ctr']:.2f}%", f"₩{a['spend']:,.0f}"] for a in hook_weak]
        ))
    if hook_strong and hook_weak:
        avg_s = sum(a["vavg"] for a in hook_strong) / len(hook_strong)
        avg_w = sum(a["vavg"] for a in hook_weak) / len(hook_weak)
        gap   = avg_s - avg_w
        blocks.append(co(
            f"고훅 소재 평균 {avg_s:.1f}초 vs 저훅 소재 평균 {avg_w:.1f}초 (차이 {gap:.1f}초). "
            f"저시청 소재 도입부를 고시청 소재 방식으로 교체 시 시청 시간 개선 및 CVR 상승 기대.", "⚠️"
        ))
else:
    blocks.append(p("동영상 소재 시청 지표 없음 — 이미지 중심 운영 중이거나 데이터 미수집."))
blocks.append(div())

# ── 4. 피로도 & 라이프사이클 ─────────────────────────────────────────────────
blocks.append(h2("4️⃣ 소재 피로도 & 라이프사이클"))
if fatigue_ads:
    blocks.append(tbl(
        ["소재명", "빈도", "지출", "ROAS", "조치"],
        [[a["name"][:32], f"{a['frequency']:.1f}", f"₩{a['spend']:,.0f}",
          f"{a['roas']:.2f}x" if a["roas"] else "N/A",
          "교체 우선" if (not a["roas"] or a["roas"] < 1) else "모니터링"]
         for a in fatigue_ads[:8]]
    ))
    if replace_list:
        names = " / ".join([f"{a['name'][:22]}(빈도{a['frequency']:.1f})" for a in replace_list[:3]])
        blocks.append(co(f"교체 우선순위: {names}", "🔄"))
else:
    blocks.append(p("빈도 3 이상 소재 없음 — 피로 위험 낮음."))
blocks.append(div())

# ── 5. 인사이트 & 회고 ────────────────────────────────────────────────────────
blocks.append(h2("5️⃣ 인사이트 및 회고"))
blocks.append(h3("이번 주 주요 발견 (데이터 근거)"))
for ins in insights:
    blocks.append(blt(ins))
blocks.append(h3("잘한 운영 판단"))
for w in well_done:
    blocks.append(blt(w))
if not well_done:
    blocks.append(blt("이번 주 특별히 잘한 판단 없음 — 개선 집중 필요"))
blocks.append(h3("아쉬운 점 / 놓친 것"))
for m in missed:
    blocks.append(blt(m))
if not missed:
    blocks.append(blt("이번 주 운영상 주요 아쉬움 없음"))
blocks.append(div())

# ── 6. To-Do & Next Action ────────────────────────────────────────────────────
blocks.append(h2("6️⃣ To-Do & Next Action"))
blocks.append(h3("소재 조치 (이번 주 내)"))
for t in todo:
    blocks.append(blt(t))
blocks.append(h3("다음 주 실험 가설 & 기대 지표"))
for hyp in hypotheses:
    blocks.append(blt(hyp))
if not hypotheses:
    blocks.append(blt("데이터 축적 후 가설 도출 예정"))

# ── Notion 업로드 ─────────────────────────────────────────────────────────────
print("[2/3] Notion 페이지 생성...")
nh = {"Authorization": f"Bearer {NOTION_TOKEN}",
      "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

page = requests.post("https://api.notion.com/v1/pages", headers=nh, json={
    "parent": {"page_id": NOTION_PARENT},
    "properties": {"title": {"title": [{"text": {"content": f"📊 위클리 성과 보고서 - {CW}"}}]}},
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

print(f"\n✅ 위클리 보고서 완료! {page.get('url')}")
