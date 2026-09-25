import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))
from scoring import weekend_points, classified_pos, norm

R = json.load(open(pathlib.Path(__file__).parent.parent / "config" / "rules.json"))

# Cases taken from the owner's manually maintained sheet (place / quali -> points)
def test_antonelli_china():   # GP P1 pole, sprint P5, sprint quali 2  => 39
    assert weekend_points(R, 1, 1, 5, 2)["total"] == 39
def test_russell_china():     # GP P2 q2, sprint P1 sprint pole => 40.5
    assert weekend_points(R, 2, 2, 1, 1)["total"] == 40.5
def test_russell_canada():    # GP NC but pole, sprint P1 sprint pole => 19.5
    assert weekend_points(R, None, 1, 1, 1)["total"] == 19.5
def test_norris_china_dns():  # GP DNS, sprint P4 => 7.5
    assert weekend_points(R, None, 6, 4, 3)["total"] == 7.5
def test_leclerc_barcelona(): # P15 => 1
    assert weekend_points(R, 15, 10)["total"] == 1
def test_antonelli_barcelona():  # P16 => 0
    assert weekend_points(R, 16, 3)["total"] == 0
def test_norris_miami():      # P2 q4, sprint P1 sprint pole => 24+15+1.5 = 40.5
    assert weekend_points(R, 2, 4, 1, 1)["total"] == 40.5
def test_classified():
    assert classified_pos({"positionText": "7"}) == 7
    assert classified_pos({"positionText": "R"}) is None
def test_norm():
    assert norm("Nico Hülkenberg") == "nicohulkenberg"
