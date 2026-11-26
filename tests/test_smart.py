import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import smart

NOW = 1_800_000_000


def trade(**kw):
    t = {"side": "BUY", "price": 0.5, "usdc_size": 1000, "timestamp": NOW - 60,
         "transaction_hash": "0xa", "asset": "t1", "outcome": "Yes", "title": "X", "condition_id": "c"}
    t.update(kw)
    return t


def row(**kw):
    r = {"wallet": "0xA", "condition_id": "c", "outcome": "Yes", "whale": "a",
         "usd": "10", "contracts": "20", "status": "OPEN", "pnl": "", "ver": ""}
    r.update(kw)
    return r


class T(unittest.TestCase):
    def test_rows_shapes(self):
        self.assertEqual(smart.rows([1]), [1])
        self.assertEqual(smart.rows({"data": [2]}), [2])
        self.assertEqual(smart.rows({"x": 1}), [])

    def test_age_filter(self):
        self.assertTrue(smart.qualifies(trade(), NOW))
        self.assertTrue(smart.qualifies(trade(timestamp=NOW - 11 * 3600), NOW))
        self.assertFalse(smart.qualifies(trade(timestamp=NOW - 13 * 3600), NOW))
        self.assertTrue(smart.qualifies(trade(timestamp=(NOW - 60) * 1000), NOW))

    def test_filters(self):
        self.assertFalse(smart.qualifies(trade(side="SELL"), NOW))
        self.assertFalse(smart.qualifies(trade(usdc_size=499), NOW))
        self.assertFalse(smart.qualifies(trade(price=0.95), NOW))
        self.assertFalse(smart.qualifies(trade(price=0.01), NOW))

    def test_two_sided(self):
        acts = [trade(outcome="Yes"), trade(outcome="No"), trade(condition_id="d")]
        self.assertEqual(smart.two_sided(acts), {"c"})

    def test_pick_entry(self):
        self.assertEqual(smart.pick_entry(0.50, 0.52), (0.52, "live ask"))
        self.assertIsNone(smart.pick_entry(0.50, 0.56)[0])   # ran away
        self.assertIsNone(smart.pick_entry(0.88, 0.91)[0])   # too pricey
        self.assertIsNone(smart.pick_entry(0.50, None)[0])   # no book
        self.assertEqual(smart.pick_entry(0.50, 0.46)[0], 0.46)  # a bit cheaper is fine
        self.assertIsNone(smart.pick_entry(0.52, 0.03)[0])   # game already turned

    def test_resolve_clob(self):
        m = {"closed": True, "tokens": [{"outcome": "Yes", "winner": True}, {"outcome": "No", "winner": False}]}
        self.assertEqual(smart.resolve_clob(m), {"Yes": 1.0, "No": 0.0})
        self.assertIsNone(smart.resolve_clob({"closed": True, "tokens": [{"outcome": "Yes", "winner": False}]}))
        self.assertIsNone(smart.resolve_clob({"closed": False, "tokens": []}))

    def test_resolve_gamma(self):
        m = {"closed": True, "outcomes": '["Yes","No"]', "outcomePrices": '["1","0"]'}
        self.assertEqual(smart.resolve_gamma(m), {"Yes": 1.0, "No": 0.0})
        m["outcomePrices"] = '["0.5","0.5"]'
        self.assertEqual(smart.resolve_gamma(m), {"Yes": 0.5, "No": 0.5})
        m["outcomePrices"] = '["0.7","0.3"]'
        self.assertIsNone(smart.resolve_gamma(m))  # closed but not final
        self.assertIsNone(smart.resolve_gamma({"closed": False}))

    def test_settle(self):
        r = row()
        self.assertEqual(smart.settle(r, {"Yes": 1.0, "No": 0.0}), ("WON", 10.0))
        self.assertEqual(smart.settle(r, {"Yes": 0.0, "No": 1.0}), ("LOST", -10.0))
        self.assertEqual(smart.settle(r, {"Yes": 0.5, "No": 0.5}), ("VOID", 0.0))
        self.assertIsNone(smart.settle(r, None))
        self.assertIsNone(smart.settle(r, {"Over": 1.0}))

    def test_clean_dedupes_and_drops_two_sided(self):
        R = [row(), row(), row(condition_id="m", outcome="Yes"), row(condition_id="m", outcome="No"),
             row(wallet="0xa", condition_id="z")]
        C = smart.clean(R)
        self.assertEqual(sorted(r["condition_id"] for r in C), ["c", "z"])

    def test_summary_verdict(self):
        R = [row(status="WON", pnl="5"), row(condition_id="d")]
        s = smart.summarize(R)
        self.assertEqual((s["clean"]["settled"], s["clean"]["open"]), (1, 1))
        self.assertTrue(s["verdict"].startswith("too early"))
        lots = [row(condition_id=str(i), status="LOST", pnl="-10") for i in range(60)]
        self.assertTrue(smart.summarize(lots)["verdict"].startswith("NEGATIVE"))


if __name__ == "__main__":
    unittest.main()
