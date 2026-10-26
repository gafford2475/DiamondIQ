"""Tracking-device integrations: adapter registry and format auto-detection."""

from __future__ import annotations

from .base import Adapter, NormalizedEvent, read_rows
from .blast import BlastAdapter
from .generic import GenericAdapter
from .hittrax import HitTraxAdapter
from .rapsodo import RapsodoHittingAdapter, RapsodoPitchingAdapter
from .statcast import StatcastAdapter
from .trackman import TrackmanAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    a.name: a
    for a in (TrackmanAdapter, RapsodoPitchingAdapter, RapsodoHittingAdapter, HitTraxAdapter, StatcastAdapter, BlastAdapter, GenericAdapter)
}
ALIASES = {"statcast": "hawkeye", "savant": "hawkeye", "yakkertech": "trackman", "flightscope": "trackman", "diamond_kinetics": "blast", "rapsodo": "rapsodo_pitching"}


def get_adapter(name: str) -> Adapter:
    key = name.strip().lower()
    key = ALIASES.get(key, key)
    if key not in ADAPTERS:
        raise KeyError(f"No adapter '{name}'. Available: {sorted(ADAPTERS)}")
    return ADAPTERS[key]()


def detect_source(content: bytes | str) -> str | None:
    best, best_score = None, 0.0
    for name, cls in ADAPTERS.items():
        if not cls.signature:
            continue
        rows = read_rows(content, cls.header_hints)
        if not rows:
            continue
        score = cls.matches(list(rows[0].keys()))
        if score > best_score:
            best, best_score = name, score
    return best if best_score >= 0.5 else None


__all__ = ["ADAPTERS", "Adapter", "NormalizedEvent", "detect_source", "get_adapter"]
