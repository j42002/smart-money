"""smart-money v2 - paper-trades Polymarket top wallets. Never places real orders.

v2 vs v1:
- grader actually settles (CLOB `winner` flag, gamma closed=true fallback)
- entry = live best ask when the bot sees the trade, not "whale + 2c"
- one position per wallet+market+outcome (no 8x fill spam)
- skips whales buying both sides of a market (market makers, not bets)
"""
import csv, json, os, sys, time, urllib.request
from collections import defaultdict

DATA = "https://data-api.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "data")
PAPER = os.path.join(D, "paper.csv")
OLD_SEEN = os.path.join(D, "seen.json")  # v1 state, deleted on first v2 run
SUMMARY = os.path.join(D, "summary.md")

TOP = 10              # wallets from the 30-day PnL leaderboard
MIN_USD = 500         # whale buy must be at least this big
STAKE = 10.0          # paper dollars per copy
MAX_AGE = 12 * 3600   # GitHub cron is throttled to every few hours, so look back 12h
MAX_ENTRY = 0.90      # don't pay 95c to win 5c
MAX_CHASE = 0.05      # skip if price moved 5c+ either way since the whale bought
MIN_SETTLED = 50      # settled positions before a verdict means anything

COLS = ["time", "whale", "wallet", "title", "outcome", "condition_id", "whale_price",
        "entry", "contracts", "usd", "status", "pnl", "token_id", "whale_usd", "entry_src", "ver"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "smart-money/2"})
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


def jl(x):
    return json.loads(x) if isinstance(x, str) else (x or [])


def ts_of(r):
    ts = float(f(r, "timestamp") or 0)
    return ts / 1000 if ts > 1e12 else ts


def cid_of(r):
    return f(r, "condition_id", "conditionId")


def pos_key(wallet, cid, outcome):
    return (str(wallet).lower(), str(cid), str(outcome))


# ---------- scan ----------

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


def qualifies(r, now):
    ts = ts_of(r)
    if not ts or now - ts > MAX_AGE:
        return False
    usd = float(f(r, "usdc_size", "usdcSize") or 0)
    p = float(f(r, "price") or 0)
    return f(r, "side") == "BUY" and usd >= MIN_USD and 0.03 < p < MAX_ENTRY


def two_sided(acts):
    """Markets where this wallet bought more than one outcome = market making / hedging."""
    bought = defaultdict(set)
    for r in acts:
        if f(r, "side") == "BUY":
            bought[cid_of(r)].add(f(r, "outcome"))
    return {c for c, o in bought.items() if len(o) > 1}


def best_ask(token_id):
    book = get(f"{CLOB}/book?token_id={token_id}")
    asks = [float(a["price"]) for a in (book.get("asks") or []) if float(a.get("size") or 0) > 0]
    return min(asks) if asks else None


def pick_entry(whale_price, ask):
    """Return (entry, reason). entry None = skip."""
    if ask is None:
        return None, "no book"
    if ask >= MAX_ENTRY:
        return None, f"ask {ask:.2f} too high"
    if abs(ask - whale_price) > MAX_CHASE:  # either way: ran away, or the game already turned
        return None, f"moved {whale_price:.2f}->{ask:.2f}"
    return ask, "live ask"


def read_paper():
    if not os.path.exists(PAPER):
        return []
    with open(PAPER, newline="") as fh:
        return list(csv.DictReader(fh))


def write_paper(R):
    with open(PAPER, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(R)


def scan(now=None):
    now = now or time.time()
    os.makedirs(D, exist_ok=True)
    if os.path.exists(OLD_SEEN):
        os.remove(OLD_SEEN)
    W = whales()
    print(f"tracking {len(W)} wallets")
    R = read_paper()
    have = {pos_key(r["wallet"], r["condition_id"], r["outcome"]) for r in R}
    new, skips = 0, defaultdict(int)
    for wallet, name, _ in W:
        try:
            acts = rows(get(f"{DATA}/v2/activity?user={wallet}&type=TRADE&limit=100"))
        except Exception as e:
            print(f"fetch error {name}: {e}")
            continue
        hedged = two_sided(acts)
        for r in sorted(acts, key=ts_of):
            if not qualifies(r, now):
                continue
            cid, out = cid_of(r), f(r, "outcome")
            k = pos_key(wallet, cid, out)
            if k in have:
                continue
            if cid in hedged:
                skips["two-sided"] += 1
                have.add(k)
                continue
            p, tok = float(f(r, "price")), f(r, "asset", "token_id")
            try:
                ask = best_ask(tok) if tok else None
            except Exception:
                ask = None
            entry, why = pick_entry(p, ask)
            have.add(k)
            if entry is None:
                skips[why.split()[0]] += 1
                print(f"  skip {name[:18]} {out} @ {p:.2f} ({why}) | {f(r,'title')}")
                continue
            usd = float(f(r, "usdc_size", "usdcSize") or 0)
            R.append({"time": time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)), "whale": name,
                      "wallet": wallet, "title": f(r, "title"), "outcome": out, "condition_id": cid,
                      "whale_price": p, "entry": entry, "contracts": round(STAKE / entry, 4),
                      "usd": STAKE, "status": "OPEN", "pnl": "", "token_id": tok,
                      "whale_usd": round(usd), "entry_src": why, "ver": "v2"})
            new += 1
            print(f"[COPY] {name[:18]} BUY {out} whale@{p:.2f} us@{entry:.2f} ${usd:,.0f} | {f(r,'title')}")
        time.sleep(0.3)
    write_paper(R)
    print(f"new paper positions: {new} | skipped: {dict(skips)}")


# ---------- grade ----------

def resolve_clob(m):
    """CLOB /markets/{cid} -> {outcome: payout} once a winner is flagged, else None."""
    if not m or not m.get("closed"):
        return None
    toks = m.get("tokens") or []
    if not any(t.get("winner") for t in toks):
        return None
    return {t["outcome"]: (1.0 if t.get("winner") else 0.0) for t in toks}


def resolve_gamma(m):
    """gamma market -> {outcome: payout} if closed with final prices (1/0 or 0.5/0.5), else None."""
    if not m or not m.get("closed"):
        return None
    outs, ps = jl(m.get("outcomes")), [float(x) for x in jl(m.get("outcomePrices"))]
    if not outs or len(outs) != len(ps):
        return None
    final = max(ps) >= 0.99 or all(abs(p - 0.5) < 0.01 for p in ps)
    return dict(zip(outs, ps)) if final else None


def resolution(cid, debug=None):
    try:
        res = resolve_clob(get(f"{CLOB}/markets/{cid}"))
        if res:
            return res
    except Exception as e:
        if debug is not None:
            debug.append(f"clob {cid[:12]}: {e}")
    for q in ("&closed=true", ""):
        try:
            ms = rows(get(f"{GAMMA}/markets?condition_ids={cid}{q}"))
        except Exception as e:
            if debug is not None:
                debug.append(f"gamma {cid[:12]}: {e}")
            continue
        for m in ms:
            if str(m.get("conditionId", cid)).lower() == cid.lower():
                res = resolve_gamma(m)
                if res:
                    return res
    return None


def settle(r, res):
    """Return (status, pnl) for a row given {outcome: payout}, or None if outcome unknown."""
    if not res or r["outcome"] not in res:
        return None
    pay, usd = float(res[r["outcome"]]), float(r["usd"])
    pnl = round(float(r["contracts"]) * pay - usd, 2)
    return ("WON" if pay > 0.5 else "LOST" if pay < 0.5 else "VOID", pnl)


def grade():
    R = read_paper()
    cache, debug, newly = {}, [], 0
    for r in R:
        if r["status"] != "OPEN" or not r["condition_id"]:
            continue
        cid = r["condition_id"]
        if cid not in cache:
            cache[cid] = resolution(cid, debug)
            time.sleep(0.1)
        out = settle(r, cache[cid])
        if out:
            r["status"], r["pnl"] = out
            newly += 1
    print(f"checked {len(cache)} markets, settled {newly} rows")
    for d in debug[:5]:
        print("  debug:", d)
    if R:
        write_paper(R)
    write_summary(R)


# ---------- summary ----------

def clean(R):
    """One row per wallet+market+outcome, minus markets the wallet traded both sides of."""
    sides, firsts = defaultdict(set), {}
    for r in R:
        sides[(r["wallet"].lower(), r["condition_id"])].add(r["outcome"])
        firsts.setdefault(pos_key(r["wallet"], r["condition_id"], r["outcome"]), r)
    return [r for r in firsts.values() if len(sides[(r["wallet"].lower(), r["condition_id"])]) == 1]


def stats(R):
    done = [r for r in R if r["status"] in ("WON", "LOST", "VOID")]
    risked = sum(float(r["usd"]) for r in done)
    pnl = sum(float(r["pnl"]) for r in done)
    wins = sum(r["status"] == "WON" for r in done)
    return {"n": len(R), "settled": len(done), "open": len(R) - len(done), "wins": wins,
            "win_rate": wins / len(done) if done else 0.0, "pnl": pnl, "risked": risked,
            "roi": pnl / risked if risked else 0.0}


def verdict(s):
    if s["settled"] < MIN_SETTLED:
        return f"too early ({s['settled']}/{MIN_SETTLED} settled)"
    if s["roi"] > 0.05:
        return "POSITIVE - keep paper-trading to 150 before any real $"
    if s["roi"] >= 0:
        return "FLAT - no edge after spread"
    return "NEGATIVE - copying these whales loses money"


def summarize(R):
    C = clean(R)
    s = stats(C)
    per = defaultdict(lambda: [0, 0.0])
    for r in C:
        if r["status"] in ("WON", "LOST", "VOID"):
            per[r["whale"]][0] += 1
            per[r["whale"]][1] += float(r["pnl"])
    return {"raw": stats(R), "clean": s, "v2": stats([r for r in C if r.get("ver") == "v2"]),
            "per": {k: tuple(v) for k, v in per.items()}, "verdict": verdict(s)}


def line(label, s):
    return (f"| {label} | {s['n']} | {s['settled']} | {s['win_rate']:.0%} | "
            f"${s['pnl']:+.2f} | {s['roi']:+.1%} |")


def write_summary(R):
    S = summarize(R)
    L = ["# smart-money scoreboard (PAPER ONLY)", "",
         f"Updated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}", "",
         f"**Verdict: {S['verdict']}**", "",
         f"${STAKE:.0f} paper stake per copy. P/L is after paying the ask.", "",
         "| set | positions | settled | win rate | P/L | ROI |", "|---|---|---|---|---|---|",
         line("clean (verdict)", S["clean"]), line("v2 live-ask only", S["v2"]),
         line("raw rows (v1 dupes)", S["raw"]), "", "## P/L per whale (clean)"]
    per = sorted(S["per"].items(), key=lambda x: -x[1][1])
    L += [f"- {k[:28]}: ${v:+.2f} over {n}" for k, (n, v) in per] or ["- none settled yet"]
    os.makedirs(D, exist_ok=True)
    open(SUMMARY, "w").write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"scan": scan, "grade": grade}.get(cmd, lambda: print("usage: smart.py scan|grade"))()
