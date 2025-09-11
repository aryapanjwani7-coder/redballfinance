#!/usr/bin/env python3
import os, json, time, urllib.request, urllib.parse
from datetime import date, datetime, timedelta

API = os.environ.get("EODHD_API_KEY")
BASE = "https://eodhd.com/api"
OUT  = "data/dividends.json"

# Map your .NS symbols to EODHD's ".NSE" format
def to_eodhd(sym: str) -> str:
    if sym.upper().endswith(".NS"):
        return sym[:-3] + ".NSE"
    return sym

def http_get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status} {url}")
        return r.read().decode("utf-8")

def parse_date(s):
    # EODHD dates are YYYY-MM-DD
    return datetime.strptime(s, "%Y-%m-%d").date()

def fx_usdinr_on(d: date) -> float:
    # Use EODHD FX endpoint: /api/real-time/FX/INRUSD
    # But we need INR per USD. EODHD returns USD/INR (USDINR) via /eod/FX/INRUSD? Or use LIVE FX/forex
    # Safer: use EOD endpoint historical for USDINR ("USDINR.FOREX"). Docs allow /eod/PAIR
    pair = "USDINR.FOREX"
    q = urllib.parse.urlencode({"api_token": API, "from": d.isoformat(), "to": d.isoformat(), "fmt": "json"})
    url = f"{BASE}/eod/{pair}?{q}"
    data = json.loads(http_get(url))
    if not data:
        # fallback: look back a few days
        for back in range(1, 7):
            dd = d - timedelta(days=back)
            q = urllib.parse.urlencode({"api_token": API, "from": dd.isoformat(), "to": dd.isoformat(), "fmt": "json"})
            url = f"{BASE}/eod/{pair}?{q}"
            data = json.loads(http_get(url))
            if data: break
    if not data:
        raise RuntimeError(f"No USDINR FX for {d}")
    # use close
    return float(data[-1]["close"])

def fetch_dividends_for(sym: str, start: date, end: date):
    # /api/dividends/{SYMBOL}?from=YYYY-MM-DD&to=YYYY-MM-DD&api_token=...
    s = to_eodhd(sym)
    q = urllib.parse.urlencode({"from": start.isoformat(), "to": end.isoformat(), "api_token": API, "fmt": "json"})
    url = f"{BASE}/dividends/{urllib.parse.quote(s)}?{q}"
    raw = json.loads(http_get(url))
    out = []
    for row in raw:
        # Expected keys: exDate, paymentDate, value, currency
        try:
            exd = parse_date(row["exDate"])
            amt = float(row["value"])
            ccy = (row.get("currency") or "INR").upper()
        except Exception:
            continue
        if amt <= 0: 
            continue
        if ccy == "USD":
            usd = amt
        elif ccy == "INR":
            rate = fx_usdinr_on(exd)  # INR per USD
            usd  = amt / rate
        else:
            # could extend with cross FX if you add more markets
            continue
        out.append({"symbol": sym, "date": exd.isoformat(), "amount_usd": round(usd, 2)})
        time.sleep(0.2)  # be nice
    return out

def main():
    if not API:
        raise SystemExit("EODHD_API_KEY not set")
    # read your symbols from transactions.json
    with open("data/transactions.json", "r", encoding="utf-8") as f:
        tx = json.load(f)
    symbols = sorted({t["symbol"] for t in tx if t.get("symbol")})

    # choose a sensible window (5y back to today)
    end = date.today()
    start = end - timedelta(days=5*365)

    all_divs = []
    for sym in symbols:
        try:
            got = fetch_dividends_for(sym, start, end)
            all_divs.extend(got)
        except Exception as e:
            print(f"[dividends] {sym}: {e}")

    os.makedirs("data", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(sorted(all_divs, key=lambda r: (r["symbol"], r["date"])), f, ensure_ascii=False)
    print(f"[dividends] wrote {OUT} rows={len(all_divs)}")
    
if __name__ == "__main__":
    main()
