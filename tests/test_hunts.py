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


def test_haos_camera_profile_finds_ptz_onvif_and_excludes_webcams():
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


def test_smart_lock_profile_requires_real_door_lock_and_haos_verification():
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
