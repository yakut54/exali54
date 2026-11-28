import unittest
from decimal import Decimal

from services.calculations.calculator import calculate_margin, rate_breakdown_by_vat


class CalculatorTests(unittest.TestCase):
    def test_rate_breakdown(self):
        result = rate_breakdown_by_vat(Decimal("200000"), False, 2201)
        self.assertEqual(result["with_vat"], Decimal("244000.00"))
        self.assertEqual(result["with_vat_per_km"], Decimal("110.9"))

    def test_agent_margin(self):
        result = calculate_margin(
            "usn_6_agent", Decimal("200000"), Decimal("150000")
        )
        self.assertEqual(result.net_profit, Decimal("47000.00"))
        self.assertEqual(result.stop_price, Decimal("150000.00"))

    def test_invalid_rates_are_rejected(self):
        with self.assertRaises(ValueError):
            calculate_margin("usn_6", Decimal("0"), Decimal("100"))


if __name__ == "__main__":
    unittest.main()
