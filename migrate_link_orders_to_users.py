# migrate_link_orders_to_users.py
import sqlite3, os

DB_PATH = os.path.join("instance", "mmvali_farm.db")
if not os.path.exists(DB_PATH):
    print("DB not found:", DB_PATH); raise SystemExit(1)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

# Ensure user_id column exists in order table
cur.execute("PRAGMA table_info('order')")
cols = [r[1] for r in cur.fetchall()]
if "user_id" not in cols:
    print("No user_id column found in 'order' table. Exiting.")
    raise SystemExit(1)

# Build mapping email->user_id from user table
cur.execute("SELECT id, email FROM user")
users = cur.fetchall()
email_to_uid = {email.lower(): uid for (uid, email) in users if email}

print(f"Found {len(email_to_uid)} registered users.")

# Find orders with NULL user_id but having customer_email
cur.execute("SELECT id, customer_email, user_id FROM 'order'")
rows = cur.fetchall()

updates = 0
for oid, cemail, uid in rows:
    if uid is not None:
        continue
    if not cemail:
        continue
    key = cemail.lower()
    if key in email_to_uid:
        new_uid = email_to_uid[key]
        cur.execute("UPDATE 'order' SET user_id = ? WHERE id = ?", (new_uid, oid))
        updates += 1
        print(f"Order {oid} -> user_id {new_uid} (matched email {cemail})")

con.commit()
print(f"Updated {updates} orders.")
con.close()
