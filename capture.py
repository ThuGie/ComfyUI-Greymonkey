"""Shared capture catalog resolver with per-dimension override semantics."""
import json
from pathlib import Path
from . import client
from .contracts import envelope, entries


def catalog():
    data = client.catalog().get("capture_catalog")
    if data is None:
        data = json.loads((Path(__file__).parent / "capture-catalog.json").read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise client.GreymonkeyError("Unsupported capture catalog version. Refresh or reinstall.")
    return data


def resolve(preset, **choices):
    data = catalog()
    if preset not in data["presets"]:
        raise client.GreymonkeyError("Unknown camera preset; your saved choice has not been reset.")
    ids = list(data["presets"][preset])
    metadata = {e["id"]: e for e in entries("global_details")}
    device = choices.get("device", "Unspecified")
    method = choices.get("capture_method", "Unspecified")
    nonphone = device in ("Compact digital camera", "Disposable film camera")
    if nonphone:
        ids = [i for i in ids if not i.startswith("phone_lifestyle_")]
        if method in ("Front-camera selfie", "Rear-camera mirror selfie", "Rear-camera candid", "Phone timer"):
            raise client.GreymonkeyError("The selected capture method requires a phone; choose a phone device or Unspecified method.")
        if choices.get("processing") == "Phone HDR" or choices.get("flash") == "Direct phone flash":
            raise client.GreymonkeyError("Phone HDR/phone flash requires a phone device.")
        if choices.get("lens") == "Front selfie lens" or choices.get("focus") == "Eyes and phone in focus":
            raise client.GreymonkeyError("Phone lens/focus cannot be combined with this non-phone camera.")
    if choices.get("focus") == "Eyes and phone in focus" and method != "Rear-camera mirror selfie":
        raise client.GreymonkeyError("Eyes and reflected-phone focus requires Rear-camera mirror selfie.")
    if choices.get("lens") == "Front selfie lens" and method in ("Rear-camera mirror selfie", "Rear-camera candid"):
        raise client.GreymonkeyError("A front selfie lens conflicts with a rear-camera capture method.")
    for dimension, value in choices.items():
        options = data["dimensions"].get(dimension)
        if options is None or value not in options:
            raise client.GreymonkeyError(f"Unsupported camera {dimension}: {value}.")
        selected = options[value]
        if selected is None:
            continue
        replaced = data["replace_slots"].get(dimension, [])
        ids = [i for i in ids if metadata.get(i, {}).get("slot") not in replaced]
        # Older catalogs lack slots, but still carry the published legacy IDs.
        legacy = {"noise": [0, 1, 2], "focus": [5, 6], "compression": [3, 4], "device": [8, 9], "lens": [10], "camera_angle": [11]}.get(dimension, [])
        ids = [i for i in ids if i not in ["phone_lifestyle_quality_" + str(n) for n in legacy]]
        ids.append(selected)
    ids = list(dict.fromkeys(ids))
    if len(ids) > 32:
        raise client.GreymonkeyError("Too many capture selections.")
    return envelope("capture", global_detail_ids=ids, preset=preset, choices=choices)
