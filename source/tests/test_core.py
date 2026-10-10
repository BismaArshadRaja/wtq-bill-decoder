"""Offline unit tests (no API calls): python -m unittest discover tests"""
import unittest

from billdecoder.calc import safe_eval
from billdecoder.normalize import (LEVEL1_FIELDS, consistency_issues, normalize_level1,
                                   to_iso_date, to_month, to_number)


class TestNormalize(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(to_number("Rs. 19,964"), 19964)
        self.assertEqual(to_number("38209CR"), -38209)
        self.assertEqual(to_number("-0.53"), -0.53)
        self.assertIsNone(to_number(""))

    def test_dates(self):
        self.assertEqual(to_iso_date("22nd Sep 2026"), "2026-09-22")
        self.assertEqual(to_iso_date("03-Apr-26"), "2026-04-03")
        self.assertEqual(to_iso_date("21/04/2026"), "2026-04-21")
        self.assertEqual(to_month("MAR 2026"), "2026-03")
        self.assertEqual(to_month("Apr-26"), "2026-04")

    def test_schema_and_rules(self):
        raw = {"charges": [{"type": "energy", "amount": "1,054"}, {"type": "fixed", "amount": 0},
                           {"type": "subsidy", "amount": 300}, {"type": "weird", "amount": 5}],
               "taxes": [{"type": "GST", "amount": 520.21}],
               "payable_after_due_date": ["3,574", "3,716"]}
        j = normalize_level1(raw, "KESC_0008")
        self.assertEqual(list(j), LEVEL1_FIELDS)
        self.assertEqual(j["provider"], "KE")
        self.assertEqual(j["charges"], [{"type": "energy", "amount": 1054},
                                        {"type": "subsidy", "amount": -300},
                                        {"type": "other", "amount": 5}])
        self.assertEqual(j["taxes"], [{"type": "gst", "amount": 520.21}])
        self.assertEqual(j["payable_after_due_date"], 3716)

    def test_consistency(self):
        j = normalize_level1({"charges": [{"type": "energy", "amount": 100}],
                              "total_charges": 500}, "LESCO_1")
        self.assertTrue(consistency_issues(j))


class TestCalc(unittest.TestCase):
    def test_eval(self):
        self.assertAlmostEqual(safe_eval("569.62 / 3430.24 * 100"), 16.6058, places=3)
        self.assertEqual(safe_eval("max(239, 203, 151)"), 239)
        self.assertEqual(safe_eval("len([239, 203])"), 2)

    def test_rejects_code(self):
        for bad in ("__import__('os')", "open('x')", "(1).__class__"):
            with self.assertRaises(Exception):
                safe_eval(bad)


if __name__ == "__main__":
    unittest.main()
