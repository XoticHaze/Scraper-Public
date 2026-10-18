from vehicle_engine.link_verification import verify_vehicle_detail

VIN = "2T3G1RFV9MC195862"
REQUESTED = "https://dealer.example/used/Toyota/2021-Toyota-RAV4-abc.htm"
DETAIL = f"Used 2021 Toyota RAV4 LE\nVIN {VIN}\nMileage: 20,776 miles\nPrice $23,951"


def check(**overrides):
    params = {
        "status": 200,
        "requested_url": REQUESTED,
        "final_url": REQUESTED,
        "title": "Used 2021 Toyota RAV4 LE",
        "body": DETAIL,
        "vin": VIN,
    }
    params.update(overrides)
    return verify_vehicle_detail(**params)


def test_verified_vin_on_fetched_detail_page():
    assert check() == (True, "vin_confirmed_on_detail_page")


def test_broken_capital_one_match_page_must_not_be_promoted():
    assert check(body=f"We didn't find an exact match for this vehicle. VIN {VIN}") == (
        False, "listing_unavailable_message"
    )


def test_a_valid_http_response_without_the_actual_vin_is_not_a_listing():
    assert check(body="Used 2021 Toyota RAV4 LE\nVIN 2T3P1RFV7MC243570")[0] is False


def test_http_404_does_not_promote_cached_listing():
    assert check(status=404)[0] is False


def test_redirected_search_page_without_vin_is_not_a_vehicle_detail():
    assert check(final_url="https://dealer.example/used-inventory", body="Used 2021 Toyota RAV4 LE")[0] is False


def test_missing_vin_is_discovery_only_not_verified():
    assert check(vin=None)[0] is False


def test_unavailable_listing_with_vin_is_not_verified():
    assert check(body=DETAIL + "\nThis vehicle is no longer available")[0] is False


def test_invalid_url_scheme_is_not_verified():
    assert check(final_url="file:///tmp/listing.html")[0] is False
