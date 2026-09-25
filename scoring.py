"""Pure scoring helpers (no network) so they can be unit-tested."""
import re, unicodedata


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", s.lower())


def classified_pos(entry: dict):
    """Finishing position as int if the driver was classified, else None.
    Jolpica/Ergast: positionText is numeric when classified, R/D/W/N/E/F otherwise."""
    pt = str(entry.get("positionText", "")).strip()
    return int(pt) if pt.isdigit() else None


def place_points(pos, table):
    if pos is None or pos < 1 or pos > len(table):
        return 0
    return table[pos - 1]


def weekend_points(rules, race_pos=None, quali_pos=None, sprint_pos=None, sprint_quali_pos=None):
    """Return breakdown dict for one driver at one weekend."""
    b = {
        "race": place_points(race_pos, rules["race_points"]),
        "pole": rules["pole_bonus"] if quali_pos == 1 else 0,
        "sprint": place_points(sprint_pos, rules["sprint_points"]),
        "sprint_pole": rules["sprint_pole_bonus"] if sprint_quali_pos == 1 else 0,
    }
    b["total"] = round(sum(b.values()), 2)
    return b
