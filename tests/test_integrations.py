from conftest import SAMPLES

from diamondiq.integrations import detect_source, get_adapter
from diamondiq.integrations.base import clock_to_degrees, normalize_pitch_type


def _read(name):
    return (SAMPLES / name).read_bytes()


def test_detects_vendor_formats():
    assert detect_source(_read("trackman_game.csv")) == "trackman"
    assert detect_source(_read("rapsodo_pitching.csv")) == "rapsodo_pitching"
    assert detect_source(_read("hittrax_session.csv")) == "hittrax"
    assert detect_source(_read("statcast.csv")) == "hawkeye"
    assert detect_source(_read("blast_swings.csv")) == "blast"


def test_trackman_creates_pitch_and_batted_ball_events():
    events = get_adapter("trackman").parse(_read("trackman_game.csv"))
    pitches = [e for e in events if e.event_type == "pitch"]
    batted = [e for e in events if e.event_type == "batted_ball"]
    assert len(pitches) == 6 and len(batted) == 2
    assert pitches[0].player_name == "Marco Reyes" and pitches[0].pitch_type == "FF"
    assert pitches[1].pitch_result == "swinging_strike"
    assert batted[1].player_name == "Luis Diaz" and batted[1].exit_velocity == 104.8


def test_rapsodo_preamble_units_and_spin_direction():
    events = get_adapter("rapsodo").parse(_read("rapsodo_pitching.csv"))
    assert len(events) == 3
    fb = events[0]
    assert fb.pitch_type == "FF" and fb.velocity == 91.8
    assert fb.ivb == 17.3  # prefers spin-based (induced) break
    assert abs(fb.plate_z - 30.1 / 12) < 1e-3
    assert fb.spin_axis == clock_to_degrees("1:15") == 217.5


def test_statcast_converts_feet_to_inches():
    events = get_adapter("statcast").parse(_read("statcast.csv"))
    fb = events[0]
    assert fb.player_name == "Sam Ace" and fb.player_external_id == "670001"
    assert abs(fb.ivb - 1.42 * 12) < 0.01
    hitter = [e for e in events if e.role == "hitter"]
    assert any(e.exit_velocity == 103.4 for e in hitter)
    assert any(e.event_type == "swing" and e.bat_speed == 71.2 for e in hitter)


def test_hittrax_and_blast():
    ht = get_adapter("hittrax").parse(_read("hittrax_session.csv"))
    assert [e.exit_velocity for e in ht] == [91.2, 98.7, 101.4, 84.5]
    assert ht[0].player_name == "Jordan Cole"
    bl = get_adapter("blast").parse(_read("blast_swings.csv"), player_name="Jordan Cole")
    assert [e.bat_speed for e in bl] == [68.4, 70.2] and bl[0].time_to_contact == 0.152


def test_generic_adapter_with_unit_conversion():
    csv = "Athlete,Speed (km/h),RPM\nAiko Tanaka,150,2400\n"
    ev = get_adapter("generic").parse(csv, column_map={"player_name": "Athlete", "velocity": "Speed (km/h)", "spin_rate": "RPM"},
                                      units={"velocity": "kph"}, event_type="pitch", source_name="pocket_radar")
    assert ev[0].source == "pocket_radar" and abs(ev[0].velocity - 93.2) < 0.1


def test_pitch_type_normalization():
    assert normalize_pitch_type("Four-Seam") == "FF"
    assert normalize_pitch_type("ChangeUp") == "CH"
    assert normalize_pitch_type("Sweeper") == "ST"
