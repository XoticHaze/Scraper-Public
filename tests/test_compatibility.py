from deal_engine.compatibility import compatibility_allows_hunt, evaluate_compatibility


MATRIX = {
    "capability_rules": [
        {
            "id": "matter_thread",
            "target": "haos",
            "match_all": ["matter", "thread"],
            "status": "verified_with_requirements",
            "integration": "Matter",
            "requirements": ["Matter Server", "Thread border router"],
            "local_control": True,
        },
        {
            "id": "z_wave",
            "target": "haos",
            "match_any": ["z-wave", "z wave"],
            "status": "verified_with_requirements",
            "integration": "Z-Wave",
            "requirements": ["adapter"],
            "local_control": True,
        },
        {
            "id": "wifi",
            "target": "haos",
            "match_any": ["wifi", "wi-fi"],
            "status": "unknown",
            "integration": None,
            "requirements": ["exact integration"],
        },
    ],
    "vendor_rules": [
        {
            "id": "goodwe",
            "target": "haos",
            "match_any": ["goodwe"],
            "product_any": ["inverter"],
            "status": "candidate",
            "integration": "GoodWe",
            "requirements": ["supported model"],
            "local_control": True,
        }
    ],
    "exact_overrides": [
        {
            "identity": "upc:exact",
            "target": "haos",
            "status": "variant_required",
            "integration": "Z-Wave or Zigbee",
            "requirements": ["exact radio variant"],
        }
    ],
}


def product(name, identity="upc:test"):
    return {"name": name, "identity": identity}


def test_exact_identity_override_beats_text_capability_guess():
    result = evaluate_compatibility(
        MATRIX,
        product("Matter Thread smart lock", identity="upc:exact"),
    )
    assert result["status"] == "variant_required"
    assert result["basis"] == "exact_identity"


def test_matter_thread_is_verified_with_requirements():
    result = evaluate_compatibility(MATRIX, product("Matter over Thread smart lock"))
    assert result["status"] == "verified_with_requirements"
    assert result["integration"] == "Matter"
    assert "Thread border router" in result["requirements"]


def test_wifi_alone_never_becomes_compatibility_proof():
    result = evaluate_compatibility(MATRIX, product("WiFi fingerprint smart lock"))
    assert result["status"] == "unknown"
    assert result["integration"] is None


def test_vendor_solar_inverter_is_candidate_until_exact_model_clears():
    result = evaluate_compatibility(MATRIX, product("GoodWe hybrid solar inverter"))
    assert result["status"] == "candidate"
    assert result["integration"] == "GoodWe"


def test_ruled_out_compatibility_blocks_gated_hunt():
    assert compatibility_allows_hunt({"status": "ruled_out"}, "haos") is False
    assert compatibility_allows_hunt({"status": "candidate"}, "haos") is True
    assert compatibility_allows_hunt({"status": "ruled_out"}, None) is True
