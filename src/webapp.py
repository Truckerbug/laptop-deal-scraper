"""
Local web app — one process, pure Python backend, single HTML page.

Run with `python3 -m src.webapp` (or via launchd, see launchd/) and open
http://127.0.0.1:8420 in a browser. The page loads all listings as JSON
and does sorting/filtering client-side (instant, no server round trip);
the "search eBay" box POSTs to /api/search to run a live query and drop
the results straight into the same table.
"""

import sqlite3
import time
import traceback

from flask import Flask, jsonify, request, send_from_directory

from src import config, ebay_client, main as scraper_main, storage

app = Flask(__name__, static_folder="../static", static_url_path="")


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["dual_storage"] = bool(d.get("dual_storage"))
    d["enriched"] = bool(d.get("enriched"))
    d["active"] = bool(d.get("active", 1))
    return d


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/listings")
def api_listings():
    rows = storage.all_listings(limit=2000)
    return jsonify({
        "listings": [_row_to_dict(r) for r in rows],
        "brands": storage.distinct_values("brand"),
        "gpu_tiers": storage.distinct_values("gpu_tier"),
        "queries": storage.distinct_values("query"),
        "min_score_to_alert": config.SPEC_TARGETS["min_score_to_alert"],
    })


@app.route("/api/search", methods=["POST"])
def api_search():
    body = request.get_json(force=True, silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400
    if len(query) > 120:
        return jsonify({"error": "query too long"}), 400

    try:
        result = scraper_main.run_query(query, limit=50)
    except ebay_client.EbayAuthError as exc:
        return jsonify({"error": f"eBay auth error: {exc}"}), 502
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 502

    return jsonify(result)


@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    """Re-run all configured SEARCH_QUERIES on demand, from the UI, instead
    of waiting for the next scheduled launchd run."""
    started = time.time()
    results = []
    for query in config.SEARCH_QUERIES:
        try:
            results.append(scraper_main.run_query(query, limit=50))
        except Exception as exc:  # noqa: BLE001
            results.append({"query": query, "error": str(exc)})
    return jsonify({
        "elapsed_seconds": round(time.time() - started, 1),
        "results": results,
    })


@app.route("/api/enrich", methods=["POST"])
def api_enrich():
    """On-demand: fetch full item detail for one listing and re-parse it.
    Bypasses the "already enriched" skip and the missing-specs check, since
    this is an explicit user request for one specific listing — useful for
    older rows that predate this feature, or a title-parse you want to
    double-check against the real listing."""
    body = request.get_json(force=True, silent=True) or {}
    item_id = (body.get("item_id") or "").strip()
    if not item_id:
        return jsonify({"error": "item_id is required"}), 400

    row = storage.get_listing(item_id)
    if row is None:
        return jsonify({"error": "listing not found"}), 404

    try:
        updated = scraper_main.enrich_item(dict(row))
    except ebay_client.EbayAuthError as exc:
        return jsonify({"error": f"eBay auth error: {exc}"}), 502
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 502

    if updated is not None:
        storage.upsert_listing(updated)
    storage.mark_enriched([item_id])

    fresh = storage.get_listing(item_id)
    return jsonify({"listing": _row_to_dict(fresh)})


@app.route("/api/enrich_missing", methods=["POST"])
def api_enrich_missing():
    """Bulk: enrich every not-yet-enriched listing still missing a key spec,
    up to a cap so this can't blow through the day's API quota by accident."""
    body = request.get_json(force=True, silent=True) or {}
    limit = min(int(body.get("limit", 40)), 150)

    candidates = [
        dict(r) for r in storage.all_listings(limit=2000)
        if not r["enriched"] and (r["gpu"] is None or r["ram_gb"] is None or r["storage_gb"] is None)
    ][:limit]

    enriched, failed = 0, 0
    for item in candidates:
        try:
            updated = scraper_main.enrich_item(item)
            if updated is not None:
                storage.upsert_listing(updated)
            enriched += 1
        except Exception:  # noqa: BLE001
            failed += 1
        storage.mark_enriched([item["item_id"]])

    return jsonify({"attempted": len(candidates), "enriched": enriched, "failed": failed})


@app.route("/api/sweep_sold", methods=["POST"])
def api_sweep_sold():
    """Manually trigger the sold/ended-listing check from the UI, instead
    of waiting for the next scheduled run."""
    body = request.get_json(force=True, silent=True) or {}
    limit = min(int(body.get("limit", 30)), 100)
    try:
        result = scraper_main.sweep_sold_listings(limit=limit)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


def run():
    app.run(host=config.WEBAPP_HOST, port=config.WEBAPP_PORT, debug=False)


if __name__ == "__main__":
    run()