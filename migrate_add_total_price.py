# migrate_add_total_price.py
import sqlite3
import os

# adjust if your DB filename is different
DB_PATH = os.path.join("instance", "mmvali_farm.db")

# product price map - must match PRODUCTS in your app.py
PRICE_MAP = {
    "Fresh Cow Milk (1L)": 60,
    "Milk Kova (250g)": 180,
    "Paneer (250g)": 120,
    "Curd (500ml)": 45,
    "Ghee (200g)": 260
}

if not os.path.exists(DB_PATH):
    print("DB not found at", DB_PATH)
    raise SystemExit(1)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()

# 1) Add column if it doesn't exist
# SQLite allows ADD COLUMN; it's a no-op if already there but we'll check first.
cur.execute("PRAGMA table_info('order')")
cols = [row[1] for row in cur.fetchall()]
if "total_price" in cols:
    print("Column 'total_price' already exists.")
else:
    print("Adding column 'total_price' to 'order' table...")
    cur.execute("ALTER TABLE 'order' ADD COLUMN total_price INTEGER")
    con.commit()
    print("Column added.")

# 2) Update existing rows: compute price = unit_price * quantity
print("Updating existing orders total_price where NULL or 0...")
cur.execute("SELECT id, product, quantity, total_price FROM 'order'")
rows = cur.fetchall()
updates = 0
for row in rows:
    oid, product, qty, tprice = row
    try:
        qty = int(qty) if qty is not None else 1
    except:
        qty = 1
    unit = PRICE_MAP.get(product)
    if unit is None:
        # if product name doesn't match, skip (or set 0)
        print(f" - WARNING: unknown product for order {oid}: '{product}' (skipping)")
        continue
    new_total = unit * qty
    # update only if NULL or different
    if tprice is None or int(tprice) != new_total:
        cur.execute("UPDATE 'order' SET total_price = ? WHERE id = ?", (new_total, oid))
        updates += 1

con.commit()
print(f"Updated {updates} order(s).")
con.close()
print("Done. Restart your Flask app now.")
