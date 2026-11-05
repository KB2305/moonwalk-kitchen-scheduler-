"""
FastAPI web application exposing kitchen order management and countdown endpoints.
"""
import time
import uuid
from pathlib import Path
from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from database import get_db, init_db, seed_data
from scheduler import calculate_kitchen_etas

app = FastAPI(
    title="MoonWalk Kitchen Scheduling System",
    description="Resource-aware kitchen countdown timer system for MoonWalk and other restaurants.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# Schemas
class OrderItemInput(BaseModel):
    dish_id: int
    quantity: int = Field(default=1, ge=1)


class AddItemRequest(BaseModel):
    dish_id: int
    quantity: int = Field(default=1, ge=1)


class OrderCreateRequest(BaseModel):
    restaurant_id: str = "moonwalk"
    customer_name: str
    items: List[OrderItemInput]


# Endpoints
@app.get("/")
def serve_homepage():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "MoonWalk API is running. Go to /docs for the API interface."}


@app.get("/api/restaurants")
def get_restaurants():
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, buffer_percentage, algorithm FROM restaurants;")
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


@app.get("/api/menu")
def get_menu(restaurant_id: str = "moonwalk"):
    conn = get_db()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT id, name, price, category FROM dishes WHERE restaurant_id = ?;", (restaurant_id,))
        dishes = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT name FROM stations WHERE restaurant_id = ?;", (restaurant_id,))
        stations = [r["name"] for r in cursor.fetchall()]

        cursor.execute("SELECT name, skills FROM staff WHERE restaurant_id = ?;", (restaurant_id,))
        staff = [dict(r) for r in cursor.fetchall()]

        return {
            "restaurant_id": restaurant_id,
            "stations": stations,
            "staff": staff,
            "dishes": dishes,
        }
    finally:
        conn.close()


@app.post("/api/orders", status_code=201)
def place_order(request: OrderCreateRequest):
    if not request.items:
        raise HTTPException(status_code=400, detail="Order must include at least one dish.")

    now = time.time()
    order_id = f"ORD-{uuid.uuid4().hex[:6].upper()}"

    conn = get_db()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO orders (id, restaurant_id, customer_name, status, created_at)
            VALUES (?, ?, ?, 'PREPARING', ?);
        """, (order_id, request.restaurant_id, request.customer_name, now))

        for item in request.items:
            cursor.execute("SELECT name FROM dishes WHERE id = ? AND restaurant_id = ?;", (item.dish_id, request.restaurant_id))
            dish_row = cursor.fetchone()
            if not dish_row:
                raise HTTPException(status_code=404, detail=f"Dish ID {item.dish_id} not found.")

            dish_name = dish_row["name"]
            for _ in range(item.quantity):
                cursor.execute("""
                    INSERT INTO order_items (order_id, dish_id, dish_name, status)
                    VALUES (?, ?, ?, 'PREPARING');
                """, (order_id, item.dish_id, dish_name))

        conn.commit()
    finally:
        conn.close()

    calculate_kitchen_etas(restaurant_id=request.restaurant_id, current_time=now, trigger_reason="NEW_ORDER")
    return get_order_status(order_id)


@app.get("/api/orders/{order_id}")
def get_order_status(order_id: str):
    now = time.time()
    conn = get_db()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM orders WHERE id = ?;", (order_id,))
        order_row = cursor.fetchone()
        if not order_row:
            raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")

        cursor.execute("SELECT * FROM order_items WHERE order_id = ?;", (order_id,))
        item_rows = cursor.fetchall()
    finally:
        conn.close()

    dishes = []
    for item in item_rows:
        ready_at = item["ready_at"]
        item_status = item["status"]
        if item_status == "PREPARING" and ready_at and ready_at <= now:
            item_status = "COMPLETED"

        if item_status == "CANCELLED":
            rem_sec = None
        elif item_status == "COMPLETED":
            rem_sec = 0
        else:
            rem_sec = max(0, int(ready_at - now)) if ready_at else None

        dishes.append({
            "order_item_id": item["id"],
            "dish_id": item["dish_id"],
            "name": item["dish_name"],
            "status": item_status,
            "ready_at": ready_at,
            "remaining_seconds": rem_sec,
        })

    order_ready_at = order_row["ready_at"]
    order_status = order_row["status"]
    if order_status == "PREPARING" and order_ready_at and order_ready_at <= now:
        order_status = "COMPLETED"

    if order_status == "CANCELLED":
        order_rem_sec = None
    elif order_status == "COMPLETED":
        order_rem_sec = 0
    else:
        order_rem_sec = max(0, int(order_ready_at - now)) if order_ready_at else None

    return {
        "order_id": order_row["id"],
        "restaurant_id": order_row["restaurant_id"],
        "customer_name": order_row["customer_name"],
        "status": order_status,
        "created_at": order_row["created_at"],
        "order_ready_at": order_ready_at,
        "order_remaining_seconds": order_rem_sec,
        "dishes": dishes,
    }


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: str):
    now = time.time()
    conn = get_db()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT restaurant_id, status, created_at FROM orders WHERE id = ?;", (order_id,))
        order_row = cursor.fetchone()
        if not order_row:
            raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")
        if order_row["status"] == "COMPLETED":
            raise HTTPException(status_code=400, detail="Cannot cancel an order that is already completed.")
        if order_row["status"] == "CANCELLED":
            raise HTTPException(status_code=400, detail="Order is already cancelled.")

        restaurant_id = order_row["restaurant_id"]
        created_at = order_row["created_at"]

        cursor.execute("UPDATE orders SET status = 'CANCELLED' WHERE id = ?;", (order_id,))
        cursor.execute("UPDATE order_items SET status = 'CANCELLED' WHERE order_id = ?;", (order_id,))

        actual_elapsed = max(0.0, now - created_at)
        cursor.execute("""
            INSERT INTO eta_history (
                restaurant_id, order_id, calculated_at,
                estimated_duration_seconds, actual_elapsed_seconds,
                order_status, trigger_reason, algorithm
            ) VALUES (?, ?, ?, 0.0, ?, 'CANCELLED', 'ORDER_CANCELLED', 'FIFO');
        """, (restaurant_id, order_id, now, round(actual_elapsed, 1)))

        conn.commit()
    finally:
        conn.close()

    calculate_kitchen_etas(restaurant_id=restaurant_id, current_time=now, trigger_reason="ORDER_CANCELLED")
    return get_order_status(order_id)


@app.post("/api/orders/{order_id}/items")
def add_item_to_order(order_id: str, request: AddItemRequest):
    now = time.time()
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT restaurant_id, status FROM orders WHERE id = ?;", (order_id,))
        order_row = cursor.fetchone()
        if not order_row:
            raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")
        if order_row["status"] != "PREPARING":
            raise HTTPException(status_code=400, detail="Cannot add items to completed or cancelled orders.")

        restaurant_id = order_row["restaurant_id"]
        cursor.execute("SELECT name FROM dishes WHERE id = ? AND restaurant_id = ?;", (request.dish_id, restaurant_id))
        dish_row = cursor.fetchone()
        if not dish_row:
            raise HTTPException(status_code=404, detail="Dish not found.")

        dish_name = dish_row["name"]
        for _ in range(request.quantity):
            cursor.execute("""
                INSERT INTO order_items (order_id, dish_id, dish_name, status)
                VALUES (?, ?, ?, 'PREPARING');
            """, (order_id, request.dish_id, dish_name))
        conn.commit()
    finally:
        conn.close()

    calculate_kitchen_etas(restaurant_id=restaurant_id, current_time=now, trigger_reason="ITEM_ADDED")
    return get_order_status(order_id)


@app.post("/api/orders/{order_id}/items/{item_id}/cancel")
def cancel_order_item(order_id: str, item_id: int):
    now = time.time()
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT restaurant_id, status FROM orders WHERE id = ?;", (order_id,))
        order_row = cursor.fetchone()
        if not order_row:
            raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")
        if order_row["status"] == "CANCELLED":
            raise HTTPException(status_code=400, detail="Order is already cancelled.")

        cursor.execute("SELECT id, dish_name, status FROM order_items WHERE id = ? AND order_id = ?;", (item_id, order_id))
        item_row = cursor.fetchone()
        if not item_row:
            raise HTTPException(status_code=404, detail=f"Order item {item_id} not found in order {order_id}.")
        if item_row["status"] == "CANCELLED":
            raise HTTPException(status_code=400, detail="Item is already cancelled.")

        restaurant_id = order_row["restaurant_id"]
        cursor.execute("UPDATE order_items SET status = 'CANCELLED' WHERE id = ?;", (item_id,))

        # If all items are cancelled, mark the entire order cancelled
        cursor.execute("SELECT COUNT(*) as active_cnt FROM order_items WHERE order_id = ? AND status = 'PREPARING';", (order_id,))
        active_cnt = cursor.fetchone()["active_cnt"]

        order_status = "PREPARING"
        if active_cnt == 0:
            order_status = "CANCELLED"
            cursor.execute("UPDATE orders SET status = 'CANCELLED' WHERE id = ?;", (order_id,))

        cursor.execute("""
            INSERT INTO eta_history (
                restaurant_id, order_id, calculated_at,
                estimated_duration_seconds, actual_elapsed_seconds,
                order_status, trigger_reason, algorithm
            ) VALUES (?, ?, ?, 0.0, 0.0, ?, 'DISH_CANCELLED', 'FIFO');
        """, (restaurant_id, order_id, now, order_status))

        conn.commit()
    finally:
        conn.close()

    calculate_kitchen_etas(restaurant_id=restaurant_id, current_time=now, trigger_reason="DISH_CANCELLED")
    return get_order_status(order_id)


@app.get("/api/active-orders")
def get_active_orders(restaurant_id: str = "moonwalk"):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM orders
            WHERE restaurant_id = ? AND status = 'PREPARING'
            ORDER BY created_at ASC;
        """, (restaurant_id,))
        order_ids = [r["id"] for r in cursor.fetchall()]
    finally:
        conn.close()

    return [get_order_status(oid) for oid in order_ids]


@app.get("/api/history")
def get_history(restaurant_id: str = "moonwalk", limit: int = 20):
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM eta_history
            WHERE restaurant_id = ?
            ORDER BY calculated_at DESC, id DESC
            LIMIT ?;
        """, (restaurant_id, limit))
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


@app.post("/api/reset")
def reset_kitchen_orders():
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM eta_history;")
        cursor.execute("DELETE FROM order_items;")
        cursor.execute("DELETE FROM orders;")
        conn.commit()
        return {"message": "All test orders and history cleared."}
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
