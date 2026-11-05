from vehicle_engine.normalize import parse_dealer_detail


def test_north_park_doc_fee_does_not_win_price_parsing():
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
    row = parse_dealer_detail(
        {
            "url": "https://dealer.test/used/Toyota/2021-Toyota-RAV4-example.htm",
            "image_url": None,
            "text": """
            Used 2021 Toyota RAV4 XLE FWD
            Price includes $225 documentary fee.
            Internet Price $24,891
            Odometer
            49,494 miles
            Drivetrain
            Front-Wheel Drive
            VIN
            2T3P1RFV7MC243570
            """,
        },
        dealer,
    )

    assert row is not None
    assert row["price"] == 24891
    assert row["price"] != dealer["doc_fee"]


def test_fee_only_page_is_rejected_instead_of_publishing_fake_225_price():
    dealer = {
        "id": "north_park_toyota",
        "name": "North Park Toyota of San Antonio",
        "location": "San Antonio, TX",
        "market_local": True,
        "area_priority": "kelly_inner_west",
        "doc_fee": 225,
        "doc_fee_included_in_price": True,
    }
    row = parse_dealer_detail(
        {
            "url": "https://dealer.test/used/Toyota/2021-Toyota-RAV4-example.htm",
            "image_url": None,
            "text": """
            Used 2021 Toyota RAV4 LE FWD
            Price includes $225 documentary fee.
            Odometer
            53,928 miles
            """,
        },
        dealer,
    )

    assert row is None



def test_red_mccombs_toyota_uses_rmt_price_with_included_doc_fee():
    """Seller calls RMT price retail+doc; only RMT price is taxed once."""
    dealer = {
        "id": "red_mccombs_toyota", "name": "Red McCombs Toyota",
        "location": "San Antonio, TX", "market_local": True,
        "area_priority": "west_sa", "doc_fee": 225,
        "doc_fee_included_in_price": True, "mandatory_addon_amount": 0,
    }
    page = {
        "url": "https://www.redmccombstoyota.com/inventory/used-2025-toyota-rav4-le-awd-sport-utility-2t3f1rfv9sw546972/",
        "text": """
        Used 2025 Toyota RAV4 LE AWD Sport Utility
        VIN: 2T3F1RFV9SW546972
        Stock: T2498
        Retail $28,444
        Doc Fee $225
        RMT Price $28,669
        Mileage:
        46,320
        Drivetrain:
        AWD
        """,
    }
    row = parse_dealer_detail(page, dealer)
    assert row is not None
    assert row["vin"] == "2T3F1RFV9SW546972"
    assert row["price"] == 28669
    assert row["mileage"] == 46320
    assert row["drivetrain"] == "All-wheel Drive"
    assert row["dealer_doc_fee_included_in_price"] is True
