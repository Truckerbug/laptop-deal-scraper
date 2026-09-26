"""
Turns (price, ParsedSpecs) into a 0-100 "how good is this deal" score.

Weighting, roughly:
  - Price fit vs target budget   : 30 pts
  - GPU tier                     : up to 25 pts
  - RAM                          : 20 pts
  - Storage                      : 10 pts
  - Workstation-grade chassis    : 10 pts
  - Dual storage mention         : 5 pts
"""

from src import config
from src.parser import ParsedSpecs

GPU_POINTS = {tier: pts for tier, (pts, _) in config.GPU_TIERS.items()}
GPU_POINTS["gpu_other"] = config.GPU_OTHER_POINTS
GPU_POINTS["gpu_generic"] = config.GPU_GENERIC_MENTION_POINTS
MAX_GPU_POINTS = max(GPU_POINTS.values())


def _price_score(price: float) -> float:
    target = config.SPEC_TARGETS["target_price"]
    max_price = config.SPEC_TARGETS["max_price"]
    if price <= 0:
        return 0.0
    if price <= target:
        # At or under target: full marks, tiny bonus for being well under
        return 30.0
    if price >= max_price:
        return 0.0
    # Linearly taper from 30 -> 0 between target and max_price
    span = max_price - target
    return 30.0 * (1 - (price - target) / span)


def _ram_score(ram_gb: int | None) -> float:
    if ram_gb is None:
        return 5.0  # unknown — small default so it's not zeroed out unfairly
    target = config.SPEC_TARGETS["target_ram_gb"]
    floor = config.SPEC_TARGETS["min_ram_gb"]
    if ram_gb >= target:
        return 20.0
    if ram_gb < floor:
        return 0.0
    return 20.0 * (ram_gb - floor) / (target - floor)

def storage_score(storage_gb: int | None) -> float:
    # I feel like we should refactor this so that the more storage, the better.
    # For now, just give a score based on how close to the target it is.
    if storage_gb is None:
        return 5.0  # unknown — small default so it's not zeroed out unfairly
    target = config.SPEC_TARGETS["target_storage_gb"]
    floor = config.SPEC_TARGETS["min_storage_gb"]
    if storage_gb >= target:
        return 10.0
    if storage_gb < floor:
        return 0.0
    return 10.0 * (storage_gb - floor) / (target - floor)


def _gpu_score(specs: ParsedSpecs) -> float:
    if not specs.gpu_tier:
        return 0.0
    points = GPU_POINTS.get(specs.gpu_tier, 0)
    return 25.0 * (points / MAX_GPU_POINTS)


def _model_score(specs: ParsedSpecs) -> float:
    return 10.0 if specs.model_hit else 0.0

def _dual_storage_score(specs: ParsedSpecs) -> float:
    return 5.0 if specs.dual_storage else 0.0



def score_listing(price: float, specs: ParsedSpecs) -> int:
    if specs.excluded:
        return 0
    total = (
        _price_score(price)
        + _ram_score(specs.ram_gb)
        + storage_score(specs.storage_gb)
        + _gpu_score(specs)
        + _model_score(specs)
        + _dual_storage_score(specs)
    )
    return round(min(100, max(0, total)))
    # return int(total)