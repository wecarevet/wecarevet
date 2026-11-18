#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
위케어 — 관심 ETF·미국주식 장 마감 보드 데이터 갱신
=====================================================

Yahoo Finance 공개 chart API 에서 실제 일별 종가를 받아
`stocks.html` 안의 데이터 블록(`/*STOCKS_DATA_START*/ ... /*STOCKS_DATA_END*/`)과
`stocks.json` 을 갱신합니다.

    python3 scripts/stocks/update_stocks.py

옵션
    --html  PATH   갱신할 HTML (기본: 저장소 루트의 stocks.html)
    --json  PATH   함께 쓸 JSON (기본: 저장소 루트의 stocks.json)
    --only  SYM,SYM  지정 종목만 갱신(디버깅용)
    --offline PATH  네트워크 없이 기존 JSON 으로 HTML 만 다시 심기

계산 항목: 현재가, 1일/1개월/3개월/YTD %, 52주 최고·최저와 그 안에서의 위치,
최근 1년 배당 합계와 배당수익률, 1년 스파크라인, USD/KRW 환율.
값은 전부 실제 시세이며 절대 임의로 만들지 않습니다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
API = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d&events=div"

# ── 추적 종목 ────────────────────────────────────────────────────────────────
# (심볼, 한국어 이름, 시장, 분류)
#   시장: US / KR / IDX(지수) / FX(환율)
#   분류: ETF / 주식 / 지수 / 환율
TICKERS = [
    # ── 미국 ETF ──
    ("SPY",    "S&P500 (SPDR)",            "US", "ETF"),
    ("VOO",    "뱅가드 S&P500",             "US", "ETF"),
    ("IVV",    "iShares S&P500",           "US", "ETF"),
    ("QQQ",    "나스닥100 (Invesco)",       "US", "ETF"),
    ("QQQM",   "나스닥100 미니",            "US", "ETF"),
    ("QLD",    "나스닥100 2배",             "US", "ETF"),
    ("TQQQ",   "나스닥100 3배",             "US", "ETF"),
    ("SOXL",   "반도체 3배",                "US", "ETF"),
    ("SMH",    "반도체 (VanEck)",           "US", "ETF"),
    ("SCHD",   "미국 배당다우존스",         "US", "ETF"),
    ("JEPI",   "커버드콜 S&P500",            "US", "ETF"),
    ("JEPQ",   "커버드콜 나스닥100",         "US", "ETF"),
    ("TLT",    "미국채 20년+",              "US", "ETF"),
    ("GLD",    "금",                        "US", "ETF"),
    ("IWM",    "러셀2000",                 "US", "ETF"),
    ("DIA",    "다우존스 30",               "US", "ETF"),
    ("VTI",    "미국 전체시장",             "US", "ETF"),
    ("VNQ",    "미국 리츠",                 "US", "ETF"),
    ("ARKK",   "아크 혁신",                 "US", "ETF"),
    ("XLE",    "미국 에너지",               "US", "ETF"),
    # ── 미국 주식 ──
    ("NVDA",   "엔비디아",                  "US", "주식"),
    ("TSLA",   "테슬라",                    "US", "주식"),
    ("MSFT",   "마이크로소프트",            "US", "주식"),
    ("AAPL",   "애플",                      "US", "주식"),
    ("GOOGL",  "알파벳 A",                  "US", "주식"),
    ("AMZN",   "아마존",                    "US", "주식"),
    ("META",   "메타",                      "US", "주식"),
    ("AVGO",   "브로드컴",                  "US", "주식"),
    ("AMD",    "AMD",                       "US", "주식"),
    ("TSM",    "TSMC",                      "US", "주식"),
    ("PLTR",   "팔란티어",                  "US", "주식"),
    ("COST",   "코스트코",                  "US", "주식"),
    ("BRK-B",  "버크셔 해서웨이 B",         "US", "주식"),
    ("NFLX",   "넷플릭스",                  "US", "주식"),
    ("ORCL",   "오라클",                    "US", "주식"),
    ("CRM",    "세일즈포스",                "US", "주식"),
    ("ADBE",   "어도비",                    "US", "주식"),
    ("MU",     "마이크론",                  "US", "주식"),
    ("QCOM",   "퀄컴",                      "US", "주식"),
    ("ARM",    "ARM",                       "US", "주식"),
    ("INTU",   "인튜이트",                  "US", "주식"),
    ("UBER",   "우버",                      "US", "주식"),
    ("COIN",   "코인베이스",                "US", "주식"),
    ("MSTR",   "마이크로스트래티지",        "US", "주식"),
    ("HOOD",   "로빈후드",                  "US", "주식"),
    ("JPM",    "JP모건",                    "US", "주식"),
    ("V",      "비자",                      "US", "주식"),
    ("MA",     "마스터카드",                "US", "주식"),
    ("LLY",    "일라이릴리",                "US", "주식"),
    ("UNH",    "유나이티드헬스",            "US", "주식"),
    ("XOM",    "엑슨모빌",                  "US", "주식"),
    ("WMT",    "월마트",                    "US", "주식"),
    ("KO",     "코카콜라",                  "US", "주식"),
    ("DIS",    "디즈니",                    "US", "주식"),
    ("BA",     "보잉",                      "US", "주식"),
    ("PFE",    "화이자",                    "US", "주식"),
    ("MRK",    "머크",                      "US", "주식"),
    # ── 한국 ETF ──
    ("360750.KS", "TIGER 미국S&P500",         "KR", "ETF"),
    ("458730.KS", "TIGER 미국배당다우존스",   "KR", "ETF"),
    ("133690.KS", "TIGER 미국나스닥100",      "KR", "ETF"),
    ("379800.KS", "KODEX 미국S&P500TR",       "KR", "ETF"),
    ("069500.KS", "KODEX 200",                "KR", "ETF"),
    ("102110.KS", "TIGER 200",                "KR", "ETF"),
    ("305720.KS", "KODEX 2차전지산업",        "KR", "ETF"),
    # ── 한국 주식 ──
    ("005930.KS", "삼성전자",                 "KR", "주식"),
    ("000660.KS", "SK하이닉스",               "KR", "주식"),
    ("373220.KS", "LG에너지솔루션",           "KR", "주식"),
    ("207940.KS", "삼성바이오로직스",         "KR", "주식"),
    ("035420.KS", "NAVER",                    "KR", "주식"),
    ("035720.KS", "카카오",                   "KR", "주식"),
    ("005380.KS", "현대차",                   "KR", "주식"),
    ("068270.KS", "셀트리온",                 "KR", "주식"),
    # ── 지수 ──
    ("^GSPC",  "S&P 500 지수",              "IDX", "지수"),
    ("^IXIC",  "나스닥 종합",               "IDX", "지수"),
    ("^DJI",   "다우존스 산업",             "IDX", "지수"),
    ("^KS11",  "코스피",                    "IDX", "지수"),
    ("^KQ11",  "코스닥",                    "IDX", "지수"),
    # ── 환율 ──
    ("KRW=X",  "원/달러",                   "FX", "환율"),
]

SPARK_POINTS = 44
START, END = "/*STOCKS_DATA_START*/", "/*STOCKS_DATA_END*/"


# ── HTTP ─────────────────────────────────────────────────────────────────────
def _get_json(url: str, tries: int = 4) -> dict:
    last = None
    for i in range(tries):
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # 429 · timeout · 5xx
            last = exc
            time.sleep(1.2 * (i + 1) + 0.4 * i)
    raise RuntimeError(f"fetch failed: {last}")


def _sample(values: list, n: int) -> list:
    if len(values) <= n:
        return values
    step = (len(values) - 1) / (n - 1)
    return [values[round(i * step)] for i in range(n)]


def fetch_symbol(entry) -> dict | None:
    """한 종목의 실제 일별 종가 → 지표 계산."""
    sym, kr, market, group = entry
    url = API.format(sym=urllib.parse.quote(sym, safe=""), rng="2y")
    try:
        payload = _get_json(url)
    except Exception as exc:
        print(f"  ! {sym}: {exc}", file=sys.stderr)
        return None
    res = (payload.get("chart") or {}).get("result") or []
    if not res:
        print(f"  ! {sym}: no result", file=sys.stderr)
        return None
    res = res[0]
    meta = res.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    stamps = res.get("timestamp") or []
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []

    rows = []
    for ts, close in zip(stamps, closes):
        if close is None:
            continue
        day = (datetime.fromtimestamp(ts, timezone.utc) + timedelta(seconds=offset)).date()
        rows.append((day, float(close)))
    if len(rows) < 2:
        print(f"  ! {sym}: not enough closes", file=sys.stderr)
        return None
    rows.sort(key=lambda r: r[0])

    last_day, price = rows[-1]
    prev = rows[-2][1]

    def pct_change(back: int):
        if len(rows) <= back:
            return None
        base = rows[-1 - back][1]
        return None if not base else (price / base - 1) * 100

    # YTD: 작년 마지막 거래일 종가 기준
    ytd = None
    base_ytd = None
    for day, close in reversed(rows):
        if day.year < last_day.year:
            base_ytd = close
            break
    if base_ytd:
        ytd = (price / base_ytd - 1) * 100

    # 52주 최고·최저 (마지막 거래일 기준 365일)
    cut = last_day - timedelta(days=365)
    window = [c for d, c in rows if d >= cut]
    hi = max(window) if window else max(c for _, c in rows)
    lo = min(window) if window else min(c for _, c in rows)
    pos = None if hi == lo else (price - lo) / (hi - lo) * 100

    # 최근 1년 배당
    div_ttm = 0.0
    divs = (((res.get("events") or {}).get("dividends")) or {})
    cut_ts = (last_day - timedelta(days=365)).isoformat()
    for item in divs.values():
        amt = item.get("amount")
        d = item.get("date")
        if amt is None or d is None:
            continue
        day = (datetime.fromtimestamp(d, timezone.utc) + timedelta(seconds=offset)).date().isoformat()
        if day >= cut_ts:
            div_ttm += float(amt)
    div_yield = (div_ttm / price * 100) if price else None

    spark_rows = [round(c, 2) for day, c in rows if day >= cut] or [round(c, 2) for _, c in rows]
    spark = _sample(spark_rows, SPARK_POINTS)

    return {
        "sym": sym,
        "kr": kr,
        "en": meta.get("longName") or meta.get("shortName") or sym,
        "mkt": market,
        "grp": group,
        "cur": meta.get("currency") or ("KRW" if market in ("KR", "IDX") else "USD"),
        "px": round(price, 4),
        "prev": round(prev, 4),
        "d1": None if not prev else round((price / prev - 1) * 100, 2),
        "m1": _r(pct_change(21)),
        "m3": _r(pct_change(63)),
        "ytd": _r(ytd),
        "hi": round(hi, 4),
        "lo": round(lo, 4),
        "pos": _r(pos),
        "divAmt": round(div_ttm, 4),
        "divY": _r(div_yield),
        "date": last_day.isoformat(),
        "spark": spark,
    }


def _r(v):
    return None if v is None else round(v, 2)


# ── 빌드 ─────────────────────────────────────────────────────────────────────
def build(only=None) -> dict:
    entries = [t for t in TICKERS if not only or t[0] in only]
    print(f"· {len(entries)}개 종목 시세 수집 (Yahoo Finance chart API)")
    items, failed = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for out in pool.map(fetch_symbol, entries):
            if out:
                items.append(out)
            else:
                failed.append("?")
    order = {t[0]: i for i, t in enumerate(TICKERS)}
    items.sort(key=lambda it: order.get(it["sym"], 999))

    fx = next((it for it in items if it["sym"] == "KRW=X"), None)
    dates = {}
    for it in items:
        if it["mkt"] in ("US", "KR") and it["grp"] != "지수":
            key = "KR" if it["mkt"] == "KR" else "US"
            dates[key] = max(dates.get(key, ""), it["date"])

    now = datetime.now(KST)
    return {
        "schema": 1,
        "source": "Yahoo Finance chart API",
        "updated_kst": now.strftime("%Y-%m-%d %H:%M"),
        "updated_iso": now.isoformat(timespec="seconds"),
        "usd_krw": {
            "rate": fx["px"] if fx else None,
            "d1": fx["d1"] if fx else None,
            "date": fx["date"] if fx else None,
        },
        "close_date": {"US": dates.get("US"), "KR": dates.get("KR")},
        "items": items,
        "count": len(items),
        "failed": len(failed),
    }


def write_outputs(data: dict, html_path: str, json_path: str) -> None:
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(blob + "\n")
        print(f"· JSON  → {json_path}  ({len(blob)/1024:.1f} KB)")

    if not html_path:
        return
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    if START not in html or END not in html:
        raise SystemExit(f"! {html_path} 에 {START} … {END} 블록이 없습니다")
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
    html = pattern.sub(START + blob + END, html, count=1)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"· HTML  → {html_path}")


def report(data: dict) -> None:
    print()
    print(f"  기준: 미국장 {data['close_date'].get('US')} 종가 · 한국장 {data['close_date'].get('KR')} 종가")
    fxd = data.get("usd_krw") or {}
    print(f"  USD/KRW {fxd.get('rate')} ({fxd.get('d1')}%) · 갱신 {data['updated_kst']} KST")
    print()
    print(f"  {'종목':<26}{'현재가':>12}{'1D':>8}{'1M':>8}{'YTD':>9}{'52주위치':>9}{'배당':>7}")
    for it in data["items"]:
        def f(v, suf="%"):
            return "-" if v is None else f"{v:+.2f}{suf}"
        price = it["px"]
        ps = f"{price:,.0f}" if it["cur"] == "KRW" else f"{price:,.2f}"
        pos = "-" if it["pos"] is None else f"{it['pos']:.0f}%"
        dy = "-" if it["divY"] is None else f"{it['divY']:.2f}%"
        print(f"  {it['kr']+' ('+it['sym']+')':<26}{ps:>12}{f(it['d1']):>8}{f(it['m1']):>8}{f(it['ytd']):>9}{pos:>9}{dy:>7}")


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=os.path.join(root, "stocks.html"))
    ap.add_argument("--json", default=os.path.join(root, "stocks.json"))
    ap.add_argument("--only", default=None)
    ap.add_argument("--offline", default=None, help="기존 JSON 으로 HTML 만 재생성")
    args = ap.parse_args()

    if args.offline:
        with open(args.offline, encoding="utf-8") as f:
            data = json.load(f)
        print(f"· 오프라인 모드: {args.offline}")
    else:
        only = {s.strip().upper() for s in args.only.split(",")} if args.only else None
        data = build(only)

    write_outputs(data, args.html, args.json)
    report(data)
    print()
    print(f"  → {data['count']}종목 갱신 완료" + (f" · 실패 {data['failed']}건" if data.get("failed") else ""))


if __name__ == "__main__":
    main()
