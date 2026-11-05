# MoonWalk — Space Kitchen Scheduling & Countdown System

> **A resource-aware kitchen scheduling engine and real-time customer countdown timer system built for MoonWalk Space Diner and multi-tenant restaurants.**

---

## 1. Project Overview

When customers place orders at **MoonWalk Space Diner**, dish preparation times cannot simply be summed together. Real kitchen operations are bounded by physical constraints:
- **Station Capacity**: Physical stations (e.g., Grill, Fryer, Barista counter) can only handle a limited number of items simultaneously.
- **Staff Availability & Skills**: Chefs have specific skills (e.g., Alice handles Grill, Fryer, Prep, and Plating; Bob specializes in Barista beverages; Charlie assists with Grill, Fryer, and Plating).
- **Sequential Dependencies**: A burger must be grilled before bun dressing and plating.
- **Independent Parallel Stations**: Drinks prepared at the Barista counter run in parallel and do not get blocked by grilling or food plating.

### Simple Menu (Indian Pricing & Times)
| Dish | Category | Prep Steps & Duration | Station Used | Assigned Staff | Price |
|---|---|---|---|---|---|
| **Cold Coffee** | Drink (Low Time) | 1. Espresso & Blending (3m)<br>2. Pouring & Serving (1m) = **4 mins (240s)** | `Barista` | Bob | **₹80** |
| **French Fries** | Snack (Medium Time) | 1. Deep Frying (5m)<br>2. Plating & Salting (2m) = **7 mins (420s)** | `Fryer` → `Plating` | Alice / Charlie | **₹100** |
| **Veg Cheese Burger** | Meal (High Time) | 1. Patty Grilling (7m)<br>2. Bun Dressing (4m)<br>3. Plating (2m) = **13 mins (780s)** | `Grill` → `Prep` → `Plating` | Alice / Charlie | **₹150** |

---

## 2. Problem Requirements Addressed

### Part 1: Core Kitchen Scheduling & Audit Trail
1. **Resource-Aware Scheduling**: Factors in kitchen backlog, station capacities, staff skills/availability, and sequential steps.
2. **Per-Dish and Order Countdown Timers**: Each dish has its own ready timestamp (`ready_at`). The overall order timer displays the slowest dish.
3. **Safety Buffer**: Configurable restaurant buffer (e.g. 10%) applied **once** to the remaining predicted duration.
4. **Recalculation on Events**: Automatically recalculates schedules when an order is placed, cancelled, or finished.
5. **Immutable Audit History**: Every calculation records an immutable log in `eta_history` containing `timestamp`, `estimated_duration`, `actual_elapsed`, `trigger_reason`, and `algorithm`.

### Part 2: Multi-Restaurant Support (Multi-Tenancy)
- The entire engine is **data-driven**: Menu items, cooking steps, kitchen stations, staff skills, and safety buffers are stored in database configuration tables (`restaurants`, `stations`, `staff`, `dishes`, `dish_steps`).
- Adding a new restaurant (e.g. **Orion Woodfired Pizza** with Margherita Pizza, DoughTable, Oven, and 15% buffer) requires **zero code changes** — only database rows.

---

## 3. Architecture & Project Structure

The project is designed with clean, beginner-friendly Python code tailored for maintainability and clear explanations:

```text
Moonwalk/
├── database.py         # SQLite connection helper, table schemas, and initial seed data
├── scheduler.py        # Core scheduling engine using resource availability tracking
├── main.py             # FastAPI REST API endpoints and static file hosting
├── test_app.py         # 10 comprehensive unit and integration tests (pytest)
├── static/             # Single-page customer countdown frontend
│   ├── index.html      # Customer UI layout
│   ├── style.css       # Clean styling & responsive layout
│   └── script.js       # Live 1-second countdown clock and 5-second polling
├── requirements.txt    # Minimal dependencies (fastapi, uvicorn, pytest, requests)
└── README.md           # Documentation and interview guide
```

---

## 4. How the Scheduling Engine Works

The scheduler in `scheduler.py` uses an intuitive **Resource Availability Timeline**:

### Step 1: Resource State Tracking
Two simple dictionaries track when each station and employee will next be free:
```python
station_free_at = {"Grill": sim_now, "Fryer": sim_now, "Barista": sim_now, ...}
staff_free_at   = {"Alice": sim_now, "Bob": sim_now, "Charlie": sim_now}
```

### Step 2: Sequential Step Allocation
Orders are processed in arrival sequence (FIFO). For each sequential step in a dish:
1. Find qualified staff for the required station.
2. Select the qualified staff member who becomes free earliest:
   ```python
   chosen_staff = min(qualified_staff, key=lambda name: staff_free_at[name])
   ```
3. Calculate the step start time based on all 4 constraints:
   ```python
   step_start = max(step_prev_finish, station_free_at[station], staff_free_at[chosen_staff], sim_now)
   step_finish = step_start + duration
   ```
4. Mark the station and staff as busy until `step_finish`:
   ```python
   station_free_at[station] = step_finish
   staff_free_at[chosen_staff] = step_finish
   step_prev_finish = step_finish
   ```

### Step 3: Buffer Calculation
After all steps for a dish are scheduled, the restaurant safety buffer (e.g. 10%) is applied once to the remaining predicted preparation duration:
```python
remaining_prep = max(0.0, step_finish - sim_now)
dish_ready_at = sim_now + (remaining_prep * (1.0 + buffer_pct))
```

### Step 4: Full Order ETA
The order completion time is the maximum of all its dish ready times:
```python
order_ready_at = max(dish_ready_times)
```

---

## 5. Why Coffee No Longer Waits 40 Minutes

### The Problem
Previously, Cold Coffee shared Step 2 ("Pouring") with the food `Plating` station, which was operated by chefs grilling and assembling burgers. When a customer ordered burgers, subsequent coffee orders were queued behind all burger prep.

### The Solution
Cold Coffee was restructured to be **100% self-contained at the `Barista` counter**:
1. Step 1: Espresso & Blending (3m) at `Barista`
2. Step 2: Pouring & Serving (1m) at `Barista`
3. Chef Bob is dedicated to `Barista`.

Because the Barista counter and Bob operate completely independently of the Grill and Fryer stations, **Cold Coffee always takes ~4.4 minutes (240s base + 10% buffer = 264s)** even if 5 burgers are queued on the grill!

---

## 6. How to Run the Application

### Prerequisites
- Python 3.9+ installed.

### 1. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 2. Run the Web Server
```powershell
python main.py
```
*(Or via uvicorn directly: `uvicorn main:app --reload`)*

The server will start at:
- **Customer UI**: [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

### 3. Run Automated Tests
```powershell
python -m pytest test_app.py -v
```

All 10 tests will run and pass:
```text
test_app.py::test_database_initialization_and_seed PASSED
test_app.py::test_coffee_standalone_eta PASSED
test_app.py::test_burger_standalone_eta PASSED
test_app.py::test_parallel_stations_coffee_not_blocked_by_burger PASSED
test_app.py::test_station_and_staff_contention_multiple_burgers PASSED
test_app.py::test_cancellation_frees_capacity_and_recalculates PASSED
test_app.py::test_multi_restaurant_isolation PASSED
test_app.py::test_eta_history_audit_trail PASSED
test_app.py::test_api_endpoints_flow PASSED
test_app.py::test_place_order_validation_errors PASSED
```

---

## 7. REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Serves the customer countdown timer HTML page |
| `GET` | `/api/restaurants` | List all configured restaurants (Part 2) |
| `GET` | `/api/menu?restaurant_id={id}` | Get dishes, stations, and staff for a restaurant |
| `POST` | `/api/orders` | Place a customer order and receive initial countdown |
| `GET` | `/api/orders/{order_id}` | Poll remaining countdown seconds and dish statuses |
| `POST` | `/api/orders/{order_id}/cancel` | Cancel an order and recalculate kitchen schedules |
| `GET` | `/api/history?restaurant_id={id}` | Inspect immutable ETA calculation audit records |

---
