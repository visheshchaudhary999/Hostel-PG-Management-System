"""Hostel and PG Management System: Flask web application.

    python seed_demo.py      (once: creates hostel.db with demo rooms, residents and bills)
    python app.py            then open http://127.0.0.1:5000
"""
import csv
import io
import os
import secrets
from datetime import date
from functools import wraps
from pathlib import Path

from flask import (Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import hostel
import rules
from hostel import HostelError

BASE = Path(__file__).resolve().parent


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(16),
        DATABASE=str(BASE / "hostel.db"),
        TODAY=None,                     # tests set a fixed date here
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)

    def today():
        return app.config["TODAY"] or date.today()

    def db():
        if "db" not in g:
            g.db = hostel.connect(app.config["DATABASE"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    # ---- Security: CSRF token on every form, login and roles ----------------------

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.filters["short"] = lambda iso: date.fromisoformat(iso).strftime("%d %b").lstrip("0")

    @app.before_request
    def check_csrf():
        if request.method == "POST":
            sent = request.form.get("csrf", "")
            if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
                abort(400, "The form expired. Go back, reload the page and try again.")

    @app.before_request
    def load_user():
        g.user = None
        if "user_id" in session:
            g.user = db().execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    def role_required(role):
        def decorator(view):
            @wraps(view)
            def wrapped(*args, **kwargs):
                if g.user is None:
                    return redirect(url_for("login", next=request.path))
                if g.user["role"] != role:
                    abort(403)
                return view(*args, **kwargs)
            return wrapped
        return decorator

    warden_only = role_required("warden")
    resident_only = role_required("resident")

    @app.context_processor
    def template_globals():
        return {"user": g.get("user"), "today": today(), "rupees": rupees, "month_name": month_name}

    def form_int(name, default=0):
        try:
            return int(request.form.get(name) or default)
        except ValueError:
            raise HostelError(f"Enter a whole number for {name.replace('_', ' ')}")

    def form_date(name):
        try:
            return date.fromisoformat(request.form.get(name, ""))
        except ValueError:
            raise HostelError("Enter a valid date")

    # ---- Login ------------------------------------------------------------------

    @app.route("/")
    def home():
        if g.user is None:
            return redirect(url_for("login"))
        return redirect(url_for("dashboard" if g.user["role"] == "warden" else "me"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            row = db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
            if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
                if row["role"] == "resident":
                    s = hostel.resident(db(), row["resident_id"])
                    if s is None or s["status"] != "active":
                        row = None
                        error = "This account is closed because the resident has left."
                if row:
                    session.clear()
                    session["user_id"] = row["id"]
                    nxt = request.args.get("next", "")
                    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("home"))
            else:
                error = "Wrong email or password."
        return render_template("login.html", error=error)

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---- Warden: dashboard and rooms ---------------------------------------------

    @app.route("/warden")
    @warden_only
    def dashboard():
        hostel.apply_late_fees(db(), today())
        return render_template("dashboard.html", s=hostel.dashboard(db(), today()),
                               complaints=hostel.complaints(db())[:5], notices=hostel.notices(db(), 3),
                               unpaid=sorted(hostel.invoices(db(), unpaid_only=True), key=lambda b: b["due_on"])[:6])

    @app.route("/warden/rooms", methods=["GET", "POST"])
    @warden_only
    def rooms():
        if request.method == "POST":
            try:
                hostel.add_room(db(), request.form.get("number", ""), request.form.get("block"), form_int("floor"),
                                form_int("capacity"), form_int("rent"), request.form.get("ac") == "1")
                flash(f"Room {request.form['number'].strip().upper()} added.")
                return redirect(url_for("rooms"))
            except HostelError as e:
                flash(str(e), "error")
        block = request.args.get("block")
        all_rooms = hostel.rooms(db(), block if block in ("Boys", "Girls") else None)
        people = {r["id"]: hostel.occupants(db(), r["id"]) for r in all_rooms}
        return render_template("rooms.html", rooms=all_rooms, people=people, block=block)

    # ---- Warden: residents -----------------------------------------------------

    @app.route("/warden/residents")
    @warden_only
    def residents():
        q = request.args.get("q", "").strip()
        status = request.args.get("status", "active")
        return render_template("residents.html", residents=hostel.residents(db(), q, status), q=q, status=status)

    @app.route("/warden/residents/new", methods=["GET", "POST"])
    @warden_only
    def admit():
        gender = request.values.get("gender", "M") if request.values.get("gender") in ("M", "F") else "M"
        if request.method == "POST":
            try:
                password = request.form.get("password", "")
                if len(password) < 8:
                    raise HostelError("The resident's password needs at least 8 characters")
                rid = hostel.admit(db(), request.form, form_int("room_id"), form_date("joined_on"),
                                   generate_password_hash(password))
                flash(f"{request.form['name'].strip()} admitted. They can log in with their email and the password "
                      "you set.")
                return redirect(url_for("resident_detail", rid=rid))
            except HostelError as e:
                flash(str(e), "error")
        return render_template("admit.html", gender=gender, form=request.form,
                               vacant={g_: hostel.vacant_rooms_for(db(), g_) for g_ in ("M", "F")})

    @app.route("/warden/residents/<int:rid>")
    @warden_only
    def resident_detail(rid):
        s = hostel.resident(db(), rid) or abort(404)
        return render_template("resident.html", s=s, bills=hostel.invoices(db(), resident_id=rid),
                               payments=hostel.payments_of(db(), rid), balance=hostel.outstanding(db(), rid),
                               roommates=[p for p in hostel.occupants(db(), s["room_id"]) if p["id"] != rid]
                               if s["room_id"] else [],
                               vacant=hostel.vacant_rooms_for(db(), s["gender"]),
                               complaints=hostel.complaints(db(), resident_id=rid),
                               preview=rules.settlement(s["deposit"], hostel.outstanding(db(), rid)))

    @app.route("/warden/residents/<int:rid>/shift", methods=["POST"])
    @warden_only
    def shift(rid):
        try:
            number = hostel.shift_room(db(), rid, form_int("room_id"))
            flash(f"Moved to room {number}.")
        except HostelError as e:
            flash(str(e), "error")
        return redirect(url_for("resident_detail", rid=rid))

    @app.route("/warden/residents/<int:rid>/vacate", methods=["POST"])
    @warden_only
    def vacate(rid):
        try:
            result = hostel.vacate(db(), rid, form_date("left_on"))
            if result["collect"]:
                flash(f"Checked out. Collect {rupees(result['collect'])} more: dues are larger than the deposit.")
            else:
                flash(f"Checked out. Refund {rupees(result['refund'])} of the {rupees(result['deposit'])} deposit "
                      f"(dues of {rupees(result['outstanding'])} adjusted).")
        except HostelError as e:
            flash(str(e), "error")
        return redirect(url_for("resident_detail", rid=rid))

    # ---- Warden: rent ---------------------------------------------------------

    @app.route("/warden/dues")
    @warden_only
    def dues():
        month = request.args.get("month") or rules.month_of(today())
        if not rules.valid_month(month):
            abort(404)
        hostel.apply_late_fees(db(), today())
        bills = hostel.invoices(db(), month)
        show = request.args.get("show", "all")
        if show == "unpaid":
            bills = [b for b in bills if b["total"] > b["paid"]]
        totals = {"billed": sum(b["total"] for b in bills), "paid": sum(b["paid"] for b in bills)}
        return render_template("dues.html", bills=bills, month=month, show=show, totals=totals,
                               prev=rules.previous_month(month), modes=rules.PAYMENT_MODES)

    @app.route("/warden/dues/generate", methods=["POST"])
    @warden_only
    def generate():
        month = request.form.get("month", "")
        try:
            n = hostel.generate_invoices(db(), month)
            flash(f"{n} new bill(s) created for {month_name(month)}." if n else
                  f"Every current resident already has a bill for {month_name(month)}.")
        except HostelError as e:
            flash(str(e), "error")
        return redirect(url_for("dues", month=month if rules.valid_month(month) else None))

    @app.route("/warden/invoices/<int:iid>/pay", methods=["POST"])
    @warden_only
    def pay(iid):
        inv = hostel.invoice(db(), iid) or abort(404)
        try:
            pid = hostel.record_payment(db(), iid, form_int("amount"), request.form.get("mode", ""), today())
            flash(f"Payment recorded for {inv['name']}.")
            return redirect(url_for("receipt", pid=pid))
        except HostelError as e:
            flash(f"{inv['name']}: {e}", "error")
        return redirect(request.form.get("back") if request.form.get("back", "").startswith("/")
                        else url_for("dues", month=inv["month"]))

    @app.route("/warden/dues.csv")
    @warden_only
    def dues_csv():
        month = request.args.get("month", "")
        if not rules.valid_month(month):
            abort(404)
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Resident", "Phone", "Room", "Month", "Rent", "Late fee", "Total", "Paid", "Balance", "Due on"])
        for b in hostel.invoices(db(), month):
            w.writerow([b["name"], b["phone"], b["room_number"], b["month"], b["rent"], b["late_fee"], b["total"],
                        b["paid"], b["total"] - b["paid"], b["due_on"]])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=dues-{month}.csv"})

    @app.route("/receipt/<int:pid>")
    def receipt(pid):
        if g.user is None:
            return redirect(url_for("login", next=request.path))
        p = hostel.payment(db(), pid) or abort(404)
        if g.user["role"] == "resident" and g.user["resident_id"] != p["resident_id"]:
            abort(404)                  # a resident sees only their own receipts
        return render_template("receipt.html", p=p)

    # ---- Warden: complaints and notices -----------------------------------------

    @app.route("/warden/complaints", methods=["GET", "POST"])
    @warden_only
    def complaints():
        if request.method == "POST":
            try:
                hostel.update_complaint(db(), form_int("id"), request.form.get("status", ""),
                                        request.form.get("remark", ""), today())
                flash("Complaint updated.")
            except HostelError as e:
                flash(str(e), "error")
            return redirect(url_for("complaints", status=request.args.get("status")))
        status = request.args.get("status")
        return render_template("complaints.html", items=hostel.complaints(
            db(), status if status in ("open", "in_progress", "resolved") else None), status=status)

    @app.route("/warden/notices", methods=["GET", "POST"])
    @warden_only
    def notices():
        if request.method == "POST":
            try:
                hostel.add_notice(db(), request.form.get("title", ""), request.form.get("body", ""), today())
                flash("Notice posted. Residents see it on their page.")
                return redirect(url_for("notices"))
            except HostelError as e:
                flash(str(e), "error")
        return render_template("notices.html", items=hostel.notices(db(), 50))

    # ---- Resident portal ------------------------------------------------------

    @app.route("/me", methods=["GET", "POST"])
    @resident_only
    def me():
        rid = g.user["resident_id"]
        if request.method == "POST":
            try:
                hostel.add_complaint(db(), rid, request.form.get("category", ""),
                                     request.form.get("description", ""), today())
                flash("Complaint sent to the warden.")
                return redirect(url_for("me") + "#complaints")
            except HostelError as e:
                flash(str(e), "error")
        hostel.apply_late_fees(db(), today())
        s = hostel.resident(db(), rid)
        return render_template("me.html", s=s, bills=hostel.invoices(db(), resident_id=rid),
                               payments=hostel.payments_of(db(), rid), balance=hostel.outstanding(db(), rid),
                               roommates=[p for p in hostel.occupants(db(), s["room_id"]) if p["id"] != rid],
                               complaints=hostel.complaints(db(), resident_id=rid), notices=hostel.notices(db(), 5),
                               categories=rules.CATEGORIES)

    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(400)
    def error_page(e):
        return render_template("error.html", e=e), e.code

    return app


def rupees(amount):
    """Indian digit grouping: 125000 -> ₹1,25,000."""
    sign, n = ("-" if amount < 0 else ""), str(abs(int(amount)))
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        n = ",".join(([head] if head else []) + groups) + "," + tail
    return f"{sign}₹{n}"


def month_name(month):
    if not rules.valid_month(month or ""):
        return month
    first, _ = rules.month_bounds(month)
    return first.strftime("%B %Y")


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")
