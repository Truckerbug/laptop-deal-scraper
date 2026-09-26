"""
Extracts rough hardware specs from an eBay listing title (and short
description, when available). Titles are noisy and inconsistent, so this
is deliberately best-effort — it feeds the scorer, not a source of truth.
"""

import re
from dataclasses import dataclass

from src import config


@dataclass
class ParsedSpecs:
    ram_gb: int | None
    gpu: str | None
    gpu_tier: str | None
    dual_storage: bool
    model_hit: str | None
    cpu: str | None
    brand: str | None
    storage_gb: int | None
    excluded: bool


_RAM_RE = re.compile(r"(\d{2,3})\s?GB\s?(RAM|Memory)?", re.IGNORECASE)
_DUAL_STORAGE_RE = re.compile(
    r"(dual\s?(m\.?2|nvme|ssd)|2\s?x\s?\d+\s?GB|2x\s?nvme)", re.IGNORECASE
)
_CPU_RE = re.compile(
    r"(Core\s?i[3579][\s-]?\d{4,5}[A-Z]{0,2}|i[3579][\s-]\d{4,5}[A-Z]{0,2}"
    r"|Xeon\s?[EW]-?\d{3,5}[A-Z]{0,2}"
    r"|Ryzen\s?[3579]\s?\d{3,4}[A-Z]{0,2}|Ryzen\s?[3579]"
    r"|Core\s?i[3579]|\bi[3579]\b|Xeon"
    r"|Apple\s?M[123]\s?(Pro|Max|Ultra)?)",
    re.IGNORECASE,
)
_STORAGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s?(TB|GB)\s?(SSD|NVMe|HDD|Storage)?", re.IGNORECASE
)
# Generic fallback: any RTX/GTX/Quadro/MX + model number not covered by the
# explicit GPU_TIERS lists in config.py still gets flagged (as "gpu_other")
# instead of scoring as if there's no GPU at all — keeps new/unlisted models
# from being penalized just because they're not in the hand-maintained list.
_GPU_FALLBACK_RE = re.compile(
    r"(RTX\s?A?\d{3,5}(\s?TI)?|GTX\s?\d{3,4}(\s?TI)?|QUADRO\s?\w*\s?\d{3,4}|MX\s?\d{3,4})",
    re.IGNORECASE,
)
_GPU_GENERIC_MENTION_RE = re.compile(r"\b(NVIDIA|QUADRO|GEFORCE|RTX)\b", re.IGNORECASE)


def _find_ram(text: str) -> int | None:
    """Pick the largest plausible RAM figure mentioned (8-128GB range),
    since titles often also mention storage size in GB."""
    candidates = []
    for match in _RAM_RE.finditer(text):
        val = int(match.group(1))
        if 4 <= val <= 128:
            # Bias toward matches explicitly followed by RAM/Memory
            weight = 1000 if match.group(2) else val
            candidates.append((weight, val))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _find_gpu(text: str) -> tuple[str | None, str | None, int]:
    upper = text.upper()
    best_tier, best_points, best_model = None, 0, None
    for tier, (points, models) in config.GPU_TIERS.items():
        for model in models:
            if re.search(rf"\b{re.escape(model)}\b", upper):
                if points > best_points:
                    best_tier, best_points, best_model = tier, points, model
    if best_model is None:
        # nothing in the explicit lists matched — try the generic fallback
        # so unlisted/newer GPU models still register as *something*.
        match = _GPU_FALLBACK_RE.search(upper)
        if match:
            best_model = re.sub(r"\s+", " ", match.group(1)).strip()
            best_tier = "gpu_other"
            best_points = config.GPU_OTHER_POINTS
        elif _GPU_GENERIC_MENTION_RE.search(upper):
            # brand mentioned but no model number at all — still a dGPU,
            # just an unknown one. Small credit rather than none.
            best_model = "dGPU (unspecified)"
            best_tier = "gpu_generic"
            best_points = config.GPU_GENERIC_MENTION_POINTS
    return best_model, best_tier, best_points


def _find_model_bonus(text: str) -> str | None:
    upper = text.upper()
    for model in config.WORKSTATION_MODEL_BONUS:
        if model in upper:
            return model
    return None


def _is_excluded(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in config.EXCLUDE_TERMS)


def _find_cpu(text: str) -> str | None:
    match = _CPU_RE.search(text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _find_brand(text: str) -> str | None:
    upper = text.upper()
    for brand, keywords in config.BRAND_KEYWORDS:
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", upper):
                return brand
    return None


def _find_storage(text: str) -> int | None:
    """Largest storage figure mentioned, normalized to GB (TB -> *1024).
    Bare TB values always count (laptops don't ship TB of RAM, so it's
    unambiguous even without an SSD/NVMe/HDD keyword). Bare GB values count
    if paired with a storage keyword, OR if the number is over 128 — modern
    laptop RAM essentially never exceeds 128GB, so a bare ">128GB" mention
    is safe to treat as storage even without a keyword nearby."""
    best = None
    for match in _STORAGE_RE.finditer(text):
        val, unit, keyword = match.group(1), match.group(2).upper(), match.group(3)
        if unit == "GB" and not keyword and float(val) <= 128:
            continue  # ambiguous with RAM — skip
        gb = float(val) * 1024 if unit == "TB" else float(val)
        gb = int(gb)
        if best is None or gb > best:
            best = gb
    return best


def parse(title: str, extra_text: str = "") -> ParsedSpecs:
    full_text = f"{title} {extra_text}"
    gpu_model, gpu_tier, _ = _find_gpu(full_text)
    return ParsedSpecs(
        ram_gb=_find_ram(full_text),
        gpu=gpu_model,
        gpu_tier=gpu_tier,
        dual_storage=bool(_DUAL_STORAGE_RE.search(full_text)),
        model_hit=_find_model_bonus(full_text),
        cpu=_find_cpu(full_text),
        brand=_find_brand(full_text),
        storage_gb=_find_storage(full_text),
        excluded=_is_excluded(full_text),
    )


_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_MAP = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'", "&#8217;": "'", "&rsquo;": "'",
}


def strip_html(html_text: str | None) -> str:
    """Best-effort HTML -> plain text for eBay's item description field
    (which is raw seller HTML, often template-heavy)."""
    if not html_text:
        return ""
    text = _TAG_RE.sub(" ", html_text)
    for entity, replacement in _ENTITY_MAP.items():
        text = text.replace(entity, replacement)
    return re.sub(r"\s+", " ", text).strip()


def flatten_aspects(aspects: list[dict] | None) -> str:
    """eBay's "item specifics" (localizedAspects from the getItem response)
    are structured seller-filled fields — e.g. {"name": "RAM Size", "value":
    "32 GB"}. Field names aren't standardized across sellers, so rather than
    map each one explicitly, flatten them into "name: value" text and let
    the existing regex parsing pick up whatever it recognizes. Structured
    data is far more reliable than title text, so this is worth doing even
    though it's a blunt approach."""
    if not aspects:
        return ""
    parts = []
    for aspect in aspects:
        name = aspect.get("name", "")
        value = aspect.get("value", "")
        if isinstance(value, list):
            value = " ".join(str(v) for v in value)
        parts.append(f"{name}: {value}")
    return "; ".join(parts)