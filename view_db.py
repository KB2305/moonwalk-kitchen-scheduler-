"""
view_db.py - Simple Database Inspector

Run this script in terminal anytime:
    python view_db.py

It prints out all the tables stored inside 'moonwalk.db' so you can physically inspect them!
"""
import sqlite3
import os

DB_FILE = "moonwalk.db"

if not os.path.exists(DB_FILE):
    print(f"Database file '{DB_FILE}' not found. Run main.py or database.py first to create it.")
    exit()

conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

def print_section(title):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

# 1. Restaurants
print_section("1. RESTAURANTS TABLE")
cursor.execute("SELECT * FROM restaurants;")
for r in cursor.fetchall():
    print(f"• ID: {r['id']:<14} Name: {r['name']:<25} Buffer: {int(r['buffer_percentage']*100)}%   Algo: {r['algorithm']}")

# 2. Stations (Kitchen Sections)
print_section("2. KITCHEN STATIONS (SECTIONS) TABLE")
cursor.execute("SELECT * FROM stations ORDER BY restaurant_id, id;")
for s in cursor.fetchall():
    print(f"• Restaurant: {s['restaurant_id']:<14} Station Name: {s['name']}")

# 3. Staff (Employees & Skills)
print_section("3. STAFF MEMBERS & SKILLS TABLE")
cursor.execute("SELECT * FROM staff ORDER BY restaurant_id, id;")
for st in cursor.fetchall():
    print(f"• Restaurant: {st['restaurant_id']:<14} Name: {st['name']:<10} Qualified For: {st['skills']}")

# 4. Dishes (Menu Items & Indian Prices)
print_section("4. DISHES TABLE (MENU ITEMS)")
cursor.execute("SELECT * FROM dishes ORDER BY restaurant_id, id;")
for d in cursor.fetchall():
    print(f"• ID #{d['id']} [{d['restaurant_id']}]: {d['name']:<20} Price: Rs {d['price']:<6} Category: {d['category']}")

# 5. Dish Steps (Cooking Sequence)
print_section("5. DISH PREPARATION STEPS TABLE")
cursor.execute("""
    SELECT d.name as dish_name, ds.step_order, ds.name as step_name, ds.station_name, ds.duration_seconds
    FROM dish_steps ds
    JOIN dishes d ON ds.dish_id = d.id
    ORDER BY d.id, ds.step_order;
""")
for ds in cursor.fetchall():
    print(f"• {ds['dish_name']:<20} Step {ds['step_order']}: {ds['step_name']:<32} Station: {ds['station_name']:<10} Duration: {ds['duration_seconds']}s ({ds['duration_seconds']//60}m)")

# 6. Orders (Placed by Customers)
print_section("6. CUSTOMER ORDERS TABLE")
cursor.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 10;")
orders = cursor.fetchall()
if not orders:
    print("  (No active orders currently. Place an order on http://localhost:8000 to see it here!)")
else:
    for o in orders:
        print(f"• Order: {o['id']} | Customer: {o['customer_name']:<12} | Status: {o['status']:<10} | Restaurant: {o['restaurant_id']}")

# 7. Order Items (Dishes inside each order)
print_section("7. ORDER ITEMS TABLE")
cursor.execute("SELECT * FROM order_items ORDER BY id DESC LIMIT 10;")
items = cursor.fetchall()
if not items:
    print("  (No order items currently)")
else:
    for item in items:
        print(f"• Order #{item['order_id']} | Dish: {item['dish_name']:<20} | Status: {item['status']}")

# 8. ETA History (Audit Log)
print_section("8. ETA CALCULATION AUDIT HISTORY (LAST 5)")
cursor.execute("SELECT * FROM eta_history ORDER BY id DESC LIMIT 5;")
history = cursor.fetchall()
if not history:
    print("  (No calculation history yet)")
else:
    for h in history:
        print(f"• #{h['id']} | Order: {h['order_id']} | Reason: {h['trigger_reason']:<16} | Est: {h['estimated_duration_seconds']}s | Elapsed: {h['actual_elapsed_seconds']}s")

print("\n" + "=" * 60 + "\n")
conn.close()

