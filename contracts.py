"""Versioned, JSON-compatible node contracts. No network or random work at import."""
import copy
import hashlib
import json
import random
import re
from . import client

VERSION = 1
ENTITY_TYPES = ("person", "animal", "product")
SCENE_TYPES = (*ENTITY_TYPES, "landscape", "architecture", "poster")
COLORS = {"black": "#000000", "white": "#FFFFFF", "red": "#DC2626", "orange": "#F97316", "yellow": "#EAB308", "green": "#16A34A", "teal": "#0D9488", "blue": "#2563EB", "navy": "#172554", "purple": "#9333EA", "pink": "#EC4899", "brown": "#854D0E", "grey": "#808080", "cream": "#FFFDD0", "gold": "#FFD700", "silver": "#C0C0C0"}


def entry_id(value):
    if value in ("Random", "random", "Unspecified", "unspecified", "None", "none", ""):
        return None
    return str(value).rsplit("[", 1)[-1].removesuffix("]")


def entries(group):
    return client.catalog().get("controls", {}).get(group, [])


def lookup(group, value, kind=None):
    selected = entry_id(value)
    if selected is None:
        return None
    aliases = client.catalog().get("option_aliases", {})
    seen = set()
    while selected in aliases:
        if selected in seen or not isinstance(aliases[selected], str):
            raise client.GreymonkeyError("Invalid cyclic option migration in the catalog.")
        seen.add(selected)
        selected = aliases[selected]
    item = next((e for e in entries(group) if e["id"] == selected), None)
    if item is None:
        raise client.GreymonkeyError(f"Saved {group} option {selected!r} is absent from the catalog. Refresh the catalog or select its replacement; it has not been reset.")
    if kind and kind not in item.get("types", [item.get("type")]):
        raise client.GreymonkeyError(f"{item['name']} is not compatible with subject type {kind}. Select a matching identity/detail or switch subject type.")
    return item


def envelope(kind, **data):
    return {"schema_version": VERSION, "kind": kind, **data}


def check(value, kind, allowed):
    if not isinstance(value, dict) or value.get("schema_version") != VERSION or value.get("kind") != kind:
        raise client.GreymonkeyError(f"Connect a supported Greymonkey {kind} output.")
    if set(value) - {"schema_version", "kind", *allowed}:
        raise client.GreymonkeyError(f"Unknown fields in {kind} input.")
    return copy.deepcopy(value)


def details(value):
    if value is None:
        return []
    data = check(value, "details", {"items"})
    if not isinstance(data.get("items"), list) or len(data["items"]) > 64:
        raise client.GreymonkeyError("Use at most 64 subject detail items.")
    slots = {}
    for item in data["items"]:
        if not isinstance(item, dict) or set(item) - {"id", "color", "weight"} or not isinstance(item.get("id"), str):
            raise client.GreymonkeyError("Malformed subject detail item.")
        e = lookup("details", item["id"])
        slot = e.get("slot")
        if slot and slot in slots and slots[slot] != item["id"]:
            raise client.GreymonkeyError(f"Two explicitly selected details compete for {slot}: {slots[slot]} and {item['id']}.")
        if slot:
            slots[slot] = item["id"]
        color = item.get("color")
        if color is not None and (not e.get("colorable") or not isinstance(color, str) or color != "random" and not re.fullmatch(r"#[0-9A-Fa-f]{6}", color)):
            raise client.GreymonkeyError("This detail does not support the selected color.")
        weight = item.get("weight", 1.0)
        if type(weight) not in (int, float) or not 0.1 <= weight <= 2.0:
            raise client.GreymonkeyError("Detail weight must be between 0.1 and 2.0.")
    return data["items"]


def scene(value):
    data = check(value, "scene", {"mode", "scene_type", "subject_count", "species_pool", "subjects", "legacy_choices"})
    if data.get("mode") == "random":
        if "subjects" in data:
            raise client.GreymonkeyError("Random scenes cannot also contain an explicit subject chain.")
        if data.get("scene_type") not in SCENE_TYPES or data.get("species_pool") not in ("mixed", "human", "fantasy"):
            raise client.GreymonkeyError("Invalid random scene recipe.")
        legacy = data.get("legacy_choices", {})
        if not isinstance(legacy, dict) or set(legacy) - {"gender", "hybrid_type"} or legacy.get("gender", "random") not in ("random", "female", "male", "nonbinary") or not isinstance(legacy.get("hybrid_type", "none"), str):
            raise client.GreymonkeyError("Malformed legacy random-scene preferences.")
        count = data.get("subject_count")
        if type(count) is not int or (not 1 <= count <= 8 if data["scene_type"] in ENTITY_TYPES else count != 0):
            raise client.GreymonkeyError("Entity scenes need 1â€“8 subjects; other scenes need zero.")
    elif data.get("mode") == "subjects":
        if set(data) - {"schema_version", "kind", "mode", "subjects"}:
            raise client.GreymonkeyError("Subject chains cannot also contain random-scene settings.")
        actors = data.get("subjects")
        if not isinstance(actors, list) or not 1 <= len(actors) <= 8:
            raise client.GreymonkeyError("A subject chain must contain 1â€“8 entries.")
        seen = set()
        for actor in actors:
            if not isinstance(actor, dict) or set(actor) - {"ref", "type", "selected_ids", "colors", "weights", "details", "interactions", "allow_random_props", "allow_random_magic", "random_related", "creator_settings"}:
                raise client.GreymonkeyError("Malformed subject entry.")
            ref = actor.get("ref")
            if not isinstance(ref, str) or not ref or ref in seen or actor.get("type") not in ENTITY_TYPES:
                raise client.GreymonkeyError("Subject references must be unique and have valid entity types.")
            seen.add(ref)
            selected = actor.get("selected_ids", [])
            if not isinstance(selected, list) or len(selected) > 256 or any(not isinstance(i, str) or not i for i in selected):
                raise client.GreymonkeyError("Subject selections must be a list of option IDs.")
            for field in ("colors", "weights", "details"):
                if field in actor and not isinstance(actor[field], dict):
                    raise client.GreymonkeyError(f"Subject {field} must be an object.")
            for option_id, color in actor.get("colors", {}).items():
                if option_id not in selected or not isinstance(color, dict) or set(color) != {"hex"} or not isinstance(color["hex"], str) or color["hex"] != "random" and not re.fullmatch(r"#[0-9A-Fa-f]{6}", color["hex"]):
                    raise client.GreymonkeyError("Invalid owned subject color.")
            for option_id, weight in actor.get("weights", {}).items():
                if option_id not in selected or type(weight) not in (int, float) or not 0.1 <= weight <= 2:
                    raise client.GreymonkeyError("Invalid owned subject weight.")
            if "creator_settings" in actor:
                from .creator import settings
                actor["creator_settings"] = settings(actor["creator_settings"])
            link_request = actor.get("random_related")
            if link_request is not None and (not isinstance(link_request, dict) or set(link_request) != {"action"} or link_request["action"] not in ("none", "next_to", "in_front_of", "behind", "looking_at", "leaning_against", "inside", "sitting_driver", "sitting_passenger", "driving", "entering", "exiting", "sitting_hood", "holding", "reading", "drinking_from", "speaking_into", "singing_into", "recording_with", "holding_near_face", "holding_at_chest", "holding_two_handed", "holding_left_hand", "holding_right_hand", "holding_delicately", "holding_on_palm", "holding_at_arm_length", "throwing")):
                raise client.GreymonkeyError("Invalid random related-object request.")
            if not isinstance(actor.get("interactions", []), list):
                raise client.GreymonkeyError("Subject interactions must be a list.")
            for flag in ("allow_random_props", "allow_random_magic"):
                if flag in actor and type(actor[flag]) is not bool:
                    raise client.GreymonkeyError(f"Invalid {flag} flag.")
        for actor in actors:
            for link in actor.get("interactions", []):
                if not isinstance(link, dict) or set(link) != {"target_ref", "action"} or link["target_ref"] not in seen or link["target_ref"] == actor["ref"]:
                    raise client.GreymonkeyError("A relationship must target another existing subject.")
    else:
        raise client.GreymonkeyError("Unknown scene recipe mode.")
    return data


def request_scene(recipe, seed, generation_theme=None):
    recipe = scene(recipe)
    if recipe["mode"] == "random":
        return ({k: recipe[k] for k in ("scene_type", "subject_count", "species_pool")} |
                {"hybrid_type": "random" if recipe["scene_type"] == "person" and recipe["species_pool"] != "human" else "none"} |
                recipe.get("legacy_choices", {}))
    actors = copy.deepcopy(recipe["subjects"])
    rng = random.Random(seed)
    for actor in actors:
        random_link = actor.pop("random_related", None)
        if random_link is not None:
            action = random_link["action"]
            if generation_theme == "influencer" or "subject_direction_influencer" in actor.get("selected_ids", []):
                actor["creator_related_action"] = action
                continue
            candidates = [e for e in entries("identities") if e.get("type") == "product"]
            if action in ("inside", "sitting_driver", "sitting_passenger", "driving", "entering", "exiting"):
                candidates = [e for e in candidates if e.get("capabilities", {}).get("vehicle_cabin")]
            if action == "sitting_hood":
                candidates = [e for e in candidates if e.get("capabilities", {}).get("vehicle_hood")]
            if action == "leaning_against":
                candidates = [e for e in candidates if e.get("capabilities", {}).get("object_kind") in ("vehicle", "furniture", "scenery")]
            if action in ("speaking_into", "singing_into", "recording_with"):
                candidates = [e for e in candidates if "microphone" in (e.get("name", "") + e["id"]).lower()]
            if not candidates:
                raise client.GreymonkeyError(f"No related objects support {action} in the catalog.")
            chosen = rng.choice(sorted(candidates, key=lambda e: e["id"]))
            related_ref = actor["ref"] + ":related"
            if any(a["ref"] == related_ref for a in actors):
                raise client.GreymonkeyError("The related-object reference collides with an existing subject.")
            actors.append(dict(ref=related_ref, type="product", selected_ids=[chosen["id"]], colors={}, weights={}, details={}, interactions=[], allow_random_props=False, allow_random_magic=False))
            if action != "none":
                actor.setdefault("interactions", []).append(dict(target_ref=related_ref, action=action))
    if len(actors) > 8:
        raise client.GreymonkeyError("Related objects would exceed the eight-subject limit.")
    for actor in actors:
        if actor.get("details", {}).get("position", "").startswith("held ") and not any(link.get("target_ref") == actor["ref"] and link.get("action", "").startswith("holding") for owner in actors for link in owner.get("interactions", [])):
            raise client.GreymonkeyError("An object with Hold position needs a person holding it. Connect Scene Object.related_object to Scene Subject.object_settings, then connect the person's scene to the generator.")
    refs = {actor["ref"]: "subject-" + str(index + 1) for index, actor in enumerate(actors)}
    overrides = []
    for actor in actors:
        item = {k: copy.deepcopy(v) for k, v in actor.items() if k != "ref"}
        item["interactions"] = [{"target_id": refs[link["target_ref"]], "action": link["action"]} for link in item.get("interactions", [])]
        overrides.append(item)
    kind = "person" if any(a["type"] == "person" for a in actors) else actors[0]["type"]
    return dict(scene_type=kind, subject_count=len(actors), species_pool="mixed", subject_overrides=overrides)


def cache_key(payload, dataset):
    value = {k: v for k, v in payload.items() if k not in ("model_id", "quality")}
    return hashlib.sha256(json.dumps([value, dataset], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
