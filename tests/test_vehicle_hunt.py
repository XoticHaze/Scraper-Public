from vehicle_engine.normalize import parse_cars_com_card
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


def test_locality_is_first_class():
    assert locality_bucket(12, POLICY) == "local"
    assert locality_bucket(40, POLICY) == "nearby"
    assert locality_bucket(150, POLICY) == "regional"
    assert locality_bucket(250, POLICY) == "out_of_scope"


def test_low_mileage_23k_can_beat_20k_high_mileage():
    low_miles = {
        "source": "cars.com", "source_url": "https://x/1", "year": 2021,
        "price": 23178, "mileage": 20776, "drivetrain": "All-wheel Drive",
        "distance_miles": 25, "vin": "2T3G1RFV9MC195862", "certified": False,
    }
    cheap_worn = {
        "source": "cars.com", "source_url": "https://x/2", "year": 2020,
        "price": 20000, "mileage": 93000, "drivetrain": "All-wheel Drive",
        "distance_miles": 10, "vin": "2T3A1RFV9LC123456", "certified": False,
    }
    comps = [
        {"source":"cars.com","source_url":"https://x/3","year":2021,"price":24500,"mileage":50000,"drivetrain":"All-wheel Drive","distance_miles":20,"vin":"2T3A1RFV9MC000001","certified":False},
        {"source":"cars.com","source_url":"https://x/4","year":2021,"price":25000,"mileage":55000,"drivetrain":"All-wheel Drive","distance_miles":30,"vin":"2T3A1RFV9MC000002","certified":False},
        {"source":"cars.com","source_url":"https://x/5","year":2020,"price":23500,"mileage":60000,"drivetrain":"All-wheel Drive","distance_miles":40,"vin":"2T3A1RFV9LC000003","certified":False},
    ]
    ranked = rank_vehicles([low_miles, cheap_worn, *comps], POLICY)
    assert ranked[0]["vin"] == low_miles["vin"]
    assert "maintenance_history_can_be_taken_over_early" in ranked[0]["reasons"]


def test_otd_estimate_is_explicit_and_tax_aware():
    assert estimate_otd(23000, POLICY) == 24912.5
