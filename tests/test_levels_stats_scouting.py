import datetime as dt
from types import SimpleNamespace

import pytest

from diamondiq.levels import assign_level, get_level
from diamondiq.scouting import consensus, normalize_tool_grades, suggested_ofp
from diamondiq.stats import hitting_rates, ip_to_outs, pitching_rates


def test_aliases_resolve():
    assert get_level("d1").code == "NCAA_D1"
    assert get_level("High-A").code == "A_PLUS"
    assert get_level("njcaa").code == "JUCO"
    with pytest.raises(KeyError):
        get_level("beer league")


def test_levels_ordered_on_talent_scale():
    order = ["HS", "NCAA_D3", "NCAA_D1", "A", "AA", "AAA", "MLB"]
    means = [get_level(c).talent_mean for c in order]
    assert means == sorted(means)
    assert get_level("MLB").talent_mean == 50


def test_assign_level_respects_age():
    assert get_level("HS").category.value == "high_school"
    assert assign_level(40, 16.5).code == "HS"  # minors aren't an option at 16
    assert assign_level(48, 26).code == "MLB"
    assert assign_level(30, 20, pathway="college").code == "NCAA_D1"
    assert assign_level(10, 27) is None  # out of organized baseball


def test_hitting_and_pitching_rates():
    r = hitting_rates({"pa": 100, "ab": 88, "h": 26, "2b": 6, "3b": 1, "hr": 4, "bb": 10, "so": 20, "hbp": 1, "sf": 1})
    assert r["avg"] == pytest.approx(26 / 88, abs=1e-3)
    assert r["iso"] == pytest.approx(r["slg"] - r["avg"], abs=1e-3)
    assert r["k_pct"] == 0.2
    p = pitching_rates({"ip": "6.2", "h": 5, "er": 2, "bb": 2, "so": 8, "hr": 1})
    assert ip_to_outs("6.2") == 20
    assert p["era"] == pytest.approx(2 * 9 / (20 / 3), abs=1e-3)


def test_grades_normalize_and_consensus():
    g = normalize_tool_grades({"Hit": 55, "raw power": {"present": 40, "future": 60}})
    assert g == {"hit": {"future": 55}, "raw_power": {"present": 40, "future": 60}}
    with pytest.raises(ValueError):
        normalize_tool_grades({"hit": 90})
    assert suggested_ofp("hitter", {"hit": 60, "game_power": 50, "field": 50, "run": 50, "arm": 50}) == pytest.approx(53.3, abs=0.1)
    reports = [
        SimpleNamespace(scout_name="A", report_date=dt.date(2026, 5, 1), report_type="hitter", tool_grades={"hit": {"present": 40, "future": 55}}, ofp=55, projectability=60, makeup=None),
        SimpleNamespace(scout_name="B", report_date=dt.date(2026, 3, 1), report_type="hitter", tool_grades={"hit": {"present": 30, "future": 50}}, ofp=50, projectability=None, makeup=55),
    ]
    c = consensus(reports)
    assert c["report_count"] == 2
    assert 35 < c["tools"]["hit"]["present"]["mean"] < 40  # recency-weighted toward scout A
    assert c["tools"]["hit"]["future"]["spread"] == 2.5
