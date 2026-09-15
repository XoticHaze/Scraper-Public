from vehicle_engine.identity import dedupe_rows
from vehicle_engine.normalize import parse_autotrader_card, parse_cars_com_card, parse_dealer_detail
from vehicle_engine.scoring import estimate_otd, locality_bucket, rank_vehicles


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
    }, {"id": "autotrader_inner_west_sa", "location": "San Antonio, TX", "area_priority": "inner_sa"})
    assert row is not None
    assert row["year"] == 2023
    assert row["trim"] == "LE"
    assert row["mileage"] == 28000
    assert row["price"] == 27499
    assert row["dealer"] == "Red McCombs Hyundai"
    assert row["distance_miles"] == 6.88
    assert row["source_kind"] == "aggregator"


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
    assert set(rows[0]["alternate_urls"]) == {"https://dealer/1", "https://agg/1"}
    assert set(rows[0]["sources"]) == {"north_park_toyota", "autotrader_inner_west_sa"}


def test_otd_estimate_is_explicit_and_tax_aware():
    assert estimate_otd(23000, POLICY) == 24912.5
