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

HTML = """<h4>Franco Colapinto</h4><table><tr><th>Date</th></tr>
<tr><td>14/6/2026</td><td>Barcelona GP</td><td>Grand prix</td><td>x</td><td>1</td></tr>
<tr><td>23/8/2026</td><td>Dutch GP</td><td>Grand prix</td><td>y</td><td>3</td></tr>
<tr><td>3/8/2025</td><td>Old GP</td><td>Grand prix</td><td>z</td><td>2</td></tr></table>
<h4>Lando Norris</h4><p>No penalty points incurred over 12 months prior to August 25 2026</p>"""

class Resp:
    def __init__(self, js=None, text=""): self._j, self.text, self.status_code = js, text, 200
    def json(self): return self._j
    def raise_for_status(self): pass

def fake_get(self, url, params=None, timeout=None):
    if "racefans" in url: return Resp(text=HTML)
    if "openf1.org/v1/sessions" in url: return Resp([{"session_key": 99, "date_start": "2026-03-13T07:30:00+00:00"}])
    if "openf1.org/v1/session_result" in url: return Resp([{"driver_number": 63, "position": 1}])
    if "openf1.org/v1/drivers" in url: return Resp([{"last_name": "Russell"}])
    if url.endswith("/2026.json"): return Resp(CAL)
    if url.endswith("driverstandings.json"): return Resp({"MRData": {"StandingsTable": {"StandingsLists": [{"DriverStandings": [{"Driver": {"familyName": "Antonelli"}}]}]}}})
    tbl = {"/1/results.json": ("Results", R1_RACE), "/1/qualifying.json": ("QualifyingResults", R1_QUALI),
           "/2/results.json": ("Results", R2_RACE), "/2/qualifying.json": ("QualifyingResults", R2_QUALI),
           "/2/sprint.json": ("SprintResults", R2_SPRINT)}
    for suffix, (k, v) in tbl.items():
        if url.endswith(suffix): return Resp(wrap(k, v))
    raise AssertionError(url)

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
    assert d["penalty_asof"] == "August 25 2026"
    assert d["races"][1]["sprint_pole"] == "russell"
    assert by["antonelli"]["detail"]["2"]["pole"] == 3 and by["antonelli"]["tier"] == 1
    assert by["russell"]["detail"]["2"]["sprint_pole"] == 1.5
    assert d["tiers"]["3"][0] == "Fernando Alonso" and d["rules"]["race_points"][0] == 30
    out.unlink()
