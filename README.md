# smart-money (paper only)

Copies the top 10 Polymarket wallets (30-day profit) with **fake $10 bets** and keeps score. Answers one question with receipts: *does copying whales actually make money?*

**Never places real orders. No keys, no secrets.**

How it decides (v2):
- Whale BUY of $500+ in the last 12h, price under 90c
- Skips markets where the whale bought both sides (market making, not a bet)
- One position per whale + market + outcome (no fill spam)
- Entry = the live best ask when the bot sees it (what you'd really pay), skipped if price already ran 5c+

Scoreboard: [`data/summary.md`](data/summary.md). Verdict means nothing under 50 settled.

- `python smart.py scan` - log new paper positions to `data/paper.csv`
- `python smart.py grade` - settle finished markets, rewrite the scoreboard
