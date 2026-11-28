import unittest
from decimal import Decimal

from services.parser import _normalize_rate, _rate_hint


class RateHintTests(unittest.TestCase):
    def assert_rate(self, text, amount, rate_type="total"):
        hint = _rate_hint(text)
        self.assertIsNotNone(hint)
        raw, kind, _ = hint
        self.assertEqual((raw, kind), (Decimal(str(amount)), rate_type))

    def test_plain_short_rate_is_total_thousands(self):
        self.assert_rate("тайшет айхал 200", 200)
        self.assertEqual(
            _normalize_rate(Decimal("200"), "total", None, None, [], "тайшет айхал 200"),
            Decimal("200000"),
        )

    def test_explicit_units(self):
        self.assert_rate("тайшет айхал 200 тыс", 200)
        self.assert_rate("тайшет айхал 200 р/км", 200, "per_km")
        self.assert_rate("калининград мхч 80 ндс", 80)

    def test_weight_and_date_are_not_rates(self):
        self.assertIsNone(_rate_hint("тайшет айхал 20т"))
        self.assertIsNone(_rate_hint("тайшет айхал 20/82"))
        self.assertIsNone(_rate_hint("тайшет айхал 27.11"))


if __name__ == "__main__":
    unittest.main()
