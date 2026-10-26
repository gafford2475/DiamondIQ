"""Swing analysis from a pose sequence.

Phases: stance, load (hands furthest back), stride foot lift, foot down,
contact (peak hand speed) and finish.
"""

from __future__ import annotations

import numpy as np

from .common import MotionResult, fps_warnings, landing_frame, other, rnd, scale_factor
from .keypoints import PoseSequence
from .kinematics import UP, derivative, flexion, horizontal, peak_index, segment_rotation, speed, unit


def analyze_hitting(seq: PoseSequence, bats: str = "R", height_m: float | None = None) -> MotionResult:
    seq = seq.cleaned()
    fps = seq.fps
    warnings = fps_warnings(fps)
    back = "right" if bats.upper().startswith("R") else "left"
    lead = other(back)
    H, to_m = scale_factor(seq, height_m)

    lead_ankle, back_ankle = seq.side(lead, "ankle"), seq.side(back, "ankle")
    lead_knee, lead_hip, back_hip = seq.side(lead, "knee"), seq.side(lead, "hip"), seq.side(back, "hip")
    lead_sh, back_sh = seq.side(lead, "shoulder"), seq.side(back, "shoulder")
    back_elbow, back_wrist = seq.side(back, "elbow"), seq.side(back, "wrist")
    hands = seq.mid("left_wrist", "right_wrist")
    hip_mid, sh_mid = seq.mid("left_hip", "right_hip"), seq.mid("left_shoulder", "right_shoulder")
    nose = seq.joint("nose")

    toward_pitcher = unit(horizontal(lead_ankle[0] - back_ankle[0]))

    hand_speed = speed(hands, fps)
    contact = peak_index(hand_speed, int(0.3 * seq.n_frames))
    stride_lift = peak_index(lead_ankle[:, 1], 0, max(contact - 1, 1))
    foot_down = landing_frame(lead_ankle, fps, stride_lift, contact, H)
    hands_fwd = hands @ toward_pitcher
    load = peak_index(hands_fwd, 0, max(foot_down, 1), mode="min")
    if not load <= foot_down <= contact:
        warnings.append("Could not cleanly order load / foot down / contact; check camera angle and framing.")
    finish = min(seq.n_frames - 1, contact + int(0.3 * fps))

    pelvis_rot = segment_rotation(back_hip, lead_hip, toward_pitcher, (0, contact))
    trunk_rot = segment_rotation(back_sh, lead_sh, toward_pitcher, (0, contact))
    separation = pelvis_rot - trunk_rot
    pelvis_vel, trunk_vel = derivative(pelvis_rot, fps), derivative(trunk_rot, fps)
    pelvis_peak = peak_index(pelvis_vel, load, finish)
    trunk_peak = peak_index(trunk_vel, load, finish)

    lead_knee_flex = flexion(lead_hip, lead_knee, lead_ankle)
    back_elbow_flex = flexion(back_sh, back_elbow, back_wrist)
    spine = sh_mid - hip_mid
    spine_tilt = np.degrees(np.arccos(np.clip((spine @ UP) / (np.linalg.norm(spine, axis=-1) + 1e-9), -1, 1)))
    sh_line = lead_sh - back_sh
    shoulder_tilt = np.degrees(np.arctan2(sh_line[:, 1], np.linalg.norm(horizontal(sh_line), axis=-1)))

    stance_w = np.linalg.norm(horizontal(lead_ankle[0] - back_ankle[0]))
    stride_w = np.linalg.norm(horizontal(lead_ankle[foot_down] - back_ankle[foot_down]))
    head_move = np.linalg.norm(nose[contact] - nose[load])
    head_drop = nose[load, 1] - nose[contact, 1]

    metrics = {
        "stance_width_pct_height": rnd(100 * stance_w / H),
        "stride_length_pct_height": rnd(100 * stride_w / H),
        "stride_gain_pct_height": rnd(100 * (stride_w - stance_w) / H),
        "hip_shoulder_separation_fd_deg": rnd(separation[foot_down]),
        "max_hip_shoulder_separation_deg": rnd(np.nanmax(separation[load:contact + 1])),
        "pelvis_rotation_at_fd_deg": rnd(pelvis_rot[foot_down]),
        "pelvis_rotation_at_contact_deg": rnd(pelvis_rot[contact]),
        "lead_knee_flexion_fd_deg": rnd(lead_knee_flex[foot_down]),
        "lead_knee_flexion_contact_deg": rnd(lead_knee_flex[contact]),
        "lead_knee_extension_deg": rnd(lead_knee_flex[foot_down] - lead_knee_flex[contact]),
        "back_elbow_flexion_fd_deg": rnd(back_elbow_flex[foot_down]),
        "spine_tilt_contact_deg": rnd(spine_tilt[contact]),
        "shoulder_tilt_contact_deg": rnd(shoulder_tilt[contact]),
        "head_movement_pct_height": rnd(100 * head_move / H),
        "head_drop_pct_height": rnd(100 * head_drop / H),
        "peak_pelvis_velocity_dps": rnd(pelvis_vel[pelvis_peak], 0),
        "peak_trunk_velocity_dps": rnd(trunk_vel[trunk_peak], 0),
        "peak_hand_speed_mps": rnd(hand_speed[contact] * to_m, 2),
        "trunk_after_pelvis_ms": rnd(1000 * (trunk_peak - pelvis_peak) / fps, 0),
        "proper_sequence": bool(pelvis_peak <= trunk_peak <= contact),
        "fd_to_contact_ms": rnd(1000 * (contact - foot_down) / fps, 0),
        "load_to_contact_ms": rnd(1000 * (contact - load) / fps, 0),
    }
    phases = {"load": load, "stride_lift": stride_lift, "foot_down": foot_down, "contact": contact, "finish": finish}
    return MotionResult(
        motion_type="hitting",
        phases=phases,
        phase_times_s={k: round(v / fps, 3) for k, v in phases.items()},
        metrics=metrics,
        warnings=warnings,
    )
