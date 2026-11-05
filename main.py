"""
main.py - FastAPI Web Server & API Endpoints

Provides REST endpoints for:
1. Viewing menu and kitchen stations.
2. Placing customer orders and returning live countdowns.
3. Polling remaining seconds every few seconds.
4. Cancelling an order and recalculating remaining customer ETAs.
5. Inspecting the immutable calculation audit history.
"""
import time
import uuid
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import get_db, init_db, seed_data
from scheduler import calculate_kitchen_etas

# Initialize FastAPI
app = FastAPI(
    title="MoonWalk Kitchen Scheduling System",
    description="Resource-aware kitchen countdown timer system for MoonWalk and other restaurants.",
    version="1.0.0"
)

# Allow CORS for browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files folder for the HTML/CSS/JS frontend
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ----------------------------------------------------
# Request and Response Models
# ----------------------------------------------------
class OrderItemInput(BaseModel):
    dish_id: int
    quantity: int = 1


class OrderCreateRequest(BaseModel):
    restaurant_id: str = "moonwalk"
    customer_name: str
    items: List[OrderItemInput]


# ----------------------------------------------------
# API Endpoints
# ----------------------------------------------------
@app.get("/")
def serve_homepage():
    """Serves the customer countdown timer HTML page."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "MoonWalk API is running. Go to /docs for the API interface."}


@app.get("/api/restaurants")
def get_restaurants():
    """Returns a list of all configured restaurants (Part 2)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, buffer_percentage, algorithm FROM restaurants;")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


@app.get("/api/menu")
def get_menu(restaurant_id: str = "moonwalk"):
    """Returns the menu items and stations for the specified restaurant."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, price, category FROM dishes WHERE restaurant_id = ?;", (restaurant_id,))
    dishes = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT name FROM stations WHERE restaurant_id = ?;", (restaurant_id,))
    stations = [r["name"] for r in cursor.fetchall()]

    cursor.execute("SELECT name, skills FROM staff WHERE restaurant_id = ?;", (restaurant_id,))
    staff = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "restaurant_id": restaurant_id,
        "stations": stations,
        "staff": staff,
        "dishes": dishes,
    }


@app.post("/api/orders", status_code=201)
def place_order(request: OrderCreateRequest):
    """
    Places a new customer order and immediately calculates realistic countdown ETAs.
    """
    if not request.items:
        raise HTTPException(status_code=400, detail="Order must include at least one dish.")

    now = time.time()
    order_id = f"ORD-{uuid.uuid4().hex[:6].upper()}"

    conn = get_db()
    cursor = conn.cursor()

    # 1. Insert order record
    cursor.execute("""
        INSERT INTO orders (id, restaurant_id, customer_name, status, created_at)
        VALUES (?, ?, ?, 'PREPARING', ?);
    """, (order_id, request.restaurant_id, request.customer_name, now))

    # 2. Insert order items
    for item in request.items:
        cursor.execute("SELECT name FROM dishes WHERE id = ? AND restaurant_id = ?;", (item.dish_id, request.restaurant_id))
        dish_row = cursor.fetchone()
        if not dish_row:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Dish ID {item.dish_id} not found.")

        dish_name = dish_row["name"]
        for _ in range(item.quantity):
            cursor.execute("""
                INSERT INTO order_items (order_id, dish_id, dish_name, status)
                VALUES (?, ?, ?, 'PREPARING');
            """, (order_id, item.dish_id, dish_name))

    conn.commit()
    conn.close()

    # 3. Calculate ETAs for all active backlog in the kitchen
    calculate_kitchen_etas(restaurant_id=request.restaurant_id, current_time=now, trigger_reason="NEW_ORDER")

    # 4. Return the order status with countdown
    return get_order_status(order_id)


@app.get("/api/orders/{order_id}")
def get_order_status(order_id: str):
    """
    Returns the live status, ready timestamp, and countdown seconds for each dish in the order.
    The browser polls this endpoint every 5 seconds.
    """
    now = time.time()
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM orders WHERE id = ?;", (order_id,))
    order_row = cursor.fetchone()
    if not order_row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")

    cursor.execute("SELECT * FROM order_items WHERE order_id = ?;", (order_id,))
    item_rows = cursor.fetchall()
    conn.close()

    dishes = []
    for item in item_rows:
        ready_at = item["ready_at"]
        rem_sec = max(0, int(ready_at - now)) if ready_at else None
        dishes.append({
            "order_item_id": item["id"],
            "dish_id": item["dish_id"],
            "name": item["dish_name"],
            "status": item["status"],
            "ready_at": ready_at,
            "remaining_seconds": rem_sec,
        })

    order_ready_at = order_row["ready_at"]
    order_rem_sec = max(0, int(order_ready_at - now)) if order_ready_at else None

    return {
        "order_id": order_row["id"],
        "restaurant_id": order_row["restaurant_id"],
        "customer_name": order_row["customer_name"],
        "status": order_row["status"],
        "created_at": order_row["created_at"],
        "order_ready_at": order_ready_at,
        "order_remaining_seconds": order_rem_sec,
        "dishes": dishes,
    }


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    """
    Cancels an order, immediately frees pending kitchen capacity,
    and recalculates schedules for other waiting customers.
    """
    now = time.time()
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT restaurant_id, status, created_at FROM orders WHERE id = ?;", (order_id,))
    order_row = cursor.fetchone()
    if not order_row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")

    restaurant_id = order_row["restaurant_id"]
    created_at = order_row["created_at"]

    cursor.execute("UPDATE orders SET status = 'CANCELLED' WHERE id = ?;", (order_id,))
    cursor.execute("UPDATE order_items SET status = 'CANCELLED' WHERE order_id = ?;", (order_id,))

    # Record cancellation event in immutable audit log
    actual_elapsed = max(0.0, now - created_at)
    cursor.execute("""
        INSERT INTO eta_history (
            restaurant_id, order_id, calculated_at,
            estimated_duration_seconds, actual_elapsed_seconds,
            trigger_reason, algorithm
        ) VALUES (?, ?, ?, 0.0, ?, 'ORDER_CANCELLED', 'FIFO');
    """, (restaurant_id, order_id, now, round(actual_elapsed, 1)))

    conn.commit()
    conn.close()

    # Recalculate remaining backlog with trigger_reason='ORDER_CANCELLED'
    calculate_kitchen_etas(restaurant_id=restaurant_id, current_time=now, trigger_reason="ORDER_CANCELLED")

    return get_order_status(order_id)


@app.get("/api/history")
def get_history(restaurant_id: str = "moonwalk", limit: int = 20):
    """
    Retrieves the immutable audit history of recent ETA calculations.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM eta_history
        WHERE restaurant_id = ?
        ORDER BY calculated_at DESC, id DESC
        LIMIT ?;
    """, (restaurant_id, limit))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)

