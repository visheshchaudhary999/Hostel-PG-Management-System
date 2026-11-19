"""The hostel's business rules as plain functions, with no database or web code, so they are easy to test."""
import calendar
import re
from datetime import date, timedelta

DUE_DAY = 10          # rent for a month is due by the 10th
LATE_FEE = 200        # added once to a bill that is still unpaid after the due date
BLOCK_FOR = {"M": "Boys", "F": "Girls"}
CATEGORIES = ["Electrical", "Plumbing", "Cleaning", "Wi-Fi", "Furniture", "Mess / food", "Other"]
PAYMENT_MODES = ["Cash", "UPI", "Card", "Bank transfer"]

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_PHONE = re.compile(r"^[6-9]\d{9}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)


def valid_month(text):
    return bool(_MONTH.match(text or ""))


def valid_phone(text):
    """A 10-digit Indian mobile number starting with 6, 7, 8 or 9."""
    return bool(_PHONE.match(text or ""))


def valid_email(text):
    return bool(_EMAIL.match(text or ""))


def month_of(day):
    return f"{day.year}-{day.month:02d}"


def month_bounds(month):
    """First and last day of a month given as 'YYYY-MM'."""
    year, mon = map(int, month.split("-"))
    return date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])


def previous_month(month):
    first, _ = month_bounds(month)
    year, mon = (first.year - 1, 12) if first.month == 1 else (first.year, first.month - 1)
    return f"{year}-{mon:02d}"


JOINING_GRACE_DAYS = 7  # someone who joins after the 10th gets a week to pay their first bill


def due_date(month, joined_on=None):
    """Rent is due by the 10th. In the month a resident joins, it is due 7 days after joining if that is later."""
    first, _ = month_bounds(month)
    due = first.replace(day=DUE_DAY)
    if joined_on and joined_on.strftime("%Y-%m") == month:
        due = max(due, joined_on + timedelta(days=JOINING_GRACE_DAYS))
    return due


def rent_for_month(rent, joined_on, month):
    """Rent a resident owes for one month.

    The month a resident joins is charged only for the days from the joining date (both days counted), rounded to
    the nearest rupee. Every later month, including the month they leave, is charged in full.
    """
    first, last = month_bounds(month)
    if joined_on > last:
        return 0
    if joined_on <= first:
        return rent
    days = (last - joined_on).days + 1
    return (rent * days + last.day // 2) // last.day      # whole rupees, half rounds up


def billable(joined_on, left_on, month):
    """True if the resident lived in the hostel for at least one day of the month."""
    first, last = month_bounds(month)
    return joined_on <= last and (left_on is None or left_on >= first)


def needs_late_fee(due_on, balance, late_fee, today):
    return late_fee == 0 and balance > 0 and today > due_on


def can_allocate(room_block, capacity, occupied, gender):
    """(True, '') if a resident of this gender can take a bed in the room, else (False, reason)."""
    if BLOCK_FOR.get(gender) != room_block:
        return False, f"Room is in the {room_block} block"
    if occupied >= capacity:
        return False, "Room is full"
    return True, ""


def settlement(deposit, outstanding):
    """What happens to the security deposit when a resident leaves."""
    return {
        "deposit": deposit,
        "outstanding": outstanding,
        "refund": max(deposit - outstanding, 0),
        "collect": max(outstanding - deposit, 0),
    }


def receipt_no(payment_id, paid_on):
    return f"RCP-{paid_on.year}-{payment_id:05d}"


def occupancy_percent(occupied, beds):
    return round(100 * occupied / beds) if beds else 0
