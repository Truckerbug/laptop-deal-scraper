"""
Thin client around the eBay Browse API (item_summary/search) using the
client-credentials OAuth flow (app-level token, no user login needed).
"""

import json
import time
import base64
import requests
from urllib.parse import quote

from src import config


class EbayAuthError(RuntimeError):
    pass

class ItemNotFoundError(RuntimeError):
    """Raised when getItem 404s — the listing has been removed/sold/ended."""
    def __init__(self, item_id: str):
        super().__init__(f"item not found (likely sold/ended): {item_id}")
        self.item_id = item_id

def _load_cached_token() -> str | None:
    if not config.TOKEN_CACHE_PATH.exists():
        return None
    try:
        cache = json.loads(config.TOKEN_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if cache.get("expires_at", 0) > time.time() + 60:  # 60s safety margin
        return cache.get("access_token")
    return None


def _store_token(access_token: str, expires_in: int) -> None:
    cache = {"access_token": access_token, "expires_at": time.time() + expires_in}
    config.TOKEN_CACHE_PATH.write_text(json.dumps(cache))


def get_access_token() -> str:
    cached = _load_cached_token()
    if cached:
        return cached

    if not config.EBAY_CLIENT_ID or not config.EBAY_CLIENT_SECRET:
        raise EbayAuthError(
            "Missing EBAY_CLIENT_ID / EBAY_CLIENT_SECRET env vars. "
            "Create an app at https://developer.ebay.com/my/keys and set them."
        )

    creds = f"{config.EBAY_CLIENT_ID}:{config.EBAY_CLIENT_SECRET}"
    basic = base64.b64encode(creds.encode()).decode()

    resp = requests.post(
        config.EBAY_AUTH_URL,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic}",
        },
        data={"grant_type": "client_credentials", "scope": config.EBAY_SCOPE},
        timeout=20,
    )
    if resp.status_code != 200:
        raise EbayAuthError(f"eBay auth failed ({resp.status_code}): {resp.text[:300]}")

    body = resp.json()
    _store_token(body["access_token"], body["expires_in"])
    return body["access_token"]


def search_items(query: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Search active listings for `query`, filtered to the configured price
    window and category. Returns raw itemSummaries from the API."""
    token = get_access_token()

    price_filter = f"price:[{config.MIN_PRICE}..{config.MAX_PRICE}],priceCurrency:USD"
    params = {
        "q": query,
        "category_ids": config.CATEGORY_ID,
        "filter": f"{price_filter},buyingOptions:{{FIXED_PRICE|AUCTION}},conditionIds:{{1000|1500|2000|2500|3000}}",
        "sort": "newlyListed",
        "limit": str(limit),
        "offset": str(offset),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": config.EBAY_MARKETPLACE,
        "Content-Type": "application/json",
    }

    resp = requests.get(config.EBAY_SEARCH_URL, headers=headers, params=params, timeout=20)
    if resp.status_code == 401:
        # token might have just expired/been revoked — clear cache once and retry
        config.TOKEN_CACHE_PATH.unlink(missing_ok=True)
        token = get_access_token()
        headers["Authorization"] = f"Bearer {token}"
        resp = requests.get(config.EBAY_SEARCH_URL, headers=headers, params=params, timeout=20)

    if resp.status_code != 200:
        raise RuntimeError(f"eBay search failed for '{query}' ({resp.status_code}): {resp.text[:300]}")

    return resp.json().get("itemSummaries", [])


def get_item(item_id: str) -> dict:
    """Fetch full listing detail (Browse API getItem) — includes seller
    "item specifics" (localizedAspects: structured Processor/RAM/GPU/Storage
    fields) and the full description, neither of which the search endpoint
    returns. One API call per item, so callers should use this sparingly."""
    token = get_access_token()
    encoded_id = quote(item_id, safe="")
    url = f"{config.EBAY_ITEM_URL}/{encoded_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": config.EBAY_MARKETPLACE,
        "Content-Type": "application/json",
    }

    resp = requests.get(url, headers=headers, timeout=20)
    if resp.status_code == 401:
        config.TOKEN_CACHE_PATH.unlink(missing_ok=True)
        token = get_access_token()
        headers["Authorization"] = f"Bearer {token}"
        resp = requests.get(url, headers=headers, timeout=20)

    if resp.status_code in (404, 410):
        raise ItemNotFoundError(item_id)
    if resp.status_code != 200:
        raise RuntimeError(f"eBay getItem failed for '{item_id}' ({resp.status_code}): {resp.text[:300]}")

    return resp.json()


def is_item_active(item_id: str) -> bool:
    """True if the listing is still live, False if it is sold/ended."""
    try:
        detail = get_item(item_id)
    except ItemNotFoundError:
        return False

    availabilities = detail.get("estimatedAvailabilities") or [{}]
    if isinstance(availabilities, dict):
        availabilities = [availabilities]

    for availability in availabilities:
        status = str(availability.get("estimatedAvailabilityStatus", "")).upper()
        if status in {"OUT_OF_STOCK", "SOLD_OUT"}:
            return False

        remaining = availability.get("estimatedRemainingQuantity")
        if remaining is not None:
            try:
                if float(remaining) <= 0:
                    return False
            except (TypeError, ValueError):
                pass

    return True