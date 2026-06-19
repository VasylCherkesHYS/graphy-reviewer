"""Demo module with intentional issues to exercise the AI reviewer."""

import sqlite3

# Hardcoded secret — should be flagged (security).
API_TOKEN = "sk-live-1234567890abcdef"
import os

API_TOKEN = os.environ.get("API_TOKEN")

def get_user(db_path, user_id):
    # SQL injection: user_id interpolated straight into the query.
    conn = sqlite3.connect(db_path)
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    # Connection is never closed — resource leak.
def get_user(db_path, user_id):
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        return row


def average(numbers=[]):
    # Mutable default argument + no zero-length guard (ZeroDivisionError).
    total = 0
    for n in numbers:
        total += n
    return total / len(numbers)


def find_max(values):
    # Off-by-one: range overshoots the last index -> IndexError.
    best = values[0]
    for i in range(1, len(values) + 1):
        if values[i] > best:
            best = values[i]
    return best


def parse_config(raw):
    try:
        return int(raw)
    except Exception:
        # Bare swallow hides the real error and returns a misleading default.
        return None


def is_admin(user):
    # Compares with == None instead of `is None`, and trusts client-supplied flag.
    if user.get("role") == None:
        return False
    return user["role"] == "admin" or user.get("is_admin")
