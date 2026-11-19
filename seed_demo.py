"""Creates hostel.db with demo data so the app can be shown straight away.

    python seed_demo.py            (deletes and recreates hostel.db)

Logins: warden@hostel.local / warden123, and every resident with their email / resident123
(for example rohan.mehta@example.com). All names, numbers and addresses are made up.
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

import hostel
import rules

ROOMS = [  # number, block, floor, beds, rent, ac
    ("101", "Boys", 1, 3, 5500, 0), ("102", "Boys", 1, 3, 5500, 0), ("103", "Boys", 1, 2, 7000, 0),
    ("104", "Boys", 1, 1, 9000, 0), ("201", "Boys", 2, 2, 8500, 1), ("202", "Boys", 2, 2, 7000, 0),
    ("203", "Boys", 2, 3, 5500, 0), ("204", "Boys", 2, 1, 10500, 1),
    ("G101", "Girls", 1, 2, 7000, 0), ("G102", "Girls", 1, 3, 5500, 0), ("G103", "Girls", 1, 1, 9000, 0),
    ("G201", "Girls", 2, 2, 8500, 1), ("G202", "Girls", 2, 2, 7000, 0), ("G203", "Girls", 2, 1, 10500, 1),
]

# name, gender, course, room, days since joining
PEOPLE = [
    ("Rohan Mehta", "M", "B.Tech CSE, 2nd year", "101", 400), ("Arjun Yadav", "M", "B.Tech ME, 3rd year", "101", 380),
    ("Kunal Sharma", "M", "BCA, 1st year", "101", 95),
    ("Vivek Tiwari", "M", "B.Tech ECE, 2nd year", "102", 300), ("Aman Gupta", "M", "B.Tech CE, 4th year", "102", 520),
    ("Siddharth Rao", "M", "MBA, 1st year", "103", 70), ("Harsh Vardhan", "M", "B.Tech IT, 3rd year", "103", 250),
    ("Nikhil Pandey", "M", "M.Tech CSE, 1st year", "104", 120),
    ("Rahul Singh", "M", "B.Tech EE, 2nd year", "201", 200), ("Deepak Verma", "M", "B.Pharm, 3rd year", "201", 180),
    ("Ankit Mishra", "M", "B.Tech CSE, 1st year", "202", 40),
    ("Yash Saxena", "M", "B.Tech CSE, 4th year", "203", 600), ("Prateek Jain", "M", "BBA, 2nd year", "203", 330),
    ("Priya Kumari", "F", "B.Tech CSE, 2nd year", "G101", 390), ("Neha Chauhan", "F", "B.Tech IT, 2nd year", "G101", 390),
    ("Sneha Gupta", "F", "MCA, 1st year", "G102", 110), ("Ananya Tripathi", "F", "B.Tech ECE, 3rd year", "G102", 260),
    ("Pooja Rawat", "F", "B.Sc Nursing, 1st year", "G102", 25),
    ("Kavya Srivastava", "F", "B.Tech CSE, 4th year", "G103", 610),
    ("Riya Agarwal", "F", "B.Tech ME, 2nd year", "G201", 150), ("Ishita Bansal", "F", "BBA, 3rd year", "G201", 340),
    ("Simran Kaur", "F", "B.Tech CE, 1st year", "G202", 60),
]

LEAVER = ("Manish Dubey", "M", "B.Tech EE, 4th year", "204", 420, 30)   # left 30 days ago

COMPLAINTS = [
    ("Rohan Mehta", "Electrical", "The tube light in room 101 flickers and goes off at night.", 9, "resolved", "Choke replaced."),
    ("Priya Kumari", "Wi-Fi", "Wi-Fi on the first floor of the girls block drops every evening between 8 and 11 pm.", 4, "in_progress", "Router ordered, will be installed this week."),
    ("Vivek Tiwari", "Plumbing", "The tap in the second bathroom on floor 1 keeps leaking.", 3, "open", ""),
    ("Sneha Gupta", "Cleaning", "Corridor outside G102 has not been mopped for two days.", 2, "open", ""),
    ("Rahul Singh", "Furniture", "One study chair in room 201 has a broken leg.", 1, "open", ""),
    ("Kavya Srivastava", "Mess / food", "Dinner was served after 9:30 pm on Sunday. Please keep to the time table.", 12, "resolved", "Spoken to the mess contractor."),
]

NOTICES = [
    ("Rent for this month", "Please pay this month's rent by the 10th. A late fee of ₹200 is added to bills unpaid after the due date.", 2),
    ("Water tank cleaning on Sunday", "Water supply will be off from 10 am to 2 pm on Sunday for tank cleaning. Please store water.", 5),
    ("Gate timings", "The main gate closes at 10:30 pm. Late entry needs prior permission from the warden.", 20),
]


def phone_for(i):
    return f"9{(812345678 + i * 7919) % 10**9:09d}"


def main(path=None, today=None):
    path = Path(path or Path(__file__).with_name("hostel.db"))
    today = today or date.today()
    rng = random.Random(7)
    if path.exists():
        path.unlink()
    db = hostel.connect(str(path))
    hostel.init_db(db)
    db.execute("INSERT INTO users (email, password_hash, role) VALUES (?, ?, 'warden')",
               ("warden@hostel.local", generate_password_hash("warden123")))
    room_ids = {}
    for number, block, floor, beds, rent, ac in ROOMS:
        room_ids[number] = hostel.add_room(db, number, block, floor, beds, rent, ac)

    resident_pw = generate_password_hash("resident123")
    ids = {}
    for i, (name, gender, course, number, days) in enumerate(PEOPLE + [LEAVER[:5]]):
        first, last = name.lower().split()[0], name.lower().split()[-1]
        form = {"name": name, "gender": gender, "phone": phone_for(i), "email": f"{first}.{last}@example.com",
                "course": course, "guardian_name": f"Mr. {name.split()[-1]}", "guardian_phone": phone_for(i + 50),
                "address": rng.choice(["Lucknow", "Kanpur", "Prayagraj", "Varanasi", "Gorakhpur", "Agra", "Bareilly",
                                       "Jhansi", "Meerut", "Ayodhya"]) + ", Uttar Pradesh",
                "deposit": 10000 if days > 60 else 8000}
        ids[name] = hostel.admit(db, form, room_ids[number], today - timedelta(days=days), resident_pw)

    # Bills for the last four months, then payments: older months fully paid, recent ones partly.
    month = rules.month_of(today)
    months = [month]
    for _ in range(3):
        months.insert(0, rules.previous_month(months[0]))
    late_payers = {"Kunal Sharma", "Harsh Vardhan", "Ankit Mishra", "Pooja Rawat"}
    leaver_id, left_on = ids[LEAVER[0]], today - timedelta(days=LEAVER[5])
    for n, m in enumerate(months):
        hostel.generate_invoices(db, m)
        for inv in hostel.invoices(db, m):
            due = date.fromisoformat(inv["due_on"])
            if m == month:
                # this month: about half have paid so far, but only if the 1st has passed
                if inv["name"] in late_payers or (inv["resident_id"] + n) % 3 == 0:
                    continue
                paid_on = min(today, due - timedelta(days=rng.randint(0, 6)))
            elif m == months[-2] and inv["name"] in late_payers:
                if inv["name"] == "Harsh Vardhan":       # paid half last month
                    hostel.record_payment(db, inv["id"], inv["total"] // 2, "UPI", due - timedelta(days=1))
                continue
            else:
                paid_on = due - timedelta(days=rng.randint(0, 8))
            hostel.record_payment(db, inv["id"], inv["total"], rng.choice(["UPI", "UPI", "Cash", "Bank transfer"]),
                                  max(paid_on, rules.month_bounds(m)[0]))
        if m == rules.month_of(left_on):           # the leaver checks out after paying; deposit refunded
            hostel.vacate(db, leaver_id, left_on)
            for inv in hostel.invoices(db, resident_id=leaver_id, unpaid_only=True):
                hostel.record_payment(db, inv["id"], inv["total"] - inv["paid"], "Cash", left_on)
    hostel.apply_late_fees(db, today)

    for name, cat, text, ago, status, remark in COMPLAINTS:
        cid = hostel.add_complaint(db, ids[name], cat, text, today - timedelta(days=ago))
        if status != "open":
            hostel.update_complaint(db, cid, status, remark, today - timedelta(days=max(ago - 2, 0)))
    for title, body, ago in NOTICES:
        hostel.add_notice(db, title, body, today - timedelta(days=ago))
    db.close()
    print(f"Created {path.name}: {len(ROOMS)} rooms, {len(PEOPLE)} current residents, bills for {', '.join(months)}.")
    print("Log in as warden@hostel.local / warden123, or rohan.mehta@example.com / resident123.")


if __name__ == "__main__":
    main(today=date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None)
