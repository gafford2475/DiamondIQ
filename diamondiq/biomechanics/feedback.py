"""Turn biomechanics metrics into coaching feedback.

Reference ranges come from published pitching/hitting biomechanics work
(ASMI, Driveline, and university motion-capture studies) and coaching norms.
They are starting points: ``REFERENCES`` is plain data so an organization can
tune ranges per level band, and ranges can be re-derived from the system's
own population once enough analyses exist (see ``population_reference``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..levels import LevelCategory, get_level


@dataclass
class Ref:
    label: str
    unit: str
    optimal: tuple[float, float]
    flag: tuple[float | None, float | None]  # beyond these = flag; between optimal and flag = watch
    why: str
    low_cue: str = ""
    high_cue: str = ""
    low_drills: list[str] = field(default_factory=list)
    high_drills: list[str] = field(default_factory=list)
    weight: float = 1.0
    speed_metric: bool = False  # sensitive to frame rate
    band_optimal: dict[str, tuple[float, float]] = field(default_factory=dict)  # youth | amateur | pro overrides


PITCHING: dict[str, Ref] = {
    "stride_length_pct_height": Ref(
        "Stride length", "% height", (80, 100), (68, 112),
        "Longer strides (with control) let the pelvis travel and rotate later, adding velocity without extra arm stress.",
        low_cue="Stride is short. Drive down the mound longer and stay closed while the hips move toward the plate.",
        high_cue="Stride is very long; check that the lead leg can still brace and the head stays over the front foot.",
        low_drills=["Rocker/step-back drill", "Hip-lead walk-ins with a band", "Lateral bounds for lower-half power"],
        high_drills=["Stride-length markers on the mound", "Lead-leg block holds at foot plant"],
        weight=1.2, band_optimal={"youth": (70, 92), "amateur": (77, 98)},
    ),
    "stride_offset_pct_height": Ref(
        "Stride direction", "% height (+ closed)", (-4, 8), (-10, 15),
        "Landing too open lets the trunk fly open early; landing too closed forces the arm to throw across the body.",
        low_cue="Front foot is landing open (toward the glove side). Keep the front side closed longer and stride on line.",
        high_cue="Front foot is landing closed, so you throw across your body. Aim the stride on the line to the plate.",
        low_drills=["Line drill (stride along tape)", "Closed-hip walk-throughs"],
        high_drills=["Line drill (stride along tape)", "Open-stride step-overs"],
    ),
    "hip_shoulder_separation_fp_deg": Ref(
        "Hip-shoulder separation at foot plant", "deg", (30, 60), (15, 75),
        "Separation stores elastic energy in the trunk; it is one of the strongest mechanical correlates of velocity.",
        low_cue="Hips and shoulders open together. Let the hips start rotating while the chest stays closed.",
        high_cue="Separation is very large; make sure it is not coming from the shoulders reaching back too far.",
        low_drills=["Hip-shoulder separation med-ball throws", "Walking windup with hip lead", "Split-stance rotation holds"],
        high_drills=["Med-ball shot puts focusing on timed trunk rotation"],
        weight=1.5,
    ),
    "trunk_rotation_at_fp_deg": Ref(
        "Trunk rotation at foot plant", "deg (0 = closed)", (-10, 25), (None, 40),
        "Shoulders opening before foot plant leak energy and are associated with higher shoulder and elbow load.",
        high_cue="The trunk is opening before the front foot lands. Keep the glove side closed until foot strike.",
        high_drills=["Glove-side 'show the number' holds", "Towel drill with closed front shoulder", "Rocker drill"],
        weight=1.3,
    ),
    "lead_knee_flexion_fp_deg": Ref(
        "Lead knee flexion at foot plant", "deg", (35, 55), (25, 65),
        "Landing with a moderately bent knee lets the lead leg accept force and then brace.",
        low_cue="Landing with a very straight front leg; you may be stepping too stiff to absorb force.",
        high_cue="Landing very bent at the front knee; you may be collapsing instead of bracing.",
        low_drills=["Drop-step landings", "Single-leg landing control"],
        high_drills=["Lead-leg block drill", "Eccentric single-leg squats", "Box-jump landings"],
    ),
    "lead_knee_extension_deg": Ref(
        "Lead leg block (extension foot plant -> release)", "deg", (5, 30), (-10, None),
        "Firming up the front leg converts forward momentum into rotation. Pitchers who brace tend to throw harder.",
        low_cue="The front knee keeps bending through release. Plant and firm up the front leg so the trunk rotates over it.",
        low_drills=["Lead-leg block drill", "Step-behind med-ball throws", "Isometric lead-leg holds"],
        weight=1.3,
    ),
    "shoulder_abduction_fp_deg": Ref(
        "Shoulder abduction at foot plant", "deg", (80, 105), (65, 120),
        "An upper arm near shoulder height at foot plant keeps the arm on time and reduces shoulder load.",
        low_cue="The throwing elbow is low at foot plant; get the arm up to shoulder height on time.",
        high_cue="The elbow is above the shoulder line at foot plant; that can increase shoulder stress.",
        low_drills=["Connection-ball throws", "Arm-path 'high-guard' drill", "Plyo ball pivot picks"],
        high_drills=["Plyo ball reverse throws", "Arm-path mirror work"],
        weight=1.2,
    ),
    "elbow_flexion_fp_deg": Ref(
        "Elbow flexion at foot plant", "deg", (75, 110), (55, 130),
        "A roughly 90-degree elbow at foot plant is typical of efficient, on-time arm action.",
        low_cue="The arm is fairly straight at foot plant (long arm action); shorten the arm path.",
        high_cue="The elbow is very bent at foot plant.",
        low_drills=["Plyo ball pivot picks", "Short-arm connection throws"],
    ),
    "elbow_height_fp_pct_height": Ref(
        "Elbow height vs shoulder at foot plant", "% height", (-4, 6), (-8, 12),
        "An elbow below the shoulder line at foot plant (late arm) is a commonly cited elbow-stress risk.",
        low_cue="Elbow is below the shoulder line at foot plant. The arm is late; start it earlier out of the glove.",
        low_drills=["Arm-timing 'pick-up' drill", "Connection-ball throws"],
        weight=1.2,
    ),
    "trunk_forward_tilt_release_deg": Ref(
        "Forward trunk tilt at release", "deg", (25, 45), (15, 55),
        "Forward tilt adds release extension and lets the trunk contribute to velocity.",
        low_cue="You are upright at release. Finish over a firm front leg and let the chest get out over it.",
        high_cue="Very forward tilt at release; check that it is not from a collapsing front leg.",
        low_drills=["Rocker drill with full finish", "Walking windups", "Hip mobility (90/90)"],
    ),
    "trunk_lateral_tilt_release_deg": Ref(
        "Glove-side trunk tilt at release", "deg", (5, 35), (None, 45),
        "Some tilt sets the arm slot. Excess contralateral tilt is associated with higher elbow load.",
        high_cue="Large glove-side lean at release. Raise the arm slot with the arm rather than by bending the trunk.",
        high_drills=["Anti-lateral-flexion core work (suitcase carries)", "Slot-matching mirror drill"],
    ),
    "head_drift_glove_side_pct_height": Ref(
        "Head drift toward glove side", "% height", (-3, 8), (None, 15),
        "A stable head path supports command and a consistent release point.",
        high_cue="The head is pulling toward the glove side through release. Keep the eyes on line to the target.",
        high_drills=["Target-focus drills", "Stride-and-hold balance work"],
    ),
    "peak_pelvis_velocity_dps": Ref(
        "Peak pelvis rotation velocity", "deg/s", (550, 800), (420, None),
        "Pelvis speed drives the kinematic chain.",
        low_cue="Pelvis rotation is slow. Build lower-half rotational power.",
        low_drills=["Rotational med-ball scoop toss", "Hip-lead step-behind throws", "Lateral bounds", "Hip mobility"],
        speed_metric=True, band_optimal={"youth": (350, 700), "amateur": (450, 750)},
    ),
    "peak_trunk_velocity_dps": Ref(
        "Peak trunk rotation velocity", "deg/s", (900, 1300), (700, None),
        "Trunk speed is a direct contributor to arm speed and velocity.",
        low_cue="Trunk rotation is slow. Develop rotational power and thoracic mobility.",
        low_drills=["Med-ball shot puts", "Thoracic rotation mobility", "Split-stance cable rotations"],
        speed_metric=True, band_optimal={"youth": (650, 1100), "amateur": (800, 1200)},
    ),
    "trunk_after_pelvis_ms": Ref(
        "Pelvis-to-trunk timing", "ms", (20, 60), (0, 90),
        "The trunk should peak shortly after the pelvis. That proximal-to-distal timing transfers energy efficiently.",
        low_cue="Pelvis and trunk peak together (or the trunk first). Let the hips lead.",
        high_cue="Long gap between pelvis and trunk peaks; energy may dissipate between segments.",
        low_drills=["Hip-lead med-ball throws", "Separation drill with pause at foot plant"],
        speed_metric=True,
    ),
    "fp_to_release_ms": Ref(
        "Foot plant to release time", "ms", (120, 180), (90, 230),
        "Shows how quickly the trunk and arm convert the stride into release.",
        high_cue="Slow from foot plant to release; the upper body may be waiting on the lower half.",
        high_drills=["Rocker drill", "Plyo pivot picks"],
        speed_metric=True,
    ),
}

HITTING: dict[str, Ref] = {
    "stance_width_pct_height": Ref(
        "Stance width", "% height", (25, 60), (15, 75),
        "Stance sets balance and how much the stride has to do.",
        low_cue="Very narrow stance; you rely on a big stride for direction and power.",
        high_cue="Very wide stance; check that you can still load into the back hip.",
    ),
    "stride_gain_pct_height": Ref(
        "Stride length", "% height", (5, 25), (-5, 35),
        "A controlled stride moves energy toward the pitcher without pulling the head along.",
        low_cue="Little or no stride; make sure you still get a forward move and hip load.",
        high_cue="Overstriding; it can cause head movement and late, lunging swings.",
        low_drills=["Step-back drill", "Hover-load tee work"],
        high_drills=["Stride-to-a-marker tee work", "Balance-beam stride holds"],
    ),
    "hip_shoulder_separation_fd_deg": Ref(
        "Hip-shoulder separation at foot down", "deg", (15, 40), (5, 55),
        "The torso staying closed while the hips begin to open stores elastic energy for bat speed.",
        low_cue="Hips and shoulders turn together. Let the hips start while the front shoulder stays in.",
        high_cue="Very large separation; make sure the shoulders are not wrapping (bat tip too far behind).",
        low_drills=["Separation drill with pause at foot down", "Med-ball hitter's throws", "Walk-through swings"],
        high_drills=["Bat-on-shoulder rotation holds", "Short-bat drill"],
        weight=1.5,
    ),
    "pelvis_rotation_at_fd_deg": Ref(
        "Pelvis rotation at foot down", "deg (0 = closed)", (-5, 30), (None, 45),
        "Hips opening early leave little rotation for the swing and expose you to off-speed.",
        high_cue="The hips are already open when the front foot lands. Land closed, then rotate.",
        high_drills=["Closed-landing stride holds", "Step-close drill"],
        weight=1.2,
    ),
    "lead_knee_extension_deg": Ref(
        "Front leg brace (foot down -> contact)", "deg", (5, 35), (-10, None),
        "Firming the front leg stops forward travel and turns it into rotation and bat speed.",
        low_cue="The front knee keeps bending into contact. Plant and firm up the front side.",
        low_drills=["Front-leg block tee drill", "Med-ball step-and-stick throws", "Single-leg strength work"],
        weight=1.3,
    ),
    "back_elbow_flexion_fd_deg": Ref(
        "Back elbow at foot down", "deg", (70, 110), (50, 130),
        "The back elbow angle reflects the hand position before launch.",
        low_cue="Back arm fairly straight at foot down (barred arm); the swing can get long.",
        high_cue="Back elbow very bent and pinned; check that the hands can work up and through the zone.",
        low_drills=["Fence drill", "Short-bat one-hand drills"],
    ),
    "shoulder_tilt_contact_deg": Ref(
        "Shoulder tilt at contact", "deg (lead shoulder up)", (15, 40), (5, 50),
        "Shoulder tilt sets the bat's attack angle and lets you match the plane of the pitch.",
        low_cue="Shoulders are level at contact; the swing may be flat and hard to keep on plane.",
        high_cue="Extreme tilt at contact; the swing may be getting too uphill.",
        low_drills=["High-tee/low-tee plane matching", "Side-bend posture holds"],
        high_drills=["Line-drive net targets", "Top-hand release drill"],
    ),
    "spine_tilt_contact_deg": Ref(
        "Spine tilt at contact", "deg from vertical", (20, 40), (10, 55),
        "Holding posture through contact keeps the barrel on plane.",
        low_cue="Very upright at contact; hinge at the hips and keep posture.",
        high_cue="Bent far over at contact; check balance and pitch location.",
    ),
    "head_movement_pct_height": Ref(
        "Head movement (load -> contact)", "% height", (0, 5), (None, 9),
        "A quiet head helps pitch recognition and barrel accuracy.",
        high_cue="The head moves a lot between load and contact. Shorten the stride and stay centered.",
        high_drills=["Tee work with head marker", "Front-toss with stride control", "Balance-beam swings"],
        weight=1.3,
    ),
    "head_drop_pct_height": Ref(
        "Head drop (load -> contact)", "% height", (-2, 5), (None, 9),
        "Too much drop changes eye level mid-swing.",
        high_cue="The head drops a lot during the swing; the legs may be collapsing.",
        high_drills=["Hip-hinge posture holds", "Mirror swings"],
    ),
    "peak_pelvis_velocity_dps": Ref(
        "Peak pelvis rotation velocity", "deg/s", (600, 900), (450, None),
        "Pelvis speed starts the kinematic chain that produces bat speed.",
        low_cue="Pelvis rotation is slow. Build rotational power from the ground up.",
        low_drills=["Rotational med-ball scoop toss", "Hip-turn band drills", "Overload/underload bat training"],
        speed_metric=True, band_optimal={"youth": (400, 800), "amateur": (500, 850)},
    ),
    "peak_trunk_velocity_dps": Ref(
        "Peak trunk rotation velocity", "deg/s", (850, 1300), (650, None),
        "Trunk speed is closely tied to bat speed.",
        low_cue="Trunk rotation is slow. Work on rotational power and thoracic mobility.",
        low_drills=["Med-ball hitter's throws", "Thoracic mobility", "Overload/underload bat training"],
        speed_metric=True, band_optimal={"youth": (600, 1100), "amateur": (750, 1200)},
    ),
    "trunk_after_pelvis_ms": Ref(
        "Pelvis-to-trunk timing", "ms", (15, 50), (0, 80),
        "Proximal-to-distal sequencing (pelvis -> trunk -> arms -> bat) maximizes bat speed.",
        low_cue="Hips and trunk fire together (or the trunk first). Let the hips lead.",
        high_cue="Long delay between hip and trunk peaks.",
        low_drills=["Separation drill", "Step-behind med-ball throws"],
        speed_metric=True,
    ),
    "fd_to_contact_ms": Ref(
        "Foot down to contact time", "ms", (150, 230), (110, 300),
        "Shows how efficiently the swing converts from stride to contact.",
        low_cue="Very quick from foot down to contact; check that the front foot isn't landing late and rushing the swing.",
        low_drills=["Early-stride timing drills", "Varied-speed front toss"],
        high_cue="Slow from foot down to contact; the swing may be long.",
        high_drills=["Short-bat drills", "High-velocity front toss"],
        speed_metric=True,
    ),
}

SEQUENCE_REF = {
    "label": "Kinematic sequence (pelvis -> trunk -> arm)",
    "why": "Efficient movers peak pelvis first, then trunk, then arm or hands. Out-of-order sequencing costs speed and adds load on the arm.",
    "cue": "Segments are peaking out of order. Lead with the lower half and let the trunk and arm follow.",
    "drills": ["Hip-lead med-ball throws", "Step-behind drill", "Rocker drill"],
}


def level_band(level_code: str | None) -> str:
    if not level_code:
        return "amateur"
    try:
        lvl = get_level(level_code)
    except KeyError:
        return "amateur"
    if lvl.category in (LevelCategory.HIGH_SCHOOL, LevelCategory.TRAVEL):
        return "youth"
    if lvl.is_amateur:
        return "amateur"
    return "pro"


@dataclass
class FeedbackItem:
    metric: str
    label: str
    value: float | bool | None
    unit: str
    optimal: tuple[float, float] | None
    status: str  # optimal | watch | flag | unavailable
    message: str
    why: str
    drills: list[str]
    priority: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _assess(name: str, ref: Ref, value: Any, band: str, fps: float) -> FeedbackItem:
    lo, hi = ref.band_optimal.get(band, ref.optimal)
    if value is None:
        return FeedbackItem(name, ref.label, None, ref.unit, (lo, hi), "unavailable", "Not measurable from this video.", ref.why, [], 0)
    flo, fhi = ref.flag
    if ref.band_optimal.get(band) and flo is not None:
        flo = lo - (ref.optimal[0] - flo)  # shift flag thresholds with the band
    if lo <= value <= hi:
        status, msg, drills = "optimal", f"{ref.label} is in the target range.", []
    elif value < lo:
        status = "flag" if flo is not None and value < flo else "watch"
        msg, drills = ref.low_cue or f"{ref.label} is below target.", ref.low_drills
    else:
        status = "flag" if fhi is not None and value > fhi else "watch"
        msg, drills = ref.high_cue or f"{ref.label} is above target.", ref.high_drills
    if ref.speed_metric and fps < 120 and status == "flag":
        status = "watch"
        msg += f" (Low confidence at {fps:.0f} fps.)"
    severity = {"optimal": 0, "watch": 1, "flag": 2}[status]
    width = max(hi - lo, 1e-6)
    distance = 0 if status == "optimal" else min(abs(value - (lo if value < lo else hi)) / width, 3)
    return FeedbackItem(name, ref.label, value, ref.unit, (lo, hi), status, msg, ref.why, list(drills), round(ref.weight * (severity + distance), 2))


def build_feedback(motion_type: str, metrics: dict[str, Any], level_code: str | None = None, fps: float = 240) -> dict[str, Any]:
    refs = PITCHING if motion_type == "pitching" else HITTING
    band = level_band(level_code)
    items = [_assess(name, ref, metrics.get(name), band, fps) for name, ref in refs.items()]
    seq_ok = metrics.get("proper_sequence")
    if seq_ok is not None:
        items.append(
            FeedbackItem(
                "proper_sequence", SEQUENCE_REF["label"], bool(seq_ok), "", None,
                "optimal" if seq_ok else ("watch" if fps < 120 else "flag"),
                "Segments peak in the efficient order." if seq_ok else SEQUENCE_REF["cue"],
                SEQUENCE_REF["why"], [] if seq_ok else SEQUENCE_REF["drills"], 0 if seq_ok else 3.0,
            )
        )

    scored = [i for i in items if i.status != "unavailable"]
    pts = {"optimal": 1.0, "watch": 0.6, "flag": 0.2}
    weights = {i.metric: refs[i.metric].weight if i.metric in refs else 1.5 for i in scored}
    total_w = sum(weights.values()) or 1
    score = round(100 * sum(pts[i.status] * weights[i.metric] for i in scored) / total_w, 1)

    priorities = sorted((i for i in scored if i.status != "optimal"), key=lambda i: -i.priority)
    strengths = [i.label for i in scored if i.status == "optimal"]
    out = {
        "level_band": band,
        "mechanics_score": score,
        "items": [i.to_dict() for i in items],
        "top_priorities": [i.to_dict() for i in priorities[:3]],
        "strengths": strengths,
    }
    if motion_type == "pitching":
        out["arm_stress"] = arm_stress_indicators(metrics, {i.metric: i.status for i in items})
    return out


def arm_stress_indicators(metrics: dict[str, Any], status: dict[str, str]) -> dict[str, Any]:
    """Mechanical patterns associated in research with elevated elbow/shoulder load.

    These are screening indicators, not a medical assessment.
    """
    checks = [
        ("elbow_height_fp_pct_height", "Late arm: elbow below shoulder at foot plant"),
        ("shoulder_abduction_fp_deg", "Shoulder abduction outside 80-105 deg at foot plant"),
        ("trunk_rotation_at_fp_deg", "Early trunk rotation (shoulders open before foot plant)"),
        ("trunk_lateral_tilt_release_deg", "Excessive glove-side trunk tilt at release"),
        ("lead_knee_extension_deg", "No lead-leg block"),
        ("proper_sequence", "Out-of-order kinematic sequence"),
    ]
    found = [label for key, label in checks if status.get(key) == "flag"]
    watch = [label for key, label in checks if status.get(key) == "watch"]
    load = len(found) * 2 + len(watch)
    level = "low" if load <= 1 else "moderate" if load <= 4 else "elevated"
    return {
        "level": level,
        "flags": found,
        "watch": watch,
        "note": "Screening indicators from video, not a medical or injury diagnosis. Pair with workload tracking and a qualified clinician.",
    }
