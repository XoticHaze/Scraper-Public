from vehicle_engine.images import select_gallery_photo, valid_photo_url
from vehicle_engine.normalize import parse_dealer_detail


DEALER = {
    "id": "universal_toyota",
    "name": "Red McCombs Universal Toyota",
    "location": "San Antonio, TX",
    "market_local": True,
}


def test_selects_actual_vehicle_gallery_photo_and_not_site_logo():
    photos = [
        {"url": "https://dealer.test/logo.png", "width": 800, "height": 400,
         "gallery": False, "alt": "Toyota"},
        {"url": "https://dealer.test/images/rav4-front.jpg", "width": 1024,
         "height": 720, "gallery": True, "alt": "2021 Toyota RAV4 XLE"},
    ]
    photo = select_gallery_photo(photos, vin="2T3A1RFV1MC123456")
    assert photo == {
        "url": "https://dealer.test/images/rav4-front.jpg",
        "source": "dealer_detail_gallery",
    }


def test_no_generic_car_photos_without_vehicle_gallery_proof():
    assert select_gallery_photo([
        {"url": "https://dealer.test/advertising/vehicle.jpg", "width": 1000,
         "height": 700, "gallery": False, "alt": "A nice vehicle"},
    ]) is None
    assert not valid_photo_url("https://dealer.test/no-photo.jpg")
    assert not valid_photo_url("https://dealer.test/header-logo.png")
    assert not valid_photo_url("https://dealer.test/photo.svg")


def test_drivetrain_navigation_word_fails_closed():
    row = parse_dealer_detail({
        "url": "https://dealer.test/used/Toyota/2021-example.htm",
        "text": """2021 Toyota RAV4 XLE for Sale in San Antonio, TX
Asking Price $26,220
Odometer
36,000 miles
Drivetrain
Location
Fuel Type
Gasoline
VIN
2T3A1RFV1MC123456""",
    }, DEALER)
    assert row is not None
    assert row["drivetrain"] is None
    assert row["mileage"] == 36000
    assert row["title"] == "2021 Toyota RAV4 XLE"


def test_mileage_never_taken_from_powertrain_warranty_copy():
    row = parse_dealer_detail({
        "url": "https://dealer.test/used/Toyota/2025-example.htm",
        "text": """Vic Vaughan Toyota of Boerne Used Vehicles 2025 Toyota RAV4 XLE
Asking Price $25,225
100,000 miles powertrain warranty
90,000 miles limited warranty
Odometer
23,450 miles
Drive type:
Front-wheel drive
VIN
2T3A1RFV1SC123456""",
    }, DEALER)
    assert row is not None
    assert row["title"] == "2025 Toyota RAV4 XLE"
    assert row["mileage"] == 23450
    assert row["drivetrain"] == "Front-Wheel Drive"


def test_rejects_detail_with_only_warranty_mileage():
    row = parse_dealer_detail({
        "url": "https://dealer.test/used/Toyota/2025-example.htm",
        "text": """2025 Toyota RAV4 XLE
Asking Price $25,225
100,000 miles powertrain warranty
VIN
2T3A1RFV1SC123456""",
    }, DEALER)
    assert row is None
