# MoonWalk — Space Kitchen Scheduling System

A resource-aware restaurant kitchen scheduling engine and real-time customer countdown system built with Python, SQLite, and FastAPI.

---

## 1. Overview

In a commercial restaurant kitchen, preparation times cannot simply be summed together because physical resources are finite:
- **Station Capacities**: Stations (`Grill`, `Fryer`, `Barista`, `Prep`, `Plating`) have limited slots.
- **Staff & Skills**: Staff members (`Alice`, `Bob`, `Charlie`) have specific station proficiencies.
- **Sequential Dependencies**: A dish requires ordered steps (e.g., grilling patty → bun assembly → plating).
- **Parallel Execution**: Independent stations (e.g., Barista beverage counter) run concurrently without blocking cooking stations.

### Menu Configuration (MoonWalk Space Diner)
| Dish | Steps & Base Prep | Station(s) | Primary Staff | Price |
|---|---|---|---|---|
| **Cold Coffee** | Blending (3m) → Pouring (1m) = **4 mins (240s)** | `Barista` | Bob | ₹80 |
| **French Fries** | Deep Frying (5m) → Plating (2m) = **7 mins (420s)** | `Fryer` → `Plating` | Alice / Charlie | ₹100 |
| **Veg Cheese Burger** | Grilling (7m) → Prep (4m) → Plating (2m) = **13 mins (780s)** | `Grill` → `Prep` → `Plating` | Alice / Charlie | ₹150 |

---

## 2. Core Scheduling Logic

The engine in `scheduler.py` uses a **Resource Availability Timeline**:

1. **Resource Tracking**: Timestamps track when each physical station and staff member becomes free:
   ```python
   station_free_at = {"Grill": now, "Fryer": now, "Barista": now, ...}
   staff_free_at   = {"Alice": now, "Bob": now, "Charlie": now}
   ```
2. **Step Start Calculation**:
   $$\text{step\_start} = \max(\text{prev\_step\_finish}, \text{station\_free}, \text{staff\_free}, \text{now})$$
3. **Safety Buffer**: The restaurant's configured buffer percentage (e.g., 10%) is applied once to the remaining preparation duration:
   $$\text{ready\_at} = \text{now} + (\text{remaining\_duration} \times (1 + \text{buffer}))$$
4. **Order Completion**: Overall order ETA equals the maximum ready time among its dishes:
   $$\text{order\_ready\_at} = \max(\text{dish\_ready\_times})$$
5. **Dynamic Updates**: Recalculations are automatically triggered when new orders arrive, orders complete, or orders are cancelled (immediately freeing capacity for queued orders).
6. **Audit Trail**: Every calculation is logged in an append-only `eta_history` database table recording timestamp, estimated duration, actual elapsed time, algorithm, and trigger reason.

---

## 3. Multi-Restaurant Support (Multi-Tenancy)

The engine is **data-driven**. All restaurant menus, cooking steps, kitchen stations, staff skills, and safety buffers are stored in database configuration tables (`restaurants`, `stations`, `staff`, `dishes`, `dish_steps`).

Adding another restaurant (e.g. *Orion Woodfired Pizza* with a 15% safety buffer and distinct stations like `Oven` and `DoughTable`) requires **zero code changes**—only database records.

---

## 4. Quick Start

### Prerequisites
- Python 3.9+

### Installation
```bash
pip install -r requirements.txt
```

### Run Server
```bash
python main.py
```
- **Customer UI**: [http://localhost:8000](http://localhost:8000)
- **API Documentation (Swagger)**: [http://localhost:8000/docs](http://localhost:8000/docs)

### Run Tests
```bash
pytest test_app.py -v
```

---

## 5. API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Customer countdown timer UI |
| `GET` | `/api/restaurants` | List configured restaurants |
| `GET` | `/api/menu?restaurant_id={id}` | Get dishes, stations, and staff for a restaurant |
| `POST` | `/api/orders` | Place a customer order and receive dish & order ETAs |
| `GET` | `/api/orders/{order_id}` | Poll remaining countdown seconds and statuses |
| `POST` | `/api/orders/{order_id}/cancel` | Cancel order and recalculate kitchen schedules |
| `GET` | `/api/history?restaurant_id={id}` | Retrieve immutable ETA calculation audit logs |
