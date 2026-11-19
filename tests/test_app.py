"""Tests for the database operations and the web pages, on a fresh temporary database each time."""
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from werkzeug.security import generate_password_hash

import hostel
from app import create_app, rupees
from hostel import HostelError

TODAY = date(2026, 11, 15)


def person(name, gender="M", phone="9876500001", email=None):
    return {"name": name, "gender": gender, "phone": phone,
            "email": email or name.lower().replace(" ", ".") + "@example.com", "deposit": "10000"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "test.db")
        self.db = hostel.connect(self.path)
        hostel.init_db(self.db)
        self.db.execute("INSERT INTO users (email, password_hash, role) VALUES ('warden@test', ?, 'warden')",
                        (generate_password_hash("wardenpass"),))
        self.r_double = hostel.add_room(self.db, "101", "Boys", 1, 2, 7000, False)
        self.r_single = hostel.add_room(self.db, "102", "Boys", 1, 1, 9000, False)
        self.r_girls = hostel.add_room(self.db, "G1", "Girls", 1, 2, 7000, False)
        self.pw = generate_password_hash("residentpass")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def admit(self, name, room, joined=date(2026, 9, 1), **kw):
        return hostel.admit(self.db, person(name, **kw), room, joined, self.pw)


class Operations(Base):
    def test_room_fills_up_and_rejects_wrong_block(self):
        self.admit("Amit Kumar", self.r_double, phone="9876500001")
        self.admit("Ravi Kumar", self.r_double, phone="9876500002")
        with self.assertRaisesRegex(HostelError, "full"):
            self.admit("Third Person", self.r_double, phone="9876500003")
        with self.assertRaisesRegex(HostelError, "Girls block"):
            self.admit("Fourth Person", self.r_girls, phone="9876500004")
        self.assertEqual(hostel.room(self.db, self.r_double)["occupied"], 2)
        # the failed admissions left nothing behind
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM residents").fetchone()[0], 2)

    def test_duplicate_phone_and_bad_input(self):
        self.admit("Amit Kumar", self.r_double)
        with self.assertRaisesRegex(HostelError, "phone number already exists"):
            self.admit("Other Person", self.r_single)
        with self.assertRaisesRegex(HostelError, "10-digit"):
            self.admit("Other Person", self.r_single, phone="12345")
        with self.assertRaisesRegex(HostelError, "already exists"):
            hostel.add_room(self.db, "101", "Boys", 1, 2, 7000, False)

    def test_generate_bills_is_prorated_and_idempotent(self):
        a = self.admit("Amit Kumar", self.r_double, joined=date(2026, 9, 1), phone="9876500001")
        b = self.admit("Ravi Kumar", self.r_double, joined=date(2026, 11, 16), phone="9876500002")
        self.assertEqual(hostel.generate_invoices(self.db, "2026-11"), 2)
        self.assertEqual(hostel.generate_invoices(self.db, "2026-11"), 0)       # second click adds nothing
        bills = {i["resident_id"]: i for i in hostel.invoices(self.db, "2026-11")}
        self.assertEqual(bills[a]["rent"], 7000)
        self.assertEqual(bills[b]["rent"], 3500)
        self.assertEqual(bills[b]["due_on"], "2026-11-23")
        self.assertEqual(hostel.generate_invoices(self.db, "2026-10"), 1)       # Ravi had not joined in October

    def test_payments_partial_overpay_and_late_fee(self):
        a = self.admit("Amit Kumar", self.r_double)
        hostel.generate_invoices(self.db, "2026-11")
        inv = hostel.invoices(self.db, "2026-11")[0]
        hostel.record_payment(self.db, inv["id"], 3000, "UPI", date(2026, 11, 5))
        with self.assertRaisesRegex(HostelError, "more than the balance"):
            hostel.record_payment(self.db, inv["id"], 4500, "Cash", date(2026, 11, 6))
        self.assertEqual(hostel.apply_late_fees(self.db, date(2026, 11, 10)), 0)   # not late yet
        self.assertEqual(hostel.apply_late_fees(self.db, date(2026, 11, 11)), 1)
        self.assertEqual(hostel.apply_late_fees(self.db, date(2026, 11, 20)), 0)   # only once
        self.assertEqual(hostel.outstanding(self.db, a), 4200)
        pid = hostel.record_payment(self.db, inv["id"], 4200, "Cash", date(2026, 11, 12))
        self.assertEqual(hostel.outstanding(self.db, a), 0)
        self.assertEqual(hostel.payment(self.db, pid)["receipt_no"], f"RCP-2026-{pid:05d}")
        with self.assertRaisesRegex(HostelError, "already paid"):
            hostel.record_payment(self.db, inv["id"], 1, "Cash", date(2026, 11, 12))

    def test_paid_bill_gets_no_late_fee(self):
        self.admit("Amit Kumar", self.r_double)
        hostel.generate_invoices(self.db, "2026-11")
        inv = hostel.invoices(self.db, "2026-11")[0]
        hostel.record_payment(self.db, inv["id"], 7000, "UPI", date(2026, 11, 9))
        self.assertEqual(hostel.apply_late_fees(self.db, date(2026, 11, 30)), 0)

    def test_shift_room(self):
        a = self.admit("Amit Kumar", self.r_double, phone="9876500001")
        self.admit("Ravi Kumar", self.r_single, phone="9876500002")
        with self.assertRaisesRegex(HostelError, "full"):
            hostel.shift_room(self.db, a, self.r_single)
        with self.assertRaisesRegex(HostelError, "already"):
            hostel.shift_room(self.db, a, self.r_double)
        r103 = hostel.add_room(self.db, "103", "Boys", 1, 2, 7000, False)
        self.assertEqual(hostel.shift_room(self.db, a, r103), "103")
        self.assertEqual(hostel.room(self.db, self.r_double)["occupied"], 0)
        self.assertEqual(hostel.room(self.db, r103)["occupied"], 1)

    def test_vacate_bills_leaving_month_and_settles_deposit(self):
        a = self.admit("Amit Kumar", self.r_single)
        hostel.generate_invoices(self.db, "2026-10")
        inv = hostel.invoices(self.db, "2026-10")[0]
        hostel.record_payment(self.db, inv["id"], 9000, "UPI", date(2026, 10, 5))
        result = hostel.vacate(self.db, a, date(2026, 11, 5))
        self.assertEqual(result, {"deposit": 10000, "outstanding": 9000, "refund": 1000, "collect": 0})
        self.assertEqual(hostel.room(self.db, self.r_single)["occupied"], 0)
        self.assertEqual(hostel.generate_invoices(self.db, "2026-12"), 0)        # no bills after leaving
        with self.assertRaisesRegex(HostelError, "already left"):
            hostel.vacate(self.db, a, date(2026, 11, 6))

    def test_complaint_validation(self):
        a = self.admit("Amit Kumar", self.r_single)
        with self.assertRaisesRegex(HostelError, "at least 10"):
            hostel.add_complaint(self.db, a, "Plumbing", "leak", TODAY)
        with self.assertRaisesRegex(HostelError, "category"):
            hostel.add_complaint(self.db, a, "Spaceship", "it is broken badly", TODAY)
        cid = hostel.add_complaint(self.db, a, "Plumbing", "Tap is leaking in the bathroom", TODAY)
        hostel.update_complaint(self.db, cid, "resolved", "Washer replaced", TODAY)
        c = hostel.complaints(self.db, resident_id=a)[0]
        self.assertEqual((c["status"], c["resolved_on"]), ("resolved", "2026-11-15"))

    def test_dashboard(self):
        self.admit("Amit Kumar", self.r_double)
        s = hostel.dashboard(self.db, TODAY)
        self.assertEqual((s["beds"], s["occupied"], s["vacant"], s["occupancy"]), (5, 1, 4, 20))

    def test_rupees_format(self):
        self.assertEqual(rupees(125000), "₹1,25,000")
        self.assertEqual(rupees(999), "₹999")


class Pages(Base):
    def setUp(self):
        super().setUp()
        self.amit = self.admit("Amit Kumar", self.r_double, phone="9876500001")
        self.ravi = self.admit("Ravi Kumar", self.r_double, phone="9876500002")
        hostel.generate_invoices(self.db, "2026-11")
        self.app = create_app({"DATABASE": self.path, "TODAY": TODAY, "TESTING": True, "SECRET_KEY": "test"})
        self.client = self.app.test_client()

    def csrf(self, path):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)

    def login(self, email, password):
        token = self.csrf("/login")
        return self.client.post("/login", data={"email": email, "password": password, "csrf": token},
                                follow_redirects=True)

    def test_pages_need_login_and_role(self):
        self.assertIn("/login", self.client.get("/warden").headers["Location"])
        self.login("amit.kumar@example.com", "residentpass")
        self.assertEqual(self.client.get("/warden").status_code, 403)
        self.assertEqual(self.client.get("/warden/dues").status_code, 403)

    def test_wrong_password(self):
        self.assertIn("Wrong email or password", self.login("warden@test", "nope").get_data(as_text=True))

    def test_post_without_csrf_is_rejected(self):
        self.login("warden@test", "wardenpass")
        r = self.client.post("/warden/rooms", data={"number": "999", "block": "Boys", "floor": 1, "capacity": 1,
                                                    "rent": 5000})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(self.db.execute("SELECT id FROM rooms WHERE number = '999'").fetchone())

    def test_warden_flow(self):
        page = self.login("warden@test", "wardenpass").get_data(as_text=True)
        self.assertIn("occupancy", page)
        self.assertIn("40%", page)                                   # 2 of 5 beds
        token = self.csrf("/warden/dues")
        inv = hostel.invoices(self.db, "2026-11", resident_id=self.amit)[0]
        r = self.client.post(f"/warden/invoices/{inv['id']}/pay", data={"amount": 7200, "mode": "UPI", "csrf": token},
                             follow_redirects=True)
        page = r.get_data(as_text=True)
        self.assertIn("Rent receipt", page)                          # late fee was added: 7000 + 200
        self.assertIn("₹7,200", page)
        csv = self.client.get("/warden/dues.csv?month=2026-11").get_data(as_text=True)
        self.assertIn("Amit Kumar", csv)
        self.assertIn(",7200,7200,0,", csv)

    def test_admit_through_form_rejects_full_room(self):
        self.login("warden@test", "wardenpass")
        token = self.csrf("/warden/residents/new")
        r = self.client.post("/warden/residents/new", data={**person("New Boy", phone="9876500009"),
                             "room_id": self.r_double, "joined_on": "2026-11-15", "password": "longenough",
                             "csrf": token}, follow_redirects=True)
        self.assertIn("Room 101: Room is full", r.get_data(as_text=True))

    def test_resident_portal_and_privacy(self):
        page = self.login("amit.kumar@example.com", "residentpass").get_data(as_text=True)
        self.assertIn("Hello, Amit", page)
        self.assertIn("Ravi Kumar", page)                             # roommate
        token = self.csrf("/me")
        r = self.client.post("/me", data={"category": "Wi-Fi", "description": "<b>No internet</b> since morning",
                                          "csrf": token}, follow_redirects=True)
        page = r.get_data(as_text=True)
        self.assertIn("&lt;b&gt;No internet&lt;/b&gt;", page)        # escaped, not bold
        # Ravi's receipt is not visible to Amit
        inv = hostel.invoices(self.db, "2026-11", resident_id=self.ravi)[0]
        pid = hostel.record_payment(self.db, inv["id"], 1000, "Cash", TODAY)
        self.assertEqual(self.client.get(f"/receipt/{pid}").status_code, 404)

    def test_left_resident_cannot_log_in(self):
        hostel.vacate(self.db, self.ravi, TODAY)
        page = self.login("ravi.kumar@example.com", "residentpass").get_data(as_text=True)
        self.assertIn("account is closed", page)


if __name__ == "__main__":
    unittest.main()
