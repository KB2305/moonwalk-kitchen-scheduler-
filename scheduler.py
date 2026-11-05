"""
Kitchen scheduling engine for calculating order and dish preparation times.
Simulates kitchen throughput based on station capacities, chef skill sets,
and sequential dish preparation steps.
"""
import time
from database import get_db


def calculate_kitchen_etas(restaurant_id: str = "moonwalk", current_time: float = None, trigger_reason: str = "SCHEDULE_UPDATE"):
    sim_now = current_time if current_time is not None else time.time()
    conn = get_db()
    try:
        cursor = conn.cursor()

        # Mark completed individual dishes and completed orders
        cursor.execute("""
            UPDATE order_items
            SET status = 'COMPLETED'
            WHERE status = 'PREPARING'
              AND ready_at IS NOT NULL
              AND ready_at <= ?;
        """, (sim_now,))

        cursor.execute("""
            UPDATE orders
            SET status = 'COMPLETED'
            WHERE restaurant_id = ?
              AND status = 'PREPARING'
              AND ready_at IS NOT NULL
              AND ready_at <= ?;
        """, (restaurant_id, sim_now))
        conn.commit()

        # Load restaurant settings
        cursor.execute("SELECT buffer_percentage, algorithm FROM restaurants WHERE id = ?;", (restaurant_id,))
        rest_row = cursor.fetchone()
        if not rest_row:
            return {}

        buffer_pct = rest_row["buffer_percentage"]
        algorithm_name = rest_row["algorithm"]

        # Fetch active orders in arrival sequence
        cursor.execute("""
            SELECT id, created_at
            FROM orders
            WHERE restaurant_id = ? AND status = 'PREPARING'
            ORDER BY created_at ASC;
        """, (restaurant_id,))
        active_orders = cursor.fetchall()

        if not active_orders:
            return {}

        # Start timeline from earliest active order
        earliest_time = min(r["created_at"] for r in active_orders)

        # Initialize station availability
        cursor.execute("SELECT name FROM stations WHERE restaurant_id = ?;", (restaurant_id,))
        station_names = [row["name"] for row in cursor.fetchall()]
        station_free_at = {st: earliest_time for st in station_names}

        # Initialize staff availability and map skills
        cursor.execute("SELECT name, skills FROM staff WHERE restaurant_id = ?;", (restaurant_id,))
        staff_rows = cursor.fetchall()
        staff_free_at = {row["name"]: earliest_time for row in staff_rows}

        station_to_staff = {st: [] for st in station_names}
        for row in staff_rows:
            staff_name = row["name"]
            skills = [s.strip() for s in row["skills"].split(",")]
            for sk in skills:
                if sk in station_to_staff:
                    station_to_staff[sk].append(staff_name)

        order_results = {}

        for ord_row in active_orders:
            order_id = ord_row["id"]
            order_created_at = ord_row["created_at"]

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

                cursor.execute("""
                    SELECT name, station_name, duration_seconds
                    FROM dish_steps
                    WHERE dish_id = ?
                    ORDER BY step_order ASC;
                """, (dish_id,))
                steps = cursor.fetchall()

                step_prev_finish = order_created_at

                for step in steps:
                    station = step["station_name"]
                    duration = step["duration_seconds"]

                    qualified = station_to_staff.get(station, [])
                    if qualified:
                        chosen_staff = min(qualified, key=lambda name: staff_free_at[name])
                        staff_ready_time = staff_free_at[chosen_staff]
                    else:
                        chosen_staff = None
                        staff_ready_time = earliest_time

                    station_ready_time = station_free_at.get(station, earliest_time)

                    # Step starts once previous step, station, and staff are all ready
                    step_start = max(step_prev_finish, station_ready_time, staff_ready_time)
                    step_finish = step_start + duration

                    if station in station_free_at:
                        station_free_at[station] = step_finish
                    if chosen_staff and chosen_staff in staff_free_at:
                        staff_free_at[chosen_staff] = step_finish

                    step_prev_finish = step_finish

                # Apply buffer to remaining preparation duration
                unbuffered_finish = step_prev_finish
                remaining_prep = max(0.0, unbuffered_finish - sim_now)
                dish_ready_at = sim_now + (remaining_prep * (1.0 + buffer_pct))
                dish_ready_times.append(dish_ready_at)

                cursor.execute("""
                    UPDATE order_items
                    SET ready_at = ?
                    WHERE id = ?;
                """, (dish_ready_at, item_id))

            # Order completes when all dishes finish
            order_ready_at = max(dish_ready_times) if dish_ready_times else order_created_at

            cursor.execute("""
                UPDATE orders
                SET ready_at = ?
                WHERE id = ?;
            """, (order_ready_at, order_id))

            # Record audit log
            actual_elapsed = max(0.0, sim_now - order_created_at)
            estimated_duration = max(0.0, order_ready_at - sim_now)

            cursor.execute("""
                INSERT INTO eta_history (
                    restaurant_id, order_id, calculated_at,
                    estimated_duration_seconds, actual_elapsed_seconds,
                    order_status, trigger_reason, algorithm
                ) VALUES (?, ?, ?, ?, ?, 'PREPARING', ?, ?);
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
        return order_results
    finally:
        conn.close()
