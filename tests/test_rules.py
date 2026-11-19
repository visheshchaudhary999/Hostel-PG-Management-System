"""Tests for the business rules in rules.py.   Run from the project folder:  python -m unittest -v"""
import unittest
from datetime import date

import rules


class RentRules(unittest.TestCase):
    def test_full_month_if_joined_before(self):
        self.assertEqual(rules.rent_for_month(7000, date(2026, 8, 20), "2026-11"), 7000)

    def test_first_month_is_prorated(self):
        # joined 16 Nov: 15 of 30 days
        self.assertEqual(rules.rent_for_month(7000, date(2026, 11, 16), "2026-11"), 3500)
        # joined 15 Feb 2026: 14 of 28 days
        self.assertEqual(rules.rent_for_month(6000, date(2026, 2, 15), "2026-02"), 3000)

    def test_proration_rounds_to_rupee(self):
        # 5500 x 18 / 31 = 3193.5 -> 3194
        self.assertEqual(rules.rent_for_month(5500, date(2026, 10, 14), "2026-10"), 3194)

    def test_no_rent_before_joining(self):
        self.assertEqual(rules.rent_for_month(7000, date(2026, 12, 1), "2026-11"), 0)

    def test_billable(self):
        self.assertTrue(rules.billable(date(2026, 1, 1), None, "2026-11"))
        self.assertTrue(rules.billable(date(2026, 1, 1), date(2026, 11, 3), "2026-11"))
        self.assertFalse(rules.billable(date(2026, 1, 1), date(2026, 10, 31), "2026-11"))
        self.assertFalse(rules.billable(date(2026, 12, 2), None, "2026-11"))

    def test_due_date_and_grace_for_new_residents(self):
        self.assertEqual(rules.due_date("2026-11"), date(2026, 11, 10))
        self.assertEqual(rules.due_date("2026-11", date(2026, 11, 3)), date(2026, 11, 10))
        self.assertEqual(rules.due_date("2026-11", date(2026, 11, 20)), date(2026, 11, 27))
        self.assertEqual(rules.due_date("2026-11", date(2026, 6, 20)), date(2026, 11, 10))

    def test_late_fee_only_once_and_only_when_unpaid_after_due(self):
        due = date(2026, 11, 10)
        self.assertFalse(rules.needs_late_fee(due, 5000, 0, date(2026, 11, 10)))   # on the due date: not late
        self.assertTrue(rules.needs_late_fee(due, 5000, 0, date(2026, 11, 11)))
        self.assertFalse(rules.needs_late_fee(due, 0, 0, date(2026, 11, 20)))      # paid
        self.assertFalse(rules.needs_late_fee(due, 5000, 200, date(2026, 11, 20)))  # already charged


class OtherRules(unittest.TestCase):
    def test_allocation(self):
        self.assertEqual(rules.can_allocate("Boys", 3, 2, "M"), (True, ""))
        self.assertEqual(rules.can_allocate("Boys", 3, 3, "M"), (False, "Room is full"))
        self.assertEqual(rules.can_allocate("Girls", 2, 0, "M"), (False, "Room is in the Girls block"))

    def test_settlement(self):
        self.assertEqual(rules.settlement(10000, 2500)["refund"], 7500)
        s = rules.settlement(8000, 9500)
        self.assertEqual((s["refund"], s["collect"]), (0, 1500))

    def test_months(self):
        self.assertTrue(rules.valid_month("2026-11"))
        self.assertFalse(rules.valid_month("2026-13"))
        self.assertFalse(rules.valid_month("2026-1"))
        self.assertEqual(rules.previous_month("2026-01"), "2025-12")
        self.assertEqual(rules.month_bounds("2028-02")[1], date(2028, 2, 29))

    def test_validation(self):
        self.assertTrue(rules.valid_phone("9876543210"))
        self.assertFalse(rules.valid_phone("1234567890"))
        self.assertFalse(rules.valid_phone("98765"))
        self.assertTrue(rules.valid_email("a.b@example.com"))
        self.assertFalse(rules.valid_email("a@b"))

    def test_receipt_and_occupancy(self):
        self.assertEqual(rules.receipt_no(42, date(2026, 11, 8)), "RCP-2026-00042")
        self.assertEqual(rules.occupancy_percent(22, 28), 79)
        self.assertEqual(rules.occupancy_percent(0, 0), 0)


if __name__ == "__main__":
    unittest.main()
