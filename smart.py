"""smart-money v1 - paper-trades Polymarket top wallets. Never places real orders."""
import csv, json, os, sys, time, urllib.request
from collections import defaultdict

DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "data")
SEEN = os.path.join(D, "seen.json")
PAPER = os.path.join(D, "paper.csv")
SUMMARY = os.path.join(D, "summary.md")
TOP, MIN_USD, STAKE, SLIP, MAX_AGE = 10, 500, 10.0, 0.02, 30 * 60
COLS = ["time", "whale", "wallet", "title", "outcome", "condition_id",
        "whale_price", "entry", "contracts", "usd", "status", "pnl"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "smart-money/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def rows(x):
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for k in ("data", "items", "activity", "results"):
            if isinstance(x.get(k), list):
                return x[k]
    return []


def f(r, *keys):
    for k in keys:
        if r.get(k) not in (None, ""):
            return r[k]
    return None


def whales():
    lb = get(f"{DATA}/v2/leaderboard?time_period=month&sort_by=PNL&limit={TOP}")
    out = []
    for e in rows(lb):
        a = f(e, "proxy_wallet", "proxyWallet", "user_id", "wallet", "address")
        if a:
            out.append((a, f(e, "user_name", "userName") or a[:10], float(f(e, "pnl") or 0)))
    if not out:
        print("WARNING leaderboard parsed 0 wallets, raw:", str(lb)[:300])
    return out


def trade_key(r):
    return "|".join(str(f(r, *k) or "") for k in (
        ("transaction_hash", "transactionHash"), ("token_id", "asset"), ("side",), ("price",)))


def entry_price(p):
    return min(round(p + SLIP, 3), 0.99)


def qualifies(r, now):
    ts = float(f(r, "timestamp") or 0)
    if ts > 1e12:
        ts /= 1000
    if not ts or now - ts > MAX_AGE:
        return False
    usd = float(f(r, "usdc_size", "usdcSize") or 0)
    p = float(f(r, "price") or 0)
    return f(r, "side") == "BUY" and usd >= MIN_USD and 0 < p < 0.97


def load_seen():
    return set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()


def read_paper():
    if not os.path.exists(PAPER):
        return []
    with open(PAPER, newline="") as fh:
        return list(csv.DictReader(fh))


def write_paper(R):
    with open(PAPER, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(R)


def scan(now=None):
    now = now or time.time()
    os.makedirs(D, exist_ok=True)
    W = whales()
    print(f"tracking {len(W)} wallets")
    seen, R, new = load_seen(), read_paper(), 0
    for wallet, name, pnl in W:
        try:
            acts = rows(get(f"{DATA}/v2/activity?user={wallet}&type=TRADE&limit=50"))
        except Exception as e:
            print(f"fetch error {name}: {e}")
            continue
        for r in acts:
            k = trade_key(r)
            if k in seen:
                continue
            seen.add(k)
            if not qualifies(r, now):
                continue
            p = float(f(r, "price"))
            e = entry_price(p)
            R.append({"time": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)), "whale": name,
                      "wallet": wallet, "title": f(r, "title"), "outcome": f(r, "outcome"),
                      "condition_id": f(r, "condition_id", "conditionId"), "whale_price": p,
                      "entry": e, "contracts": round(STAKE / e, 4), "usd": STAKE,
                      "status": "OPEN", "pnl": ""})
            new += 1
            print(f"[WHALE] {name} BUY {f(r,'outcome')} @ {p:.2f} ${float(f(r,'usdc_size','usdcSize')):,.0f} | {f(r,'title')}")
        time.sleep(0.5)
    json.dump(sorted(seen), open(SEEN, "w"))
    write_paper(R)
    print(f"new paper trades: {new}")


def settle(r, market):
    """Return (status, pnl) for an OPEN row given a gamma market dict, or None if not settled."""
    if not market or not market.get("closed"):
        return None
    outs = json.loads(market["outcomes"]) if isinstance(market["outcomes"], str) else market["outcomes"]
    ps = market["outcomePrices"]
    ps = [float(x) for x in (json.loads(ps) if isinstance(ps, str) else ps)]
    if r["outcome"] not in outs:
        return None
    won = ps[outs.index(r["outcome"])] > 0.5
    usd = float(r["usd"])
    return ("WON", round(float(r["contracts"]) - usd, 2)) if won else ("LOST", -usd)


def grade():
    R = read_paper()
    for r in R:
        if r["status"] != "OPEN":
            continue
        try:
            m = rows(get(f"{GAMMA}/markets?condition_ids={r['condition_id']}"))
        except Exception as e:
            print("grade fetch error:", e)
            continue
        res = settle(r, m[0] if m else None)
        if res:
            r["status"], r["pnl"] = res
    if R:
        write_paper(R)
    write_summary(R)


def summarize(R):
    done = [r for r in R if r["status"] in ("WON", "LOST")]
    wins = sum(r["status"] == "WON" for r in done)
    pnl = sum(float(r["pnl"]) for r in done)
    per = defaultdict(float)
    for r in done:
        per[r["whale"]] += float(r["pnl"])
    verdict = ("need 50+ settled" if len(done) < 50 else
               ("POSITIVE so far" if pnl > 0 else "NEGATIVE - copying does not pay"))
    return {"total": len(R), "settled": len(done), "open": len(R) - len(done),
            "win_rate": wins / len(done) if done else 0, "pnl": pnl, "per": dict(per),
            "verdict": verdict}


def write_summary(R):
    s = summarize(R)
    lines = ["# smart-money scoreboard (PAPER ONLY)", "",
             f"Updated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}", "",
             f"Trades: {s['total']} | Settled: {s['settled']} | Open: {s['open']}",
             f"Win rate: {s['win_rate']:.0%} | P/L: ${s['pnl']:+.2f} on ${STAKE*s['settled']:.0f} risked",
             f"Verdict: {s['verdict']}", "", "## P/L per whale"]
    lines += [f"- {k}: ${v:+.2f}" for k, v in sorted(s["per"].items(), key=lambda x: -x[1])] or ["- none settled yet"]
    os.makedirs(D, exist_ok=True)
    open(SUMMARY, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    {"scan": scan, "grade": grade}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print("usage: smart.py scan|grade"))()
