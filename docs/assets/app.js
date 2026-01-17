async function fetchJson(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return await res.json();
}

function norm(s) {
  return (s || "").toString().toLowerCase();
}

function eventMatches(ev, query, onlyAllDay) {
  const q = norm(query).trim();
  if (onlyAllDay && !ev.allDay) return false;
  if (!q) return true;

  const p = ev.extendedProps || {};
  const hay = [
    ev.title,
    p.location,
    p.notes,
    p.dateinfo,
    p.time,
    p.dow,
  ].map(norm).join(" | ");

  return hay.includes(q);
}

function parseStart(ev) {
  const s = ev.start;
  if (!s) return null;
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

function renderMeta(meta, rangeInfo) {
  const el = document.getElementById("meta");
  const d = new Date(meta.updated_at);

  const rangeHtml = rangeInfo
    ? `<div><b>Event-Range:</b> ${rangeInfo.min} → ${rangeInfo.max}</div>`
    : "";

  el.innerHTML = `
    <div><b>Letztes Update:</b> ${d.toLocaleString("de-CH")}</div>
    <div><b>Parsed rows:</b> ${meta.rows_parsed}</div>
    <div><b>Events:</b> ${meta.events_generated}</div>
    <div><b>Phase-Projektion:</b> ${meta.phase_lookahead_days} Tage</div>
    ${rangeHtml}
  `;
}

(async function main() {
  const [events, meta] = await Promise.all([
    fetchJson("data/events.json"),
    fetchJson("data/meta.json")
  ]);

  // Force visible event colors (helps in dark themes / custom CSS)
  for (const ev of events) {
    ev.backgroundColor = "rgba(255,255,255,0.22)";
    ev.borderColor = "rgba(255,255,255,0.45)";
    ev.textColor = "#ffffff";
  }

  // Compute min/max date for sanity + auto-jump
  const starts = events.map(parseStart).filter(Boolean).sort((a, b) => a - b);
  const minD = starts.length ? starts[0] : null;
  const maxD = starts.length ? starts[starts.length - 1] : null;
  const rangeInfo = (minD && maxD) ? {
    min: minD.toLocaleString("de-CH"),
    max: maxD.toLocaleString("de-CH"),
  } : null;

  renderMeta(meta, rangeInfo);

  const qInput = document.getElementById("q");
  const onlyAllDay = document.getElementById("onlyAllDay");
  const resetBtn = document.getElementById("reset");
  const calendarEl = document.getElementById("calendar");

  let currentQuery = "";
  let currentOnlyAllDay = false;

  function filteredEvents() {
    return events.filter(ev => eventMatches(ev, currentQuery, currentOnlyAllDay));
  }

  // If "today" is outside event range, jump to first event date
  const today = new Date();
  let initialDate = today;
  if (minD && maxD) {
    if (today < minD || today > maxD) initialDate = minD;
  } else if (minD) {
    initialDate = minD;
  }

  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: "timeGridWeek",
    initialDate: initialDate,
    height: "auto",
    nowIndicator: true,
    firstDay: 1, // Monday
    headerToolbar: {
      left: "prev,next today",
      center: "title",
      right: "timeGridDay,timeGridWeek,dayGridMonth"
    },
    eventTimeFormat: { hour: "2-digit", minute: "2-digit", hour12: false },

    // IMPORTANT: pass an ARRAY, not a function object
    events: filteredEvents(),

    eventClick: function (info) {
      const url = info.event.url;
      if (url) {
        info.jsEvent.preventDefault();
        window.open(url, "_blank", "noopener");
      }
    },

    eventDidMount: function (arg) {
      const p = arg.event.extendedProps || {};
      const parts = [];
      if (p.location) parts.push(`Ort: ${p.location}`);
      if (p.notes) parts.push(`Hinweis: ${p.notes}`);
      if (p.dateinfo) parts.push(`Datum/Phase: ${p.dateinfo}`);
      if (p.time) parts.push(`Zeit: ${p.time}`);
      if (parts.length) arg.el.title = parts.join("\n");
    }
  });

  calendar.render();

  function refresh() {
    calendar.removeAllEvents();
    calendar.addEventSource(filteredEvents());
  }

  qInput.addEventListener("input", (e) => {
    currentQuery = e.target.value;
    refresh();
  });

  onlyAllDay.addEventListener("change", (e) => {
    currentOnlyAllDay = e.target.checked;
    refresh();
  });

  resetBtn.addEventListener("click", () => {
    qInput.value = "";
    onlyAllDay.checked = false;
    currentQuery = "";
    currentOnlyAllDay = false;
    refresh();
  });
})().catch((err) => {
  console.error(err);
  alert("Fehler beim Laden der Daten. Öffne die Konsole (F12) für Details.");
});
