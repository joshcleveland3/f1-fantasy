#!/usr/bin/env python3
"""Fetch 2026 F1 data, apply the league's scoring rules, write docs/data.json.

Sources
  * Jolpica (Ergast successor): calendar, race, qualifying, sprint results, driver standings
  * OpenF1: Sprint Qualifying results (needed for the 1.5 pt sprint pole; Jolpica lacks it)
  * RaceFans: FIA super-licence penalty-point tables (2026-dated awards only)
"""
import datetime as dt
import json
import pathlib
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from scoring import norm, classified_pos, weekend_points  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RULES = json.load(open(ROOT / "config" / "rules.json"))
ROSTERS = json.load(open(ROOT / "config" / "rosters.json"))
TIERS = json.load(open(ROOT / "config" / "tiers.json"))
TIER_OF = {**TIERS["keys"], **TIERS.get("extra", {})}
OUT = ROOT / "docs" / "data.json"
SEASON = RULES["season"]

JOLPICA = "https://api.jolpi.ca/ergast/f1"
OPENF1 = "https://api.openf1.org/v1"
PENALTY_URL = "https://www.racefans.net/f1-information/formula-1-drivers-current-penalty-points/"

S = requests.Session()
S.headers["User-Agent"] = "f1-fantasy-dashboard/1.0 (friends league; GitHub Actions)"
warnings = []


def get_json(url, params=None, tries=4):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(3 * (i + 1))
                continue
            r.raise_for_status()
            time.sleep(0.35)  # be polite to free APIs
            return r.json()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def jolpica(path):
    return get_json(f"{JOLPICA}/{path}", {"limit": 100})["MRData"]


def races_of(md):
    return md["RaceTable"]["Races"]


# ---------------------------------------------------------------- calendar
calendar = races_of(jolpica(f"{SEASON}.json"))
today = dt.date.today()

# OpenF1 sprint-qualifying sessions (date -> session_key)
sprint_q_sessions = []
try:
    sprint_q_sessions = get_json(f"{OPENF1}/sessions", {"year": SEASON, "session_name": "Sprint Qualifying"})
except Exception as e:  # noqa: BLE001
    warnings.append(f"OpenF1 sprint-qualifying sessions unavailable: {e}")


def sprint_quali_winner(race_date: dt.date):
    """Return driver key of Sprint Qualifying P1 for the weekend ending on race_date."""
    for s in sprint_q_sessions:
        d = dt.date.fromisoformat(s["date_start"][:10])
        if 0 < (race_date - d).days <= 4:
            key = s["session_key"]
            res = get_json(f"{OPENF1}/session_result", {"session_key": key, "position": 1})
            if not res:
                return None
            num = res[0]["driver_number"]
            drivers = get_json(f"{OPENF1}/drivers", {"session_key": key, "driver_number": num})
            if drivers:
                return norm(drivers[0].get("last_name", ""))
            return ("num", num)
    return None


# ---------------------------------------------------------------- per round
races_out = []
driver_info = {}   # key -> {name, team, number}
points = {}        # key -> {round -> breakdown}
seen_in_race = {}  # round -> set(keys) (to detect replaced / absent drivers)

for race in calendar:
    rnd = int(race["round"])
    rdate = dt.date.fromisoformat(race["date"])
    is_sprint = "Sprint" in race
    entry = {
        "round": rnd,
        "name": race["raceName"].replace(" Grand Prix", " GP"),
        "country": race["Circuit"]["Location"]["country"],
        "date": race["date"],
        "sprint": is_sprint,
        "status": "upcoming",
    }
    if rdate > today + dt.timedelta(days=3):
        races_out.append(entry)
        continue

    race_res = quali_res = sprint_res = []
    try:
        r = races_of(jolpica(f"{SEASON}/{rnd}/results.json"))
        race_res = r[0]["Results"] if r else []
        q = races_of(jolpica(f"{SEASON}/{rnd}/qualifying.json"))
        quali_res = q[0]["QualifyingResults"] if q else []
        if is_sprint:
            sp = races_of(jolpica(f"{SEASON}/{rnd}/sprint.json"))
            sprint_res = sp[0]["SprintResults"] if sp else []
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Round {rnd} ({race['raceName']}): Jolpica fetch failed: {e}")

    sq_winner = None
    if is_sprint and (sprint_res or rdate <= today + dt.timedelta(days=3)):
        try:
            sq_winner = sprint_quali_winner(rdate)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Round {rnd}: sprint qualifying lookup failed: {e}")
        if is_sprint and sprint_res and sq_winner is None:
            warnings.append(f"Round {rnd} ({race['raceName']}): sprint pole not found; sprint pole points missing.")

    per = {}  # key -> dict of positions
    def slot(d):
        key = norm(d["Driver"]["familyName"])
        driver_info.setdefault(key, {})
        driver_info[key].update({
            "name": f'{d["Driver"]["givenName"]} {d["Driver"]["familyName"]}',
            "team": d["Constructor"]["name"],
            "number": d["Driver"].get("permanentNumber"),
        })
        return per.setdefault(key, {})

    for d in race_res:
        slot(d)["race_pos"] = classified_pos(d)
        slot(d)["race_status"] = d.get("status")
    for d in quali_res:
        slot(d)["quali_pos"] = int(d["position"])
    for d in sprint_res:
        slot(d)["sprint_pos"] = classified_pos(d)
    if isinstance(sq_winner, tuple):  # only a car number came back
        for k, v in driver_info.items():
            if str(v.get("number")) == str(sq_winner[1]):
                sq_winner = k
                break
        else:
            sq_winner = None
    if sq_winner:
        per.setdefault(sq_winner, {})["sprint_quali_pos"] = 1

    if not (race_res or quali_res or sprint_res or sq_winner):
        races_out.append(entry)
        continue

    entry["status"] = "done" if race_res else "live"
    entry["sprint_pole"] = sq_winner if isinstance(sq_winner, str) else None
    entry["pole"] = next((k for k, v in per.items() if v.get("quali_pos") == 1), None)
    races_out.append(entry)
    seen_in_race[rnd] = set(k for k, v in per.items() if "race_pos" in v or "race_status" in v)

    for key, v in per.items():
        b = weekend_points(RULES, v.get("race_pos"), v.get("quali_pos"), v.get("sprint_pos"), v.get("sprint_quali_pos"))
        b.update({k: v.get(k) for k in ("race_pos", "quali_pos", "sprint_pos", "sprint_quali_pos", "race_status")})
        points.setdefault(key, {})[rnd] = b

# ---------------------------------------------------------------- champion
season_complete = bool(races_out) and all(r["status"] == "done" for r in races_out)
champion_key = None
try:
    st = jolpica(f"{SEASON}/driverstandings.json")["StandingsTable"]["StandingsLists"]
    if st:
        champion_key = norm(st[0]["DriverStandings"][0]["Driver"]["familyName"])
except Exception as e:  # noqa: BLE001
    warnings.append(f"Driver standings unavailable: {e}")

# ---------------------------------------------------------------- penalties
# Primary source: RacingNews365 (updated after every race weekend, lists expiry dates so the issue date
# is expiry minus one year). Cross-check / fallback: RaceFans. If both fail, the previous run's data is kept.
RN_URL = "https://racingnews365.com/2026-f1-driver-penalty-points-total"
RN_NAME, RF_NAME = "RacingNews365", "RaceFans"
NUM_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                       "august", "september", "october", "november", "december"], 1)}


def parse_loose_date(s):
    """'25 August 2026' or 'August 25, 2026' -> date, else None."""
    if not s:
        return None
    for fmt in ("%d %B %Y", "%B %d %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def fetch_racefans():
    soup = BeautifulSoup(S.get(PENALTY_URL, timeout=30).text, "html.parser")
    if soup.find("h4") is None:
        raise ValueError("RaceFans page layout changed (no driver headings found)")
    m = re.search(r"prior to (\d{1,2} [A-Za-z]+ \d{4}|[A-Za-z]+ \d{1,2},? \d{4})", soup.get_text(" "))
    rows, current = [], None
    for el in soup.find_all(["h4", "table"]):
        if el.name == "h4":
            current = el.get_text(" ", strip=True)
            continue
        if not current:
            continue
        for tr in el.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) < 3:
                continue
            dm = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", tds[0])
            if not dm or int(dm.group(3)) != SEASON:
                continue
            try:
                pts = int(re.sub(r"\D", "", tds[-1]))
            except ValueError:
                continue
            rows.append({"driver_raw": current, "date": f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}",
                         "event": tds[1], "session": tds[2] if len(tds) > 3 else "",
                         "description": tds[3] if len(tds) > 4 else "", "points": pts})
    return rows, (m.group(1) if m else None)


def fetch_rn365():
    """Driver headings ('Carlos Sainz - two points') each followed by bullets
    ('Two points - expires September 25th, 2027. <reason>'). Only points expiring in SEASON+1 were issued this season."""
    soup = BeautifulSoup(S.get(RN_URL, timeout=30).text, "html.parser")
    rows, seen = [], 0
    for h in soup.find_all(["h2", "h3"]):
        ht = h.get_text(" ", strip=True)
        if not re.search(r"\bpoints?\b", ht, re.I) or not re.search(r"\s[-\u2013\u2014]\s", ht):
            continue
        name = re.split(r"\s[-\u2013\u2014]\s", ht)[0].strip()
        seen += 1
        for el in h.find_all_next(["h2", "h3", "li"]):
            if el.name in ("h2", "h3"):
                break
            txt = el.get_text(" ", strip=True)
            m = re.match(r"(\w+) points?\b\W*expires?\s+([A-Za-z]+)\s+(\d{1,2})\w*,?\s+(\d{4})\W*(.*)", txt, re.I)
            if not m or m.group(1).lower() not in NUM_WORDS or m.group(2).lower() not in MONTHS:
                continue
            yr = int(m.group(4))
            if yr != SEASON + 1:
                continue                      # issued last season, does not count for this bet
            mo, day = MONTHS[m.group(2).lower()], int(m.group(3))
            try:
                issued = dt.date(yr - 1, mo, day)
            except ValueError:                # 29 Feb
                issued = dt.date(yr - 1, mo, day - 1)
            rows.append({"driver_raw": name, "date": issued.isoformat(), "event": m.group(5).strip() or "Penalty points",
                         "session": "", "description": "", "points": NUM_WORDS[m.group(1).lower()]})
    if seen == 0:
        raise ValueError("RacingNews365 page layout changed (no driver headings found)")
    return rows


rf_rows = rn_rows = None
penalty_asof = None                # RaceFans' own "current as of" date (used to detect a lagging RaceFans)
try:
    rf_rows, penalty_asof = fetch_racefans()
except Exception as e:  # noqa: BLE001
    warnings.append(f"{RF_NAME} penalty source unavailable: {e}")
try:
    rn_rows = fetch_rn365()
except Exception as e:  # noqa: BLE001
    warnings.append(f"{RN_NAME} penalty source unavailable: {e}")

penalties, penalty_source = [], None
if rn_rows is not None:
    penalties, penalty_source = rn_rows, RN_NAME
elif rf_rows is not None:
    penalties, penalty_source = rf_rows, RF_NAME
    warnings.append(f"Using {RF_NAME} for penalty points because {RN_NAME} could not be read.")
elif OUT.exists():
    try:
        prev = json.load(open(OUT))
        penalties = prev.get("penalties", [])
        penalty_source = prev.get("penalty_source")
        for p in penalties:
            p["stale"] = True
        warnings.append("No penalty source could be read; showing penalty points from the last successful update.")
    except Exception:  # noqa: BLE001
        pass

known = list(driver_info) + [d["key"] for f in ROSTERS["ftos"] for d in f["drivers"]]


def key_of(raw):
    hit = [k for k in known if k in norm(raw)]
    return hit[0] if hit else norm(raw)


def totals(rows):
    t = {}
    for r in rows:
        k = key_of(r["driver_raw"])
        t[k] = t.get(k, 0) + r["points"]
    return t


for p in penalties:
    p["driver"] = p.get("driver") or key_of(p["driver_raw"])
pen_by_driver = {}
for p in penalties:
    pen_by_driver[p["driver"]] = pen_by_driver.get(p["driver"], 0) + p["points"]

# ---------------------------------------------------------------- penalty cross-check
owner_of_pre = {d["key"]: f["name"] for f in ROSTERS["ftos"] if f["active"] for d in f["drivers"]}
asof_date = parse_loose_date(penalty_asof)
races_after = [r["name"] for r in races_out
               if r["status"] == "done" and asof_date and dt.date.fromisoformat(r["date"]) > asof_date]
rf_lagging = bool(races_after)
penalty_check = {"status": "unavailable", "primary": penalty_source, "differences": [], "lagging": [],
                 "stale_races": races_after if penalty_source == RF_NAME else []}
if rn_rows is not None and rf_rows is not None:
    t_rn, t_rf = totals(rn_rows), totals(rf_rows)
    for k in sorted(set(t_rn) | set(t_rf)):
        a, b = t_rn.get(k, 0), t_rf.get(k, 0)
        if a == b:
            continue
        nm = driver_info.get(k, {}).get("name", k.title())
        if a > b and rf_lagging:
            penalty_check["lagging"].append(nm)       # RaceFans hasn't caught up yet; expected, not a warning
            continue
        penalty_check["differences"].append({"driver": nm, "owner": owner_of_pre.get(k, "Unowned"),
                                             "used": a, "other_source": b})
    penalty_check["status"] = "mismatch" if penalty_check["differences"] else "ok"
    penalty_check["other"] = RF_NAME
if penalty_check["stale_races"]:
    warnings.append(f"{RF_NAME} says it is current {penalty_asof}, but {len(penalty_check['stale_races'])} race(s) finished since "
                    f"({', '.join(penalty_check['stale_races'])}). Recent penalty points may be missing.")
for dfr in penalty_check["differences"]:
    warnings.append(f"Penalty points differ for {dfr['driver']} ({dfr['owner']}): dashboard uses {dfr['used']} ({RN_NAME}), "
                    f"{RF_NAME} shows {dfr['other_source']}. Verify against the FIA documents.")

# ---------------------------------------------------------------- owners
owner_of = {}
for f in ROSTERS["ftos"]:
    if f["active"]:
        for d in f["drivers"]:
            owner_of[d["key"]] = f["name"]

rounds_done = [r["round"] for r in races_out if r["status"] in ("done", "live")]
status_by_round = {r["round"]: r["status"] for r in races_out}
ftos_out = []
for f in ROSTERS["ftos"]:
    if not f["active"]:
        continue
    by_round = {r: 0.0 for r in rounds_done}
    drivers = []
    for d in f["drivers"]:
        k = d["key"]
        tot = 0.0
        for r in rounds_done:
            p = points.get(k, {}).get(r)
            if p:
                by_round[r] += p["total"]
                tot += p["total"]
        info = driver_info.get(k, {"name": k.title(), "team": "?"})
        drivers.append({"key": k, "name": info["name"], "team": info["team"], "tier": d["tier"],
                        "points": round(tot, 2), "penalty_points": pen_by_driver.get(k, 0)})
        for r in rounds_done:
            if status_by_round.get(r) == "done" and k not in seen_in_race.get(r, set()):
                warnings.append(f"{info['name']} ({f['name']}) has no result in round {r}: possible replacement or DNS not in feed; review.")
    gross = round(sum(by_round.values()), 2)
    pen_pts = sum(x["penalty_points"] for x in drivers)
    pen_ded = pen_pts * RULES["penalty_point_deduction"]
    repl = 0
    for rp in ROSTERS.get("replacements", []):
        if rp["fto"] == f["name"]:
            repl += RULES["replacement_penalty_by_tier"].get(str(rp["tier"]), 0)
    bonus = RULES["champion_bonus"] if (season_complete and champion_key in [d["key"] for d in f["drivers"]]) else 0
    cum, running = [], 0.0
    for r in rounds_done:
        running += by_round[r]
        cum.append(round(running, 2))
    ftos_out.append({
        "name": f["name"], "color_slot": f["color_slot"], "drivers": drivers,
        "by_round": {str(r): round(v, 2) for r, v in by_round.items()},
        "cumulative": cum, "gross": gross, "penalty_points": pen_pts,
        "penalty_deduction": -pen_ded, "replacement_penalty": -repl, "champion_bonus": bonus,
        "total": round(gross - pen_ded - repl + bonus, 2),
    })

ftos_out.sort(key=lambda x: -x["total"])
lead = ftos_out[0]["total"] if ftos_out else 0
for i, f in enumerate(ftos_out):
    f["rank"] = i + 1
    f["gap"] = round(lead - f["total"], 2)

# all-driver table (includes unowned "Ghost" drivers)
all_drivers = []
for k, info in driver_info.items():
    tot = sum(p["total"] for p in points.get(k, {}).values())
    all_drivers.append({"key": k, "name": info["name"], "team": info["team"],
                        "owner": owner_of.get(k, "Unowned"), "points": round(tot, 2),
                        "tier": TIER_OF.get(k),
                        "penalty_points": pen_by_driver.get(k, 0),
                        "by_round": {str(r): p["total"] for r, p in points.get(k, {}).items()},
                        "detail": {str(r): {"race_pos": p.get("race_pos"), "race_status": p.get("race_status"),
                                            "quali_pos": p.get("quali_pos"), "sprint_pos": p.get("sprint_pos"),
                                            "race": p["race"], "pole": p["pole"], "sprint": p["sprint"],
                                            "sprint_pole": p["sprint_pole"], "total": p["total"]}
                                   for r, p in points.get(k, {}).items()}})
all_drivers.sort(key=lambda x: -x["points"])

champ_info = driver_info.get(champion_key, {})
out = {
    "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    "season": SEASON, "pot": RULES["pot"], "season_complete": season_complete,
    "races": races_out, "ftos": ftos_out, "drivers": all_drivers,
    "champion_leader": {"key": champion_key, "name": champ_info.get("name"),
                        "owner": owner_of.get(champion_key, "Unowned")},
    "penalties": [{k: v for k, v in p.items() if k != "driver_raw"} | {"name": driver_info.get(p["driver"], {}).get("name", p["driver_raw"]),
                   "owner": owner_of.get(p["driver"], "Unowned")} for p in penalties],
    "penalty_asof": penalty_asof,
    "penalty_source": penalty_source,
    "penalty_check": penalty_check,
    "warnings": warnings,
    "tiers": TIERS["tiers"],
    "rules": {k: RULES[k] for k in ("pole_bonus", "sprint_pole_bonus", "champion_bonus", "penalty_point_deduction",
                                    "race_points", "sprint_points", "replacement_penalty_by_tier")},
}
OUT.parent.mkdir(exist_ok=True)
json.dump(out, open(OUT, "w"), indent=1)
# raw per-driver/round breakdown for reconcile.py
json.dump({k: {str(r): v for r, v in d.items()} for k, d in points.items()},
          open(ROOT / "scripts" / "_breakdown.json", "w"), indent=1)
print(f"Wrote {OUT}: {len(rounds_done)} rounds scored, {len(penalties)} penalty entries, {len(warnings)} warnings")
for w in warnings:
    print("WARNING:", w)
