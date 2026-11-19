"""Database operations. Every function takes an open sqlite3 connection, so the web app and the tests share them."""
import sqlite3
from datetime import date
from pathlib import Path

import rules

SCHEMA = Path(__file__).with_name("schema.sql")


class HostelError(Exception):
    """A rule was broken; the message is shown to the user."""


def connect(path):
    db = sqlite3.connect(path, detect_types=0, isolation_level=None)   # autocommit; we open transactions ourselves
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db(db):
    db.executescript(SCHEMA.read_text(encoding="utf-8"))


def d(text):
    return date.fromisoformat(text) if text else None


# ---- Rooms -----------------------------------------------------------------------

ROOMS_SQL = """
    SELECT r.*, COUNT(s.id) AS occupied
    FROM rooms r LEFT JOIN residents s ON s.room_id = r.id AND s.status = 'active'
    {where}
    GROUP BY r.id ORDER BY r.block, r.number
"""


def rooms(db, block=None):
    if block:
        return db.execute(ROOMS_SQL.format(where="WHERE r.block = ?"), (block,)).fetchall()
    return db.execute(ROOMS_SQL.format(where="")).fetchall()


def room(db, room_id):
    return db.execute(ROOMS_SQL.format(where="WHERE r.id = ?"), (room_id,)).fetchone()


def add_room(db, number, block, floor, capacity, rent, ac):
    number = number.strip().upper()
    if not number:
        raise HostelError("Enter a room number")
    if block not in ("Boys", "Girls"):
        raise HostelError("Choose a block")
    if not 1 <= capacity <= 4:
        raise HostelError("A room has 1 to 4 beds")
    if rent <= 0:
        raise HostelError("Rent must be more than zero")
    try:
        cur = db.execute("INSERT INTO rooms (number, block, floor, capacity, rent, ac) VALUES (?, ?, ?, ?, ?, ?)",
                         (number, block, floor, capacity, rent, 1 if ac else 0))
    except sqlite3.IntegrityError:
        raise HostelError(f"Room {number} already exists")
    return cur.lastrowid


def vacant_rooms_for(db, gender):
    block = rules.BLOCK_FOR[gender]
    return [r for r in rooms(db, block) if r["occupied"] < r["capacity"]]


def occupants(db, room_id):
    return db.execute("SELECT id, name, course FROM residents WHERE room_id = ? AND status = 'active' ORDER BY name",
                      (room_id,)).fetchall()


def _check_room(db, room_id, gender, exclude_resident=None):
    """Raises HostelError unless the room has a free bed for this gender. Call inside a transaction."""
    r = db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if r is None:
        raise HostelError("No such room")
    occupied = db.execute("SELECT COUNT(*) FROM residents WHERE room_id = ? AND status = 'active' AND id IS NOT ?",
                          (room_id, exclude_resident)).fetchone()[0]
    ok, reason = rules.can_allocate(r["block"], r["capacity"], occupied, gender)
    if not ok:
        raise HostelError(f"Room {r['number']}: {reason}")
    return r


# ---- Residents -------------------------------------------------------------------

def admit(db, form, room_id, joined_on, password_hash):
    """Admits a new resident into a room and creates their login. form holds the personal details."""
    name = form.get("name", "").strip()
    gender = form.get("gender")
    phone = form.get("phone", "").strip()
    email = form.get("email", "").strip().lower()
    if len(name) < 2:
        raise HostelError("Enter the resident's full name")
    if gender not in rules.BLOCK_FOR:
        raise HostelError("Choose male or female")
    if not rules.valid_phone(phone):
        raise HostelError("Enter a 10-digit mobile number")
    if not rules.valid_email(email):
        raise HostelError("Enter a valid email address")
    guardian_phone = form.get("guardian_phone", "").strip()
    if guardian_phone and not rules.valid_phone(guardian_phone):
        raise HostelError("Enter a 10-digit mobile number for the guardian")
    deposit = int(form.get("deposit") or 0)
    if deposit < 0:
        raise HostelError("Deposit cannot be negative")
    db.execute("BEGIN IMMEDIATE")         # lock: two wardens can't give away the same last bed
    try:
        _check_room(db, room_id, gender)
        cur = db.execute(
            """INSERT INTO residents (name, gender, phone, email, course, guardian_name, guardian_phone, address,
                                      room_id, joined_on, deposit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, gender, phone, email, form.get("course", "").strip(), form.get("guardian_name", "").strip(),
             guardian_phone, form.get("address", "").strip(), room_id, joined_on.isoformat(), deposit))
        resident_id = cur.lastrowid
        db.execute("INSERT INTO users (email, password_hash, role, resident_id) VALUES (?, ?, 'resident', ?)",
                   (email, password_hash, resident_id))
        db.execute("COMMIT")
        return resident_id
    except sqlite3.IntegrityError as e:
        db.execute("ROLLBACK")
        field = "phone number" if "phone" in str(e) else "email"
        raise HostelError(f"A resident with this {field} already exists")
    except Exception:
        db.execute("ROLLBACK")
        raise


def resident(db, resident_id):
    return db.execute("""SELECT s.*, r.number AS room_number, r.block, r.rent, r.capacity
                         FROM residents s LEFT JOIN rooms r ON r.id = s.room_id WHERE s.id = ?""",
                      (resident_id,)).fetchone()


def residents(db, q="", status="active"):
    sql = """SELECT s.*, r.number AS room_number, r.block,
                    COALESCE((SELECT SUM(i.rent + i.late_fee) FROM invoices i WHERE i.resident_id = s.id), 0)
                  - COALESCE((SELECT SUM(p.amount) FROM payments p JOIN invoices i ON i.id = p.invoice_id
                              WHERE i.resident_id = s.id), 0) AS balance
             FROM residents s LEFT JOIN rooms r ON r.id = s.room_id WHERE 1 = 1"""
    args = []
    if status in ("active", "left"):
        sql += " AND s.status = ?"
        args.append(status)
    if q:
        sql += " AND (s.name LIKE ? OR s.phone LIKE ? OR s.course LIKE ? OR r.number LIKE ?)"
        args += [f"%{q}%"] * 4
    return db.execute(sql + " ORDER BY s.name", args).fetchall()


def shift_room(db, resident_id, room_id):
    db.execute("BEGIN IMMEDIATE")
    try:
        s = db.execute("SELECT * FROM residents WHERE id = ?", (resident_id,)).fetchone()
        if s is None or s["status"] != "active":
            raise HostelError("Only a current resident can change rooms")
        if s["room_id"] == room_id:
            raise HostelError("The resident is already in this room")
        r = _check_room(db, room_id, s["gender"], exclude_resident=resident_id)
        db.execute("UPDATE residents SET room_id = ? WHERE id = ?", (room_id, resident_id))
        db.execute("COMMIT")
        return r["number"]
    except Exception:
        db.execute("ROLLBACK")
        raise


def outstanding(db, resident_id):
    billed = db.execute("SELECT COALESCE(SUM(rent + late_fee), 0) FROM invoices WHERE resident_id = ?",
                        (resident_id,)).fetchone()[0]
    paid = db.execute("""SELECT COALESCE(SUM(p.amount), 0) FROM payments p JOIN invoices i ON i.id = p.invoice_id
                         WHERE i.resident_id = ?""", (resident_id,)).fetchone()[0]
    return billed - paid


def vacate(db, resident_id, left_on):
    """Checks a resident out: bills the leaving month in full if it hasn't been billed, frees the bed and returns
    the deposit settlement."""
    s = resident(db, resident_id)
    if s is None or s["status"] != "active":
        raise HostelError("This resident has already left")
    if left_on < d(s["joined_on"]):
        raise HostelError("Leaving date is before the joining date")
    db.execute("BEGIN IMMEDIATE")
    try:
        month = rules.month_of(left_on)
        db.execute("""INSERT OR IGNORE INTO invoices (resident_id, month, room_number, rent, due_on)
                      VALUES (?, ?, ?, ?, ?)""",
                   (resident_id, month, s["room_number"], rules.rent_for_month(s["rent"], d(s["joined_on"]), month),
                    rules.due_date(month, d(s["joined_on"])).isoformat()))
        db.execute("UPDATE residents SET status = 'left', left_on = ?, room_id = NULL WHERE id = ?",
                   (left_on.isoformat(), resident_id))
        result = rules.settlement(s["deposit"], outstanding(db, resident_id))
        db.execute("COMMIT")
        return result
    except Exception:
        db.execute("ROLLBACK")
        raise


# ---- Bills and payments -----------------------------------------------------------

INVOICE_SQL = """
    SELECT i.*, s.name, s.phone, s.id AS resident_id, i.rent + i.late_fee AS total,
           COALESCE((SELECT SUM(amount) FROM payments p WHERE p.invoice_id = i.id), 0) AS paid
    FROM invoices i JOIN residents s ON s.id = i.resident_id
"""


def generate_invoices(db, month):
    """Creates this month's rent bill for every resident who stayed in the month. Running it again only adds bills
    for residents admitted since, so it is safe to click twice. Returns the number of new bills."""
    if not rules.valid_month(month):
        raise HostelError("Choose a month")
    created = 0
    db.execute("BEGIN IMMEDIATE")
    try:
        rows = db.execute("""SELECT s.id, s.joined_on, s.left_on, r.number, r.rent FROM residents s
                             JOIN rooms r ON r.id = s.room_id WHERE s.status = 'active'""").fetchall()
        for row in rows:
            joined, left = d(row["joined_on"]), d(row["left_on"])
            if not rules.billable(joined, left, month):
                continue
            cur = db.execute("""INSERT OR IGNORE INTO invoices (resident_id, month, room_number, rent, due_on)
                                VALUES (?, ?, ?, ?, ?)""",
                             (row["id"], month, row["number"], rules.rent_for_month(row["rent"], joined, month),
                              rules.due_date(month, joined).isoformat()))
            created += cur.rowcount
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return created


def apply_late_fees(db, today):
    """Adds the late fee once to every bill that is past its due date and still not fully paid."""
    count = 0
    for inv in db.execute(INVOICE_SQL + " WHERE i.late_fee = 0 AND i.due_on < ?", (today.isoformat(),)).fetchall():
        if rules.needs_late_fee(d(inv["due_on"]), inv["total"] - inv["paid"], inv["late_fee"], today):
            db.execute("UPDATE invoices SET late_fee = ? WHERE id = ? AND late_fee = 0", (rules.LATE_FEE, inv["id"]))
            count += 1
    return count


def invoices(db, month=None, resident_id=None, unpaid_only=False):
    sql, args = INVOICE_SQL + " WHERE 1 = 1", []
    if month:
        sql += " AND i.month = ?"
        args.append(month)
    if resident_id:
        sql += " AND i.resident_id = ?"
        args.append(resident_id)
    rows = db.execute(sql + " ORDER BY i.month DESC, s.name", args).fetchall()
    if unpaid_only:
        rows = [r for r in rows if r["total"] > r["paid"]]
    return rows


def invoice(db, invoice_id):
    return db.execute(INVOICE_SQL + " WHERE i.id = ?", (invoice_id,)).fetchone()


def record_payment(db, invoice_id, amount, mode, paid_on):
    if mode not in rules.PAYMENT_MODES:
        raise HostelError("Choose how the rent was paid")
    if amount <= 0:
        raise HostelError("Enter an amount more than zero")
    db.execute("BEGIN IMMEDIATE")
    try:
        inv = invoice(db, invoice_id)
        if inv is None:
            raise HostelError("No such bill")
        balance = inv["total"] - inv["paid"]
        if balance <= 0:
            raise HostelError("This bill is already paid")
        if amount > balance:
            raise HostelError(f"Amount is more than the balance of ₹{balance}")
        cur = db.execute("INSERT INTO payments (invoice_id, amount, mode, paid_on) VALUES (?, ?, ?, ?)",
                         (invoice_id, amount, mode, paid_on.isoformat()))
        receipt = rules.receipt_no(cur.lastrowid, paid_on)
        db.execute("UPDATE payments SET receipt_no = ? WHERE id = ?", (receipt, cur.lastrowid))
        db.execute("COMMIT")
        return cur.lastrowid
    except Exception:
        db.execute("ROLLBACK")
        raise


def payment(db, payment_id):
    return db.execute("""SELECT p.*, i.month, i.room_number, i.rent, i.late_fee, i.resident_id, s.name, s.phone,
                                i.rent + i.late_fee AS total,
                                (SELECT SUM(amount) FROM payments q WHERE q.invoice_id = i.id AND q.id <= p.id) AS paid_to_date
                         FROM payments p JOIN invoices i ON i.id = p.invoice_id JOIN residents s ON s.id = i.resident_id
                         WHERE p.id = ?""", (payment_id,)).fetchone()


def payments_of(db, resident_id):
    return db.execute("""SELECT p.*, i.month FROM payments p JOIN invoices i ON i.id = p.invoice_id
                         WHERE i.resident_id = ? ORDER BY p.paid_on DESC, p.id DESC""", (resident_id,)).fetchall()


# ---- Complaints and notices -----------------------------------------------------

def add_complaint(db, resident_id, category, description, today):
    description = description.strip()
    if category not in rules.CATEGORIES:
        raise HostelError("Choose a category")
    if len(description) < 10:
        raise HostelError("Describe the problem in a few words (at least 10 characters)")
    if len(description) > 1000:
        raise HostelError("Keep the description under 1000 characters")
    return db.execute("INSERT INTO complaints (resident_id, category, description, created_on) VALUES (?, ?, ?, ?)",
                      (resident_id, category, description, today.isoformat())).lastrowid


def update_complaint(db, complaint_id, status, remark, today):
    if status not in ("open", "in_progress", "resolved"):
        raise HostelError("Choose a status")
    db.execute("UPDATE complaints SET status = ?, remark = ?, resolved_on = ? WHERE id = ?",
               (status, remark.strip()[:300], today.isoformat() if status == "resolved" else None, complaint_id))


def complaints(db, status=None, resident_id=None):
    sql = """SELECT c.*, s.name, r.number AS room_number FROM complaints c JOIN residents s ON s.id = c.resident_id
             LEFT JOIN rooms r ON r.id = s.room_id WHERE 1 = 1"""
    args = []
    if status:
        sql += " AND c.status = ?"
        args.append(status)
    if resident_id:
        sql += " AND c.resident_id = ?"
        args.append(resident_id)
    return db.execute(sql + " ORDER BY c.status = 'resolved', c.created_on DESC, c.id DESC", args).fetchall()


def add_notice(db, title, body, today):
    title, body = title.strip(), body.strip()
    if not title or not body:
        raise HostelError("Enter a title and the notice text")
    return db.execute("INSERT INTO notices (title, body, posted_on) VALUES (?, ?, ?)",
                      (title[:120], body[:2000], today.isoformat())).lastrowid


def notices(db, limit=20):
    return db.execute("SELECT * FROM notices ORDER BY posted_on DESC, id DESC LIMIT ?", (limit,)).fetchall()


# ---- Dashboard -------------------------------------------------------------------

def dashboard(db, today):
    all_rooms = rooms(db)
    beds = sum(r["capacity"] for r in all_rooms)
    occupied = sum(r["occupied"] for r in all_rooms)
    month = rules.month_of(today)
    blocks = {}
    for r in all_rooms:
        b = blocks.setdefault(r["block"], {"beds": 0, "occupied": 0})
        b["beds"] += r["capacity"]
        b["occupied"] += r["occupied"]
    this_month = invoices(db, month)
    collected = db.execute("SELECT COALESCE(SUM(amount), 0) FROM payments WHERE substr(paid_on, 1, 7) = ?",
                           (month,)).fetchone()[0]
    pending = [i for i in invoices(db) if i["total"] > i["paid"]]
    return {
        "month": month,
        "rooms": len(all_rooms),
        "beds": beds,
        "occupied": occupied,
        "vacant": beds - occupied,
        "occupancy": rules.occupancy_percent(occupied, beds),
        "blocks": blocks,
        "billed": sum(i["total"] for i in this_month),
        "collected": collected,
        "pending_total": sum(i["total"] - i["paid"] for i in pending),
        "overdue": sum(1 for i in pending if d(i["due_on"]) < today),
        "open_complaints": db.execute("SELECT COUNT(*) FROM complaints WHERE status != 'resolved'").fetchone()[0],
        "residents": db.execute("SELECT COUNT(*) FROM residents WHERE status = 'active'").fetchone()[0],
    }
