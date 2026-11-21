import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import smart

NOW = 1_800_000_000


def trade(**kw):
    t = {"side": "BUY", "price": 0.5, "usdc_size": 1000, "timestamp": NOW - 60,
         "transaction_hash": "0xa", "token_id": "t1", "outcome": "Yes", "title": "X", "condition_id": "c"}
    t.update(kw)
    return t


class T(unittest.TestCase):
    def test_rows_shapes(self):
        self.assertEqual(smart.rows([1]), [1])
        self.assertEqual(smart.rows({"data": [2]}), [2])
        self.assertEqual(smart.rows({"x": 1}), [])

    def test_dedupe_key(self):
        self.assertEqual(smart.trade_key(trade()), smart.trade_key(trade()))
        self.assertNotEqual(smart.trade_key(trade()), smart.trade_key(trade(price=0.6)))

    def test_age_filter(self):
        self.assertTrue(smart.qualifies(trade(), NOW))
        self.assertFalse(smart.qualifies(trade(timestamp=NOW - 31 * 60), NOW))
        self.assertTrue(smart.qualifies(trade(timestamp=(NOW - 60) * 1000), NOW))

    def test_filters(self):
        self.assertFalse(smart.qualifies(trade(side="SELL"), NOW))
        self.assertFalse(smart.qualifies(trade(usdc_size=499), NOW))
        self.assertFalse(smart.qualifies(trade(price=0.97), NOW))

    def test_entry(self):
        self.assertAlmostEqual(smart.entry_price(0.5), 0.52)
        self.assertEqual(smart.entry_price(0.98), 0.99)

    def test_settle(self):
        r = {"outcome": "Yes", "contracts": "20", "usd": "10"}
        m = {"closed": True, "outcomes": '["Yes","No"]', "outcomePrices": '["1","0"]'}
        self.assertEqual(smart.settle(r, m), ("WON", 10.0))
        m["outcomePrices"] = '["0","1"]'
        self.assertEqual(smart.settle(r, m), ("LOST", -10.0))
        self.assertIsNone(smart.settle(r, {"closed": False}))

    def test_summary_verdict(self):
        R = [{"status": "WON", "pnl": "5", "whale": "a"}, {"status": "OPEN", "pnl": "", "whale": "a"}]
        s = smart.summarize(R)
        self.assertEqual((s["settled"], s["open"], s["verdict"]), (1, 1, "need 50+ settled"))


if __name__ == "__main__":
    unittest.main()
