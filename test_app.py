"""
test_app.py - Automated Unit & Integration Tests

Covers:
1. Database schema and seed data verification.
2. Single dish ETA calculation with restaurant buffer.
3. Parallel station execution (Cold Coffee is NOT blocked by Burger).
4. Station & staff contention (Sequential queueing when 2 orders need Grill & Chef).
5. Order cancellation freeing capacity and recalculating downstream ETAs.
6. Multi-restaurant isolation (MoonWalk vs Orion Pizza).
7. Append-only ETA history audit log.
8. REST API endpoints (Menu, Orders, Polling, Cancellation, and History).
"""
import pytest
from fastapi import HTTPException

from database import get_db, init_db, seed_data
from scheduler import calculate_kitchen_etas
from main import (
    get_restaurants,
    get_menu,
    place_order,
    get_order_status,
    cancel_order,
    get_history,
    OrderCreateRequest,
    OrderItemInput,
)


@pytest.fixture(autouse=True)
def clean_orders_and_history():
    """
    Runs before every test.
    Clears orders, order items, and calculation history so each test runs with a clean slate.
    The menu, stations, and staff remain intact.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM eta_history;")
    cursor.execute("DELETE FROM order_items;")
    cursor.execute("DELETE FROM orders;")
    conn.commit()
    conn.close()
    yield


def test_database_initialization_and_seed():
    """Verify that tables exist and sample data for MoonWalk and Orion Pizza are seeded."""
    conn = get_db()
    cursor = conn.cursor()

    # Check restaurants
    cursor.execute("SELECT id, name FROM restaurants;")
    restaurants = {r["id"]: r["name"] for r in cursor.fetchall()}
    assert "moonwalk" in restaurants
    assert "orion-pizza" in restaurants

    # Check MoonWalk dishes (Indian menu: Burger, Fries, Coffee)
    cursor.execute("SELECT name, price FROM dishes WHERE restaurant_id = 'moonwalk';")
    dishes = {r["name"]: r["price"] for r in cursor.fetchall()}
    assert "Veg Cheese Burger" in dishes
    assert dishes["Veg Cheese Burger"] == 150.0
    assert "French Fries" in dishes
    assert dishes["French Fries"] == 100.0
    assert "Cold Coffee" in dishes
    assert dishes["Cold Coffee"] == 80.0

    # Check MoonWalk stations
    cursor.execute("SELECT name FROM stations WHERE restaurant_id = 'moonwalk';")
    station_names = [r["name"] for r in cursor.fetchall()]
    assert set(station_names) == {"Grill", "Fryer", "Barista", "Prep", "Plating"}

    conn.close()


def test_coffee_standalone_eta():
    """
    Cold Coffee:
    Step 0: Espresso & Milk Blending (180s) at Barista station
    Step 1: Pouring & Serving (60s) at Barista station
    Base duration = 240 seconds (4 minutes).
    Safety buffer = 10% (0.10).
    Expected finish = 240 * 1.10 = 264 seconds (4.4 minutes).
    """
    now = 1000.0
    conn = get_db()
    cursor = conn.cursor()

    # Find Cold Coffee dish ID
    cursor.execute("SELECT id FROM dishes WHERE restaurant_id = 'moonwalk' AND name = 'Cold Coffee';")
    coffee_id = cursor.fetchone()["id"]

    # Insert order
    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-COFFEE', 'moonwalk', 'Rohan', 'PREPARING', ?);",
        (now,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-COFFEE', ?, 'Cold Coffee', 'PREPARING');",
        (coffee_id,)
    )
    conn.commit()
    conn.close()

    results = calculate_kitchen_etas(restaurant_id="moonwalk", current_time=now)
    assert "ORD-COFFEE" in results

    expected_ready_at = now + (240 * 1.10)  # 1264.0
    assert results["ORD-COFFEE"]["order_ready_at"] == pytest.approx(expected_ready_at, abs=0.1)
    assert results["ORD-COFFEE"]["remaining_seconds"] == 264


def test_burger_standalone_eta():
    """
    Veg Cheese Burger:
    Step 0: Patty Grilling (420s) at Grill
    Step 1: Bun Toasting & Dressing (240s) at Prep
    Step 2: Plating & Wrapping (120s) at Plating
    Base duration = 780 seconds (13 minutes).
    Safety buffer = 10%.
    Expected finish = 780 * 1.10 = 858 seconds (14.3 minutes).
    """
    now = 2000.0
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM dishes WHERE restaurant_id = 'moonwalk' AND name = 'Veg Cheese Burger';")
    burger_id = cursor.fetchone()["id"]

    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-BURGER', 'moonwalk', 'Priya', 'PREPARING', ?);",
        (now,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-BURGER', ?, 'Veg Cheese Burger', 'PREPARING');",
        (burger_id,)
    )
    conn.commit()
    conn.close()

    results = calculate_kitchen_etas(restaurant_id="moonwalk", current_time=now)
    assert "ORD-BURGER" in results

    expected_ready_at = now + (780 * 1.10)  # 2858.0
    assert results["ORD-BURGER"]["order_ready_at"] == pytest.approx(expected_ready_at, abs=0.1)
    assert results["ORD-BURGER"]["remaining_seconds"] == 858


def test_parallel_stations_coffee_not_blocked_by_burger():
    """
    KEY USER REQUIREMENT:
    Customer 1 orders Veg Cheese Burger (uses Grill, Prep, Plating).
    Customer 2 orders Cold Coffee (uses Barista station with Bob).

    Since the Barista station and Bob are completely independent of Grill/Plating,
    the Cold Coffee MUST NOT wait behind the Burger!
    Coffee ready time is ~4.4 minutes (264s), NOT 40 minutes!
    """
    now = 3000.0
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM dishes WHERE restaurant_id = 'moonwalk' AND name = 'Veg Cheese Burger';")
    burger_id = cursor.fetchone()["id"]

    cursor.execute("SELECT id FROM dishes WHERE restaurant_id = 'moonwalk' AND name = 'Cold Coffee';")
    coffee_id = cursor.fetchone()["id"]

    # Customer 1: Burger
    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-CUST1', 'moonwalk', 'Alice', 'PREPARING', ?);",
        (now,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-CUST1', ?, 'Veg Cheese Burger', 'PREPARING');",
        (burger_id,)
    )

    # Customer 2: Coffee placed 5 seconds later
    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-CUST2', 'moonwalk', 'Bob', 'PREPARING', ?);",
        (now + 5,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-CUST2', ?, 'Cold Coffee', 'PREPARING');",
        (coffee_id,)
    )

    conn.commit()
    conn.close()

    results = calculate_kitchen_etas(restaurant_id="moonwalk", current_time=now)

    burger_ready = results["ORD-CUST1"]["order_ready_at"]
    coffee_ready = results["ORD-CUST2"]["order_ready_at"]

    # Coffee takes ~269.5s from now (240s prep + 5s arrival offset + 10% buffer)
    expected_coffee_ready = now + (245 * 1.10)
    assert coffee_ready == pytest.approx(expected_coffee_ready, abs=0.1)

    # Burger takes ~858s from now
    assert burger_ready == pytest.approx(now + 858.0, abs=0.1)

    # Coffee is ready MUCH sooner than burger
    assert coffee_ready < burger_ready
    # Coffee does NOT take 40 minutes (2400 seconds)
    assert results["ORD-CUST2"]["remaining_seconds"] <= 300


def test_station_and_staff_contention_multiple_burgers():
    """
    Customer 1 orders Veg Cheese Burger.
    Customer 2 orders Veg Cheese Burger.
    Both need Grill, Prep, and Plating.
    Order 1 finishes at now + 858s (780s base * 1.10).
    Order 2 is scheduled sequentially behind Order 1 for Grill and Alice (Prep).
    Unbuffered completion for Order 2 is 1440s.
    With 10% buffer: 1440 * 1.10 = 1584 seconds.
    """
    now = 5000.0
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM dishes WHERE restaurant_id = 'moonwalk' AND name = 'Veg Cheese Burger';")
    burger_id = cursor.fetchone()["id"]

    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-1', 'moonwalk', 'Ananya', 'PREPARING', ?);",
        (now,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-1', ?, 'Veg Cheese Burger', 'PREPARING');",
        (burger_id,)
    )

    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-2', 'moonwalk', 'Vikram', 'PREPARING', ?);",
        (now + 1,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-2', ?, 'Veg Cheese Burger', 'PREPARING');",
        (burger_id,)
    )

    conn.commit()
    conn.close()

    results = calculate_kitchen_etas(restaurant_id="moonwalk", current_time=now)

    # Order 1 finishes at now + 858s
    assert results["ORD-1"]["order_ready_at"] == pytest.approx(now + 858.0, abs=0.1)

    # Order 2 is delayed due to resource contention and finishes at now + 1584s
    assert results["ORD-2"]["order_ready_at"] == pytest.approx(now + 1584.0, abs=0.1)
    assert results["ORD-2"]["order_ready_at"] > results["ORD-1"]["order_ready_at"]


def test_cancellation_frees_capacity_and_recalculates():
    """
    Customer 1 orders Burger.
    Customer 2 orders Burger (waiting behind Customer 1).
    Customer 1 CANCELS their order.
    The scheduler recalculates and Customer 2 gets the resources immediately!
    Customer 2 ready time drops from 1584s down to 858s (saves 12 minutes).
    """
    now = 6000.0
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM dishes WHERE restaurant_id = 'moonwalk' AND name = 'Veg Cheese Burger';")
    burger_id = cursor.fetchone()["id"]

    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-CANCEL-1', 'moonwalk', 'Amit', 'PREPARING', ?);",
        (now,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-CANCEL-1', ?, 'Veg Cheese Burger', 'PREPARING');",
        (burger_id,)
    )

    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-CANCEL-2', 'moonwalk', 'Deepa', 'PREPARING', ?);",
        (now,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-CANCEL-2', ?, 'Veg Cheese Burger', 'PREPARING');",
        (burger_id,)
    )

    conn.commit()
    conn.close()

    # Initial calculation: ORD-CANCEL-2 takes 1584s
    res_before = calculate_kitchen_etas(restaurant_id="moonwalk", current_time=now)
    assert res_before["ORD-CANCEL-2"]["remaining_seconds"] == 1584

    # Now cancel ORD-CANCEL-1
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = 'CANCELLED' WHERE id = 'ORD-CANCEL-1';")
    cursor.execute("UPDATE order_items SET status = 'CANCELLED' WHERE order_id = 'ORD-CANCEL-1';")
    conn.commit()
    conn.close()

    # Recalculate after cancellation
    res_after = calculate_kitchen_etas(restaurant_id="moonwalk", current_time=now, trigger_reason="ORDER_CANCELLED")

    # ORD-CANCEL-1 is no longer in active results
    assert "ORD-CANCEL-1" not in res_after

    # ORD-CANCEL-2 now gets the Grill immediately: takes 858s instead of 1584s!
    assert res_after["ORD-CANCEL-2"]["remaining_seconds"] == 858


def test_multi_restaurant_isolation():
    """
    Part 2 Requirement:
    MoonWalk and Orion Pizza have separate kitchens, menus, and buffer percentages.
    An order in MoonWalk should not affect an order in Orion Pizza.
    """
    now = 7000.0
    conn = get_db()
    cursor = conn.cursor()

    # MoonWalk: Burger
    cursor.execute("SELECT id FROM dishes WHERE restaurant_id = 'moonwalk' AND name = 'Veg Cheese Burger';")
    burger_id = cursor.fetchone()["id"]
    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-MW', 'moonwalk', 'Karan', 'PREPARING', ?);",
        (now,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-MW', ?, 'Veg Cheese Burger', 'PREPARING');",
        (burger_id,)
    )

    # Orion Pizza: Margherita Pizza (300s + 420s + 90s = 810s. Buffer = 15% -> 810 * 1.15 = 931.5s)
    cursor.execute("SELECT id FROM dishes WHERE restaurant_id = 'orion-pizza' AND name = 'Margherita Pizza';")
    pizza_id = cursor.fetchone()["id"]
    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-OP', 'orion-pizza', 'Mario', 'PREPARING', ?);",
        (now,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-OP', ?, 'Margherita Pizza', 'PREPARING');",
        (pizza_id,)
    )

    conn.commit()
    conn.close()

    # Calculate MoonWalk
    mw_res = calculate_kitchen_etas(restaurant_id="moonwalk", current_time=now)
    assert "ORD-MW" in mw_res
    assert "ORD-OP" not in mw_res
    assert mw_res["ORD-MW"]["remaining_seconds"] == 858

    # Calculate Orion Pizza
    op_res = calculate_kitchen_etas(restaurant_id="orion-pizza", current_time=now)
    assert "ORD-OP" in op_res
    assert "ORD-MW" not in op_res
    assert op_res["ORD-OP"]["remaining_seconds"] == int(810 * 1.15)


def test_eta_history_audit_trail():
    """
    Part 1 Requirement:
    Verify that every calculation appends an immutable audit record to eta_history
    with order_id, calculated_at, estimated_duration_seconds, actual_elapsed_seconds, trigger_reason, and algorithm.
    """
    now = 8000.0
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM dishes WHERE restaurant_id = 'moonwalk' AND name = 'French Fries';")
    fries_id = cursor.fetchone()["id"]

    cursor.execute(
        "INSERT INTO orders (id, restaurant_id, customer_name, status, created_at) VALUES ('ORD-AUDIT', 'moonwalk', 'Sunil', 'PREPARING', ?);",
        (now,)
    )
    cursor.execute(
        "INSERT INTO order_items (order_id, dish_id, dish_name, status) VALUES ('ORD-AUDIT', ?, 'French Fries', 'PREPARING');",
        (fries_id,)
    )
    conn.commit()
    conn.close()

    calculate_kitchen_etas(restaurant_id="moonwalk", current_time=now, trigger_reason="TEST_NEW_ORDER")

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM eta_history WHERE order_id = 'ORD-AUDIT';")
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 1
    record = dict(rows[0])
    assert record["restaurant_id"] == "moonwalk"
    assert record["order_id"] == "ORD-AUDIT"
    assert record["trigger_reason"] == "TEST_NEW_ORDER"
    assert record["algorithm"] == "FIFO"
    assert record["calculated_at"] == now
    assert record["estimated_duration_seconds"] == pytest.approx(420 * 1.10, abs=0.1)  # 462.0s
    assert record["actual_elapsed_seconds"] == 0.0


def test_api_endpoints_flow():
    """
    Full end-to-end API test:
    1. get_restaurants()
    2. get_menu()
    3. place_order()
    4. get_order_status()
    5. cancel_order()
    6. get_history()
    """
    # 1. Restaurants
    rest_data = get_restaurants()
    assert len(rest_data) >= 2
    assert any(r["id"] == "moonwalk" for r in rest_data)

    # 2. Menu
    menu_data = get_menu(restaurant_id="moonwalk")
    assert len(menu_data["dishes"]) == 3
    coffee_dish = next(d for d in menu_data["dishes"] if d["name"] == "Cold Coffee")

    # 3. Place order
    req = OrderCreateRequest(
        restaurant_id="moonwalk",
        customer_name="Divya",
        items=[OrderItemInput(dish_id=coffee_dish["id"], quantity=1)]
    )
    order_data = place_order(req)
    order_id = order_data["order_id"]
    assert order_data["status"] == "PREPARING"
    assert len(order_data["dishes"]) == 1
    assert order_data["dishes"][0]["name"] == "Cold Coffee"
    assert order_data["order_remaining_seconds"] <= 265

    # 4. Poll status
    poll_data = get_order_status(order_id)
    assert poll_data["order_id"] == order_id
    assert poll_data["status"] == "PREPARING"
    assert poll_data["customer_name"] == "Divya"

    # 5. Cancel order
    cancel_data = cancel_order(order_id)
    assert cancel_data["status"] == "CANCELLED"
    assert cancel_data["dishes"][0]["status"] == "CANCELLED"

    # 6. History
    history = get_history(restaurant_id="moonwalk")
    assert len(history) >= 2
    reasons = [h["trigger_reason"] for h in history]
    assert "NEW_ORDER" in reasons
    assert "ORDER_CANCELLED" in reasons


def test_place_order_validation_errors():
    """Verifies that invalid requests are cleanly rejected."""
    # Empty items list
    with pytest.raises(HTTPException) as exc_info:
        place_order(OrderCreateRequest(customer_name="Test", items=[]))
    assert exc_info.value.status_code == 400

    # Non-existent dish
    with pytest.raises(HTTPException) as exc_info:
        place_order(OrderCreateRequest(
            customer_name="Test",
            items=[OrderItemInput(dish_id=99999, quantity=1)]
        ))
    assert exc_info.value.status_code == 404
