from vehicle_engine.identity import dedupe_rows
from scripts.vehicle_scan import verified_market_detail_observations
from vehicle_engine.normalize import parse_autotrader_card, parse_cars_com_card, parse_dealer_detail
from vehicle_engine.scoring import estimate_otd, locality_bucket, rank_vehicles
from vehicle_engine.vin_specs import infer_2025_rav4_drivetrain


POLICY = {
    "year_min": 2018,
    "year_max": 2025,
    "target_price": 23000,
    "max_price": 27000,
    "preferred_mileage": 45000,
    "maintenance_control_mileage": 35000,
    "max_mileage": 100000,
    "preferred_radius_miles": 50,
    "hard_radius_miles": 200,
    "priority_area_weights": {
        "kelly_inner_west": 10,
        "inner_sa": 8,
        "west_sa": 6,
        "san_antonio_other": 2,
        "nearby": 0,
        "regional": -4,
    },
    "sales_tax_rate": 0.0625,
    "estimated_title_registration": 250,
    "assumed_doc_fee": 225,
}


def card(text: str, url: str = "https://www.cars.com/vehicledetail/example/"):
    return {"text": text, "url": url, "image_url": "https://example.test/car.jpg"}


def test_parse_rendered_cars_card():
    row = parse_cars_com_card(card("""
    $23,178
    20,776 mi.
    Used 2021 Toyota RAV4 LE
    Great Deal
    Example Toyota
    San Antonio, TX (12 mi)
    Vehicle Information
    Drivetrain
    All-wheel Drive
    Fuel type
    Gasoline
    Transmission
    8-Speed Automatic
    Stock #
    ABC123
    VIN
    2T3G1RFV9MC195862
    Dealer
    Example Toyota
    """))
    assert row is not None
    assert row["year"] == 2021
    assert row["price"] == 23178
    assert row["mileage"] == 20776
    assert row["vin"] == "2T3G1RFV9MC195862"
    assert row["distance_miles"] == 12
    assert row["drivetrain"] == "All-wheel Drive"


def test_parse_direct_dealer_prefers_sale_price_and_preserves_priority():
    dealer = {
        "id": "north_park_toyota",
        "name": "North Park Toyota of San Antonio",
        "location": "San Antonio, TX",
        "market_local": True,
        "area_priority": "kelly_inner_west",
        "doc_fee": 225,
        "doc_fee_included_in_price": True,
        "mandatory_addon_amount": 0,
    }
    row = parse_dealer_detail({
        "url": "https://dealer.test/used/Toyota/2021-Toyota-RAV4-example.htm",
        "image_url": "https://dealer.test/car.jpg",
        "text": """
        Certified Pre-Owned 2021 Toyota RAV4 LE
        MSRP $29,995
        Asking Price $23,178
        Odometer
        20,776 miles
        Drivetrain
        All-Wheel Drive
        Transmission
        8 speed automatic
        VIN
        2T3G1RFV9MC195862
        Stock Number
        ABC123
        """,
    }, dealer)
    assert row is not None
    assert row["price"] == 23178
    assert row["mileage"] == 20776
    assert row["source_kind"] == "direct_dealer"
    assert row["area_priority"] == "kelly_inner_west"
    assert row["certified"] is True
    assert row["dealer_doc_fee"] == 225
    assert row["dealer_doc_fee_included_in_price"] is True


def test_parse_autotrader_card_supports_compact_mileage_and_distance():
    row = parse_autotrader_card({
        "url": "https://www.autotrader.com/cars-for-sale/inventory/123",
        "image_url": "https://example.test/a.jpg",
        "text": """
        Used 2023 Toyota RAV4
        LE
        28K mi
        27,499
        Great Price
        Dealer Fees Included
        Red McCombs Hyundai
        6.88 mi. away
        """,
    }, {"id": "autotrader_inner_west_sa", "location": "San Antonio, TX"})
    assert row is not None
    assert row["year"] == 2023
    assert row["trim"] == "LE"
    assert row["mileage"] == 28000
    assert row["price"] == 27499
    assert row["dealer"] == "Red McCombs Hyundai"
    assert row["distance_miles"] == 6.88
    assert row["source_kind"] == "aggregator"
    assert row["area_priority"] is None


def test_locality_is_first_class_and_supports_trusted_hint():
    assert locality_bucket(12, POLICY) == "local"
    assert locality_bucket(40, POLICY) == "nearby"
    assert locality_bucket(150, POLICY) == "regional"
    assert locality_bucket(250, POLICY) == "out_of_scope"
    assert locality_bucket(None, POLICY, False, "nearby") == "nearby"


def test_low_mileage_23k_can_beat_20k_high_mileage():
    low_miles = {
        "source": "dealer", "source_kind": "direct_dealer", "source_url": "https://x/1", "year": 2021,
        "price": 23178, "mileage": 20776, "drivetrain": "All-wheel Drive",
        "market_local": True, "area_priority": "kelly_inner_west", "vin": "2T3G1RFV9MC195862", "certified": False,
    }
    cheap_worn = {
        "source": "dealer", "source_kind": "direct_dealer", "source_url": "https://x/2", "year": 2020,
        "price": 20000, "mileage": 93000, "drivetrain": "All-wheel Drive",
        "market_local": True, "area_priority": "west_sa", "vin": "2T3A1RFV9LC123456", "certified": False,
    }
    comps = [
        {"source":"x","source_url":"https://x/3","year":2021,"price":24500,"mileage":50000,"drivetrain":"All-wheel Drive","distance_miles":20,"vin":"2T3A1RFV9MC000001","certified":False},
        {"source":"x","source_url":"https://x/4","year":2021,"price":25000,"mileage":55000,"drivetrain":"All-wheel Drive","distance_miles":30,"vin":"2T3A1RFV9MC000002","certified":False},
        {"source":"x","source_url":"https://x/5","year":2020,"price":23500,"mileage":60000,"drivetrain":"All-wheel Drive","distance_miles":40,"vin":"2T3A1RFV9LC000003","certified":False},
    ]
    ranked = rank_vehicles([low_miles, cheap_worn, *comps], POLICY)
    assert ranked[0]["vin"] == low_miles["vin"]
    assert "maintenance_history_can_be_taken_over_early" in ranked[0]["reasons"]
    assert "priority_area_kelly_inner_west" in ranked[0]["reasons"]


def test_inner_west_priority_breaks_otherwise_equal_local_tie():
    west = {"source":"a", "source_url":"https://x/w", "year":2022, "price":24000, "mileage":30000, "market_local":True, "area_priority":"kelly_inner_west", "vin":"2T3AAAAA1NC000001", "certified":False}
    other = {"source":"b", "source_url":"https://x/o", "year":2022, "price":24000, "mileage":30000, "market_local":True, "area_priority":"san_antonio_other", "vin":"2T3AAAAA1NC000002", "certified":False}
    ranked = rank_vehicles([west, other], POLICY)
    assert ranked[0]["vin"] == west["vin"]


def test_cross_source_dedupe_prefers_direct_dealer_and_keeps_alternates():
    direct = {
        "source": "north_park_toyota", "source_kind": "direct_dealer", "source_url": "https://dealer/1",
        "year": 2021, "trim": "LE", "title": "2021 Toyota RAV4 LE", "price": 23178, "mileage": 20776,
        "vin": "2T3G1RFV9MC195862", "dealer": "North Park Toyota", "drivetrain": "All-wheel Drive",
        "dealer_doc_fee": 225, "dealer_doc_fee_included_in_price": True,
    }
    aggregate = {
        "source": "autotrader_inner_west_sa", "source_kind": "aggregator", "source_url": "https://agg/1",
        "year": 2021, "trim": "LE", "title": "2021 Toyota RAV4 LE", "price": 23178, "mileage": 20776,
        "vin": None, "dealer": "North Park Toyota",
    }
    rows = dedupe_rows([aggregate, direct])
    assert len(rows) == 1
    assert rows[0]["source"] == "north_park_toyota"
    assert rows[0]["source_url"] == "https://dealer/1"
    assert rows[0]["dealer_doc_fee_included_in_price"] is True
    assert set(rows[0]["alternate_urls"]) == {"https://dealer/1", "https://agg/1"}
    assert set(rows[0]["sources"]) == {"north_park_toyota", "autotrader_inner_west_sa"}


def test_included_doc_fee_is_not_added_twice_to_otd():
    row = {
        "source": "north_park_toyota", "source_kind": "direct_dealer", "source_url": "https://dealer/1",
        "year": 2023, "price": 23000, "mileage": 25000, "market_local": True,
        "area_priority": "kelly_inner_west", "vin": "2T3AAAAA1PC000001", "certified": False,
        "dealer_doc_fee": 225, "dealer_doc_fee_included_in_price": True,
    }
    ranked = rank_vehicles([row], POLICY)
    assert ranked[0]["estimated_otd"] == 24687.5
    assert ranked[0]["incremental_doc_fee"] == 0
    assert "dealer_doc_fee_already_in_advertised_price" in ranked[0]["reasons"]


def test_otd_estimate_is_explicit_and_tax_aware():
    assert estimate_otd(23000, POLICY) == 24912.5


def test_2025_rav4_vin_family_drive_is_inferred_not_exact_vin_confirmed():
    awd = infer_2025_rav4_drivetrain("2T3F1RFV1SC512476", 2025, "Toyota", "RAV4")
    fwd = infer_2025_rav4_drivetrain("2T3W1RFV2SW378883", 2025, "Toyota", "RAV4")
    assert awd and awd["drivetrain"] == "All-wheel Drive"
    assert fwd and fwd["drivetrain"] == "Front-wheel Drive"
    assert awd["drivetrain_provenance"] == "vin_family_inferred"
    assert awd["drivetrain_evidence_url"].startswith("https://")
    assert fwd["drivetrain_provenance"] == "vin_family_inferred"


def test_vin_family_inference_fails_closed_on_other_builds_years_and_bad_vins():
    assert infer_2025_rav4_drivetrain("2T3F1RFV1SC512476", 2024, "Toyota", "RAV4") is None
    assert infer_2025_rav4_drivetrain("2T3F1RFV1SC512476", 2025, "Honda", "RAV4") is None
    assert infer_2025_rav4_drivetrain("2T3F1RFV1SC512476", 2025, "Toyota", "Prius") is None
    assert infer_2025_rav4_drivetrain("2T3P1RFV1SC496123", 2025, "Toyota", "RAV4") is None
    assert infer_2025_rav4_drivetrain("2T3F1RFV1SC", 2025, "Toyota", "RAV4") is None


def test_dealer_detail_fills_missing_drive_from_vin_family_without_claiming_proof():
    row = parse_dealer_detail({
        "url": "https://dealer.test/used/2025-toyota-rav4-le",
        "text": """
        Certified Pre-Owned 2025 Toyota RAV4 LE
        Asking Price $24,225
        Odometer
        67,400 miles
        VIN
        2T3F1RFV1SC512476
        """,
    }, {"id": "example", "name": "Example Toyota", "market_local": True})
    assert row is not None
    assert row["drivetrain"] == "All-wheel Drive"
    assert row["drivetrain_provenance"] == "vin_family_inferred"
    assert row["drivetrain_evidence_url"].startswith("https://")


def test_dealer_detail_explicit_drive_overrides_family_inference():
    row = parse_dealer_detail({
        "url": "https://dealer.test/used/2025-toyota-rav4-le",
        "text": """
        2025 Toyota RAV4 LE
        Asking Price $24,225
        Odometer
        42,414 miles
        Drivetrain
        All-wheel Drive
        VIN
        2T3F1RFV1SW512766
        """,
    }, {"id": "example", "name": "Example Toyota", "market_local": True})
    assert row is not None
    assert row["drivetrain_provenance"] == "dealer_detail"
    assert row["drivetrain_evidence_url"] is None


def test_buyer_fit_prefers_lower_maintenance_miles_to_deeply_discounted_67k_car():
    common = {
        "year": 2025, "make": "Toyota", "model": "RAV4",
        "drivetrain": "All-wheel Drive",
        "drivetrain_provenance": "vin_family_inferred",
        "locality_hint": "nearby", "certified": True,
        "source_url": "https://dealer.test/vehicle",
    }
    high = {**common, "vin": "2T3F1RFV1SC512476", "mileage": 67400, "price": 24225}
    lower = {**common, "vin": "2T3F1RFV1SW512766", "mileage": 42414, "price": 26225}
    ranked = rank_vehicles([high, lower], POLICY)
    assert ranked[0]["vin"] == lower["vin"]
    assert "above_preferred_mileage" in ranked[1]["risks"]
    assert "past_60k_service_ambiguity" in ranked[1]["risks"]
    assert "awd_family_indicated_verify_exact_sticker" in ranked[0]["reasons"]



def test_hill_country_honda_realistic_selling_price_and_exact_vin_fwd_detail():
    """Use the precise dealer selling price and don't double-add the doc fee."""
    page = {
        "url": "https://www.hillcountryhonda.com/viewdetails/used/2t3h1rfv8pw283437/2023-toyota-rav4-sport-utility?type=finance",
        "text": """
        2023 Toyota RAV4 LE 8-Speed A/T
        Vin: 2T3H1RFV8PW283437
        Stock: PW283437P
        Mileage: 36,720 Miles
        Drive Type:
        FWD
        Transmission:
        8-Speed A/T
        Payment And Price Options
        Finance For
        $384.42
        Per Month
        Finance this 2023 Toyota RAV4 LE (Model 4430, VIN 2T3H1RFV8PW283437).
        Price $26,195.00. Selling price $26,420.00, with $3,929.00 down.
        Prices include $225 dealer doc fee.
        Does not include optional accessories of $695 PermaPlate 1-Year.
        """,
    }
    dealer = {
        "id": "hill_country_honda", "name": "Hill Country Honda",
        "market_local": True, "area_priority": "west_sa", "doc_fee": 225,
        "doc_fee_included_in_price": True, "mandatory_addon_amount": 0,
    }
    row = parse_dealer_detail(page, dealer)
    assert row is not None
    assert row["vin"] == "2T3H1RFV8PW283437"
    assert row["price"] == 26420
    assert row["mileage"] == 36720
    assert row["drivetrain"] == "Front-Wheel Drive"
    assert row["drivetrain_provenance"] == "dealer_detail"
    assert row["dealer_doc_fee_included_in_price"] is True
    ranked = rank_vehicles([row], POLICY)
    assert ranked and ranked[0]["incremental_doc_fee"] == 0


def test_fresh_vehicle_snapshot_invalidates_when_dealer_registry_changes(tmp_path, monkeypatch):
    import json
    import time
    from scripts import macbid_postprocess as post

    path = tmp_path / "vehicle-previous.json"
    dealer = {
        "id": "toyota_of_boerne",
        "inventory_url": "https://dealer.test/used/toyota/rav4",
        "doc_fee": 225,
        "doc_fee_included_in_price": False,
    }
    old = {
        "generated_epoch_utc": int(time.time()),
        "vehicles": [{"price": 26225}],
        "source_registry": [dealer],
    }
    path.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(post, "VEHICLE_PREVIOUS", path)
    assert post.previous_vehicle_age_minutes([dealer]) is not None
    new_dealer = {"id": "hill_country_honda", "inventory_url": "https://www.hillcountryhonda.com/inventory/used/toyota/rav4"}
    assert post.previous_vehicle_age_minutes([dealer, new_dealer]) is None
    changed_fee = {**dealer, "doc_fee_included_in_price": True}
    assert post.previous_vehicle_age_minutes([changed_fee]) is None



def test_market_history_only_records_real_verified_vin_scan_times():
    from scripts.vehicle_price_history import build_history

    def catalog(when, price, status="verified"):
        return {
            "generated_utc": when,
            "market_observations": [{
                "vin": "2T3F1RFV1SW512766", "price": price, "year": 2025,
                "mileage": 42414, "trim": "LE", "source": "toyota_of_boerne",
                "dealer": "Vic Vaughan Toyota of Boerne", "listing_link_status": status,
            }],
            "vehicles": [],
        }

    a=catalog("2026-11-02T23:54:36+00:00",26225)
    b=catalog("2026-11-03T04:06:59+00:00",26025)
    output=build_history(b, a, published_available=True, bootstrap_seed=[])
    assert output["record_count"] == 2
    assert [r["price"] for r in output["observations"]] == [26225,26025]
    assert [r["observed_at"] for r in output["observations"]] == [
        a["generated_utc"],b["generated_utc"]]
    # Cached replay of an already published scrape is not a new point.
    duplicate=build_history(b,a,published=output["observations"],published_available=True,bootstrap_seed=[])
    assert duplicate["record_count"]==2
    blocked=build_history(catalog("2026-11-04T00:00:00+00:00",22000,"discovery_only"),
                          published=duplicate["observations"],published_available=True,bootstrap_seed=[])
    assert blocked["record_count"]==2


def test_price_history_bootstrap_is_real_short_window_not_invented_trend():
    from scripts.vehicle_price_history import build_history, load_seed
    seed=load_seed()
    assert len(seed)==15
    history=build_history({},published_available=False,bootstrap_seed=seed)
    assert history["record_count"]==15
    assert history["vin_count"]==5
    assert history["continuity_status"]=="SEED_AND_LAST_CATALOG_ONLY"
    by_vin={}
    for row in history["observations"]:
        by_vin.setdefault(row["vin"],[]).append(row)
    assert all(len(rows)==3 and len({r["price"] for r in rows})==1 for rows in by_vin.values())


def test_price_history_skips_unverified_and_invalid_price_and_year():
    from scripts.vehicle_price_history import build_history
    current={"generated_utc":"2026-11-03T07:00:00Z",
             "market_observations":[
                {"vin":"2T3F1RFV1SW512766","year":2025,"price":27100,"mileage":42414,"listing_link_status":"verified"},
                {"vin":"NOT-A-REAL-VIN","year":2025,"price":25999,"mileage":40000,"listing_link_status":"verified"},
                {"vin":"2T3F1RFV1SC512476","year":2025,"price":225,"mileage":67400,"listing_link_status":"verified"},
                {"vin":"2T3F1RFV5SC527627","year":2025,"price":24000,"mileage":47000,"listing_link_status":"discovery_only"},
             ],"vehicles":[]}
    history=build_history(current,published_available=True,bootstrap_seed=[])
    assert [(row["vin"],row["price"]) for row in history["observations"]]==[("2T3F1RFV1SW512766",27100)]


def test_market_source_observations_preserve_verified_same_vin_price_disagreement():
    """Market comparisons keep two verified source quotes even when ranking dedupes."""
    vin = "2T3G1RFV9MC195862"
    dealer = {
        "vin": vin, "price": 23178, "mileage": 20776, "year": 2021,
        "trim": "LE", "title": "2021 Toyota RAV4 LE",
        "source": "dealer_a", "source_kind": "direct_dealer",
        "source_url": "https://dealer.example/used/rav4/vin", "dealer": "Dealer A",
        "listing_link_status": "verified",
    }
    aggregator = {
        **dealer, "price": 22499, "source": "aggregator_b",
        "source_kind": "aggregator",
        "source_url": "https://aggregator.example/used/rav4/vin",
    }
    raw_verified = [aggregator, dealer]
    deduped = dedupe_rows(raw_verified)
    assert len(deduped) == 1
    assert deduped[0]["source_kind"] == "direct_dealer"

    # The former projection from deduped discarded the independent quote.
    assert len(verified_market_detail_observations(deduped)) == 1
    observed = verified_market_detail_observations(raw_verified)
    assert len(observed) == 2
    assert {(row["source_kind"], row["price"]) for row in observed} == {
        ("direct_dealer", 23178), ("aggregator", 22499)
    }
    assert all(row["vin"] == vin and row["listing_link_status"] == "verified"
               for row in observed)
    assert deduped[0]["price"] == 23178  # Buyer-ranked price is unchanged.


def test_market_source_observations_reject_discovery_or_invalid_evidence():
    vin = "2T3G1RFV9MC195862"
    good = {
        "vin": vin, "price": 23178, "source": "dealer_a",
        "source_kind": "direct_dealer", "listing_link_status": "verified",
    }
    invalid = [
        {**good, "source_kind": "aggregator", "listing_link_status": None},
        {**good, "vin": None},
        {**good, "vin": "not-a-vin"},
        {**good, "price": None},
        {**good, "price": 0},
        {**good, "price": -1},
        {**good, "price": float("inf")},
        {**good, "price": float("nan")},
        {**good, "price": True},
        {**good, "price": "23178"},
    ]
    observations = verified_market_detail_observations([*invalid, good])
    assert len(observations) == 1
    assert observations[0]["source_kind"] == "direct_dealer"
    assert observations[0]["price"] == 23178


def test_vehicle_market_rejects_non_number_json_prices():
    """Run the production JavaScript predicate against malformed JSON prices in V8."""
    import re
    import subprocess
    from pathlib import Path

    source = Path("ui/vehicle-market.js").read_text(encoding="utf-8")
    match = re.search(r"const validPrice = value => ([^;\n]+);", source)
    assert match, "Market price validator must be present in consumer source"
    javascript = (
        "const validPrice = value => " + match.group(1) + ";\n"
        "for (const p of [true, false, [], [23178], {}, '23178', null, undefined, NaN, Infinity, 0, -1]) {\n"
        "  if (validPrice(p)) throw new Error('accepted malformed price: '+JSON.stringify(p));\n"
        "}\n"
        "for (const p of [1, 23178, 27000]) {\n"
        "  if (!validPrice(p)) throw new Error('rejected positive numeric price: '+p);\n"
        "}\n"
    )
    result = subprocess.run(["node", "-e", javascript], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_vehicle_card_numeric_guard_rejects_json_coercions():
    """Test real buyer-card predicates in Node/V8, including JSON booleans and arrays."""
    import re
    import subprocess
    from pathlib import Path

    source = Path("ui/vehicles.js").read_text(encoding="utf-8")
    expressions = {}
    for name, arg in (("finiteNumber", "n"), ("knownPrice", "v"), ("knownMileage", "v")):
        match = re.search(r"const " + name + r" = " + arg + r" => ([^;\\n]+);", source)
        assert match, name + " predicate missing in vehicle-card consumer"
        expressions[name] = match.group(1)
    js = (
        "const finiteNumber = n => " + expressions["finiteNumber"] + ";\n"
        "const knownPrice = v => " + expressions["knownPrice"] + ";\n"
        "const knownMileage = v => " + expressions["knownMileage"] + ";\n"
        "for (const value of [true, false, [], [23178], {}, '23178', null, undefined, NaN, Infinity]) {\\n"
        "  if (knownPrice({price:value}) || knownMileage({mileage:value})) throw new Error('coerced buyer value');\\n"
        "}\\n"
        "if (knownPrice({price:0}) || knownPrice({price:-1}) || !knownPrice({price:23178})) throw new Error('price bound');\\n"
        "if (!knownMileage({mileage:0}) || !knownMileage({mileage:35000}) || knownMileage({mileage:-1})) throw new Error('mileage bound');\\n"
    )
    proc = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
