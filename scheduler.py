"""
scheduler.py - Kitchen Scheduling & ETA Calculation Engine

How it works:
1. Tracks when each station and employee becomes free using simple dictionaries:
   - station_free_at = {"Grill": 12:00, "Fryer": 12:00, "Barista": 12:00, ...}
   - staff_free_at = {"Alice": 12:00, "Bob": 12:00, "Charlie": 12:00}
2. Processes orders in the order they arrived (FIFO).
3. For each preparation step:
   - It finds when the previous step finishes.
   - It checks when the required station and qualified employee are free.
   - It calculates: start_time = max(previous_step_finish, station_free_time, staff_free_time, current_time)
   - It calculates: finish_time = start_time + duration
   - It updates the station and employee to be busy until finish_time.
4. Adds the restaurant safety buffer (e.g. 10%) once to the predicted preparation duration.
5. Overall order ETA is the maximum of all dish ETAs in that order.
6. Saves the calculated ready times and records the calculation in the audit history table.
"""
import time
from database import get_db


def calculate_kitchen_etas(restaurant_id: str = "moonwalk", current_time: float = None, trigger_reason: str = "SCHEDULE_UPDATE"):
    """
    Recalculates preparation schedules and countdown ETAs for all active orders in the kitchen.
    """
    sim_now = current_time if current_time is not None else time.time()
    conn = get_db()
    cursor = conn.cursor()

    # 1. Clean up: Mark orders whose ready time has already passed as COMPLETED
    cursor.execute("""
        UPDATE orders
        SET status = 'COMPLETED'
        WHERE restaurant_id = ?
          AND status = 'PREPARING'
          AND ready_at IS NOT NULL
          AND ready_at <= ?;
    """, (restaurant_id, sim_now))

    cursor.execute("""
        UPDATE order_items
        SET status = 'COMPLETED'
        WHERE status = 'PREPARING'
          AND order_id IN (SELECT id FROM orders WHERE status = 'COMPLETED');
    """)
    conn.commit()

    # 2. Get restaurant configuration (buffer percentage and algorithm)
    cursor.execute("SELECT buffer_percentage, algorithm FROM restaurants WHERE id = ?;", (restaurant_id,))
    rest_row = cursor.fetchone()
    if not rest_row:
        conn.close()
        return {}

    buffer_pct = rest_row["buffer_percentage"]
    algorithm_name = rest_row["algorithm"]

    # 3. Load active stations
    cursor.execute("SELECT name FROM stations WHERE restaurant_id = ?;", (restaurant_id,))
    station_names = [row["name"] for row in cursor.fetchall()]
    # Every station starts free at current simulation time
    station_free_at = {st: sim_now for st in station_names}

    # 4. Load staff members and their skills
    cursor.execute("SELECT name, skills FROM staff WHERE restaurant_id = ?;", (restaurant_id,))
    staff_rows = cursor.fetchall()
    staff_free_at = {row["name"]: sim_now for row in staff_rows}

    # Map each station to the list of staff members who can work there
    station_to_staff = {st: [] for st in station_names}
    for row in staff_rows:
        staff_name = row["name"]
        skills = [s.strip() for s in row["skills"].split(",")]
        for sk in skills:
            if sk in station_to_staff:
                station_to_staff[sk].append(staff_name)

    # 5. Load all active orders (FIFO order: oldest order first)
    cursor.execute("""
        SELECT id, created_at
        FROM orders
        WHERE restaurant_id = ? AND status = 'PREPARING'
        ORDER BY created_at ASC;
    """, (restaurant_id,))
    active_orders = cursor.fetchall()

    if not active_orders:
        conn.close()
        return {}

    order_results = {}

    # 6. Schedule each order through the kitchen
    for ord_row in active_orders:
        order_id = ord_row["id"]
        order_created_at = ord_row["created_at"]

        # Fetch dishes in this order
        cursor.execute("""
            SELECT id, dish_id, dish_name
            FROM order_items
            WHERE order_id = ? AND status = 'PREPARING'
            ORDER BY id ASC;
        """, (order_id,))
        items = cursor.fetchall()

        dish_ready_times = []

        for item in items:
            item_id = item["id"]
            dish_id = item["dish_id"]

            # Load the ordered sequential cooking steps for this dish
            cursor.execute("""
                SELECT name, station_name, duration_seconds
                FROM dish_steps
                WHERE dish_id = ?
                ORDER BY step_order ASC;
            """, (dish_id,))
            steps = cursor.fetchall()

            # First step starts after order creation or current time
            step_prev_finish = max(order_created_at, sim_now)

            # Schedule each step sequentially
            for step in steps:
                station = step["station_name"]
                duration = step["duration_seconds"]

                # Find available qualified staff for this station
                qualified = station_to_staff.get(station, [])
                if qualified:
                    # Pick the qualified staff member who is free earliest
                    chosen_staff = min(qualified, key=lambda name: staff_free_at[name])
                    staff_ready_time = staff_free_at[chosen_staff]
                else:
                    # Fallback if no specific staff assigned
                    chosen_staff = None
                    staff_ready_time = sim_now

                station_ready_time = station_free_at.get(station, sim_now)

                # Core scheduling equation:
                # Step starts when previous step is done AND station is free AND staff is free
                step_start = max(step_prev_finish, station_ready_time, staff_ready_time, sim_now)
                step_finish = step_start + duration

                # Update resources to be busy until this step finishes
                if station in station_free_at:
                    station_free_at[station] = step_finish
                if chosen_staff and chosen_staff in staff_free_at:
                    staff_free_at[chosen_staff] = step_finish

                # Next step must wait for this step to finish
                step_prev_finish = step_finish

            # Dish finishes when its last step completes
            unbuffered_finish = step_prev_finish
            remaining_prep = max(0.0, unbuffered_finish - sim_now)

            # Apply restaurant buffer (e.g. 10%) once to the remaining predicted preparation duration
            dish_ready_at = sim_now + (remaining_prep * (1.0 + buffer_pct))
            dish_ready_times.append(dish_ready_at)

            # Save the dish ready timestamp in database
            cursor.execute("""
                UPDATE order_items
                SET ready_at = ?
                WHERE id = ?;
            """, (dish_ready_at, item_id))

        # Overall order ready time is when its slowest dish finishes
        order_ready_at = max(dish_ready_times) if dish_ready_times else sim_now

        # Save order ready timestamp in database
        cursor.execute("""
            UPDATE orders
            SET ready_at = ?
            WHERE id = ?;
        """, (order_ready_at, order_id))

        # Save immutable audit record into eta_history (Part 1 requirement)
        actual_elapsed = max(0.0, sim_now - order_created_at)
        estimated_duration = max(0.0, order_ready_at - sim_now)

        cursor.execute("""
            INSERT INTO eta_history (
                restaurant_id, order_id, calculated_at,
                estimated_duration_seconds, actual_elapsed_seconds,
                trigger_reason, algorithm
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (
            restaurant_id,
            order_id,
            sim_now,
            round(estimated_duration, 1),
            round(actual_elapsed, 1),
            trigger_reason,
            algorithm_name,
        ))

        order_results[order_id] = {
            "order_ready_at": order_ready_at,
            "remaining_seconds": max(0, int(order_ready_at - sim_now)),
        }

    conn.commit()
    conn.close()
    return order_results

