# -*- coding: utf-8 -*-
"""백화점 상품권 거래소 시세를 수집해 html/rates.json 과 프리렌더를 만든다.

핫딜 수집(collect_deals.py)과 완전히 분리돼 있다 — 한쪽이 깨져도
다른 쪽은 그대로 나가야 하기 때문이다.

사용법:
    python collect_rates.py               수집 → rates.json → 프리렌더
    python collect_rates.py --render-only  기존 rates.json 으로 프리렌더만

수집 원칙 (상품권시세-설계.md 10절):
  - 각 업체가 자기 홈페이지에 공시한 값만 직접 읽는다
  - 비교 사이트(시세고 등)는 절대 읽지 않는다 — 남의 DB 복제이므로
  - 업체당 1회 요청, 순차, 간격 1초, 재시도 없음
  - 검증을 통과하지 못한 값은 빈 칸으로 둔다 (추정값 금지)
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import rate_parsers as rp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(BASE_DIR, "html", "rates.json")
RATE_PAGE = os.path.join(BASE_DIR, "html", "상품권시세.html")
FACE = rp.FACE

# HTTP 헤더는 latin-1 로만 인코딩되므로 한글을 넣으면 안 된다
# (넣으면 요청 단계에서 UnicodeEncodeError 로 전 업체 수집이 실패한다).
# 누가 수집하는지는 URL 로 밝힌다.
UA = ("Mozilla/5.0 (compatible; KoreaGiftcardBot/1.0; "
      "+https://koreagiftcard.co.kr)")

# 수집 대상. 미래상품권(meee.co.kr)은 SSL 인증서 만료로 제외 — 인증서 검증을
# 끄는 대신 빼 두었다. 갱신되면 {"key":"meee", ...} 로 다시 넣을 것.
SHOPS = [
    {"key": "worldticket", "name": "월드티켓상품권", "area": "명동",
     "url": "https://www.myeongdongworldticket.co.kr/", "encoding": "utf-8"},
    {"key": "xegift", "name": "엑스이상품권", "area": "명동",
     "url": "http://xegift.co.kr/html/sub0101.php", "encoding": "utf-8"},
    {"key": "choigo", "name": "최고상품권", "area": "명동",
     "url": "https://www.choigoticket.com/html/sub0101.php", "encoding": "utf-8"},
    # https 는 인증서가 만료돼 검증에 실패한다. 인증서 검증을 끄는 대신 http 로 읽는다
    # (읽는 값이 공개 시세뿐이고, 4중 검증을 통과해야 채택되므로 위험이 제한적이다).
    {"key": "meee", "name": "미래상품권", "area": "명동",
     "url": "http://meee.co.kr/", "encoding": "utf-8"},
    {"key": "centralgift", "name": "중앙상품권", "area": "명동",
     "url": "https://centralgift.imweb.me/", "encoding": "utf-8"},
    {"key": "citypay", "name": "시티페이", "area": "명동",
     "url": "https://city-pay.co.kr/", "encoding": "utf-8"},
    {"key": "sgbaekhwajeom", "name": "상품권백화점", "area": "명동",
     "url": "http://www.xn--zf0bt1zcnd5pj69p6qc.com/", "encoding": "utf-8"},
    {"key": "gogo", "name": "고고상품권", "area": "명동",
     "url": "https://xn--299aa03ct82dtjik1sz2c.com/", "encoding": "utf-8"},
]

# ── 제외된 업체 (파서는 rate_parsers.py 에 그대로 남아 있다) ──────────
# 아래 3곳은 로컬(국내 IP)에서는 정상 수집되지만 GitHub Actions 의 해외
# 데이터센터 IP 로는 차단된다. 2026-08-12 확인 — 정상 응답이 27~82KB 인데
# 765~1,600자짜리 본문에 title 도 브랜드 언급도 없는 페이지가 돌아온다.
#   mingren   명인상품권  https://www.mingren.co.kr/
#   wooticket 우천상품권  http://www.wooticket.com/            (EUC-KR)
#   woorist   우리에스티  https://woorist.co.kr/happyshop/show_pricelist_woori.php (EUC-KR)
# 프록시로 우회하지 않는다 — 상대가 막은 것을 뚫는 것은 수집 원칙에 어긋난다.
# 국내에서 도는 수집기를 따로 두게 되면 그때 다시 넣을 것.
#
# 미래상품권(meee.co.kr)은 SSL 인증서 만료로 제외. 갱신되면 다시 넣는다.
# 고고상품권은 간헐적으로 403 이 나지만 성공률이 높아 유지한다(실패해도 격리됨).

BRANDS = ["신세계", "롯데", "현대", "갤러리아", "AK"]

NOTE = ("각 업체가 홈페이지에 공시한 값을 수집한 참고 정보이며, 실제 거래 가격은 "
        "수량·권종·상품권 상태에 따라 다를 수 있습니다. "
        "거래 전 해당 업체에 직접 확인하시기 바랍니다.")


# ─────────────────────────────────────────────────────────────
# 수집
# ─────────────────────────────────────────────────────────────

def fetch(url, encoding="utf-8"):
    """페이지 1회 조회. 실패하면 예외를 그대로 올린다(재시도 없음)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    return raw.decode(encoding, "replace")


def collect():
    """업체별 수집. 실패한 업체는 건너뛰고 나머지는 그대로 반환한다."""
    shops, ok = [], 0
    for s in SHOPS:
        try:
            html = fetch(s["url"], s["encoding"])
            rows = [r for r in rp.PARSERS[s["key"]](html) if rp.validate_row(r, FACE)]
            if rows:
                shops.append({"name": s["name"], "url": s["url"],
                              "area": s["area"], "rows": rows})
                ok += 1
                print(f"[수집] {s['name']}: {len(rows)}건 "
                      f"({', '.join(r['brand'] for r in rows)})")
            else:
                # 0건일 때 "구조가 바뀐 것"과 "차단 페이지를 받은 것"을 구분해야
                # 대응이 갈린다. 응답의 지문을 함께 남긴다.
                # (로컬에서는 되는데 Actions 에서만 0건이면 IP·지역 기반 차단을 의심)
                title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
                title = re.sub(r"\s+", " ", title.group(1)).strip()[:40] if title else "(없음)"
                hits = sum(html.count(b) for b in BRANDS)
                print(f"::warning::[시세] {s['name']}: 유효한 행 0건 — "
                      f"응답 {len(html):,}자 / title \"{title}\" / 브랜드 언급 {hits}회. "
                      "브랜드 언급이 0회면 차단·리다이렉트, 있으면 구조 변경이다.")
        except Exception as e:
            print(f"::warning::[시세] {s['name']} 수집 실패: {type(e).__name__}: {e}")
        time.sleep(1.0)  # 상대 서버 예의
    return shops, {"shops_ok": ok, "shops_total": len(SHOPS)}


HISTORY_PATH = os.path.join(BASE_DIR, "html", "rates_market_history.json")
HISTORY_DAYS = 14


def append_history(result):
    """브랜드별 최저 살때를 시각별로 기록한다(히어로 트렌드 차트용, 14일 보관).

    이력 기록이 실패해도 수집 자체를 막지 않는다.
    파일이 있는데 못 읽으면 덮어쓰지 않는다 — 조용한 이력 소실 방지.
    """
    try:
        point = {"t": result["updated_at"]}
        for s in result.get("summary", []):
            if s.get("bestBuy"):
                point[s["brand"]] = s["bestBuy"]["price"]
        if len(point) <= 1:
            return

        if os.path.exists(HISTORY_PATH):
            try:
                with open(HISTORY_PATH, encoding="utf-8") as f:
                    hist = json.load(f).get("points", [])
            except Exception as e:
                print(f"::warning::rates_market_history.json 파싱 실패({e}) — 이번 기록 생략")
                return
        else:
            hist = []

        if hist and hist[-1].get("t") == point["t"]:
            return
        hist.append(point)

        cutoff = (datetime.now(timezone(timedelta(hours=9)))
                  - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d %H:%M")
        hist = [p for p in hist if isinstance(p, dict) and p.get("t", "") >= cutoff]

        with open(HISTORY_PATH, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"points": hist}, f, ensure_ascii=False, indent=1)
        print(f"[완료] 시세 이력 {len(hist)}점 기록")
    except Exception as e:
        print(f"::warning::시세 이력 기록 실패: {e}")


def build_trend(max_points=24):
    """이력에서 최근 N점을 뽑아 히어로 차트용 폴리라인 좌표를 만든다.

    점이 3개 미만이면 None 을 반환한다 — 선 하나로는 '동향'이 되지 않으므로
    화면에서 차트 영역을 통째로 숨긴다(빈 차트를 그리지 않는다).
    """
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            pts = json.load(f).get("points", [])
    except Exception:
        return None
    if len(pts) < 3:
        return None

    pts = pts[-max_points:]
    # 브랜드별로 있으나 없으나, '전체 최저 살때'의 흐름을 한 선으로 보여준다
    series = []
    for p in pts:
        vals = [v for k, v in p.items() if k != "t" and isinstance(v, (int, float))]
        if vals:
            series.append({"t": p["t"], "v": min(vals)})
    if len(series) < 3:
        return None

    lo = min(s["v"] for s in series)
    hi = max(s["v"] for s in series)
    span = (hi - lo) or 1
    W, H, PAD = 300.0, 90.0, 10.0
    coords = []
    for i, s in enumerate(series):
        x = PAD + (W - PAD * 2) * (i / max(len(series) - 1, 1))
        y = PAD + (H - PAD * 2) * (1 - (s["v"] - lo) / span)
        coords.append((round(x, 1), round(y, 1)))
    return {"coords": coords, "series": series, "lo": lo, "hi": hi,
            "first": series[0]["t"][-5:], "last": series[-1]["t"][-5:]}


def annotate_direction(result):
    """직전 기록 대비 최저 살때의 방향을 summary[].dir 에 넣는다.

    프리렌더와 JS 렌더러가 같은 값을 쓰게 하려고 데이터에 담는다
    (JS 는 이력 파일을 읽지 않으므로, 여기서 넣지 않으면 양쪽 화살표가 달라진다).
    이력이 없으면 dir 을 넣지 않는다 — 방향을 추측하지 않는다.
    """
    try:
        with open(HISTORY_PATH, encoding="utf-8") as f:
            pts = json.load(f).get("points", [])
    except Exception:
        return
    if len(pts) < 2:
        return
    prev = pts[-2]
    for s in result.get("summary", []):
        p = prev.get(s["brand"])
        buy = s.get("bestBuy")
        if not buy or not isinstance(p, (int, float)):
            continue
        s["dir"] = "down" if buy["price"] < p else ("up" if buy["price"] > p else "flat")


def build_summary(shops):
    """종류별 최저 살때 / 최고 팔때."""
    out = []
    for brand in BRANDS:
        best_buy = best_sell = None
        for s in shops:
            for r in s["rows"]:
                if r["brand"] != brand:
                    continue
                if r.get("buy") is not None:
                    if best_buy is None or r["buy"] < best_buy["price"]:
                        best_buy = {"price": r["buy"], "rate": r.get("buyRate"),
                                    "shop": s["name"]}
                if r.get("sell") is not None:
                    if best_sell is None or r["sell"] > best_sell["price"]:
                        best_sell = {"price": r["sell"], "rate": r.get("sellRate"),
                                     "shop": s["name"]}
        out.append({"brand": brand, "bestBuy": best_buy, "bestSell": best_sell})
    return out


# ─────────────────────────────────────────────────────────────
# 프리렌더 — html/상품권시세.html 의 마커 구간에 정적 HTML 을 굽는다.
#   네이버 크롤러(Yeti)는 JS 를 렌더링하지 않으므로 표가 원본 HTML 에 있어야 한다.
#   아래 마크업은 상품권시세.html 의 JS 렌더러와 1:1 로 같아야 한다.
# ─────────────────────────────────────────────────────────────

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def won(n):
    return f"{n:,}원" if isinstance(n, int) else "—"


def rate_txt(v):
    if v is None:
        return ""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{s}%"


def build_hero_table(data):
    """히어로 우측 '주요 백화점 시세 비교' 표.

    종류별 최저 살때 / 최고 팔때를 한 줄에 담고, 직전 기록 대비 방향을
    화살표로 표시한다(이력이 없으면 화살표를 생략한다 — 추측하지 않는다).
    """
    ARROWS = {"down": '<span class="hb_arw down" aria-label="하락">↓</span>',
              "up": '<span class="hb_arw up" aria-label="상승">↑</span>',
              "flat": '<span class="hb_arw flat" aria-label="보합">–</span>'}
    rows = []
    for s in data.get("summary", []):
        buy, sell = s.get("bestBuy"), s.get("bestSell")
        if not buy and not sell:
            continue
        # 방향은 rates.json 의 summary[].dir 에 담겨 있다(JS 렌더러도 같은 값을 쓴다).
        arrow = ARROWS.get(s.get("dir") or "", "")
        rows.append(
            f'<tr><th scope="row">{esc(s["brand"])}</th>'
            f'<td class="hb_buy">{won((buy or {}).get("price"))}</td>'
            f'<td class="hb_sell">{won((sell or {}).get("price"))}</td>'
            f'<td class="hb_dir">{arrow}</td></tr>')
    return f'<table class="hero_board"><tbody>{"".join(rows)}</tbody></table>'


def build_hero_chart():
    """히어로 좌측 '시장 가격 동향' 미니 차트. 이력이 부족하면 빈 문자열."""
    t = build_trend()
    if not t:
        return ""
    pts = " ".join(f"{x},{y}" for x, y in t["coords"])
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="2.4"/>' for x, y in t["coords"])
    return (
        '<div class="hero_chart">'
        '<div class="hc_head"><span>시장 가격 동향</span>'
        '<em class="hc_live">실시간 업데이트</em></div>'
        '<svg viewBox="0 0 300 90" preserveAspectRatio="none" role="img" '
        f'aria-label="최근 {len(t["coords"])}회 최저 살때 추이">'
        f'<polyline points="{pts}" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<g class="hc_dots" fill="currentColor">{dots}</g></svg>'
        f'<div class="hc_axis"><span>{esc(t["first"])}</span>'
        f'<span>{esc(t["last"])}</span></div></div>')


def build_prerender(data):
    parts = {}
    parts["ratesUpdatedAt"] = esc(data.get("updated_at", "-"))
    parts["heroBoard"] = build_hero_table(data)
    parts["heroChart"] = build_hero_chart()

    cards = []
    for s in data.get("summary", []):
        buy, sell = s.get("bestBuy"), s.get("bestSell")
        if not buy and not sell:
            continue
        cards.append(
            f'<div class="rate_card">'
            f'<div class="rc_brand">{esc(s["brand"])} 상품권</div>'
            f'<div class="rc_row"><span class="rc_label buy">살때</span>'
            f'<b>{won((buy or {}).get("price"))}</b>'
            f'<span class="rc_shop">{esc((buy or {}).get("shop") or "-")}</span></div>'
            f'<div class="rc_row"><span class="rc_label sell">팔때</span>'
            f'<b>{won((sell or {}).get("price"))}</b>'
            f'<span class="rc_shop">{esc((sell or {}).get("shop") or "-")}</span></div>'
            f'</div>')
    parts["ratesSummary"] = "".join(cards)

    brands = data.get("brands", BRANDS)
    head = "".join(f"<th>{esc(b)}</th>" for b in brands)
    body = []
    for sh in data.get("shops", []):
        by = {r["brand"]: r for r in sh["rows"]}
        tds = []
        for b in brands:
            r = by.get(b)
            if not r:
                tds.append('<td class="na">—</td>')
                continue
            tds.append(
                f'<td><span class="c_buy">{won(r.get("buy"))}</span>'
                f'<span class="c_sell">{won(r.get("sell"))}</span></td>')
        body.append(
            f'<tr><th scope="row"><a href="{esc(sh["url"])}" target="_blank" '
            f'rel="nofollow noopener">{esc(sh["name"])}</a>'
            f'<span class="area">{esc(sh.get("area", ""))}</span></th>'
            f'{"".join(tds)}</tr>')
    parts["ratesMatrix"] = (
        f'<table class="rate_table"><thead><tr><th>상품권 샵</th>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table>')

    frag = [f'{s["brand"]} {s["bestBuy"]["price"]:,}원'
            for s in data.get("summary", []) if s.get("bestBuy")][:3]
    desc = ("백화점 상품권 시세 " + "·".join(frag) + ". ") if frag else ""
    desc += ("신세계·롯데·현대·갤러리아·AK 백화점 상품권의 살때·팔때 시세를 "
             "상품권 거래소별로 비교해 한국상품권협회가 매시간 자동 집계합니다.")
    parts["ratesMetaDesc"] = f'<meta name="description" content="{esc(desc)}">'

    parts["ratesJsonld"] = (
        '<script type="application/ld+json">'
        + json.dumps({
            "@context": "https://schema.org",
            "@type": "Dataset",
            "name": "백화점 상품권 시세",
            "description": desc,
            "dateModified": data.get("updated_at"),
            "creator": {"@type": "Organization", "name": "한국상품권협회"},
            "isAccessibleForFree": True,
        }, ensure_ascii=False)
        + "</script>")
    return parts


def apply_prerender(data):
    with open(RATE_PAGE, encoding="utf-8", newline="") as f:
        html = f.read()
    for name, content in build_prerender(data).items():
        pattern = re.compile(r"(<!--PR:%s-->).*?(<!--/PR:%s-->)"
                             % (re.escape(name), re.escape(name)), re.S)
        html, n = pattern.subn(lambda m, c=content: m.group(1) + c + m.group(2), html)
        if n != 1:
            # 마커가 지워지면 프리렌더가 화석화되므로 조용히 넘어가지 않고 실패시킨다
            print(f"[오류] 프리렌더 마커 'PR:{name}' 치환 실패(발견 {n}곳) — "
                  "상품권시세.html 의 마커를 확인하세요.")
            sys.exit(1)
    with open(RATE_PAGE, "w", encoding="utf-8", newline="") as f:
        f.write(html)
    print(f"[완료] 상품권시세.html 프리렌더 갱신")


def main():
    if "--render-only" in sys.argv:
        with open(OUT_PATH, encoding="utf-8") as f:
            apply_prerender(json.load(f))
        return

    shops, health = collect()

    # 전멸 방지 — 너무 적게 모이면 기존 데이터를 보존하고 실패시킨다
    if health["shops_ok"] < 2:
        print(f"::error::시세 수집 업체가 {health['shops_ok']}곳뿐입니다 — "
              "기존 데이터를 보존하고 종료합니다.")
        sys.exit(1)

    prev_streak = 0
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            prev_streak = int(json.load(f).get("collect_health", {})
                              .get("shop_low_streak", 0) or 0)
    except Exception:
        pass
    low = health["shops_ok"] < health["shops_total"] / 2
    health["shop_low_streak"] = prev_streak + 1 if low else 0
    if low:
        print(f"::warning::시세 수집 업체가 절반 미만입니다 "
              f"({health['shops_ok']}/{health['shops_total']}, 연속 "
              f"{health['shop_low_streak']}회) — 파서 점검 필요")

    kst = timezone(timedelta(hours=9))
    result = {
        "updated_at": datetime.now(kst).strftime("%Y-%m-%d %H:%M"),
        "note": NOTE,
        "face": FACE,
        "collect_health": health,
        "brands": BRANDS,
        "summary": build_summary(shops),
        "shops": shops,
    }

    # 순서 주의: 이력 기록 → 방향 주입 → rates.json 저장 → 프리렌더.
    # 방향(dir)을 저장 뒤에 넣으면 rates.json 에 빠져 JS 렌더러만 화살표를 못 그린다.
    append_history(result)      # 히어로 트렌드 차트용 이력
    annotate_direction(result)  # 직전 대비 방향 — 프리렌더와 JS 가 같은 값을 쓰도록 데이터에 담는다

    # newline="\n" — 윈도우 로컬과 리눅스 Actions 가 교차 실행돼도 개행 diff 가 없게
    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if os.path.exists(RATE_PAGE):
        apply_prerender(result)

    print(f"[완료] {OUT_PATH}")
    print(f"       업체 {health['shops_ok']}/{health['shops_total']}곳 · "
          f"업데이트 {result['updated_at']}")
    for s in result["summary"]:
        if s["bestBuy"]:
            print(f"       - {s['brand']}: 최저 살때 {s['bestBuy']['price']:,}원 "
                  f"({s['bestBuy']['shop']})")


if __name__ == "__main__":
    main()
