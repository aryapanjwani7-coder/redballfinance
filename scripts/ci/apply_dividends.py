#!/usr/bin/env python3
import json, pathlib

root = pathlib.Path(__file__).resolve().parents[2]
nav_path = root / "data" / "nav.json"
sum_path = root / "data" / "nav_summary.json"
div_path = root / "data" / "dividends.json"

def load_json(p, default=None):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def main():
    nav = load_json(nav_path, [])
    if not nav:
        print("[apply_dividends] no nav.json; skipping")
        return

    divs = load_json(div_path, [])
    if not divs:
        print("[apply_dividends] no dividends.json; skipping")
        return

    # Build per-date USD inflows
    add_by_date = {}
    for d in divs:
        try:
            dt = d["date"]
            amt = float(d["amount_usd"])
            add_by_date[dt] = add_by_date.get(dt, 0.0) + amt
        except Exception as e:
            print("[apply_dividends] bad row:", d, e)

    running_add = 0.0
    for row in nav:
        dt = row.get("date")
        if dt in add_by_date:
            running_add += add_by_date[dt]
        # bump cash and nav if present
        if row.get("cash_usd") is not None:
            row["cash_usd"] = float(row["cash_usd"] or 0) + running_add
        if row.get("nav_usd") is not None:
            row["nav_usd"]  = float(row["nav_usd"]  or 0) + running_add
        # leave nav_index/pnl as-is (your builder can recompute if needed)

    with open(nav_path, "w", encoding="utf-8") as f:
        json.dump(nav, f, ensure_ascii=False)

    # Update summary latest
    summ = load_json(sum_path, {})
    if nav:
        latest = nav[-1]
        if "latest" not in summ: summ["latest"] = {}
        summ["latest"]["date"] = latest.get("date")
        if "cash_usd" in latest: summ["latest"]["cash"] = latest["cash_usd"]
        if "nav_usd" in latest:  summ["latest"]["nav"]  = latest["nav_usd"]

    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False)

    print("[apply_dividends] applied. Latest:", summ.get("latest"))

if __name__ == "__main__":
    main()
