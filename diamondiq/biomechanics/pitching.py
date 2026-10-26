"""Pitching delivery analysis from a pose sequence.

Phases detected: leg lift (peak lead knee height), foot plant, ball release
(peak throwing-hand speed) and finish. Metrics follow the vocabulary used in
pitching biomechanics research (stride length as % of height, hip-shoulder
separation, lead-leg block, trunk tilt, arm slot, kinematic sequence).

Single-camera markerless pose cannot measure shoulder external rotation or
joint torques directly; those are left to lab systems and can be imported
as metrics alongside these.
"""

from __future__ import annotations

import numpy as np

from .common import MotionResult, fps_warnings, landing_frame, lateral_axis, other, rnd, scale_factor
from .keypoints import PoseSequence
from .kinematics import UP, derivative, flexion, horizontal, joint_angle, peak_index, segment_rotation, speed, tilt_components, unit


def analyze_pitching(seq: PoseSequence, throws: str = "R", height_m: float | None = None) -> MotionResult:
    seq = seq.cleaned()
    fps = seq.fps
    warnings = fps_warnings(fps)
    arm = "right" if throws.upper().startswith("R") else "left"
    glove = other(arm)
    H, to_m = scale_factor(seq, height_m)

    lead_ankle, back_ankle = seq.side(glove, "ankle"), seq.side(arm, "ankle")
    lead_knee, lead_hip = seq.side(glove, "knee"), seq.side(glove, "hip")
    back_hip = seq.side(arm, "hip")
    t_sh, g_sh = seq.side(arm, "shoulder"), seq.side(glove, "shoulder")
    elbow, wrist = seq.side(arm, "elbow"), seq.side(arm, "wrist")
    hip_mid, sh_mid = seq.mid("left_hip", "right_hip"), seq.mid("left_shoulder", "right_shoulder")
    nose = seq.joint("nose")

    # --- phases ---------------------------------------------------------
    wrist_speed = speed(wrist, fps)
    release = peak_index(wrist_speed, int(0.2 * seq.n_frames))
    leg_lift = peak_index(lead_knee[:, 1] - hip_mid[:, 1], 0, max(release - 1, 1))
    foot_plant = landing_frame(lead_ankle, fps, leg_lift, release, H)
    if not leg_lift < foot_plant <= release:
        warnings.append("Could not order leg lift / foot plant / release cleanly; check camera angle and that the full delivery is in frame.")
        foot_plant = min(max(foot_plant, leg_lift + 1), release)
    finish = min(seq.n_frames - 1, release + int(0.25 * fps))

    forward = unit(horizontal(lead_ankle[foot_plant] - back_ankle[foot_plant]))
    arm_side = lateral_axis(forward, t_sh[release], g_sh[release])

    # --- rotation and sequencing ---------------------------------------
    pelvis_rot = segment_rotation(back_hip, lead_hip, forward, (0, release))
    trunk_rot = segment_rotation(t_sh, g_sh, forward, (0, release))
    separation = pelvis_rot - trunk_rot
    pelvis_vel = derivative(pelvis_rot, fps)
    trunk_vel = derivative(trunk_rot, fps)
    win = (leg_lift, finish)
    pelvis_peak = peak_index(pelvis_vel, *win)
    trunk_peak = peak_index(trunk_vel, *win)
    hand_peak = release

    # --- posture --------------------------------------------------------
    fwd_tilt, lat_tilt = tilt_components(hip_mid, sh_mid, forward)
    # tilt_components' lateral is signed to the right of forward; make positive = toward glove side.
    right_of_fwd = np.cross(forward, UP)
    glove_sign = -1.0 if arm_side @ right_of_fwd > 0 else 1.0
    lat_tilt = lat_tilt * glove_sign

    lead_knee_flex = flexion(lead_hip, lead_knee, lead_ankle)
    elbow_flex = flexion(t_sh, elbow, wrist)
    abduction = joint_angle(hip_mid, t_sh, elbow)

    arm_vec = wrist[release] - t_sh[release]
    arm_slot = np.degrees(np.arctan2(arm_vec @ UP, arm_vec @ arm_side))

    stride_vec = horizontal(lead_ankle[foot_plant] - back_ankle[foot_plant])
    stride = np.linalg.norm(stride_vec)
    # Lateral landing offset relative to the line from the rubber toward the plate (start-of-motion direction).
    start_dir = unit(horizontal(lead_ankle[foot_plant] - back_ankle[0]))
    offset = (horizontal(lead_ankle[foot_plant] - back_ankle[0]) @ arm_side) if np.linalg.norm(start_dir) else 0.0

    head_drift = (horizontal(nose[release] - nose[foot_plant]) @ (-arm_side)) / H

    metrics = {
        "stride_length_pct_height": rnd(100 * stride / H),
        "stride_offset_pct_height": rnd(100 * offset / H),  # + = closed (toward arm side)
        "lead_knee_lift_pct_height": rnd(100 * (lead_knee[leg_lift, 1] - lead_ankle[foot_plant, 1]) / H),
        "hip_shoulder_separation_fp_deg": rnd(separation[foot_plant]),
        "max_hip_shoulder_separation_deg": rnd(np.nanmax(separation[leg_lift:release + 1])),
        "trunk_rotation_at_fp_deg": rnd(trunk_rot[foot_plant]),
        "pelvis_rotation_at_fp_deg": rnd(pelvis_rot[foot_plant]),
        "lead_knee_flexion_fp_deg": rnd(lead_knee_flex[foot_plant]),
        "lead_knee_flexion_release_deg": rnd(lead_knee_flex[release]),
        "lead_knee_extension_deg": rnd(lead_knee_flex[foot_plant] - lead_knee_flex[release]),
        "shoulder_abduction_fp_deg": rnd(abduction[foot_plant]),
        "elbow_flexion_fp_deg": rnd(elbow_flex[foot_plant]),
        "elbow_height_fp_pct_height": rnd(100 * (elbow[foot_plant, 1] - t_sh[foot_plant, 1]) / H),
        "trunk_forward_tilt_release_deg": rnd(fwd_tilt[release]),
        "trunk_lateral_tilt_release_deg": rnd(lat_tilt[release]),
        "arm_slot_deg": rnd(arm_slot),
        "head_drift_glove_side_pct_height": rnd(100 * head_drift),
        "peak_pelvis_velocity_dps": rnd(pelvis_vel[pelvis_peak], 0),
        "peak_trunk_velocity_dps": rnd(trunk_vel[trunk_peak], 0),
        "peak_hand_speed_mps": rnd(wrist_speed[hand_peak] * to_m, 2),
        "pelvis_peak_ms_from_fp": rnd(1000 * (pelvis_peak - foot_plant) / fps, 0),
        "trunk_peak_ms_from_fp": rnd(1000 * (trunk_peak - foot_plant) / fps, 0),
        "trunk_after_pelvis_ms": rnd(1000 * (trunk_peak - pelvis_peak) / fps, 0),
        "proper_sequence": bool(pelvis_peak <= trunk_peak <= hand_peak),
        "fp_to_release_ms": rnd(1000 * (release - foot_plant) / fps, 0),
        "arm_slot_label": _slot_label(arm_slot),
    }
    phases = {"leg_lift": leg_lift, "foot_plant": foot_plant, "ball_release": release, "finish": finish}
    return MotionResult(
        motion_type="pitching",
        phases=phases,
        phase_times_s={k: round(v / fps, 3) for k, v in phases.items()},
        metrics=metrics,
        warnings=warnings,
    )


def _slot_label(deg: float) -> str:
    if deg >= 70:
        return "over the top"
    if deg >= 45:
        return "high three-quarters"
    if deg >= 25:
        return "three-quarters"
    if deg >= 5:
        return "low three-quarters / sidearm"
    return "submarine"
