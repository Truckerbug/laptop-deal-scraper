"""
Central config for the laptop deal scraper.
Edit SEARCH_QUERIES / SPEC_TARGETS to tune what counts as a "good" deal.
"""

import os
from pathlib import Path

# --- Paths ---------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "listings.db"
DASHBOARD_PATH = DATA_DIR / "dashboard.html"
TOKEN_CACHE_PATH = DATA_DIR / "token_cache.json"
LOG_PATH = DATA_DIR / "run.log"

DATA_DIR.mkdir(exist_ok=True)

# --- eBay API credentials (set these as env vars, don't hardcode) -------
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")
EBAY_MARKETPLACE = "EBAY_US"
EBAY_ENV = os.environ.get("EBAY_ENV", "production")  # or "sandbox"

if EBAY_ENV == "sandbox":
    EBAY_AUTH_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    EBAY_SEARCH_URL = "https://api.sandbox.ebay.com/buy/browse/v1/item_summary/search"
    EBAY_ITEM_URL = "https://api.sandbox.ebay.com/buy/browse/v1/item"
else:
    EBAY_AUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
    EBAY_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
    EBAY_ITEM_URL = "https://api.ebay.com/buy/browse/v1/item"

EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"

# --- What to search for ---------------------------------------------------
# Broad laptop deal-hunting: workstation / gaming laptops likely to have a
# capable NVIDIA GPU + high RAM. Add/remove queries freely.
SEARCH_QUERIES = [
    "ThinkPad P1",
    "ThinkPad P15",
    "ThinkPad P16",
    "ThinkPad X1 Extreme",
    "Dell Precision 5000",
    "Dell Precision 7000",
    "HP ZBook Studio",
    "HP ZBook Fury",
    "Lenovo Legion 5 Pro",
    "Lenovo Legion 7",
    "ASUS ROG Zephyrus",
    "ASUS ROG Strix",
    "MSI Creator",
    "MSI Titan",
    "Razer Blade 15",
]

# Category ID for "PC Laptops & Netbooks" on eBay US, used to keep results
# from wandering into laptop parts/accessories.
CATEGORY_ID = "177"

# Price window (USD). Kept a bit wider than the $900-1000 target budget so
# genuinely great deals just outside it still surface.
MIN_PRICE = 250
MAX_PRICE = 1500

# --- Scoring targets -------------------------------------------------------
# These describe Spencer's ideal machine; scorer.py weighs listings against
# them. Tune freely as priorities shift.
SPEC_TARGETS = {
    "target_price": 950,      # sweet spot within the $900-1000 budget
    "max_price": MAX_PRICE,
    "min_ram_gb": 16,          # partial credit floor
    "target_ram_gb": 32,       # full credit
    "min_storage_gb": 500,     # partial credit floor
    "target_storage_gb": 1000, # full credit
    "max_storage_gb": 2000,    # cap for scoring purposes (more than this doesn't help)
    "min_score_to_alert": 60,  # 0-100 scale; below this, don't surface it
}

# NVIDIA GPUs worth caring about, roughly ordered by desirability.
# Workstation (RTX A-series / Quadro) and higher-end gaming GPUs score best.
# Bare numeric forms (e.g. "T2000" without the word "Quadro") are included
# since eBay sellers frequently drop the "Quadro"/"NVIDIA" prefix.
GPU_TIERS = {
    "workstation_high": (25, [
        "RTX A5000", "RTX A4500", "RTX A4000",
        "QUADRO RTX 5000", "QUADRO RTX 4000",
        "QUADRO P5000",
        "A5000", "A4500", "A4000", "P5000",  # bare forms
        "RTX 5000", "RTX 4000",  # HP's naming for RTX A5000/A4000-class GPUs
    ]),
    "workstation_mid": (20, [
        "RTX A3000", "RTX A2000",
        "QUADRO T2000", "QUADRO T1200", "QUADRO T1000",
        "QUADRO P4000", "QUADRO P3200", "QUADRO P2000", "QUADRO M2200",
        "T2000", "T1200", "T1000", "A3000", "A2000", "P4000", "P3200", "P2000",
        "RTX 3000", "RTX 2000",  # HP naming; also covers "RTX 2000 Ada"
    ]),
    "workstation_entry": (12, [
        "RTX A500", "A500", "A1000",
        "QUADRO T600", "QUADRO T500", "QUADRO T400", "T600", "T500", "T400",
        "QUADRO P620", "QUADRO P520", "QUADRO P2200", "QUADRO P1000",
        "P620", "P520", "P2200", "P1000",
        "QUADRO M1000M", "M1000M", "M2200",
        "RTX 1000",  # HP naming; also covers "RTX 1000 Ada"
    ]),
    "gaming_high": (22, [
        "RTX 5090", "RTX 5080", "RTX 5070",
        "RTX 4090", "RTX 4080", "RTX 4070", "RTX 3080", "RTX 3070",
    ]),
    "gaming_mid": (16, [
        "RTX 5060", "RTX 4060", "RTX 3060",
        "RTX 4050", "RTX 3050 TI", "RTX 3050",
        "RTX 2080", "RTX 2070",  # older but still solid gaming-tier
    ]),
    "gaming_low": (8, [
        "GTX 1660", "GTX 1650 TI", "GTX 1650", "GTX 1050 TI", "GTX 1050",
        "GTX 1080", "GTX 1070", "GTX 1060",
        "RTX 2060", "MX 550", "MX 450", "MX150", "MX 150",
        "1650 TI", "1650", "1050 TI", "1050",  # bare, "GTX" often dropped
    ]),
}

# Fallback tier for any GPU that matches a generic RTX/GTX/Quadro/MX + model
# number pattern but isn't in the explicit lists above (new/unlisted models
# still get partial credit instead of scoring as if there's no GPU at all).
GPU_OTHER_POINTS = 5

# Even lower fallback: title mentions a dGPU brand (Nvidia/Quadro/RTX/GeForce)
# but no model number at all — still worth a little more than "no GPU".
GPU_GENERIC_MENTION_POINTS = 3

# Chassis families known for dual M.2 slots / strong build quality — small
# bonus, not a hard requirement since it's rarely stated in listing titles.
WORKSTATION_MODEL_BONUS = [
    "THINKPAD P1", "THINKPAD P15", "THINKPAD P16", "THINKPAD X1 EXTREME",
    "PRECISION 5", "PRECISION 7", "ZBOOK",
]

# Terms that, if present, strongly suggest the listing ISN'T a working full
# laptop deal (parts, broken, wrong category, etc). Filtered out entirely.
EXCLUDE_TERMS = [
    "for parts", "parts only", "cracked screen", "no power", "won't turn on",
    "wont turn on", "no battery", "screen only", "motherboard only",
    "case only", "keyboard only", "charger only", "replacement part",
    "no ssd",
    # handheld gaming PCs / UMPCs — not laptops, shouldn't be scored as such
    "gpd win", "onexplayer", "steam deck", "ayaneo",
]

# Brand detection — first match wins, checked in this order (so "ThinkPad"
# resolves to Lenovo before any generic fallback).
# Each keyword is matched as a whole word (regex \b boundaries) against the
# uppercased title, so "HP" won't false-positive inside "SHIP", etc.
BRAND_KEYWORDS = [
    ("Lenovo", ["THINKPAD", "LENOVO", "LEGION", "YOGA"]),
    ("Dell", ["DELL", "PRECISION", "LATITUDE", "ALIENWARE", "XPS"]),
    ("HP", ["ZBOOK", "OMEN", "HP", "HEWLETT"]),
    ("ASUS", ["ASUS", "ROG", "ZENBOOK", "TUF"]),
    ("MSI", ["MSI"]),
    ("Razer", ["RAZER", "RAZOR"]),  # "Razor" is a common seller misspelling
    ("Apple", ["MACBOOK"]),
    ("Acer", ["ACER", "PREDATOR", "NITRO"]),
    ("Microsoft", ["SURFACE"]),
    ("Samsung", ["SAMSUNG"]),
]

# Web app settings
WEBAPP_HOST = "0.0.0.0"
# 0.0.0.0 runs on all addresses
# In other words, it will be hosted on localhost:8420 and 127.0.0.1:8420.
# Of course, other computers on your LAN cannot access it from localhost,
# but they can access it from your computer's LAN IP address (e.g. 192.168.x.x:8420).
WEBAPP_PORT = 8420

# --- Description/item-detail enrichment -----------------------------------
# The search endpoint only returns titles. Fetching a listing's full detail
# (a separate API call) also returns the seller's structured "item specifics"
# fields (Processor, RAM Size, GPU, Storage, etc.) plus the full description
# — both much more reliable than guessing off a truncated title. Since it's
# a per-item call and eBay's Browse API has a daily quota, this only runs
# for NEW listings that are still missing a key spec after title parsing,
# capped per run so a normal hourly scan stays well within quota.
ENRICH_ENABLED = True
MAX_ENRICH_PER_RUN = 60
DESCRIPTION_CHAR_LIMIT = 1500  # cap noisy boilerplate/policy text at the end

# --- Sold/expired listing cleanup ------------------------------------------
# Search results only return currently-active listings, but a listing that
# WAS active and got stored can later sell/end without ever being "removed"
# from the DB — nothing here deletes rows automatically. Instead: listings
# not seen again in a while are re-checked directly against eBay (a sold/
# ended item 404s on getItem — an authoritative signal, unlike just "it
# didn't show up in this run's search results," which can also happen for
# a still-active listing that fell outside the top-50 newest-first window).
STALE_CHECK_HOURS = 20      # only bother re-checking listings this old
MAX_SOLD_CHECKS_PER_RUN = 50  # budget, separate from MAX_ENRICH_PER_RUN