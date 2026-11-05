"""
Utility script to print SQLite database contents to the terminal.
"""
import sqlite3
import os

DB_FILE = "moonwalk.db"

if not os.path.exists(DB_FILE):
    print(f"Database file '{DB_FILE}' not found. Run main.py first to initialize.")
    exit()

conn = sqlite3.connect(DB_FILE)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()


def print_section(title):
    print("\n" + "-" * 50)
    print(f" {title}")
    print("-" * 50)


# Restaurants
print_section("RESTAURANTS")
cursor.execute("SELECT * FROM restaurants;")
for r in cursor.fetchall():
    print(f"ID: {r['id']:<14} Name: {r['name']:<25} Buffer: {int(r['buffer_percentage']*100)}%   Algo: {r['algorithm']}")

# Stations
print_section("STATIONS")
cursor.execute("SELECT * FROM stations ORDER BY restaurant_id, id;")
for s in cursor.fetchall():
    print(f"Restaurant: {s['restaurant_id']:<14} Station: {s['name']}")

# Staff
print_section("STAFF & SKILLS")
cursor.execute("SELECT * FROM staff ORDER BY restaurant_id, id;")
for st in cursor.fetchall():
    print(f"Restaurant: {st['restaurant_id']:<14} Name: {st['name']:<10} Skills: {st['skills']}")

# Dishes
print_section("DISHES")
cursor.execute("SELECT * FROM dishes ORDER BY restaurant_id, id;")
for d in cursor.fetchall():
    print(f"ID #{d['id']} [{d['restaurant_id']}]: {d['name']:<20} Price: Rs {d['price']:<6} Category: {d['category']}")

# Steps
print_section("DISH STEPS")
cursor.execute("""
    SELECT d.name as dish_name, ds.step_order, ds.name as step_name, ds.station_name, ds.duration_seconds
    FROM dish_steps ds
    JOIN dishes d ON ds.dish_id = d.id
    ORDER BY d.id, ds.step_order;
""")
for ds in cursor.fetchall():
    print(f"{ds['dish_name']:<20} Step {ds['step_order']}: {ds['step_name']:<32} Station: {ds['station_name']:<10} Duration: {ds['duration_seconds']}s")

# Orders
print_section("ORDERS")
cursor.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 10;")
orders = cursor.fetchall()
if not orders:
    print("  (No active orders currently)")
else:
    for o in orders:
        print(f"Order: {o['id']} | Customer: {o['customer_name']:<12} | Status: {o['status']:<10} | Restaurant: {o['restaurant_id']}")

# Order Items
print_section("ORDER ITEMS")
cursor.execute("SELECT * FROM order_items ORDER BY id DESC LIMIT 10;")
items = cursor.fetchall()
if not items:
    print("  (No order items currently)")
else:
    for item in items:
        print(f"Order #{item['order_id']} | Dish: {item['dish_name']:<20} | Status: {item['status']}")

# ETA History
print_section("AUDIT HISTORY (LAST 5)")
cursor.execute("SELECT * FROM eta_history ORDER BY id DESC LIMIT 5;")
history = cursor.fetchall()
if not history:
    print("  (No calculation history yet)")
else:
    for h in history:
        print(f"#{h['id']} | Order: {h['order_id']} | Status: {h['order_status']:<10} | Reason: {h['trigger_reason']:<16} | Est: {h['estimated_duration_seconds']}s")

print("\n" + "-" * 50 + "\n")
conn.close()
