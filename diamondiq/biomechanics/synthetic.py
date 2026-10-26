"""Procedurally generated pitching and hitting motions.

Used for tests, demos, and validating the analysis code against known inputs
(the generator's parameters are the "ground truth"). Not a physics model.
"""

from __future__ import annotations

import numpy as np

from .keypoints import INDEX, LANDMARKS, PoseSequence

THIGH, SHIN, UPPER_ARM, FOREARM, TORSO = 0.45, 0.44, 0.30, 0.28, 0.52
HIP_HALF, SH_HALF = 0.17, 0.21


def _s(t, t0, t1):
    """Smoothstep from 0 at t0 to 1 at t1."""
    x = np.clip((t - t0) / (t1 - t0), 0, 1)
    return x * x * (3 - 2 * x)


def _knee(hip, ankle, bend_dir):
    """Two-link IK: knee position given hip, ankle and preferred bend direction."""
    d = ankle - hip
    L = np.linalg.norm(d)
    L = min(L, THIGH + SHIN - 1e-3)
    a = (THIGH**2 - SHIN**2 + L**2) / (2 * L)
    h = np.sqrt(max(THIGH**2 - a**2, 0))
    u = d / (np.linalg.norm(d) + 1e-9)
    perp = bend_dir - (bend_dir @ u) * u
    perp /= np.linalg.norm(perp) + 1e-9
    return hip + a * u + h * perp


def _knee_at_flexion(hip, ankle, flex_deg, bend_dir):
    """Knee placed so hip-knee-ankle shows ``flex_deg`` of flexion (segment lengths flex to fit)."""
    d = ankle - hip
    L = np.linalg.norm(d)
    half = np.radians(180 - flex_deg) / 2
    seg = L / (2 * np.sin(half))
    h = np.sqrt(max(seg**2 - (L / 2) ** 2, 0))
    u = d / (L + 1e-9)
    perp = bend_dir - (bend_dir @ u) * u
    perp /= np.linalg.norm(perp) + 1e-9
    return hip + d / 2 + h * perp


def _yaw_vec(theta_deg, forward, lateral):
    th = np.radians(theta_deg)
    return np.cos(th) * forward + np.sin(th) * lateral


def synthetic_pitch(fps: float = 240, throws: str = "R", stride_pct: float = 0.88, separation_deg: float = 45,
                    knee_brace_deg: float = 15, height_m: float = 1.88, noise: float = 0.0, seed: int = 0) -> PoseSequence:
    """A delivery toward +x. Timeline (s): lift peak 0.45, foot plant 0.75, release ~0.90."""
    rng = np.random.default_rng(seed)
    T = int(1.2 * fps)
    t = np.arange(T) / fps
    s = height_m / 1.88
    fwd = np.array([1.0, 0, 0])
    lat = np.array([0, 0, 1.0])  # arm side for this generator
    up = np.array([0, 1.0, 0])
    arm, glove = ("right", "left") if throws.upper().startswith("R") else ("left", "right")
    if arm == "left":
        lat = -lat

    fp, rel = 0.75, 0.90
    pts = np.full((T, len(LANDMARKS), 3), np.nan)
    back_ankle = np.array([0, 0.08, 0.0]) * s
    stride = stride_pct * height_m
    for i, ti in enumerate(t):
        lift = _s(ti, 0.15, 0.45) - _s(ti, 0.45, fp)
        travel = _s(ti, 0.40, fp)
        lead_ankle = back_ankle + fwd * (0.25 * s + (stride - 0.25 * s) * travel) + up * (0.35 * s * max(lift, 0)) + lat * 0.0
        pelvis_x = 0.12 * s + 0.45 * stride * _s(ti, 0.40, fp) + 0.12 * _s(ti, fp, rel + 0.1)
        drop = 0.10 * s * _s(ti, 0.40, fp)
        pelvis = np.array([pelvis_x, 0.98 * s - drop, 0])
        # Rotations (deg, 0 = closed, line pointing at target). Pelvis peaks before trunk.
        amp = 2 * (separation_deg + 5)
        pelvis_rot = 10 + amp * _s(ti, 0.68, 0.82)
        trunk_rot = 15 + (amp - 5) * _s(ti, fp, 0.87)
        hip_line = _yaw_vec(pelvis_rot, fwd, -lat)
        lead_hip = pelvis + HIP_HALF * s * hip_line
        back_hip = pelvis - HIP_HALF * s * hip_line
        tilt = np.radians(35 * _s(ti, fp - 0.08, rel - 0.04))
        lat_tilt = np.radians(20 * _s(ti, fp - 0.05, rel - 0.04))
        torso_dir = np.cos(tilt) * np.cos(lat_tilt) * up + np.sin(tilt) * fwd - np.sin(lat_tilt) * lat
        sh_mid = pelvis + TORSO * s * torso_dir
        sh_line = _yaw_vec(trunk_rot, fwd, -lat)
        glove_sh = sh_mid + SH_HALF * s * sh_line
        throw_sh = sh_mid - SH_HALF * s * sh_line
        # Throwing arm: hand breaks from the glove, cocks back by foot plant, then
        # whips forward with speed peaking at release (ease-in), then follows through.
        if ti < 0.40:
            beta, cu = 180.0, -0.2
        elif ti < fp:
            x = _s(ti, 0.40, fp)
            beta, cu = 180 + 165 * x, -0.2 - 0.3 * x
        elif ti < rel:
            x = (ti - fp) / (rel - fp)
            beta, cu = 345 + 115 * x * x, -0.5 + 1.3 * x * x
        else:
            y = min((ti - rel) / 0.25, 1.0)
            beta, cu = 460 + 80 * (1 - (1 - y) ** 2), 0.8
        upper = lat + cu * fwd + 0.1 * up
        upper /= np.linalg.norm(upper)
        elbow = throw_sh + UPPER_ARM * s * upper
        b = np.radians(beta)
        wrist = elbow + FOREARM * s * (np.cos(b) * up + np.sin(b) * fwd)
        g_elbow = glove_sh + UPPER_ARM * s * (0.8 * fwd - 0.4 * up) / np.linalg.norm(0.8 * fwd - 0.4 * up)
        g_wrist = g_elbow + FOREARM * s * np.array([0.3, -0.9, 0]) / np.linalg.norm([0.3, -0.9, 0])
        # Lead knee: bent at plant then braces (extends) through release.
        lead_ankle_eff = lead_ankle.copy()
        lead_knee = _knee(lead_hip, lead_ankle_eff, fwd + 0.3 * up)
        if ti >= 0.62:
            target_flex = 20 + 25 * _s(ti, 0.62, fp - 0.03) - knee_brace_deg * _s(ti, fp, rel - 0.04)
            lead_knee = _knee_at_flexion(lead_hip, lead_ankle_eff, target_flex, fwd + 0.3 * up)
        back_knee = _knee(back_hip, back_ankle, fwd + 0.2 * up)
        head = sh_mid + 0.25 * s * torso_dir + 0.05 * s * fwd

        j = {}
        j["nose"] = head
        j[f"{arm}_shoulder"], j[f"{glove}_shoulder"] = throw_sh, glove_sh
        j[f"{arm}_elbow"], j[f"{glove}_elbow"] = elbow, g_elbow
        j[f"{arm}_wrist"], j[f"{glove}_wrist"] = wrist, g_wrist
        j[f"{glove}_hip"], j[f"{arm}_hip"] = lead_hip, back_hip
        j[f"{glove}_knee"], j[f"{arm}_knee"] = lead_knee, back_knee
        j[f"{glove}_ankle"], j[f"{arm}_ankle"] = lead_ankle_eff, back_ankle
        _fill(pts[i], j)
    if noise:
        pts += rng.normal(0, noise, pts.shape)
    return PoseSequence(pts, fps, source="synthetic")


def synthetic_swing(fps: float = 240, bats: str = "R", stride_gain_pct: float = 0.14, separation_deg: float = 25,
                    head_move_pct: float = 0.03, height_m: float = 1.85, noise: float = 0.0, seed: int = 0) -> PoseSequence:
    """A swing with the pitcher toward +x. Load 0.35 s, foot down 0.6 s, contact ~0.78 s."""
    rng = np.random.default_rng(seed)
    T = int(1.1 * fps)
    t = np.arange(T) / fps
    s = height_m / 1.85
    fwd, up = np.array([1.0, 0, 0]), np.array([0, 1.0, 0])
    lat = np.array([0, 0, 1.0])  # toward the plate for this generator
    back, lead = ("right", "left") if bats.upper().startswith("R") else ("left", "right")
    if back == "left":
        lat = -lat
    fd, contact = 0.60, 0.78
    stance = 0.42 * height_m
    pts = np.full((T, len(LANDMARKS), 3), np.nan)
    back_ankle = np.array([0, 0.08, 0.0]) * s
    for i, ti in enumerate(t):
        lift = _s(ti, 0.35, 0.48) - _s(ti, 0.48, fd)
        lead_ankle = back_ankle + fwd * (stance + stride_gain_pct * height_m * _s(ti, 0.35, fd)) + up * 0.08 * s * max(lift, 0)
        load_back = -0.06 * s * (_s(ti, 0.1, 0.35) - _s(ti, 0.35, fd))
        pelvis = np.array([0.45 * stance + load_back + 0.06 * s * _s(ti, 0.35, fd), 0.92 * s, 0])
        pelvis_rot = 5 + (separation_deg + 5) * _s(ti, 0.52, fd + 0.02) + 55 * _s(ti, fd + 0.02, contact)
        trunk_rot = max(0.0, -5 * _s(ti, 0.2, 0.4) + (pelvis_rot - separation_deg - 5) * _s(ti, fd, contact) * 1.3)
        hip_line = _yaw_vec(pelvis_rot, fwd, lat)
        lead_hip, back_hip = pelvis + HIP_HALF * s * hip_line, pelvis - HIP_HALF * s * hip_line
        bend = np.radians(28)
        side = np.radians(25 * _s(ti, fd, contact))
        torso_dir = np.cos(bend) * up + np.sin(bend) * lat * 0.8 - np.sin(side) * fwd * 0.5
        torso_dir /= np.linalg.norm(torso_dir)
        sh_mid = pelvis + TORSO * s * torso_dir
        sh_line = _yaw_vec(trunk_rot, fwd, lat)
        tilt_up = np.radians(25 * _s(ti, fd, contact))
        sh_line = np.cos(tilt_up) * sh_line + np.sin(tilt_up) * up
        lead_sh, back_sh = sh_mid + SH_HALF * s * sh_line, sh_mid - SH_HALF * s * sh_line
        # Hands: travel back during load, then accelerate through contact.
        hand_phase = _s(ti, fd - 0.05, contact)
        hands = back_sh + np.array([-0.12, 0.02, 0.15]) * s + fwd * 0.75 * s * hand_phase**2 + lat * 0.25 * s * hand_phase
        hands = hands + fwd * load_back
        back_elbow = back_sh + (hands - back_sh) * 0.5 - up * 0.18 * s
        lead_elbow = lead_sh + (hands - lead_sh) * 0.5 - up * 0.12 * s
        knee_flex = 35 - 20 * _s(ti, fd, contact)
        lead_hip_eff = lead_hip
        lead_knee = _knee_at_flexion(lead_hip, lead_ankle, knee_flex, fwd * 0.3 + lat + 0.3 * up)
        back_knee = _knee(back_hip, back_ankle, lat + 0.3 * up)
        head = sh_mid + 0.25 * s * torso_dir + fwd * head_move_pct * height_m * _s(ti, 0.35, contact)
        j = {
            "nose": head,
            f"{lead}_shoulder": lead_sh, f"{back}_shoulder": back_sh,
            f"{lead}_elbow": lead_elbow, f"{back}_elbow": back_elbow,
            f"{lead}_wrist": hands + 0.03 * fwd, f"{back}_wrist": hands - 0.03 * fwd,
            f"{lead}_hip": lead_hip_eff, f"{back}_hip": back_hip,
            f"{lead}_knee": lead_knee, f"{back}_knee": back_knee,
            f"{lead}_ankle": lead_ankle, f"{back}_ankle": back_ankle,
        }
        _fill(pts[i], j)
    if noise:
        pts += rng.normal(0, noise, pts.shape)
    return PoseSequence(pts, fps, source="synthetic")


def _fill(frame: np.ndarray, joints: dict[str, np.ndarray]) -> None:
    for name, p in joints.items():
        frame[INDEX[name]] = p
    # Derive face/feet/hand landmarks from the main joints so every landmark is populated.
    nose = joints["nose"]
    for n in ("left_eye_inner", "left_eye", "left_eye_outer", "right_eye_inner", "right_eye", "right_eye_outer",
              "left_ear", "right_ear", "mouth_left", "mouth_right"):
        frame[INDEX[n]] = nose
    for side in ("left", "right"):
        w = frame[INDEX[f"{side}_wrist"]]
        for n in ("pinky", "index", "thumb"):
            frame[INDEX[f"{side}_{n}"]] = w
        a = frame[INDEX[f"{side}_ankle"]]
        frame[INDEX[f"{side}_heel"]] = a + np.array([-0.05, -0.05, 0])
        frame[INDEX[f"{side}_foot_index"]] = a + np.array([0.15, -0.06, 0])
