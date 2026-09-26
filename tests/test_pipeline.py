"""End-to-end test of build_data.py against mocked API responses (no network)."""
import json, pathlib, runpy, sys
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent

def drv(fam, given, num, team, pos, status="Finished"):
    return {"positionText": str(pos), "position": str(pos), "status": status,
            "Driver": {"familyName": fam, "givenName": given, "permanentNumber": str(num)},
            "Constructor": {"name": team}}

def q(fam, given, num, team, pos):
    d = drv(fam, given, num, team, pos); return d

CAL = {"MRData": {"RaceTable": {"Races": [
    {"round": "1", "raceName": "Australian Grand Prix", "date": "2026-03-08", "Circuit": {"Location": {"country": "Australia"}}},
    {"round": "2", "raceName": "Chinese Grand Prix", "date": "2026-03-15", "Sprint": {"date": "2026-03-14"},
     "Circuit": {"Location": {"country": "China"}}}]}}}

def wrap(key, val, extra=None):
    return {"MRData": {"RaceTable": {"Races": [{key: val}]}}}

R2_RACE = [drv("Antonelli","Kimi",12,"Mercedes",1), drv("Russell","George",63,"Mercedes",2),
           drv("Norris","Lando",1,"McLaren",None or "R", "Retired")]
R2_QUALI = [q("Antonelli","Kimi",12,"Mercedes",1), q("Russell","George",63,"Mercedes",2), q("Norris","Lando",1,"McLaren",6)]
R2_SPRINT = [drv("Russell","George",63,"Mercedes",1), drv("Norris","Lando",1,"McLaren",4), drv("Antonelli","Kimi",12,"Mercedes",5)]
R1_RACE = [drv("Russell","George",63,"Mercedes",1), drv("Antonelli","Kimi",12,"Mercedes",2)]
R1_QUALI = [q("Russell","George",63,"Mercedes",1), q("Antonelli","Kimi",12,"Mercedes",2)]

# Mirrors the real page: <h2>"Name - N points"</h2> followed by <p> entries (not <li>), then a "Zero points" heading.
RN365 = """<h1>2026 F1 driver penalty points total</h1><p>Intro text. Points expire after 12 months.</p>
<div class="content-field__redactor"><h2 class="">Franco Colapinto - four points</h2>
<p>One point - expires June 14th, 2027. For failing to slow for yellow flags during 2026 Barcelona-Catalunya Grand Prix.&nbsp;</p>
<p>Two points - expires August 23rd, 2027. For overtaking under yellow flags during 2026 Dutch Grand Prix.</p>
<p>One point - expires August 23rd, 2027. For not slowing under yellow flags during 2026 Dutch Grand Prix.</p></div>
<div class="content-field__redactor"><h2 class="">Carlos Sainz - two points</h2>
<p>Two points - expires October 26th, 2026. For a collision during the 2025 United States GP.</p></div>
<h2>Zero points</h2><p>Norris</p><p>Footer text - not a penalty.</p>"""
STATE = {"cal": CAL, "rn": RN365}

class Resp:
    def __init__(self, js=None, text=""): self._j, self.text, self.status_code = js, text, 200
    def json(self): return self._j
    def raise_for_status(self): pass

def fake_get(self, url, params=None, timeout=None):
    if "racingnews365" in url:
        if STATE["rn"] is None: raise requests.ConnectionError("blocked")
        return Resp(text=STATE["rn"])
    if "openf1.org/v1/sessions" in url: return Resp([{"session_key": 99, "date_start": "2026-03-13T07:30:00+00:00"}])
    if "openf1.org/v1/session_result" in url: return Resp([{"driver_number": 63, "position": 1}])
    if "openf1.org/v1/drivers" in url: return Resp([{"last_name": "Russell"}])
    if url.endswith("/2026.json"): return Resp(STATE["cal"])
    if url.endswith("driverstandings.json"): return Resp({"MRData": {"StandingsTable": {"StandingsLists": [{"DriverStandings": [{"Driver": {"familyName": "Antonelli"}}]}]}}})
    tbl = {"/1/results.json": ("Results", R1_RACE), "/1/qualifying.json": ("QualifyingResults", R1_QUALI),
           "/2/results.json": ("Results", R2_RACE), "/2/qualifying.json": ("QualifyingResults", R2_QUALI),
           "/2/sprint.json": ("SprintResults", R2_SPRINT)}
    for suffix, (k, v) in tbl.items():
        if url.endswith(suffix): return Resp(wrap(k, v))
    raise AssertionError(url)

def _run(monkeypatch, rn=RN365):
    import time
    STATE["rn"] = rn
    monkeypatch.setattr(requests.Session, "get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    out = ROOT / "docs" / "data.json"
    if out.exists(): out.unlink()
    try:
        runpy.run_path(str(ROOT / "scripts" / "build_data.py"), run_name="__main__")
        return json.load(open(out))
    finally:
        STATE["rn"] = RN365
        if out.exists(): out.unlink()

def test_penalties_come_from_racingnews365_paragraphs(monkeypatch):
    d = _run(monkeypatch)
    assert d["penalty_source"] == "RacingNews365"
    col = [p for p in d["penalties"] if p["driver"] == "colapinto"]
    assert sorted((p["date"], p["points"]) for p in col) == [("2026-06-14", 1), ("2026-08-23", 1), ("2026-08-23", 2)]
    assert col[0]["event"][0].isupper() and not col[0]["event"].startswith("For ")
    assert not any(p["driver"] == "sainz" for p in d["penalties"])      # 2025-issued points (expire 2026) ignored
    assert d["penalties"] and all(p["date"].startswith("2026") for p in d["penalties"])
    assert not any("enalty" in w for w in d["warnings"])                 # no penalty notes/flags

def test_page_unreadable_does_not_break_the_build(monkeypatch):
    d = _run(monkeypatch, None)
    assert d["penalties"] == [] and d["ftos"]

def test_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(requests.Session, "get", fake_get)
    import time; monkeypatch.setattr(time, "sleep", lambda s: None)
    out = ROOT / "docs" / "data.json"
    if out.exists(): out.unlink()
    runpy.run_path(str(ROOT / "scripts" / "build_data.py"), run_name="__main__")
    d = json.load(open(out))
    by = {x["key"]: x for x in d["drivers"]}
    assert by["antonelli"]["by_round"]["2"] == 39      # matches the sheet's China (S) figure
    assert by["russell"]["by_round"]["2"] == 40.5
    assert by["norris"]["by_round"]["2"] == 7.5        # retired GP, sprint P4
    assert by["russell"]["by_round"]["1"] == 33
    f = {x["name"]: x for x in d["ftos"]}
    assert f["Brian"]["penalty_points"] == 4 and f["Brian"]["penalty_deduction"] == -20   # Colapinto: 2026 only
    assert all(p["date"].startswith("2026") for p in d["penalties"])
    assert d["races"][1]["sprint_pole"] == "russell"
    assert by["antonelli"]["detail"]["2"]["pole"] == 3 and by["antonelli"]["tier"] == 1
    assert by["russell"]["detail"]["2"]["sprint_pole"] == 1.5
    assert d["tiers"]["3"][0] == "Fernando Alonso" and d["rules"]["race_points"][0] == 30
    out.unlink()
