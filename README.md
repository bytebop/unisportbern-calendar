# UniSport Bern Kalender (GitHub Pages)

Statischer Kalender (FullCalendar) + tägliches Update via GitHub Actions.

## Setup
1. Repo klonen
2. Lokal testen:
   ```bash
   pip install -r requirements.txt
   python scripts/scrape_unisport.py
   python -m http.server -d docs 8000
