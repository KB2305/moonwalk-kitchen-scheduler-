// MoonWalk Customer Countdown Frontend Logic
let currentOrderId = null;
let currentOrderData = null;
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
const dispOrderId = document.getElementById("dispOrderId");
const dispCustomer = document.getElementById("dispCustomer");
const dispStatus = document.getElementById("dispStatus");
const dispBigClock = document.getElementById("dispBigClock");
const dispReadyTime = document.getElementById("dispReadyTime");
const dishList = document.getElementById("dishList");
const btnCancel = document.getElementById("btnCancel");
const btnRefresh = document.getElementById("btnRefresh");
const btnReloadHistory = document.getElementById("btnReloadHistory");
const historyTable = document.getElementById("historyTable");

// Initialize on page load
window.addEventListener("DOMContentLoaded", () => {
  loadMenu(selectedRestaurant);
  loadHistory(selectedRestaurant);

  restaurantSelect.addEventListener("change", (e) => {
    selectedRestaurant = e.target.value;
    loadMenu(selectedRestaurant);
    loadHistory(selectedRestaurant);
  });

  orderForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await placeOrder();
  });

  btnCancel.addEventListener("click", async () => {
    if (!currentOrderId) return;
    if (confirm("Cancel this order? Kitchen capacity will be released immediately.")) {
      await cancelOrder();
    }
  });

  btnRefresh.addEventListener("click", () => {
    if (currentOrderId) fetchOrderStatus(currentOrderId);
  });

  btnReloadHistory.addEventListener("click", () => {
    loadHistory(selectedRestaurant);
  });
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

// 1. Load menu from backend
async function loadMenu(restaurantId) {
  try {
    const res = await fetch(`/api/menu?restaurant_id=${restaurantId}`);
    const data = await res.json();

    // Render menu items
    menuList.innerHTML = "";
    data.dishes.forEach(dish => {
      const item = document.createElement("div");
      item.className = "menu-item";
      item.innerHTML = `
        <div>
          <div class="dish-name">${getDishIcon(dish.name)} ${dish.name} (₹${dish.price})</div>
          <div class="dish-cat">${dish.category}</div>
        </div>
        <input type="number" min="0" max="10" value="0" data-id="${dish.id}" class="qty-input">
      `;
      menuList.appendChild(item);
    });

    // Default first dish to 1 portion
    const firstInput = menuList.querySelector(".qty-input");
    if (firstInput) firstInput.value = "1";

    // Render kitchen stations & staff
    kitchenStations.innerHTML = "";
    data.stations.forEach(st => {
      const tag = document.createElement("div");
      tag.className = "tag";
      tag.innerHTML = `Station: <strong>${st}</strong>`;
      kitchenStations.appendChild(tag);
    });
    data.staff.forEach(s => {
      const tag = document.createElement("div");
      tag.className = "tag";
      tag.innerHTML = `Chef: <strong>${s.name}</strong> (${s.skills})`;
      kitchenStations.appendChild(tag);
    });
  } catch (err) {
    console.error("Failed to load menu:", err);
  }
}

// 2. Submit order to backend
async function placeOrder() {
  const name = customerName.value.trim() || "Guest";
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

    if (!res.ok) throw new Error("Order failed");
    const data = await res.json();
    displayOrder(data);
    loadHistory(selectedRestaurant);
  } catch (err) {
    alert("Error: " + err.message);
  }
}

// 3. Cancel order
async function cancelOrder() {
  try {
    const res = await fetch(`/api/orders/${currentOrderId}/cancel`, { method: "POST" });
    const data = await res.json();
    displayOrder(data);
    loadHistory(selectedRestaurant);
  } catch (err) {
    alert("Cancel failed: " + err.message);
  }
}

// 4. Poll order status
async function fetchOrderStatus(orderId) {
  try {
    const res = await fetch(`/api/orders/${orderId}`);
    if (res.ok) {
      const data = await res.json();
      displayOrder(data);
    }
  } catch (err) {
    console.warn("Polling error:", err);
  }
}

// 5. Display order & start countdown
function displayOrder(order) {
  currentOrderId = order.order_id;
  currentOrderData = order;

  emptyState.style.display = "none";
  orderDisplay.style.display = "block";

  dispOrderId.textContent = order.order_id;
  dispCustomer.textContent = order.customer_name;
  dispStatus.textContent = order.status;

  if (order.status === "CANCELLED") {
    dispStatus.style.background = "#7f1d1d";
    dispStatus.style.color = "#fecaca";
    btnCancel.disabled = true;
    btnCancel.style.opacity = "0.5";
  } else {
    dispStatus.style.background = "#854d0e";
    dispStatus.style.color = "#fef08a";
    btnCancel.disabled = false;
    btnCancel.style.opacity = "1";
  }

  // Render dish cards
  dishList.innerHTML = "";
  order.dishes.forEach(dish => {
    const card = document.createElement("div");
    card.className = "dish-card";
    card.innerHTML = `
      <div>
        <div class="dish-name">${getDishIcon(dish.name)} ${dish.name}</div>
        <div class="dish-cat">Status: ${dish.status}</div>
      </div>
      <div class="dish-clock" id="clock-dish-${dish.order_item_id}">--:--</div>
    `;
    dishList.appendChild(card);
  });

  // Start local 1-second countdown
  startTimer();

  // Start 5-second polling
  startPolling(order.order_id);
}

function startTimer() {
  if (timerInterval) clearInterval(timerInterval);

  function update() {
    if (!currentOrderData) return;
    const now = Date.now() / 1000;

    // Overall clock
    if (currentOrderData.status === "CANCELLED") {
      dispBigClock.textContent = "CANCELLED";
      dispBigClock.style.color = "#ef4444";
      dispReadyTime.textContent = "Order was cancelled";
    } else if (currentOrderData.order_ready_at) {
      const rem = Math.max(0, Math.floor(currentOrderData.order_ready_at - now));
      dispBigClock.textContent = formatTime(rem);
      dispReadyTime.textContent = rem === 0 ? "Ready to serve!" : "Freshly preparing in kitchen...";
      if (rem === 0) dispBigClock.style.color = "#10b981";
    }

    // Dish clocks
    currentOrderData.dishes.forEach(dish => {
      const el = document.getElementById(`clock-dish-${dish.order_item_id}`);
      if (!el) return;
      if (dish.status === "CANCELLED" || currentOrderData.status === "CANCELLED") {
        el.textContent = "CANCELLED";
        el.style.color = "#ef4444";
      } else if (dish.ready_at) {
        const dRem = Math.max(0, Math.floor(dish.ready_at - now));
        el.textContent = formatTime(dRem);
        if (dRem === 0) el.style.color = "#10b981";
      }
    });
  }

  update();
  timerInterval = setInterval(update, 1000);
}

function startPolling(orderId) {
  if (pollingInterval) clearInterval(pollingInterval);
  pollingInterval = setInterval(() => {
    if (!currentOrderData || currentOrderData.status === "CANCELLED") {
      clearInterval(pollingInterval);
      return;
    }
    fetchOrderStatus(orderId);
  }, 5000);
}

// 6. Load audit history
async function loadHistory(restaurantId) {
  try {
    const res = await fetch(`/api/history?restaurant_id=${restaurantId}`);
    const rows = await res.json();
    historyTable.innerHTML = "";

    if (rows.length === 0) {
      historyTable.innerHTML = `<tr><td colspan="6" class="center">No history yet.</td></tr>`;
      return;
    }

    rows.forEach(r => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>#${r.id}</td>
        <td><strong>${r.trigger_reason}</strong></td>
        <td>${r.order_id}</td>
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

