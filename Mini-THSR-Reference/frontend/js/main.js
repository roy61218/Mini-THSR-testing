(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const query = new URLSearchParams(window.location.search);
  const page = document.body.dataset.page;
  const userSelect = byId("current-user");
  const reloadUsers = byId("reload-users");
  const userKey = "mini_thsr_reference_user";
  const state = { userId: "", usersReady: false, loadingUsers: false, writing: false };
  let userChanged = () => {};

  function message(id, text, error = false) {
    const element = byId(id);
    element.textContent = text;
    element.classList.toggle("is-error", error);
  }

  function url(path, fields) {
    return path + "?" + new URLSearchParams(fields).toString();
  }

  async function request(path, payload) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), window.MINI_THSR_CONFIG.requestTimeoutMs);
    try {
      const options = { signal: controller.signal, cache: "no-store" };
      if (payload !== undefined) {
        options.method = "POST";
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(payload);
      }
      const response = await fetch(path, options);
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const detail = data && data.error;
        const error = new Error(detail ? detail.code + ": " + detail.message : "HTTP " + response.status);
        error.code = detail && detail.code;
        throw error;
      }
      if (data === null) throw new Error("The API did not return valid JSON.");
      return data;
    } catch (error) {
      if (controller.signal.aborted) {
        throw new Error(payload === undefined ? "The request timed out."
          : "The request timed out. Check Booking Overview before submitting again.");
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function option(value, label) {
    const item = document.createElement("option");
    item.value = value;
    item.textContent = label;
    return item;
  }

  function userControls() {
    userSelect.disabled = !state.usersReady || state.loadingUsers || state.writing;
    reloadUsers.disabled = state.loadingUsers || state.writing;
  }

  function chooseUser() {
    state.userId = userSelect.value;
    try {
      if (state.userId) window.localStorage.setItem(userKey, state.userId);
      else window.localStorage.removeItem(userKey);
    } catch (_) {
      // Private browser settings may restrict storage; the selection still works on this page.
    }
    message("user-message", state.userId ? "Current user: " + userSelect.selectedOptions[0].textContent
      : "Choose a user to book or view tickets.");
    if (!state.loadingUsers) userChanged();
  }

  async function loadUsers() {
    if (state.loadingUsers || state.writing) return;
    let previous = state.userId;
    try {
      previous ||= window.localStorage.getItem(userKey) || "";
    } catch (_) {}
    state.loadingUsers = true;
    userControls();
    message("user-message", "Loading users…");
    try {
      const users = await request("/users");
      userSelect.replaceChildren(option("", "Select a user"),
        ...users.map((user) => option(user.user_id, user.name + " (" + user.user_id + ")")));
      userSelect.value = users.some((user) => user.user_id === previous) ? previous : "";
      state.usersReady = true;
      chooseUser();
    } catch (error) {
      state.usersReady = false;
      userSelect.replaceChildren(option("", "Select a user"));
      state.userId = "";
      message("user-message", "Could not load users. " + error.message, true);
    } finally {
      state.loadingUsers = false;
      userControls();
      userChanged();
    }
  }

  function cell(row, value) {
    const element = row.insertCell();
    element.textContent = value;
    return element;
  }

  function emptyTable(body, columns, text) {
    body.replaceChildren();
    const item = cell(body.insertRow(), text);
    item.colSpan = columns;
    item.className = "empty-cell";
  }

  function actionLink(href, text) {
    const link = document.createElement("a");
    link.href = href;
    link.className = "button button-small";
    link.textContent = text;
    return link;
  }

  async function initializeSearch() {
    const form = byId("search-form");
    const submit = form.querySelector("button[type=submit]");
    const body = byId("schedule-list");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submit.disabled) return;
      const fields = Object.fromEntries([...new FormData(form)].filter(([, value]) => value !== ""));
      submit.disabled = true;
      emptyTable(body, 5, "Searching…");
      message("search-message", "");
      try {
        const schedules = await request(url("/schedules", fields));
        body.replaceChildren();
        for (const train of schedules) {
          const row = body.insertRow();
          [train.train_no, train.departure_time, train.arrival_time, train.remain_seats].forEach((value) => cell(row, value));
          const bookingLink = url("booking.html", {
            train_no: train.train_no,
            date: train.date,
            from_station_id: fields.from_station_id,
            to_station_id: fields.to_station_id,
            departure_time: train.departure_time,
            arrival_time: train.arrival_time,
          });
          cell(row, "").append(actionLink(bookingLink, train.remain_seats ? "Book This Train" : "View Sold-Out Train"));
        }
        if (!schedules.length) emptyTable(body, 5, "No trains found.");
        message("search-message", schedules.length + " train(s) found.");
      } catch (error) {
        emptyTable(body, 5, "Search failed.");
        message("search-message", error.message, true);
      } finally {
        submit.disabled = false;
      }
    });
    message("search-message", "Loading stations…");
    try {
      const stations = await request("/stations");
      for (const id of ["from-station", "to-station"]) {
        byId(id).replaceChildren(option("", "Select a station"),
          ...stations.map((station) => option(station.station_id, station.name + " (" + station.station_id + ")")));
      }
      submit.disabled = false;
      message("search-message", "");
    } catch (error) {
      message("search-message", "Could not load stations. " + error.message, true);
    }
  }

  function initializeBooking() {
    const form = byId("booking-form");
    const submit = form.querySelector("button[type=submit]");
    const preference = byId("preference");
    const countInput = byId("seat-count");
    const refresh = byId("refresh-seats");
    const fields = ["train_no", "date", "from_station_id", "to_station_id"];
    const trip = Object.fromEntries(fields.map((name) => [name, query.get(name) || ""]));
    const hasTrip = fields.every((name) => trip[name]);
    for (const item of document.querySelectorAll("[data-trip]")) {
      item.textContent = query.get(item.dataset.trip) || "No data available";
    }
    if (hasTrip) message("trip-message", "Seats are assigned by the booking API.");
    else message("availability-message", "Select a train from Train Search.");

    function update() {
      submit.disabled = !hasTrip || !state.userId || state.loadingUsers || state.writing;
      preference.disabled = Number(countInput.value) !== 1 || state.writing;
      countInput.disabled = state.writing;
    }
    userChanged = update;
    countInput.addEventListener("input", () => {
      if (Number(countInput.value) !== 1) preference.value = "";
      update();
    });
    update();

    async function loadSeats() {
      if (!hasTrip) return;
      refresh.disabled = true;
      byId("available-seat-list").textContent = "";
      message("availability-message", "Loading seat availability…");
      try {
        const data = await request(url("/seats", trip));
        message("availability-message", data.available_seat_count + " available seat(s) for this trip.");
        byId("available-seat-list").textContent = data.seats.map((seat) => seat.seat_id).join(", ");
      } catch (error) {
        message("availability-message", error.message, true);
      } finally {
        refresh.disabled = false;
      }
    }
    refresh.addEventListener("click", loadSeats);
    loadSeats();
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (submit.disabled || state.loadingUsers || state.writing) return;
      const count = Number(countInput.value);
      const payload = {
        ...trip, user_id: state.userId, seat_count: count,
        preference: count === 1 ? preference.value.trim() || null : null,
      };
      state.writing = true;
      userControls();
      update();
      message("booking-message", "Submitting booking…");
      try {
        const created = await request("/bookings", payload);
        window.location.assign(url("booking-detail.html", { booking_id: created.booking_id }));
      } catch (error) {
        message("booking-message", error.message, true);
        if (error.code) loadSeats();
      } finally {
        state.writing = false;
        userControls();
        update();
      }
    });
  }

  function statusLabel(value) {
    return value === "cancelled" ? "Cancelled" : "Confirmed";
  }

  function initializeBookings() {
    const body = byId("booking-list");
    const form = byId("bookings-form");
    const submit = form.querySelector("button[type=submit]");
    let revision = 0;
    async function load() {
      const current = ++revision;
      submit.disabled = !state.userId || state.loadingUsers;
      if (!state.userId) {
        emptyTable(body, 7, "Choose a user to see bookings.");
        message("bookings-message", "");
        return;
      }
      const fields = { user_id: state.userId };
      const bookingId = byId("booking-id").value.trim();
      if (bookingId) fields.booking_id = bookingId;
      emptyTable(body, 7, "Loading bookings…");
      message("bookings-message", "");
      try {
        const bookings = await request(url("/bookings", fields));
        if (current !== revision) return;
        body.replaceChildren();
        for (const booking of bookings) {
          const row = body.insertRow();
          [booking.booking_id, booking.train_no, booking.date, booking.from_station_id,
            booking.to_station_id, statusLabel(booking.status)].forEach((value) => cell(row, value));
          cell(row, "").append(actionLink(url("booking-detail.html", { booking_id: booking.booking_id }), "View Details"));
        }
        if (!bookings.length) emptyTable(body, 7, "No matching bookings.");
        message("bookings-message", bookings.length + " booking(s) found.");
      } catch (error) {
        if (current !== revision) return;
        emptyTable(body, 7, "Could not load bookings.");
        message("bookings-message", error.message, true);
      }
    }
    userChanged = load;
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!submit.disabled) load();
    });
    load();
  }

  function initializeDetail() {
    const bookingId = query.get("booking_id");
    const cancel = byId("cancel-booking");
    let currentBooking = null;
    let revision = 0;
    function render(booking) {
      currentBooking = booking;
      for (const item of document.querySelectorAll("[data-booking]")) {
        const key = item.dataset.booking;
        const value = booking && booking[key];
        if (!booking) item.textContent = "No data available";
        else if (key === "seats") item.textContent = value.map((seat) => seat.seat_id).join(", ");
        else if (key === "status") item.textContent = statusLabel(value);
        else if (key === "preference" && value === null) item.textContent = "None";
        else if (value === null) item.textContent = "Not applicable";
        else if (typeof value === "boolean") item.textContent = value ? "Yes" : "No";
        else item.textContent = value;
      }
      cancel.disabled = state.writing || !booking || booking.status !== "confirmed";
    }
    async function load() {
      const current = ++revision;
      render(null);
      if (!bookingId || !state.userId) {
        message("detail-message", !bookingId ? "Open a booking from Booking Overview."
          : "Choose the user who owns this booking.");
        return;
      }
      message("detail-message", "Loading booking…");
      try {
        const result = await request(url("/bookings", { user_id: state.userId, booking_id: bookingId }));
        if (current !== revision) return;
        render(result[0] || null);
        message("detail-message", currentBooking ? "" : "No matching booking for this user.");
      } catch (error) {
        if (current === revision) message("detail-message", error.message, true);
      }
    }
    userChanged = load;
    cancel.addEventListener("click", async () => {
      if (cancel.disabled || !currentBooking) return;
      state.writing = true;
      userControls();
      cancel.disabled = true;
      message("detail-message", "Cancelling booking…");
      try {
        render(await request("/bookings/" + encodeURIComponent(bookingId) + "/cancel", { user_id: state.userId }));
        message("detail-message", "Booking cancelled. Its seats are available again.");
      } catch (error) {
        if (error.code === "ALREADY_CANCELLED") await load();
        message("detail-message", error.message, true);
      } finally {
        state.writing = false;
        userControls();
        cancel.disabled = !currentBooking || currentBooking.status !== "confirmed";
      }
    });
    load();
  }

  if (page === "search") initializeSearch();
  if (page === "booking") initializeBooking();
  if (page === "bookings") initializeBookings();
  if (page === "detail") initializeDetail();
  userSelect.addEventListener("change", chooseUser);
  reloadUsers.addEventListener("click", loadUsers);
  loadUsers();
})();
