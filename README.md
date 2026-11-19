# Hostel and PG Management System

A web application for running a hostel or paying-guest (PG) house: rooms and beds, residents, monthly rent with
late fees and receipts, complaints and a notice board. The warden manages everything; each resident has their own
login to see their room, dues and complaints.

Built with Python, Flask and SQLite. No other services are needed.

## Run it

1. Install Python 3.10 or newer from python.org (tick "Add python.exe to PATH").
2. Open a terminal in this folder and run:

   ```
   python -m venv venv
   venv\Scripts\activate            (on Linux or macOS: source venv/bin/activate)
   pip install -r requirements.txt
   python seed_demo.py
   python app.py
   ```

3. Open http://127.0.0.1:5000

| Login | Email | Password |
|---|---|---|
| Warden | warden@hostel.local | warden123 |
| Resident | rohan.mehta@example.com (or any resident's email) | resident123 |

`seed_demo.py` deletes and recreates `hostel.db` with 14 rooms, 22 residents, four months of rent bills and payments,
complaints and notices, all dated relative to today. All names and numbers are made up.

## Run the tests

```
python -m unittest -v
```

29 tests: the rent rules (proration, due dates, late fee), allocation, payments, check-out, logins, roles, CSRF
and HTML escaping.

## The rules it follows

| Rule | Where |
|---|---|
| Boys get beds only in the Boys block, girls only in the Girls block, and never more people than beds | `rules.can_allocate` |
| Rent is due by the 10th. The month someone joins is charged only for the days they stay, and is due 7 days after joining if that is later | `rules.rent_for_month`, `rules.due_date` |
| A ₹200 late fee is added once to a bill still unpaid after its due date | `rules.needs_late_fee`, `hostel.apply_late_fees` |
| A payment can be partial but never more than the balance; each gets a receipt number | `hostel.record_payment` |
| The month someone leaves is charged in full; dues are taken from the deposit and the rest refunded | `hostel.vacate`, `rules.settlement` |
| Generating bills twice for a month never double-bills anyone | `UNIQUE (resident_id, month)` + `INSERT OR IGNORE` |

All the rules are constants at the top of `rules.py`, so you can change them for your own hostel.

## Files

| File | What it does |
|---|---|
| `app.py` | Flask routes, login, roles (warden and resident) and CSRF protection |
| `hostel.py` | All database work: rooms, admissions, bills, payments, check-out, complaints, dashboard figures |
| `rules.py` | The business rules as plain functions, tested on their own |
| `schema.sql` | The seven tables with their constraints |
| `seed_demo.py` | Demo data |
| `templates/` | Jinja2 pages; `base.html` is the layout |
| `static/style.css` | The design, including the room map and the print layout for receipts |
| `tests/` | Unit and page tests |

## Security

- Passwords are stored as salted hashes (Werkzeug), never as plain text.
- Every form carries a CSRF token that is checked on each POST.
- All SQL uses `?` parameters, so input can't change a query.
- Jinja2 escapes everything it prints, so text such as `<script>` in a complaint shows as text.
- Residents only reach `/me` and their own receipts; warden pages return 403 to them.
- A resident who has checked out can no longer log in.
- Bed allocation, payments and check-out run inside `BEGIN IMMEDIATE` transactions, so two wardens working at the
  same moment can't give away the same last bed or overpay a bill.

Set a fixed `SECRET_KEY` environment variable when you deploy, so logins survive a restart.
