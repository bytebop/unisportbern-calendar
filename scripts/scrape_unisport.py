#!/usr/bin/env python3
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple
import requests
from bs4 import BeautifulSoup
from dateutil.rrule import rrule, WEEKLY
from dateutil.parser import parse as dtparse

SEARCH_URL = "https://www.zssw.unibe.ch/usp/zms/search.php"
DEFAULT_TIMEZONE = "Europe/Zurich"

# Wie weit wir "Phase"-Einträge in die Zukunft projizieren (damit Week-View sinnvoll ist)
PHASE_LOOKAHEAD_DAYS = int(os.environ.get("PHASE_LOOKAHEAD_DAYS", "28"))

UA = "unisport-calendar-bot/1.0 (+https://github.com/yourname/unisport-calendar)"

DOW_MAP = {
    "Mo": 0,
    "Di": 1,
    "Mi": 2,
    "Do": 3,
    "Fr": 4,
    "Sa": 5,
    "So": 6,
}

DATE_SINGLE_RE = re.compile(r"^\s*(\d{2}\.\d{2}\.\d{4})\s*$")
DATE_RANGE_RE = re.compile(r"^\s*(\d{2}\.\d{2})\.\s*-\s*(\d{2}\.\d{2}\.\d{4})\s*$")
PHASE_RE = re.compile(r"^\s*Phase\b", re.IGNORECASE)

TIME_RE = re.compile(r"^\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*Uhr\s*$", re.IGNORECASE)
ALLDAY_RE = re.compile(r"^\s*ganzer\s+Tag\s*$", re.IGNORECASE)

LINE_RE = re.compile(
    r"^(?P<title>.+?),\s*(?P<dow>Mo|Di|Mi|Do|Fr|Sa|So),\s*(?P<time>.+?),\s*(?P<dateinfo>.+?),\s*(?P<location>.+?)(?:,\s*(?P<rest>.*))?$"
)

@dataclass
class RawRow:
    title: str
    href: Optional[str]
    dow: str
    time_str: str
    dateinfo: str
    location: str
    rest: str

def fetch_html(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text

def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def parse_time_range(time_str: str) -> Tuple[Optional[time], Optional[time], bool]:
    t = normalize_space(time_str)
    if ALLDAY_RE.match(t):
        return None, None, True
    m = TIME_RE.match(t)
    if not m:
        return None, None, False
    start_s, end_s = m.group(1), m.group(2)
    sh, sm = map(int, start_s.split(":"))
    eh, em = map(int, end_s.split(":"))
    return time(sh, sm), time(eh, em), False

def parse_dateinfo(dateinfo: str):
    di = normalize_space(dateinfo)

    m1 = DATE_SINGLE_RE.match(di)
    if m1:
        d = datetime.strptime(m1.group(1), "%d.%m.%Y").date()
        return ("single", d, None)

    m2 = DATE_RANGE_RE.match(di)
    if m2:
        start_dm = m2.group(1)          # "18.02"
        end_dmy = m2.group(2)           # "27.05.2026"
        end_d = datetime.strptime(end_dmy, "%d.%m.%Y").date()
        # start has no year, assume same year as end (works for typical semester spans)
        start_d = datetime.strptime(f"{start_dm}.{end_d.year}", "%d.%m.%Y").date()
        return ("range", start_d, end_d)

    if PHASE_RE.match(di):
        return ("phase", None, None)

    # Fallback: treat unknown as phase-like
    return ("phase", None, None)

def extract_rows(html: str) -> List[RawRow]:
    soup = BeautifulSoup(html, "html.parser")

    # Heuristic: rows are anchors whose parent text matches the "Title, Dow, Time, Dateinfo, Location, ..."
    rows: List[RawRow] = []
    for a in soup.find_all("a"):
        title = normalize_space(a.get_text(" ", strip=True))
        if not title:
            continue
        parent = a.parent
        if not parent:
            continue

        line_text = normalize_space(parent.get_text(" ", strip=True))

        # Skip headings/categories (e.g. "Badminton" without commas)
        if line_text.count(",") < 3:
            continue

        m = LINE_RE.match(line_text)
        if not m:
            continue

        href = a.get("href")
        if href and href.startswith("/"):
            href = "https://www.zssw.unibe.ch" + href

        rows.append(
            RawRow(
                title=m.group("title").strip(),
                href=href,
                dow=m.group("dow").strip(),
                time_str=m.group("time").strip(),
                dateinfo=m.group("dateinfo").strip(),
                location=m.group("location").strip(),
                rest=(m.group("rest") or "").strip(),
            )
        )
    # Deduplicate identical lines
    seen = set()
    uniq = []
    for r in rows:
        key = (r.title, r.dow, r.time_str, r.dateinfo, r.location, r.rest, r.href)
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq

def next_date_for_weekday(from_date: date, weekday_idx: int) -> date:
    delta = (weekday_idx - from_date.weekday()) % 7
    return from_date + timedelta(days=delta)

def daterange_weekly(start: date, end: date, weekday_idx: int) -> List[date]:
    # find first occurrence of weekday >= start
    first = next_date_for_weekday(start, weekday_idx)
    if first < start:
        first += timedelta(days=7)

    out = []
    d = first
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out

def build_events(rows: List[RawRow]) -> List[dict]:
    events = []
    today = date.today()

    for r in rows:
        weekday_idx = DOW_MAP.get(r.dow)
        if weekday_idx is None:
            continue

        start_t, end_t, all_day = parse_time_range(r.time_str)
        kind, d1, d2 = parse_dateinfo(r.dateinfo)

        base = {
            "title": r.title,
            "url": r.href,
            "extendedProps": {
                "dow": r.dow,
                "time": r.time_str,
                "dateinfo": r.dateinfo,
                "location": r.location,
                "notes": r.rest,
                "source": SEARCH_URL,
                "tz": DEFAULT_TIMEZONE,
            },
        }

        def add_event(day: date):
            if all_day:
                ev = dict(base)
                ev["start"] = day.isoformat()
                ev["allDay"] = True
                events.append(ev)
                return

            if start_t is None or end_t is None:
                return

            start_dt = datetime.combine(day, start_t)
            end_dt = datetime.combine(day, end_t)
            ev = dict(base)
            ev["start"] = start_dt.isoformat()
            ev["end"] = end_dt.isoformat()
            ev["allDay"] = False
            events.append(ev)

        if kind == "single" and isinstance(d1, date):
            add_event(d1)

        elif kind == "range" and isinstance(d1, date) and isinstance(d2, date):
            for day in daterange_weekly(d1, d2, weekday_idx):
                add_event(day)

        else:
            # phase/unknown: project into next PHASE_LOOKAHEAD_DAYS so week-view is usable
            horizon = today + timedelta(days=PHASE_LOOKAHEAD_DAYS)
            # first occurrence from today
            first = next_date_for_weekday(today, weekday_idx)
            day = first
            while day <= horizon:
                add_event(day)
                day += timedelta(days=7)

    # Stable sorting
    def sort_key(ev):
        return ev.get("start", ""), ev.get("title", "")

    events.sort(key=sort_key)
    return events

def main():
    html = fetch_html(SEARCH_URL)
    rows = extract_rows(html)
    events = build_events(rows)

    out_dir = os.path.join("docs", "data")
    os.makedirs(out_dir, exist_ok=True)

    events_path = os.path.join(out_dir, "events.json")
    meta_path = os.path.join(out_dir, "meta.json")

    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)

    meta = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "rows_parsed": len(rows),
        "events_generated": len(events),
        "source": SEARCH_URL,
        "phase_lookahead_days": PHASE_LOOKAHEAD_DAYS,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"Wrote {events_path} ({len(events)} events)")
    print(f"Wrote {meta_path}")

if __name__ == "__main__":
    main()
