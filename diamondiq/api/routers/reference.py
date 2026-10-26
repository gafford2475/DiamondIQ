from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from ...biomechanics.feedback import HITTING, PITCHING
from ...levels import all_levels
from ...projection.simulate import OUTCOME_TIERS

router = APIRouter(tags=["reference"])


@router.get("/levels")
def levels():
    return [
        {"code": lv.code, "name": lv.name, "category": lv.category.value, "talent_mean": lv.talent_mean, "talent_sd": lv.talent_sd,
         "typical_age": lv.typical_age, "aliases": lv.aliases, "hitting_baseline": asdict(lv.hitting), "pitching_baseline": asdict(lv.pitching)}
        for lv in sorted(all_levels(), key=lambda x: x.talent_mean)
    ]


@router.get("/biomechanics/references")
def biomechanics_references():
    def dump(refs):
        return {k: {"label": r.label, "unit": r.unit, "optimal": r.optimal, "by_level_band": r.band_optimal, "why": r.why} for k, r in refs.items()}

    return {"pitching": dump(PITCHING), "hitting": dump(HITTING)}


@router.get("/projections/outcome-tiers")
def outcome_tiers():
    return [{"min_talent": c if c > -1e8 else None, "tier": t} for c, t in OUTCOME_TIERS]
