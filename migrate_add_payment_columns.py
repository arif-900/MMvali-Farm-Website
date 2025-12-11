# migrate_add_payment_columns.py
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join("instance", "mmvali_farm.db")

if not os.path.exists(DB_PATH):
    print("ERROR: DB not found at", DB_PATH)
    raise SystemExit(1)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

def get_columns(table):
    cur.execute(f"PRAGMA table_info('{table}')")
    return [r[1] for r in cur.fetchall()]

tbl = 'order'
cols = get_columns(tbl)
print("Existing columns in 'order':", cols)

# Add payment_method column if missing
if "payment_method" not in cols:
    print("Adding column 'payment_method' to 'order'...")
    cur.execute("ALTER TABLE 'order' ADD COLUMN payment_method TEXT")
    con.commit()
    print("Added 'payment_method'.")
else:
    print("'payment_method' already exists.")

# Add payment_status column if missing
if "payment_status" not in cols:
    print("Adding column 'payment_status' to 'order'...")
    cur.execute("ALTER TABLE 'order' ADD COLUMN payment_status TEXT")
    con.commit()
    print("Added 'payment_status'.")
else:
    print("'payment_status' already exists.")

# Backfill sensible defaults for existing rows (only when NULL)
print("Backfilling defaults for existing rows where NULL...")
cur.execute("SELECT id, payment_method, payment_status FROM 'order'")
rows = cur.fetchall()
updates = 0
for r in rows:
    oid, pm, ps = r
    # Only update rows where either is NULL or empty
    new_pm = pm if pm not in (None, '') else 'COD'
    new_ps = ps if ps not in (None, '') else 'Pending'
    if pm != new_pm or ps != new_ps:
        cur.execute("UPDATE 'order' SET payment_method = ?, payment_status = ? WHERE id = ?", (new_pm, new_ps, oid))
        updates += 1

con.commit()
print(f"Backfilled {updates} rows.")
con.close()
print("Migration finished. Restart your Flask app now.")
