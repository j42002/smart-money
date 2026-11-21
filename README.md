# smart-money (paper only)

Watches the top 10 Polymarket wallets (30-day profit) every 15 minutes and paper-trades $10 on each new BUY of $500+, entering 2 cents worse than the whale. Grades settled markets and writes `data/summary.md`.

**Never places real orders. No keys, no secrets.**

- `python smart.py scan` - one pass, logs new paper trades to `data/paper.csv`
- `python smart.py grade` - settles closed markets, writes `data/summary.md`
