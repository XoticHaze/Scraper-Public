from __future__ import annotations

import json
from pathlib import Path

from deal_engine.hunts import match_profile


PROFILES = {
    p["id"]: p
    for p in json.loads(Path("app/hunts.json").read_text(encoding="utf-8"))["profiles"]
}


def product(name: str, *, category: str = "Uncategorized", brand: str | None = None):
    return {"name": name, "category": category, "brand": brand}


def lot(**kwargs):
    base = {
        "condition": "LIKE NEW",
        "retail_price": 300,
        "deal_score": 60,
        "unique_bidders": 1,
    }
    base.update(kwargs)
    return base


def test_large_gaming_monitor_accepts_semantic_signals_and_rejects_accessories():
    assert match_profile(
        PROFILES["large-gaming-monitors"],
        product('Samsung Odyssey G9 49" Curved Gaming Monitor'),
        lot(),
    )
    assert not match_profile(
        PROFILES["large-gaming-monitors"],
        product("Heavy Duty Dual Monitor Arm Stand"),
        lot(),
    )


def test_curved_monitor_requires_real_curved_signal():
    assert match_profile(
        PROFILES["curved-monitors"],
        product("Dell 34 Curved Gaming Monitor 144Hz"),
        lot(),
    )
    assert not match_profile(
        PROFILES["curved-monitors"],
        product("Dell 34 Gaming Monitor 144Hz"),
        lot(),
    )


def test_rug_profile_preserves_size_color_intent_and_excludes_runner_pad():
    assert match_profile(
        PROFILES["large-area-rugs"],
        product("9x12 Navy Blue Geometric Area Rug"),
        lot(),
    )
    assert not match_profile(
        PROFILES["large-area-rugs"],
        product("Blue Runner Rug 2x8"),
        lot(),
    )
    assert not match_profile(
        PROFILES["large-area-rugs"],
        product("8x10 Rug Pad"),
        lot(),
    )


def test_haos_camera_profile_requires_pan_tilt_and_excludes_non_ptz_camera_noise():
    match = match_profile(
        PROFILES["ptz-cameras-haos"],
        product("Reolink PTZ PoE Security Camera with ONVIF and Optical Zoom"),
        lot(),
    )
    assert match
    assert match["compatibility_gate"] == "haos"
    assert "haos_compatibility" in match["verification"]
    assert not match_profile(
        PROFILES["ptz-cameras-haos"],
        product("4K PTZ Webcam for Video Calls"),
        lot(),
    )
    assert not match_profile(
        PROFILES["ptz-cameras-haos"],
        product("Kodak Digital Camera 4X Optical Zoom"),
        lot(),
    )
    assert not match_profile(
        PROFILES["ptz-cameras-haos"],
        product("Ring Solar Panel Charger for Security Cameras"),
        lot(),
    )


def test_solar_panel_profile_rejects_accessories_and_camera_bundles():
    assert match_profile(
        PROFILES["solar-panels"],
        product("Renogy 400W Portable Solar Panel Blanket"),
        lot(),
    )
    assert not match_profile(
        PROFILES["solar-panels"],
        product("Solar Panel Tilt Mount Bracket"),
        lot(),
    )
    assert not match_profile(
        PROFILES["solar-panels"],
        product("Security Camera with Solar Panel"),
        lot(),
    )


def test_smart_lock_profile_requires_connected_smart_signal_and_haos_verification():
    match = match_profile(
        PROFILES["smart-door-locks-haos"],
        product("Schlage Connect Z-Wave Smart Deadbolt"),
        lot(),
    )
    assert match
    assert match["compatibility_gate"] == "haos"
    assert not match_profile(
        PROFILES["smart-door-locks-haos"],
        product("Bluetooth Padlock with Keypad"),
        lot(),
    )
    assert not match_profile(
        PROFILES["smart-door-locks-haos"],
        product("Kwikset Single Cylinder Deadbolt Lock"),
        lot(),
    )


def test_apple_profile_rejects_accessory_mentions():
    assert match_profile(PROFILES["apple-devices"], product("Apple MacBook Air M3 512GB"), lot())
    assert not match_profile(
        PROFILES["apple-devices"],
        product("Adjustable Laptop Stand for MacBook Pro Air"),
        lot(),
    )
    assert not match_profile(
        PROFILES["apple-devices"],
        product("Replacement Battery for MacBook Pro"),
        lot(),
    )


def test_ranked_tech_terms_use_word_boundaries_not_substrings():
    tech = PROFILES["best-tech-deals"]
    assert match_profile(tech, product("Dell Gaming Monitor"), lot())
    assert not match_profile(tech, product("ECOTRIC UTV Windshield"), lot())
    assert not match_profile(tech, product("Karaoke Machine with Microphones"), lot())
    assert not match_profile(tech, product("Klipsch Tabletop Decor Stand"), lot())


def test_ranked_resale_profile_is_value_and_competition_gated():
    assert match_profile(PROFILES["resale-watch"], product("Brand Name Tool"), lot())
    assert not match_profile(
        PROFILES["resale-watch"],
        product("Brand Name Tool"),
        lot(unique_bidders=8),
    )
    assert not match_profile(
        PROFILES["resale-watch"],
        product("Replacement Part"),
        lot(),
    )
