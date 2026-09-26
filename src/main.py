"""
Entry point. Run manually with `python -m src.main`, or on a schedule via
cron/launchd (see launchd/com.spencer.laptopscraper.plist).
"""

import sys
import time
import traceback

from src import config, ebay_client, parser, scorer, storage

CONDITION_NAMES = {
    "1000": "New", "1500": "New other", "2000": "Certified refurb",
    "2500": "Seller refurb", "3000": "Used",
}


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(config.LOG_PATH, "a") as f:
        f.write(line + "\n")


def process_item(raw: dict, query: str) -> dict | None:
    title = raw.get("title", "")
    price_info = raw.get("price", {})
    try:
        price = float(price_info.get("value", 0))
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None

    specs = parser.parse(title)
    if specs.excluded:
        return None

    score = scorer.score_listing(price, specs)
    condition_id = raw.get("conditionId", "")

    return {
        "item_id": raw.get("itemId", ""),
        "title": title,
        "price": price,
        "url": raw.get("itemWebUrl", ""),
        "ram_gb": specs.ram_gb,
        "gpu": specs.gpu,
        "gpu_tier": specs.gpu_tier,
        "cpu": specs.cpu,
        "brand": specs.brand,
        "storage_gb": specs.storage_gb,
        "dual_storage": specs.dual_storage,
        "score": score,
        "condition": CONDITION_NAMES.get(condition_id, raw.get("condition", "")),
        "query": query,
    }


def _needs_enrichment(item: dict) -> bool:
    """Worth spending a getItem call on this listing? Only if title parsing
    left a real gap in the fields that matter for scoring."""
    return item["gpu"] is None or item["ram_gb"] is None or item["storage_gb"] is None


def enrich_item(item: dict) -> dict | None:
    """Fetch full listing detail and re-parse title + item specifics +
    description together. Returns the updated field dict on success, or
    None if the detail fetch/parse didn't change anything useful."""
    detail = ebay_client.get_item(item["item_id"])
    aspects_text = parser.flatten_aspects(detail.get("localizedAspects"))
    description = detail.get("description") or detail.get("shortDescription") or ""
    description_text = parser.strip_html(description)[: config.DESCRIPTION_CHAR_LIMIT]
    extra_text = f"{aspects_text} {description_text}"

    specs = parser.parse(item["title"], extra_text=extra_text)
    score = scorer.score_listing(item["price"], specs)

    updated = dict(item)
    updated.update({
        "ram_gb": specs.ram_gb, "gpu": specs.gpu, "gpu_tier": specs.gpu_tier,
        "cpu": specs.cpu, "brand": specs.brand, "storage_gb": specs.storage_gb,
        "dual_storage": specs.dual_storage, "score": score,
    })
    return updated


def run_query(query: str, limit: int = 50, enrich_budget: int | None = None) -> dict:
    """Search + parse + score + store one query. Shared by the scheduled
    scan (run()) and the web app's ad-hoc "search eBay" box, so both go
    through identical logic. `enrich_budget` caps how many getItem detail
    calls this invocation may spend (None = use config default)."""
    if enrich_budget is None:
        enrich_budget = config.MAX_ENRICH_PER_RUN

    raw_items = ebay_client.search_items(query, limit=limit)
    seen, new, enriched = 0, 0, 0
    for raw in raw_items:
        item = process_item(raw, query)
        if item is None or not item["item_id"]:
            continue
        seen += 1
        is_new, already_enriched = storage.upsert_listing(item)
        if is_new:
            new += 1

        eligible = config.ENRICH_ENABLED and not already_enriched and _needs_enrichment(item)
        if eligible and enrich_budget > 0:
            try:
                updated = enrich_item(item)
                if updated is not None:
                    storage.upsert_listing(updated)
                storage.mark_enriched([item["item_id"]])
                enriched += 1
            except Exception as exc:  # noqa: BLE001 — don't let one bad fetch kill the run
                log(f"    enrich failed for {item['item_id']}: {exc}")
                storage.mark_enriched([item["item_id"]])  # don't retry every run
            enrich_budget -= 1

    return {"query": query, "seen": seen, "new": new, "enriched": enriched, "results": len(raw_items)}


def sweep_sold_listings(limit: int | None = None) -> dict:
    """Directly re-checks listings that haven't shown up in search results
    in a while, and marks anything actually gone (sold/ended — confirmed via
    a 404 or out-of-stock status on getItem, not just "missing from this
    run's results," which can also happen to a still-active listing that
    fell outside the top-50 newest-first search window)."""
    if limit is None:
        limit = config.MAX_SOLD_CHECKS_PER_RUN
    candidates = storage.stale_active_listings(config.STALE_CHECK_HOURS, limit=limit)

    checked, sold, errors = 0, 0, 0
    inactive_ids = []
    for row in candidates:
        try:
            if not ebay_client.is_item_active(row["item_id"]):
                inactive_ids.append(row["item_id"])
                sold += 1
            checked += 1
        except Exception as exc:  # noqa: BLE001 — leave it active, don't guess
            log(f"    sold-check failed for {row['item_id']}: {exc}")
            errors += 1

    storage.mark_inactive(inactive_ids)
    return {"checked": checked, "sold": sold, "errors": errors}


def run() -> int:
    log(f"Starting run across {len(config.SEARCH_QUERIES)} search queries")
    new_count, seen_count, error_count, enriched_count = 0, 0, 0, 0
    remaining_budget = config.MAX_ENRICH_PER_RUN

    for query in config.SEARCH_QUERIES:
        try:
            result = run_query(query, enrich_budget=remaining_budget)
        except Exception as exc:  # noqa: BLE001 — log and keep going
            error_count += 1
            log(f"  ERROR searching '{query}': {exc}")
            continue

        seen_count += result["seen"]
        new_count += result["new"]
        enriched_count += result["enriched"]
        remaining_budget -= result["enriched"]
        log(f"  '{query}': {result['results']} results, {result['enriched']} enriched")
        time.sleep(0.3)  # be polite to the API

    sold_result = sweep_sold_listings()
    if sold_result["checked"]:
        log(f"Sold-check sweep: {sold_result['checked']} checked, "
            f"{sold_result['sold']} marked sold/ended, {sold_result['errors']} errors")

    deals = storage.unalerted_deals()
    if deals:
        log(f"{len(deals)} new deal(s) at or above threshold "
            f"({config.SPEC_TARGETS['min_score_to_alert']}+):")
        for d in deals:
            log(f"  [{d['score']:>3}] ${d['price']:.0f}  {d['title'][:70]}  {d['url']}")
        storage.mark_alerted([d["item_id"] for d in deals])
    else:
        log("No new deals above threshold this run.")

    log(f"Done. {seen_count} listings seen, {new_count} new, {enriched_count} enriched, "
        f"{sold_result['sold']} marked sold, {error_count} query error(s). "
        f"View results at http://{config.WEBAPP_HOST}:{config.WEBAPP_PORT}")
    return 0 if error_count < len(config.SEARCH_QUERIES) else 1


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception:
        log("FATAL: " + traceback.format_exc())
        sys.exit(1)