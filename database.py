"""
database.py - Simple SQLite Database Management

This file handles:
1. Connecting to the SQLite database (moonwalk.db or :memory:).
2. Creating the database tables.
3. Seeding sample menu items, stations, and staff for MoonWalk and other restaurants.
"""
import sqlite3
import os

DB_FILE = os.getenv("DB_FILE", "moonwalk.db")


def get_db():
    """
    Returns a connection to the SQLite database.
    row_factory = sqlite3.Row allows accessing columns by name like a dictionary (e.g., row['name']).
    """
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Creates the database tables if they do not already exist.
    """
    conn = get_db()
    cursor = conn.cursor()

    # 1. Restaurants table (Part 2: Multi-restaurant support)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS restaurants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            buffer_percentage REAL NOT NULL DEFAULT 0.10,
            algorithm TEXT NOT NULL DEFAULT 'FIFO'
        );
    """)

    # 2. Stations table (Grill, Fryer, Barista, Prep, Plating)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            restaurant_id TEXT NOT NULL,
            name TEXT NOT NULL
        );
    """)

    # 3. Staff table (Alice, Bob, Charlie)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            restaurant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            skills TEXT NOT NULL  -- Comma-separated station names, e.g. 'Grill,Fryer,Plating'
        );
    """)

    # 4. Dishes table (Menu items with Indian pricing)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            restaurant_id TEXT NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT NOT NULL
        );
    """)

    # 5. Dish Steps table (Sequential steps required to cook each dish)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dish_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dish_id INTEGER NOT NULL,
            step_order INTEGER NOT NULL,
            name TEXT NOT NULL,
            station_name TEXT NOT NULL,
            duration_seconds INTEGER NOT NULL
        );
    """)

    # 6. Orders table (Customer orders)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            restaurant_id TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PREPARING',  -- PREPARING, COMPLETED, CANCELLED
            created_at REAL NOT NULL,
            ready_at REAL
        );
    """)

    # 7. Order Items table (Dishes inside an order with independent timers)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            dish_id INTEGER NOT NULL,
            dish_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PREPARING',
            ready_at REAL
        );
    """)

    # 8. ETA History table (Part 1 required: Immutable audit trail)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eta_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            restaurant_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            calculated_at REAL NOT NULL,
            estimated_duration_seconds REAL NOT NULL,
            actual_elapsed_seconds REAL NOT NULL,
            trigger_reason TEXT NOT NULL,
            algorithm TEXT NOT NULL DEFAULT 'FIFO'
        );
    """)

    conn.commit()
    conn.close()


def seed_data():
    """
    Inserts initial sample data for MoonWalk Space Diner and Orion Pizza if empty.
    """
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as cnt FROM restaurants;")
    if cursor.fetchone()["cnt"] > 0:
        conn.close()
        return  # Already seeded

    # ==========================================
    # 1. MoonWalk Space Diner (Primary)
    # ==========================================
    cursor.execute("""
        INSERT INTO restaurants (id, name, buffer_percentage, algorithm)
        VALUES ('moonwalk', 'MoonWalk Space Diner', 0.10, 'FIFO');
    """)

    # MoonWalk Stations
    stations = [
        ("moonwalk", "Grill"),
        ("moonwalk", "Fryer"),
        ("moonwalk", "Barista"),
        ("moonwalk", "Prep"),
        ("moonwalk", "Plating"),
    ]
    cursor.executemany("INSERT INTO stations (restaurant_id, name) VALUES (?, ?);", stations)

    # MoonWalk Staff Members
    # Alice cooks grill, fryer, prep, and plating
    # Bob handles the coffee counter
    # Charlie helps with grill, fryer, and plating
    staff = [
        ("moonwalk", "Alice", "Grill,Fryer,Prep,Plating"),
        ("moonwalk", "Bob", "Barista"),
        ("moonwalk", "Charlie", "Grill,Fryer,Plating"),
    ]
    cursor.executemany("INSERT INTO staff (restaurant_id, name, skills) VALUES (?, ?, ?);", staff)

    # Dish 1: Veg Cheese Burger (High Time: 13 mins = 780s, ₹150)
    cursor.execute("""
        INSERT INTO dishes (restaurant_id, name, price, category)
        VALUES ('moonwalk', 'Veg Cheese Burger', 150.0, 'Burger (High Time)');
    """)
    burger_id = cursor.lastrowid
    cursor.executemany("""
        INSERT INTO dish_steps (dish_id, step_order, name, station_name, duration_seconds)
        VALUES (?, ?, ?, ?, ?);
    """, [
        (burger_id, 0, "Patty Grilling & Cheese Melting", "Grill", 420),    # 7 min
        (burger_id, 1, "Bun Toasting & Dressing", "Prep", 240),             # 4 min
        (burger_id, 2, "Plating & Wrapping", "Plating", 120),               # 2 min
    ])

    # Dish 2: French Fries (Medium Time: 7 mins = 420s, ₹100)
    cursor.execute("""
        INSERT INTO dishes (restaurant_id, name, price, category)
        VALUES ('moonwalk', 'French Fries', 100.0, 'Fries (Medium Time)');
    """)
    fries_id = cursor.lastrowid
    cursor.executemany("""
        INSERT INTO dish_steps (dish_id, step_order, name, station_name, duration_seconds)
        VALUES (?, ?, ?, ?, ?);
    """, [
        (fries_id, 0, "Deep Frying", "Fryer", 300),                         # 5 min
        (fries_id, 1, "Plating & Salting", "Plating", 120),                 # 2 min
    ])

    # Dish 3: Cold Coffee (Low Time: 4 mins = 240s, ₹80)
    # Self-contained at Barista station so Bob prepares it independently without waiting for food plating
    cursor.execute("""
        INSERT INTO dishes (restaurant_id, name, price, category)
        VALUES ('moonwalk', 'Cold Coffee', 80.0, 'Drink (Low Time)');
    """)
    coffee_id = cursor.lastrowid
    cursor.executemany("""
        INSERT INTO dish_steps (dish_id, step_order, name, station_name, duration_seconds)
        VALUES (?, ?, ?, ?, ?);
    """, [
        (coffee_id, 0, "Espresso & Milk Blending", "Barista", 180),         # 3 min
        (coffee_id, 1, "Pouring & Serving", "Barista", 60),                 # 1 min
    ])

    # ==========================================
    # 2. Orion Pizza (Part 2: Multi-Restaurant Proof)
    # Shows independent menu, stations, staff, and buffer
    # ==========================================
    cursor.execute("""
        INSERT INTO restaurants (id, name, buffer_percentage, algorithm)
        VALUES ('orion-pizza', 'Orion Woodfired Pizza', 0.15, 'FIFO');
    """)

    cursor.executemany("INSERT INTO stations (restaurant_id, name) VALUES (?, ?);", [
        ("orion-pizza", "DoughTable"),
        ("orion-pizza", "Oven"),
        ("orion-pizza", "Packing"),
    ])

    cursor.executemany("INSERT INTO staff (restaurant_id, name, skills) VALUES (?, ?, ?);", [
        ("orion-pizza", "Marco", "DoughTable,Oven"),
        ("orion-pizza", "Gianna", "DoughTable,Packing"),
    ])

    cursor.execute("""
        INSERT INTO dishes (restaurant_id, name, price, category)
        VALUES ('orion-pizza', 'Margherita Pizza', 250.0, 'Pizza');
    """)
    pizza_id = cursor.lastrowid
    cursor.executemany("""
        INSERT INTO dish_steps (dish_id, step_order, name, station_name, duration_seconds)
        VALUES (?, ?, ?, ?, ?);
    """, [
        (pizza_id, 0, "Rolling Dough & Toppings", "DoughTable", 300),
        (pizza_id, 1, "Woodfired Baking", "Oven", 420),
        (pizza_id, 2, "Slicing & Packing", "Packing", 90),
    ])

    conn.commit()
    conn.close()


# Automatically initialize and seed the database when this module is imported
init_db()
seed_data()

