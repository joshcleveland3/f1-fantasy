# 2026 F1 Fantasy Bet dashboard

Self-updating dashboard for the friends' fantasy league. No manual data entry.

- `config/rules.json` – scoring rules (from the sheet's Rules/Points tab)
- `config/rosters.json` – who owns which drivers (set once; `active:false` hides an owner)
- `scripts/build_data.py` – pulls results (Jolpica), sprint qualifying (OpenF1) and license penalty points (RaceFans), scores everything
- `docs/index.html` – the dashboard; reads `docs/data.json`
- `.github/workflows/refresh.yml` – rebuilds and publishes on a schedule (and on demand via *Actions > Run workflow*)

Run locally: `pip install -r requirements.txt && python scripts/build_data.py && python -m http.server -d docs`
Tests: `python -m pytest tests`
