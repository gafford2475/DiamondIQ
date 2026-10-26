from diamondiq.projection import ProjectionInput, project
from diamondiq.projection.development import annual_delta, expected_growth


def _hs(**kw):
    base = dict(player_type="hitter", age=17.0, current_level="HS", sims=600, seed=1,
                seasons=[{"season": 2026, "level": "HS", "age": 16.8, "pa": 110, "rates": {"k_pct": 0.12, "bb_pct": 0.13, "iso": 0.200}}])
    base.update(kw)
    return ProjectionInput(**base)


def test_aging_curve_shape():
    assert annual_delta(18) > annual_delta(23) > annual_delta(27) >= 0 > annual_delta(33)
    assert expected_growth(18, 27) > 10
    assert expected_growth(30, 34) < 0


def test_better_evidence_projects_higher():
    weak = project(_hs(seasons=[{"season": 2026, "level": "HS", "age": 16.8, "pa": 110, "rates": {"k_pct": 0.30, "bb_pct": 0.06, "iso": 0.060}}]))
    strong = project(_hs())
    assert strong["current_talent"]["overall"] > weak["current_talent"]["overall"]
    assert strong["outcomes"]["peak_talent"]["median"] > weak["outcomes"]["peak_talent"]["median"]


def test_same_stats_at_higher_level_mean_more_talent():
    hs = project(_hs())
    d1 = project(_hs(age=20, current_level="NCAA_D1", seasons=[{"season": 2026, "level": "NCAA_D1", "age": 20, "pa": 250, "rates": {"k_pct": 0.12, "bb_pct": 0.13, "iso": 0.200}}]))
    assert d1["current_talent"]["overall"] > hs["current_talent"]["overall"] + 8


def test_scouting_and_tracking_evidence_are_used_and_explained():
    r = project(_hs(scouting={"report_count": 1, "tools": {"hit": {"present": {"mean": 35, "spread": 0}, "future": {"mean": 60, "spread": 0}}}},
                    tracking={"ev_90th": 98.0}))
    sources = {s["source"] for s in r["current_talent"]["components"]["power"]["sources"]}
    assert {"level prior", "stats", "tracking"} <= sources
    assert r["growth_multipliers"]["contact"]["multiplier"] > 1.0
    assert r["growth_multipliers"]["contact"]["reasons"]


def test_veteran_regresses():
    r = project(ProjectionInput(player_type="hitter", age=32, current_level="MLB", sims=600, seed=1,
                                seasons=[{"season": 2026, "level": "MLB", "age": 31.5, "pa": 600, "rates": {"k_pct": 0.2, "bb_pct": 0.1, "iso": 0.2}}]))
    medians = [y["overall_talent"]["median"] for y in r["years"]]
    assert medians[-1] < medians[0] - 4
    woba = [y["projected_by_level"]["MLB"]["woba"]["median"] for y in r["years"]]
    assert woba[-1] < woba[0]


def test_output_structure_and_probabilities():
    r = project(_hs(years=5))
    assert len(r["years"]) == 6
    assert abs(sum(t["probability"] for t in r["outcomes"]["tier_probabilities"]) - 1) < 0.01
    reach = r["outcomes"]["probability_reach_pro_level"]
    assert reach["ROOKIE"] >= reach["A"] >= reach["AA"] >= reach["MLB"]
    for y in r["years"]:
        assert abs(sum(d["probability"] for d in y["level_distribution"]) - 1) < 0.05 or len(y["level_distribution"]) == 6
        line = y["projected_by_level"]["AA"]["avg"]
        assert line["p10"] <= line["median"] <= line["p90"]
    assert "Most likely outcome" in r["summary"]


def test_promotions_are_paced():
    r = project(_hs(scouting={"report_count": 3, "tools": {"hit": {"present": {"mean": 45, "spread": 0}}, "game_power": {"present": {"mean": 45, "spread": 0}}, "approach": {"present": {"mean": 45, "spread": 0}}}}, years=3))
    # even an elite 17-year-old doesn't skip from HS straight to MLB the next year
    assert r["years"][1]["most_likely_level"] in ("A", "ROOKIE", "A_PLUS")


def test_pitcher_projection_velo_matters():
    base = dict(player_type="pitcher", age=20, current_level="NCAA_D1", sims=600, seed=2,
                seasons=[{"season": 2026, "level": "NCAA_D1", "age": 20, "bf": 250, "rates": {"k_pct": 0.25, "bb_pct": 0.10, "hr_pct": 0.02}}])
    slow = project(ProjectionInput(**base, tracking={"fb_velo_avg": 86.0}))
    fast = project(ProjectionInput(**base, tracking={"fb_velo_avg": 95.5}))
    assert fast["current_talent"]["components"]["stuff"]["talent"] > slow["current_talent"]["components"]["stuff"]["talent"] + 5
    k_fast = fast["years"][0]["projected_by_level"]["AA"]["k_pct"]["median"]
    k_slow = slow["years"][0]["projected_by_level"]["AA"]["k_pct"]["median"]
    assert k_fast > k_slow
