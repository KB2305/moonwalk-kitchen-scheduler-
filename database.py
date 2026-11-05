"""
Database schema definition, connection helper, and seed data.
"""
import sqlite3
import os

DB_FILE = os.getenv("DB_FILE", "moonwalk.db")


def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    try:
        cursor = conn.cursor()

        # Restaurants
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS restaurants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                buffer_percentage REAL NOT NULL DEFAULT 0.10,
                algorithm TEXT NOT NULL DEFAULT 'FIFO'
            );
        """)

        # Kitchen stations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id TEXT NOT NULL,
                name TEXT NOT NULL
            );
        """)

        # Staff and skills
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                skills TEXT NOT NULL
            );
        """)

        # Menu items
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dishes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                category TEXT NOT NULL
            );
        """)

        # Sequential cooking steps per dish
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

        # Customer orders
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                restaurant_id TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PREPARING',
                created_at REAL NOT NULL,
                ready_at REAL
            );
        """)

        # Dishes within an order
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

        # Audit log of calculations
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS eta_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                calculated_at REAL NOT NULL,
                estimated_duration_seconds REAL NOT NULL,
                actual_elapsed_seconds REAL NOT NULL,
                order_status TEXT NOT NULL DEFAULT 'PREPARING',
                trigger_reason TEXT NOT NULL,
                algorithm TEXT NOT NULL DEFAULT 'FIFO'
            );
        """)

        conn.commit()
    finally:
        conn.close()


def seed_data():
    conn = get_db()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as cnt FROM restaurants;")
        if cursor.fetchone()["cnt"] > 0:
            return

        # Seed MoonWalk Space Diner
        cursor.execute("""
            INSERT INTO restaurants (id, name, buffer_percentage, algorithm)
            VALUES ('moonwalk', 'MoonWalk Space Diner', 0.10, 'FIFO');
        """)

        stations = [
            ("moonwalk", "Grill"),
            ("moonwalk", "Fryer"),
            ("moonwalk", "Barista"),
            ("moonwalk", "Prep"),
            ("moonwalk", "Plating"),
        ]
        cursor.executemany("INSERT INTO stations (restaurant_id, name) VALUES (?, ?);", stations)

        staff = [
            ("moonwalk", "Alice", "Grill,Fryer,Prep,Plating"),
            ("moonwalk", "Bob", "Barista"),
            ("moonwalk", "Charlie", "Grill,Fryer,Plating"),
        ]
        cursor.executemany("INSERT INTO staff (restaurant_id, name, skills) VALUES (?, ?, ?);", staff)

        # Dish: Veg Cheese Burger
        cursor.execute("""
            INSERT INTO dishes (restaurant_id, name, price, category)
            VALUES ('moonwalk', 'Veg Cheese Burger', 150.0, 'Burger (High Time)');
        """)
        burger_id = cursor.lastrowid
        cursor.executemany("""
            INSERT INTO dish_steps (dish_id, step_order, name, station_name, duration_seconds)
            VALUES (?, ?, ?, ?, ?);
        """, [
            (burger_id, 0, "Patty Grilling & Cheese Melting", "Grill", 420),
            (burger_id, 1, "Bun Toasting & Dressing", "Prep", 240),
            (burger_id, 2, "Plating & Wrapping", "Plating", 120),
        ])

        # Dish: French Fries
        cursor.execute("""
            INSERT INTO dishes (restaurant_id, name, price, category)
            VALUES ('moonwalk', 'French Fries', 100.0, 'Fries (Medium Time)');
        """)
        fries_id = cursor.lastrowid
        cursor.executemany("""
            INSERT INTO dish_steps (dish_id, step_order, name, station_name, duration_seconds)
            VALUES (?, ?, ?, ?, ?);
        """, [
            (fries_id, 0, "Deep Frying", "Fryer", 300),
            (fries_id, 1, "Plating & Salting", "Plating", 120),
        ])

        # Dish: Cold Coffee
        cursor.execute("""
            INSERT INTO dishes (restaurant_id, name, price, category)
            VALUES ('moonwalk', 'Cold Coffee', 80.0, 'Drink (Low Time)');
        """)
        coffee_id = cursor.lastrowid
        cursor.executemany("""
            INSERT INTO dish_steps (dish_id, step_order, name, station_name, duration_seconds)
            VALUES (?, ?, ?, ?, ?);
        """, [
            (coffee_id, 0, "Espresso & Milk Blending", "Barista", 180),
            (coffee_id, 1, "Pouring & Serving", "Barista", 60),
        ])

        # Seed Orion Pizza for multi-restaurant testing
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
    finally:
        conn.close()


init_db()
seed_data()
