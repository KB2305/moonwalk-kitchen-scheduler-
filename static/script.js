// MoonWalk Kitchen Scheduling & Live Countdown Timers (Customer Table View)
let currentOrderId = null;
let currentOrderData = null;
let currentMenuDishes = [];
let timerInterval = null;
let pollingInterval = null;
let selectedRestaurant = "moonwalk";

// Elements
const restaurantSelect = document.getElementById("restaurantSelect");
const menuList = document.getElementById("menuList");
const kitchenStations = document.getElementById("kitchenStations");
const orderForm = document.getElementById("orderForm");
const customerName = document.getElementById("customerName");
const emptyState = document.getElementById("emptyState");
const orderDisplay = document.getElementById("orderDisplay");
const btnRefresh = document.getElementById("btnRefresh");
const btnReloadHistory = document.getElementById("btnReloadHistory");
const btnResetKitchen = document.getElementById("btnResetKitchen");
const historyTable = document.getElementById("historyTable");

// Initialize on page load
window.addEventListener("DOMContentLoaded", () => {
  loadMenu(selectedRestaurant);
  loadHistory(selectedRestaurant);

  // Restore active order for this specific table session if exists
  const savedOrderId = sessionStorage.getItem("table_order_id");
  if (savedOrderId) {
    currentOrderId = savedOrderId;
    fetchOrderStatus(savedOrderId);
  }

  startGlobalTimer();
  startPolling();

  restaurantSelect.addEventListener("change", (e) => {
    selectedRestaurant = e.target.value;
    loadMenu(selectedRestaurant);
    loadHistory(selectedRestaurant);
  });

  orderForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await placeOrder();
  });

  if (btnRefresh) {
    btnRefresh.addEventListener("click", () => {
      if (currentOrderId) fetchOrderStatus(currentOrderId);
    });
  }

  if (btnReloadHistory) {
    btnReloadHistory.addEventListener("click", () => {
      loadHistory(selectedRestaurant);
    });
  }

  if (btnResetKitchen) {
    btnResetKitchen.addEventListener("click", async () => {
      if (confirm("Clear all active orders and reset kitchen queue?")) {
        try {
          await fetch("/api/reset", { method: "POST" });
          sessionStorage.removeItem("table_order_id");
          currentOrderId = null;
          currentOrderData = null;
          orderDisplay.style.display = "none";
          emptyState.style.display = "block";
          loadHistory(selectedRestaurant);
        } catch (err) {
          console.error("Reset error:", err);
        }
      }
    });
  }
});

// Helper for icons
function getDishIcon(name) {
  const n = (name || "").toLowerCase();
  if (n.includes("coffee") || n.includes("chai")) return "☕";
  if (n.includes("fries")) return "🍟";
  if (n.includes("burger")) return "🍔";
  if (n.includes("pizza")) return "🍕";
  return "🍽️";
}

// Load menu and stations
async function loadMenu(restaurantId) {
  try {
    const res = await fetch(`/api/menu?restaurant_id=${restaurantId}`);
    if (!res.ok) throw new Error("Failed to load menu");
    const data = await res.json();

    currentMenuDishes = data.dishes || [];

    // Render stations and staff
    kitchenStations.innerHTML = "";
    data.stations.forEach(st => {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.innerHTML = `<strong>${st}</strong>`;
      kitchenStations.appendChild(tag);
    });
    data.staff.forEach(st => {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.innerHTML = `Chef: <strong>${st.name}</strong> (${st.skills})`;
      kitchenStations.appendChild(tag);
    });

    // Render menu items
    menuList.innerHTML = "";
    data.dishes.forEach(d => {
      const item = document.createElement("div");
      item.className = "menu-item";
      item.innerHTML = `
        <div class="menu-item-info">
          <span class="menu-item-icon">${getDishIcon(d.name)}</span>
          <div>
            <div class="menu-item-name">${d.name}</div>
            <div class="menu-item-cat">${d.category}</div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <span class="menu-item-price">Rs ${d.price}</span>
          <input type="number" min="0" max="10" value="0" class="qty-input" data-id="${d.id}" data-name="${d.name}">
        </div>
      `;
      menuList.appendChild(item);
    });
  } catch (err) {
    console.error("Menu load error:", err);
  }
}

// Fetch order status for this table
async function fetchOrderStatus(orderId) {
  try {
    const res = await fetch(`/api/orders/${orderId}`);
    if (res.ok) {
      const data = await res.json();
      currentOrderData = data;
      renderCurrentOrder();
    } else {
      sessionStorage.removeItem("table_order_id");
      currentOrderId = null;
      currentOrderData = null;
      orderDisplay.style.display = "none";
      emptyState.style.display = "block";
    }
  } catch (err) {
    console.warn("Polling error:", err);
  }
}

// Render this table's order
function renderCurrentOrder() {
  if (!currentOrderData) {
    emptyState.style.display = "block";
    orderDisplay.style.display = "none";
    return;
  }

  emptyState.style.display = "none";
  orderDisplay.style.display = "block";

  const order = currentOrderData;
  const isCancelled = order.status === "CANCELLED";

  // Menu dropdown for adding extra dishes
  const dishOptions = currentMenuDishes
    .map(d => `<option value="${d.id}">${d.name} (Rs ${d.price})</option>`)
    .join("");

  // Dishes HTML with individual cancel dish buttons
  const dishesHtml = order.dishes
    .map(dish => {
      const dishCancelled = dish.status === "CANCELLED" || isCancelled;
      return `
        <div class="dish-card">
          <div>
            <div class="dish-name" style="${dishCancelled ? 'text-decoration: line-through; opacity: 0.7;' : ''}">
              ${getDishIcon(dish.name)} ${dish.name}
            </div>
            <div class="dish-cat">
              Status: <span class="badge ${dishCancelled ? 'badge-cancelled' : 'badge-prep'}">${dish.status}</span>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 10px;">
            <div class="dish-clock" id="clock-dish-${dish.order_item_id}" style="${dishCancelled ? 'color: #ef4444;' : ''}">
              ${dishCancelled ? 'CANCELLED' : '--:--'}
            </div>
            ${!dishCancelled && !isCancelled ? `
              <button type="button" class="btn btn-small btn-danger" onclick="cancelSingleDish(${dish.order_item_id})" title="Cancel only this dish">
                ✕ Cancel Dish
              </button>
            ` : ''}
          </div>
        </div>
      `;
    })
    .join("");

  orderDisplay.innerHTML = `
    <div class="order-meta">
      <div>
        <span class="label">ORDER ID</span>
        <div class="val">${order.order_id}</div>
      </div>
      <div>
        <span class="label">TABLE / CUSTOMER</span>
        <div class="val">${order.customer_name}</div>
      </div>
      <div>
        <span class="label">STATUS</span>
        <span class="badge ${isCancelled ? 'badge-cancelled' : 'badge-prep'}">${order.status}</span>
      </div>
    </div>

    <div class="main-clock-box">
      <div class="clock-label">Full Order Ready In</div>
      <div class="big-clock" id="dispBigClock" style="${isCancelled ? 'color: #ef4444;' : ''}">
        ${isCancelled ? 'CANCELLED' : '--:--'}
      </div>
      <div class="clock-sub" id="dispReadyTime">
        ${isCancelled ? 'This order was cancelled' : 'Freshly preparing in kitchen...'}
      </div>
    </div>

    <h3 style="margin-bottom: 8px;">Dish Countdown Timers (${order.dishes.length} items)</h3>
    <div class="dish-list">
      ${dishesHtml}
    </div>

    <!-- Inline Add Dish Box -->
    <div class="add-item-box" id="addDishBox" style="display: none; margin-top: 10px; margin-bottom: 12px; padding: 12px; background: #0f172a; border-radius: 8px; border: 1px solid #334155;">
      <label style="display: block; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 6px;">SELECT DISH TO ADD TO THIS ORDER:</label>
      <div style="display: flex; gap: 8px;">
        <select id="selectDishToAdd" style="flex: 1; padding: 8px; background: #1e293b; color: #fff; border: 1px solid #475569; border-radius: 6px;">
          ${dishOptions}
        </select>
        <button type="button" class="btn btn-primary btn-small" onclick="submitAddDish()">Confirm Add</button>
        <button type="button" class="btn btn-secondary btn-small" onclick="toggleAddDishBox()">Close</button>
      </div>
    </div>

    <div class="actions" style="margin-top: 14px;">
      ${!isCancelled ? `
        <button type="button" class="btn btn-danger btn-small" onclick="cancelFullOrder()">
          Cancel Full Order
        </button>
        <button type="button" class="btn btn-secondary btn-small" onclick="toggleAddDishBox()">
          + Add Another Dish
        </button>
      ` : ''}
      <button type="button" class="btn btn-secondary btn-small" onclick="startNewTableOrder()">
        + Place New Order
      </button>
    </div>
  `;

  updateClockTicks();
}

// 1-second countdown loop
function startGlobalTimer() {
  if (timerInterval) clearInterval(timerInterval);
  timerInterval = setInterval(updateClockTicks, 1000);
}

function updateClockTicks() {
  if (!currentOrderData) return;
  const now = Date.now() / 1000;

  const clockEl = document.getElementById("dispBigClock");
  const subEl = document.getElementById("dispReadyTime");

  if (currentOrderData.status === "CANCELLED") {
    if (clockEl) {
      clockEl.textContent = "CANCELLED";
      clockEl.style.color = "#ef4444";
    }
    if (subEl) subEl.textContent = "This order was cancelled";
    return;
  }

  if (clockEl && currentOrderData.order_ready_at) {
    const rem = Math.max(0, Math.floor(currentOrderData.order_ready_at - now));
    clockEl.textContent = formatTime(rem);
    if (subEl) {
      subEl.textContent = rem === 0 ? "Order is ready to serve!" : "Freshly preparing in kitchen...";
    }
    if (rem === 0) clockEl.style.color = "#10b981";
  }

  currentOrderData.dishes.forEach(dish => {
    const dClock = document.getElementById(`clock-dish-${dish.order_item_id}`);
    if (!dClock) return;

    if (dish.status === "CANCELLED" || currentOrderData.status === "CANCELLED") {
      dClock.textContent = "CANCELLED";
      dClock.style.color = "#ef4444";
    } else if (dish.ready_at) {
      const dRem = Math.max(0, Math.floor(dish.ready_at - now));
      dClock.textContent = formatTime(dRem);
      if (dRem === 0) dClock.style.color = "#10b981";
    }
  });
}

// Polling every 3 seconds so if kitchen capacity changes, timer updates automatically
function startPolling() {
  if (pollingInterval) clearInterval(pollingInterval);
  pollingInterval = setInterval(() => {
    if (currentOrderId && currentOrderData && currentOrderData.status !== "CANCELLED") {
      fetchOrderStatus(currentOrderId);
    }
  }, 3000);
}

// Submit a new order for this table
async function placeOrder() {
  const name = customerName.value.trim() || "Table 1";
  const inputs = document.querySelectorAll(".qty-input");
  const items = [];

  inputs.forEach(input => {
    const qty = parseInt(input.value, 10);
    if (qty > 0) {
      items.push({
        dish_id: parseInt(input.getAttribute("data-id"), 10),
        quantity: qty
      });
    }
  });

  if (items.length === 0) {
    alert("Please choose at least 1 dish!");
    return;
  }

  try {
    const res = await fetch("/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        restaurant_id: selectedRestaurant,
        customer_name: name,
        items: items
      })
    });

    if (!res.ok) throw new Error("Order submission failed");
    const data = await res.json();

    currentOrderId = data.order_id;
    currentOrderData = data;
    sessionStorage.setItem("table_order_id", data.order_id);

    // Reset quantity inputs
    inputs.forEach(input => input.value = "0");

    renderCurrentOrder();
    loadHistory(selectedRestaurant);
  } catch (err) {
    alert("Error: " + err.message);
  }
}

// Cancel this table's full order
async function cancelFullOrder() {
  if (!confirm(`Cancel this entire order? Kitchen capacity will be released immediately.`)) return;

  try {
    const res = await fetch(`/api/orders/${currentOrderId}/cancel`, { method: "POST" });
    if (!res.ok) throw new Error("Cancel failed");
    const data = await res.json();
    currentOrderData = data;
    renderCurrentOrder();
    loadHistory(selectedRestaurant);
  } catch (err) {
    alert("Cancel failed: " + err.message);
  }
}

// Cancel a particular dish inside this order
async function cancelSingleDish(itemId) {
  if (!confirm("Cancel this dish? The kitchen will release capacity for this item immediately.")) return;

  try {
    const res = await fetch(`/api/orders/${currentOrderId}/items/${itemId}/cancel`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to cancel dish");
    const data = await res.json();
    currentOrderData = data;
    renderCurrentOrder();
    loadHistory(selectedRestaurant);
  } catch (err) {
    alert("Cancel dish failed: " + err.message);
  }
}

// Toggle inline Add Dish box
function toggleAddDishBox() {
  const box = document.getElementById("addDishBox");
  if (!box) return;
  box.style.display = box.style.display === "none" ? "block" : "none";
}

// Add an extra dish to this table's active order
async function submitAddDish() {
  const select = document.getElementById("selectDishToAdd");
  if (!select) return;

  const dishId = parseInt(select.value, 10);
  try {
    const res = await fetch(`/api/orders/${currentOrderId}/items`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dish_id: dishId, quantity: 1 })
    });

    if (!res.ok) throw new Error("Failed to add dish");
    const data = await res.json();
    currentOrderData = data;
    renderCurrentOrder();
    loadHistory(selectedRestaurant);
  } catch (err) {
    alert("Error adding dish: " + err.message);
  }
}

// Reset session to place order for another table
function startNewTableOrder() {
  sessionStorage.removeItem("table_order_id");
  currentOrderId = null;
  currentOrderData = null;
  orderDisplay.style.display = "none";
  emptyState.style.display = "block";
}

// Load history audit log
async function loadHistory(restaurantId) {
  try {
    const res = await fetch(`/api/history?restaurant_id=${restaurantId}`);
    const rows = await res.json();
    historyTable.innerHTML = "";

    if (rows.length === 0) {
      historyTable.innerHTML = `<tr><td colspan="7" class="center">No history yet.</td></tr>`;
      return;
    }

    rows.forEach(r => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>#${r.id}</td>
        <td><strong>${r.trigger_reason}</strong></td>
        <td>${r.order_id}</td>
        <td><span class="badge ${r.order_status === 'CANCELLED' ? 'badge-cancelled' : 'badge-prep'}">${r.order_status || 'PREPARING'}</span></td>
        <td>${r.algorithm}</td>
        <td>${Math.round(r.estimated_duration_seconds)}s (~${Math.round(r.estimated_duration_seconds / 60)}m)</td>
        <td>${Math.round(r.actual_elapsed_seconds)}s</td>
      `;
      historyTable.appendChild(tr);
    });
  } catch (err) {
    console.error("History fetch error:", err);
  }
}

function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
