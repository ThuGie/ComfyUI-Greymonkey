"""Composable scene-wide settings and placement; no network requests during execution."""
import copy
from . import client, contracts as c

SCENE = "GREYMONKEY_SCENE"
SETTINGS = "GREYMONKEY_SCENE_SETTINGS"
ENVIRONMENT = "GREYMONKEY_ENVIRONMENT_DETAILS"

def category_name(entry):
    return f"{entry.get('category', 'Other')} [{entry.get('category_id', entry.get('category', 'Other'))}]"

def environment_entries():
    return [e for e in c.entries("global_details") if e.get("slot") not in ("location", "time_of_day")]

def validated_environment_details(value):
    if value is None:
        return []
    data = c.check(value, "environment_details", {"ids"})
    ids = data.get("ids")
    if not isinstance(ids, list) or len(ids) > 32 or any(not isinstance(i, str) for i in ids):
        raise client.GreymonkeyError("Environment details must contain at most 32 option IDs.")
    slots = {}
    for option in ids:
        entry = c.lookup("global_details", option)
        if not entry or entry.get("slot") in ("location", "time_of_day"):
            raise client.GreymonkeyError("Choose the main location and time in Scene Settings.")
        slot = entry.get("slot")
        if slot and slot in slots and slots[slot] != entry["id"]:
            raise client.GreymonkeyError(f"Two environment choices conflict in {slot}: {slots[slot]} and {entry['id']}.")
        if slot: slots[slot] = entry["id"]
    return list(dict.fromkeys(ids))

class GreymonkeyEnvironmentDetailV2:
    CATEGORY = "Greymonkey"
    FUNCTION = "build"
    RETURN_TYPES = (ENVIRONMENT,)
    RETURN_NAMES = ("environment_details",)
    DESCRIPTION = "Chain global lighting, weather, terrain, room and atmosphere details. Objects belong in Scene Object."

    @classmethod
    def INPUT_TYPES(cls):
        entries = environment_entries()
        return {"required": {"category": (sorted({category_name(e) for e in entries}),), "option": ([f"{e['name']} [{e['id']}]" for e in entries], {"greymonkeyEntries": entries})}, "optional": {"previous_details": (ENVIRONMENT,)}}

    def build(self, category, option, previous_details=None):
        entry = c.lookup("global_details", option)
        if entry is None or category_name(entry) != category:
            raise client.GreymonkeyError("Select an environment option from its matching category.")
        ids = validated_environment_details(previous_details)
        result = c.envelope("environment_details", ids=[*ids, entry["id"]])
        validated_environment_details(result)
        return (result,)

class GreymonkeySceneSettingsV2:
    CATEGORY = "Greymonkey"
    FUNCTION = "build"
    RETURN_TYPES = (SETTINGS,)
    RETURN_NAMES = ("scene_settings",)
    DESCRIPTION = "Select the shared location and time. Connect to Prompt Generator.scene_settings; applies to every subject and object."

    @classmethod
    def INPUT_TYPES(cls):
        def choices(group):
            entries = c.entries(group)
            return (["Random", *[f"{e['name']} [{e['id']}]" for e in entries]], {"greymonkeyEntries": entries})
        return {"required": {"location": choices("locations"), "time_of_day": choices("times")}, "optional": {"environment_details": (ENVIRONMENT,)}}

    def build(self, location="Random", time_of_day="Random", environment_details=None):
        location_entry = c.lookup("locations", location)
        time_entry = c.lookup("times", time_of_day)
        return (c.envelope("scene_settings", location_id=location_entry["id"] if location_entry else "random", time_id=time_entry["id"] if time_entry else "random", global_detail_ids=validated_environment_details(environment_details)),)

def apply_settings(value, payload):
    settings = c.check(value, "scene_settings", {"location_id", "time_id", "global_detail_ids"})
    for key, group in (("location_id", "locations"), ("time_id", "times")):
        option = settings.get(key)
        if not isinstance(option, str):
            raise client.GreymonkeyError(f"Invalid scene {key}.")
        if option != "random": c.lookup(group, option)
        payload[key] = option
    ids = validated_environment_details(c.envelope("environment_details", ids=settings.get("global_detail_ids")))
    if payload.get("background") == "white" and (settings["location_id"] != "random" or ids):
        raise client.GreymonkeyError("Scene location/environment details conflict with White background. Choose Environment background or disconnect Scene Settings.")
    payload["global_detail_ids"] = list(dict.fromkeys([*payload.get("global_detail_ids", []), *ids]))
    if len(payload["global_detail_ids"]) > 32:
        raise client.GreymonkeyError("Camera and environment details together exceed 32 selections.")

class GreymonkeyScenePlacementV2:
    CATEGORY = "Greymonkey"
    FUNCTION = "build"
    RETURN_TYPES = (SCENE,)
    RETURN_NAMES = ("scene",)
    DESCRIPTION = "Add an independently configured object to a subject scene, without making anybody hold it. Chain for more objects, up to eight total entities."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene": (SCENE,), "object": ("GREYMONKEY_OBJECT",), "placement": (["as configured on Scene Object", "on a table", "on a desk", "on the floor", "on a shelf", "on a wall", "on the left side of the scene", "on the right side of the scene", "in the foreground", "in the background", "beside a subject", "behind a subject", "in front of a subject"],), "target_subject": ("INT", {"default": 1, "min": 1, "max": 8})}}

    def build(self, scene, object, placement="as configured on Scene Object", target_subject=1):
        recipe = c.scene(scene)
        if recipe["mode"] != "subjects":
            raise client.GreymonkeyError("Scene Placement needs a configured Scene Subject/Object chain. Random Scene counts are resolved later; use configured subjects when placing exact objects.")
        if placement not in self.INPUT_TYPES()["required"]["placement"][0]:
            raise client.GreymonkeyError("Choose a supported object placement.")
        data = c.check(object, "object", {"subject", "relationship"})
        if data.get("relationship") != "none":
            raise client.GreymonkeyError("For a placed object choose relationship None on Scene Object. For a held/used object connect it to Scene Subject.object_settings instead.")
        obj = copy.deepcopy(data.get("subject"))
        c.scene(c.envelope("scene", mode="subjects", subjects=[obj]))
        if obj.get("details", {}).get("position", "").startswith("held "):
            raise client.GreymonkeyError("A placed object cannot also have Hold position.")
        if any(a["ref"] == obj["ref"] for a in recipe["subjects"]):
            raise client.GreymonkeyError("That object is already in the scene. Use a separate Scene Object node for another instance.")
        if len(recipe["subjects"]) >= 8:
            raise client.GreymonkeyError("Scenes support eight total subjects and objects.")
        if placement.endswith("a subject"):
            if type(target_subject) is not int or not 1 <= target_subject <= len(recipe["subjects"]):
                raise client.GreymonkeyError("Placement target must refer to an existing preceding subject.")
            action = {"beside a subject": "next_to", "behind a subject": "behind", "in front of a subject": "in_front_of"}[placement]
            obj.setdefault("interactions", []).append({"target_ref": recipe["subjects"][target_subject - 1]["ref"], "action": action})
            obj.setdefault("details", {}).pop("position", None)
        elif placement != "as configured on Scene Object":
            if obj.get("details", {}).get("position") not in (None, "", placement):
                raise client.GreymonkeyError("Object position is set differently in Scene Object and Scene Placement. Keep one explicit placement.")
            obj.setdefault("details", {})["position"] = placement
        recipe["subjects"].append(obj)
        return (c.scene(recipe),)
