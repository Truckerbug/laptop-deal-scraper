"""
Runs the parse -> score -> store -> dashboard pipeline against mock eBay
listing data (no network / real credentials needed). Sanity check, not a
full test suite.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, main, storage  # noqa: E402

MOCK_ITEMS = [
    {
        "itemId": "v1|111111111111|0",
        "title": "Lenovo ThinkPad P1 Gen 4 Core i7 32GB RAM RTX A4000 1TB SSD Workstation",
        "price": {"value": "899.00", "currency": "USD"},
        "itemWebUrl": "https://www.ebay.com/itm/111111111111",
        "conditionId": "3000",
    },
    {
        "itemId": "v1|222222222222|0",
        "title": "Dell Precision 7560 i9 64GB RAM RTX A5000 2x512GB Dual NVMe",
        "price": {"value": "1050.00", "currency": "USD"},
        "itemWebUrl": "https://www.ebay.com/itm/222222222222",
        "conditionId": "2000",
    },
    {
        "itemId": "v1|333333333333|0",
        "title": "ASUS ROG Zephyrus G14 16GB RTX 3050 Gaming Laptop",
        "price": {"value": "650.00", "currency": "USD"},
        "itemWebUrl": "https://www.ebay.com/itm/333333333333",
        "conditionId": "3000",
    },
    {
        "itemId": "v1|444444444444|0",
        "title": "HP Chromebook 4GB 32GB eMMC - for parts, cracked screen",
        "price": {"value": "40.00", "currency": "USD"},
        "itemWebUrl": "https://www.ebay.com/itm/444444444444",
        "conditionId": "3000",
    },
    {
        "itemId": "v1|555555555555|0",
        "title": "MSI Titan GT77 i9 RTX 4090 64GB RAM 2TB SSD Beast",
        "price": {"value": "1140.00", "currency": "USD"},
        "itemWebUrl": "https://www.ebay.com/itm/555555555555",
        "conditionId": "1000",
    },
]


def run_test():
    # start clean
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()

    for raw in MOCK_ITEMS:
        item = main.process_item(raw, query="TEST")
        if item is None:
            print(f"SKIPPED (excluded/invalid): {raw['title'][:60]}")
            continue
        storage.upsert_listing(item)
        print(f"[{item['score']:>3}] ${item['price']:>7.0f}  "
              f"ram={item['ram_gb']}  gpu={item['gpu']}  {item['title'][:55]}")

    deals = storage.unalerted_deals()
    print(f"Deals at/above threshold ({config.SPEC_TARGETS['min_score_to_alert']}): {len(deals)}")
    assert len(deals) >= 2, "expected at least the two clear-cut good deals to surface"

    excluded_ids = [d["item_id"] for d in deals]
    assert "v1|444444444444|0" not in excluded_ids, "parts listing should never score/alert"

    # spot-check the new parsed fields on the ThinkPad row
    all_rows = {r["item_id"]: r for r in storage.all_listings()}
    tp = all_rows["v1|111111111111|0"]
    assert tp["brand"] == "Lenovo", f"expected Lenovo, got {tp['brand']}"
    assert tp["cpu"] and "i7" in tp["cpu"].lower(), f"expected i7 cpu, got {tp['cpu']}"
    assert tp["storage_gb"] == 1024, f"expected 1024 (1TB), got {tp['storage_gb']}"
    assert tp["gpu_tier"] == "workstation_high", f"expected workstation_high, got {tp['gpu_tier']}"

    dell = all_rows["v1|222222222222|0"]
    assert dell["brand"] == "Dell", f"expected Dell, got {dell['brand']}"
    assert dell["dual_storage"] == 1, "expected dual_storage flag set"

    print("Parsed-field checks passed (brand/cpu/storage/gpu_tier/dual_storage).")

    # --- enrichment path: title alone is missing GPU/RAM/storage, but the
    # item's "specifics" fields (as returned by getItem) fill in the gaps ---
    sparse_title = "Lenovo ThinkPad P16 Mobile Workstation - Great Condition"
    sparse_raw = {
        "itemId": "v1|666666666666|0",
        "title": sparse_title,
        "price": {"value": "780.00", "currency": "USD"},
        "itemWebUrl": "https://www.ebay.com/itm/666666666666",
        "conditionId": "3000",
    }
    sparse_item = main.process_item(sparse_raw, query="TEST")
    assert sparse_item["gpu"] is None and sparse_item["ram_gb"] is None, \
        "sparse title should have nothing to parse before enrichment"
    storage.upsert_listing(sparse_item)

    mock_detail = {
        "localizedAspects": [
            {"name": "Processor", "value": "Intel Core i7-12800H"},
            {"name": "RAM Size", "value": "32 GB"},
            {"name": "GPU", "value": "NVIDIA RTX A2000"},
            {"name": "SSD Capacity", "value": "1 TB"},
        ],
        "description": "<p>Great machine, <b>32GB RAM</b>, barely used.</p>",
    }
    import unittest.mock as mock
    with mock.patch("src.ebay_client.get_item", return_value=mock_detail):
        updated = main.enrich_item(sparse_item)
    assert updated["ram_gb"] == 32, f"expected 32 from aspects, got {updated['ram_gb']}"
    assert updated["gpu"] == "RTX A2000", f"expected RTX A2000, got {updated['gpu']}"
    assert updated["storage_gb"] == 1024, f"expected 1024 from '1 TB', got {updated['storage_gb']}"
    assert updated["score"] > sparse_item["score"], "enriched score should improve on sparse score"
    print(f"Enrichment check passed: sparse title (score={sparse_item['score']}) "
          f"-> enriched (score={updated['score']}, ram={updated['ram_gb']}, gpu={updated['gpu']}).")

    print("\nAll sanity checks passed.")


if __name__ == "__main__":
    run_test()