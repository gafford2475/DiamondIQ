import json

import numpy as np

from diamondiq.biomechanics.keypoints import PoseSequence
from diamondiq.biomechanics.pipeline import analyze_sequence
from diamondiq.biomechanics.synthetic import synthetic_pitch, synthetic_swing


def test_pitching_phases_are_ordered_and_metrics_reasonable():
    r = analyze_sequence(synthetic_pitch(), "pitching", "R", height_in=74, level_code="NCAA_D1")
    ph = r["phases"]
    assert ph["leg_lift"] < ph["foot_plant"] < ph["ball_release"] < ph["finish"]
    # generator lands the foot at 0.75 s and releases at ~0.85-0.90 s
    assert abs(r["phase_times_s"]["foot_plant"] - 0.75) < 0.05
    assert 0.80 <= r["phase_times_s"]["ball_release"] <= 0.92
    mt = r["metrics"]
    assert 82 < mt["stride_length_pct_height"] < 92  # generator: 88%
    assert mt["proper_sequence"] is True
    assert 40 < mt["lead_knee_flexion_fp_deg"] < 50
    assert mt["lead_knee_extension_deg"] > 5


def test_pitching_metrics_track_mechanics_changes():
    good = analyze_sequence(synthetic_pitch(), "pitching", "R")
    bad = analyze_sequence(synthetic_pitch(stride_pct=0.68, separation_deg=10, knee_brace_deg=-12), "pitching", "R")
    g, b = good["metrics"], bad["metrics"]
    assert b["stride_length_pct_height"] < g["stride_length_pct_height"] - 12
    assert b["hip_shoulder_separation_fp_deg"] < g["hip_shoulder_separation_fp_deg"]
    assert b["lead_knee_extension_deg"] < 0 < g["lead_knee_extension_deg"]
    assert bad["feedback"]["mechanics_score"] < good["feedback"]["mechanics_score"]
    flagged = {i["metric"] for i in bad["feedback"]["items"] if i["status"] != "optimal"}
    assert {"stride_length_pct_height", "lead_knee_extension_deg"} <= flagged
    assert all(i["drills"] for i in bad["feedback"]["top_priorities"])


def test_left_handed_pitcher_mirrors_right():
    r = analyze_sequence(synthetic_pitch(), "pitching", "R")["metrics"]
    l = analyze_sequence(synthetic_pitch(throws="L"), "pitching", "L")["metrics"]
    for k in ("stride_length_pct_height", "hip_shoulder_separation_fp_deg", "arm_slot_deg", "lead_knee_extension_deg"):
        assert abs(r[k] - l[k]) < 1.0, k


def test_low_fps_warns_and_softens_speed_flags():
    r = analyze_sequence(synthetic_pitch(fps=60), "pitching", "R")
    assert r["warnings"]
    speed_items = [i for i in r["feedback"]["items"] if i["metric"] in ("peak_pelvis_velocity_dps", "trunk_after_pelvis_ms")]
    assert all(i["status"] != "flag" for i in speed_items)


def test_swing_analysis_and_feedback():
    good = analyze_sequence(synthetic_swing(), "hitting", "R", level_code="HS")
    ph = good["phases"]
    assert ph["load"] < ph["foot_down"] < ph["contact"]
    assert good["metrics"]["proper_sequence"] is True
    bad = analyze_sequence(synthetic_swing(separation_deg=3, head_move_pct=0.12), "hitting", "R", level_code="HS")
    assert bad["metrics"]["head_movement_pct_height"] > good["metrics"]["head_movement_pct_height"] + 5
    assert bad["feedback"]["mechanics_score"] < good["feedback"]["mechanics_score"]
    lefty = analyze_sequence(synthetic_swing(bats="L"), "hitting", "L")
    assert abs(lefty["metrics"]["stride_gain_pct_height"] - good["metrics"]["stride_gain_pct_height"]) < 1


def test_keypoint_json_round_trip_and_noise_tolerance():
    seq = synthetic_pitch(noise=0.008, seed=3)
    seq2 = PoseSequence.from_json(json.loads(json.dumps(seq.to_json())))
    assert np.allclose(seq.points, seq2.points, atol=1e-3)
    r = analyze_sequence(seq2, "pitching", "R")
    assert 80 < r["metrics"]["stride_length_pct_height"] < 95
