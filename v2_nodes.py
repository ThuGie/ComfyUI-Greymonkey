"""Clean v2 layouts; legacy class IDs remain registered separately."""
import copy
import json
import threading
from . import client, capture, creator
from . import contracts as c
from .nodes import CONTENT, CONTENT_ALIASES, GENDER, SPECIES, style_choices, control_choices

SCENE = "GREYMONKEY_SCENE"
DETAILS = "GREYMONKEY_DETAILS"
RESULT = "GREYMONKEY_RESULT"
RELATIONSHIPS = ["none", "kissing", "next_to", "in_front_of", "behind", "looking_at", "leaning_against", "inside", "sitting_driver", "sitting_passenger", "driving", "entering", "exiting", "sitting_hood", "holding", "reading", "drinking_from", "speaking_into", "singing_into", "recording_with", "holding_near_face", "holding_at_chest", "holding_two_handed", "holding_left_hand", "holding_right_hand", "holding_delicately", "holding_on_palm", "holding_at_arm_length", "throwing"]


def choices(group, kind=None):
    values = c.entries(group)
    return (["Random"] + [f"{e['name']} [{e['id']}]" for e in values if kind is None or kind in e.get("types", [e.get("type")])], {"greymonkeyEntries": values})


class GreymonkeyRandomSceneV2:
    CATEGORY = "Greymonkey"
    FUNCTION = "build"
    RETURN_TYPES = (SCENE,)
    RETURN_NAMES = ("scene",)
    DESCRIPTION = "Describe a random scene recipe. Generation and random choices happen only at the generator seed."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"scene_type": (list(c.SCENE_TYPES),), "subject_count": ("INT", {"default": 1, "min": 0, "max": 8}), "species_pool": (list(SPECIES),)}}

    def build(self, scene_type, subject_count=1, species_pool="All supported humanoid races"):
        if scene_type not in c.SCENE_TYPES:
            raise client.GreymonkeyError("Choose a supported random scene type.")
        result = c.envelope("scene", mode="random", scene_type=scene_type, subject_count=subject_count if scene_type in c.ENTITY_TYPES else 0, species_pool=SPECIES.get(species_pool, species_pool) if scene_type == "person" else "mixed")
        return (c.scene(result),)


class GreymonkeySubjectDetailV2:
    CATEGORY = "Greymonkey"
    FUNCTION = "build"
    RETURN_TYPES = (DETAILS,)
    RETURN_NAMES = ("subject_details",)
    DESCRIPTION = "One owned detail with an optional color and weight. Chain more detail nodes for fine control."

    @classmethod
    def INPUT_TYPES(cls):
        data = c.entries("details")
        categories = sorted({f"{e.get('category', 'Other')} [{e.get('category_id', e.get('category', 'Other'))}]" for e in data})
        return {"required": {"category": (categories or ["Other"],), "option": choices("details"), "color": (["Unspecified", "Random", *c.COLORS],), "weight": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 2.0, "step": 0.05, "greymonkeyWeightModels": [m["id"] for m in client.catalog()["models"] if "comfyui" in (m.get("capabilities") or m.get("prompt_capabilities") or {}).get("weight_workflows", [])]})}, "optional": {"previous_details": (DETAILS,)}}

    @classmethod
    def VALIDATE_INPUTS(cls, category, option):
        if not isinstance(category, str) or not isinstance(option, str):
            return "Choose a detail category and option"
        try:
            entry = c.lookup("details", option)
            if entry is None: return "Choose an actual detail option"
            if c.entry_id(category) not in (entry.get("category_id"), entry.get("category", "Other")):
                return "Detail option does not belong to this category"
            return True
        except client.GreymonkeyError as exc:
            return str(exc)

    def build(self, category, option, color="Unspecified", weight=1.0, previous_details=None):
        items = c.details(previous_details)
        entry = c.lookup("details", option)
        if entry is None:
            raise client.GreymonkeyError("Select an actual option in Subject Detail; use an unconnected detail input for unspecified details.")
        if c.entry_id(category) not in (entry.get("category_id"), entry.get("category", "Other")):
            raise client.GreymonkeyError("The selected detail belongs to a different category; select its matching category.")
        if color not in ("Unspecified", "Random", *c.COLORS):
            raise client.GreymonkeyError("Choose a supported item color.")
        if color != "Unspecified" and not entry.get("colorable"):
            raise client.GreymonkeyError("This item has no color control.")
        item = {"id": entry["id"], "weight": weight}
        if color in c.COLORS:
            item["color"] = c.COLORS[color]
        if color == "Random":
            # A marker resolved by the generator seed, not an import-time random choice.
            item["color"] = "random"
        if any(e["id"] == item["id"] for e in items):
            raise client.GreymonkeyError("This detail is already present in the chain.")
        result = c.envelope("details", items=[*items, item])
        validation_copy = copy.deepcopy(result)
        for e in validation_copy["items"]:
            if e.get("color") == "random": e.pop("color")
        c.details(validation_copy)
        return (result,)


class GreymonkeyObjectDetailV2(GreymonkeySubjectDetailV2):
    RETURN_NAMES = ("object_details",)
    DESCRIPTION = "Chain owned object details: material, finish, wheels, vehicle equipment and item colors."

    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        data = [e for e in c.entries("details") if "product" in e.get("types", [e.get("type")]) and e.get("slot") != "object_identity"]
        schema["required"]["category"] = (sorted({f"{e.get('category', 'Other')} [{e.get('category_id', e.get('category', 'Other'))}]" for e in data}),)
        schema["required"]["option"] = ([f"{e['name']} [{e['id']}]" for e in data], {"greymonkeyEntries": data})
        return schema

    def build(self, category, option, **kwargs):
        entry = c.lookup("details", option, "product")
        if entry is None or entry.get("slot") == "object_identity":
            raise client.GreymonkeyError("Choose the object's identity in Scene Object, and its properties in Object Detail.")
        return super().build(category, option, **kwargs)


class GreymonkeySceneObjectV2:
    CATEGORY = "Greymonkey"
    FUNCTION = "build"
    RETURN_TYPES = ("GREYMONKEY_OBJECT", SCENE)
    RETURN_NAMES = ("related_object", "scene")
    DESCRIPTION = "Configure an object once. Connect related_object to Scene Subject, or scene to the generator for an object-only image."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"identity": choices("identities", "product"), "color": (["Unspecified", "Random", *c.COLORS],), "relationship": ([v for v in RELATIONSHIPS if v != "kissing"],)}, "optional": {"object_details": (DETAILS,), "previous_subjects": (SCENE,), "display_text": ("STRING", {"default": "", "multiline": True, "tooltip": "Exact words printed on this object. Leave empty for no requested text."}), "text_placement": (["centered on the front", "across the upper front", "across the lower front", "on the label", "on the screen", "on the cover", "on the side", "across the front panel", "on the lid", "on a hanging tag", "on the chest print", "on the banner", "on the open pages"],), "lettering": (["large clear printed lettering", "bold sans-serif lettering", "neat handwritten lettering", "serif lettering", "typewritten lettering"],), "text_color": (["black", "white", "red", "blue", "gold", "silver"],), "face_text_to_camera": ("BOOLEAN", {"default": True}), "object_position": (["unspecified", "on a table", "on a desk", "on the floor", "on a wall", "on a shelf", "in the foreground", "beside the person"],), "hold_position": (["unspecified", "at chest height", "at waist height", "at stomach height", "at shoulder height", "at eye level", "below the chin", "beside the face", "in front of the face", "above the head", "down beside the hip", "in front of the thighs", "resting on the lap", "extended toward the camera", "out to the left side", "out to the right side"], {"default": "unspecified", "tooltip": "Where the person holds the object. Independent of the hand/grip relationship."}), "object_orientation": (["unspecified", "upright portrait orientation", "horizontal landscape orientation", "tilted slightly clockwise", "tilted slightly counterclockwise"], {"default": "unspecified"})}, "hidden": {"unique_id": "UNIQUE_ID"}}

    def build(self, identity, color="Unspecified", relationship="none", object_details=None, previous_subjects=None, unique_id=None, display_text="", text_placement="centered on the front", lettering="large clear printed lettering", text_color="black", face_text_to_camera=True, object_position="unspecified", hold_position="unspecified", object_orientation="unspecified"):
        entry = c.lookup("identities", identity, "product")
        if entry is None:
            raise client.GreymonkeyError("Select an object identity in Scene Object; use the existing Random Scene node for unconstrained random objects.")
        if relationship not in RELATIONSHIPS or relationship == "kissing":
            raise client.GreymonkeyError("Choose an object-compatible relationship.")
        ids, colors, weights = [entry["id"]], {}, {}
        if color not in ("Unspecified", "Random", *c.COLORS):
            raise client.GreymonkeyError("Choose a supported object color.")
        if color != "Unspecified":
            if not entry.get("colorable"):
                raise client.GreymonkeyError("This object does not support a direct identity color; use a colorable Object Detail.")
            colors[entry["id"]] = {"hex": "random" if color == "Random" else c.COLORS[color]}
        for item in c.details(object_details):
            detail = c.lookup("details", item["id"], "product")
            if detail.get("slot") == "object_identity":
                raise client.GreymonkeyError("Object Detail cannot replace the Scene Object identity.")
            ids.append(item["id"])
            if item.get("color"): colors[item["id"]] = {"hex": item["color"]}
            if item.get("weight", 1) != 1: weights[item["id"]] = item["weight"]
        actor = dict(ref="object:" + str(unique_id or entry["id"]), type="product", selected_ids=list(dict.fromkeys(ids)), colors=colors, weights=weights, details={}, interactions=[], allow_random_props=False, allow_random_magic=False)
        if not isinstance(display_text, str) or len(display_text) > 1000 or any(ord(ch) < 32 and ch not in "\n\t\r" for ch in display_text):
            raise client.GreymonkeyError("Object text must contain at most 1,000 characters without control characters.")
        allowed = self.INPUT_TYPES()["optional"]
        for field, value in (("text_placement", text_placement), ("lettering", lettering), ("text_color", text_color), ("object_position", object_position), ("hold_position", hold_position), ("object_orientation", object_orientation)):
            if value not in allowed[field][0]:
                raise client.GreymonkeyError(f"Choose a supported {field.replace('_', ' ')}.")
        if type(face_text_to_camera) is not bool:
            raise client.GreymonkeyError("Text-facing-camera must be enabled or disabled.")
        holding = relationship.startswith("holding")
        if hold_position != "unspecified" and not holding:
            raise client.GreymonkeyError("Hold position needs a holding relationship, such as holding_two_handed or holding_left_hand.")
        if holding and object_position != "unspecified":
            raise client.GreymonkeyError("Use Hold position for a held object; leave Object position unspecified. Object position is for placed objects.")
        fixed_positions = {"holding_at_chest": "at chest height", "holding_near_face": "beside the face", "holding_at_arm_length": "extended toward the camera"}
        if hold_position != "unspecified" and relationship in fixed_positions and hold_position != fixed_positions[relationship]:
            raise client.GreymonkeyError("The relationship already specifies a different holding position. Choose a plain holding grip, then set Hold position.")
        if hold_position != "unspecified":
            actor["details"]["position"] = f"held {hold_position} by the person holding it"
        elif object_position != "unspecified":
            actor["details"]["position"] = object_position
        if object_orientation != "unspecified":
            actor["details"]["features"] = object_orientation
        if entry["id"] == "text_surface_a4_paper":
            actor["details"]["dimensions"] = "a thin rectangular A4 sheet with its natural 1:1.414 proportions"
            paper_shape = "flexible unmounted paper with a gentle uneven bow, subtle corner curl and a few faint handling creases; slight natural perspective foreshortening"
            if holding:
                paper_shape += "; fingertips lightly indent the edges at the grip points, with small contact shadows and slight buckling around the fingers"
            actor["details"]["features"] = ", ".join(filter(None, [actor["details"].get("features"), paper_shape]))
        if display_text.strip():
            quoted = json.dumps(display_text, ensure_ascii=False)
            actor["details"]["description"] = f'The {entry["name"]} bears the exact text {quoted}, {text_placement}, in {text_color} {lettering}.'
            if face_text_to_camera:
                actor["details"]["description"] += " Its text-bearing surface is directed toward the camera at a natural angle, with the lettering readable and not covered by the grip. The lettering follows the surface curvature and perspective."
        if entry["id"].startswith("text_surface_"):
            actor["details"].setdefault("material", entry.get("capabilities", {}).get("default_material", "paper" if entry["id"] == "text_surface_a4_paper" else "cardstock" if entry["id"] in ("text_surface_card", "text_surface_poster") else "a flat sign surface"))
        previous = c.scene(previous_subjects)["subjects"] if previous_subjects is not None else []
        payload = c.envelope("object", subject=actor, relationship=relationship)
        return payload, c.scene(c.envelope("scene", mode="subjects", subjects=[*previous, actor]))


class GreymonkeySceneSubjectV2:
    CATEGORY = "Greymonkey"
    FUNCTION = "build"
    RETURN_TYPES = (SCENE,)
    RETURN_NAMES = ("scene",)
    DESCRIPTION = "Build people, animals or objects with stable ownership. Whole-image landscape/poster choices belong in Random Scene."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "subject_type": (list(c.ENTITY_TYPES),), "identity": choices("identities"), "gender": (list(GENDER),),
            "ethnicity": choices("ethnicities"), "hair_color": choices("hair_colors"), "hair_length": choices("hair_lengths"),
            "magic": (["None", *choices("magic")[0]], {"default": "None"}),
            "position": (["unspecified", "left", "center", "right", "foreground", "middle distance", "background"],),
            "relative_size": (["unspecified", "small within the frame", "medium within the frame", "large within the frame"],),
            "related_object": (["None", *choices("identities", "product")[0]], {"default": "None"}),
            "relationship": (RELATIONSHIPS,), "target_subject": ("INT", {"default": 1, "min": 1, "max": 8, "tooltip": "With no related object, target a preceding subject by its displayed chain position."}),
        }, "optional": {"previous_subjects": (SCENE,), "subject_details": (DETAILS,), "creator_settings": ("GREYMONKEY_CREATOR",), "subject_style": (["Default", "Influencer"], {"default": "Default", "tooltip": "Per-person expressions and body posing; independent of the scene theme."}), "object_settings": ("GREYMONKEY_OBJECT",)}, "hidden": {"unique_id": "UNIQUE_ID"}}

    def build(self, subject_type, identity="Random", gender="Random / varied", ethnicity="Random", hair_color="Random", hair_length="Random", magic="None", position="unspecified", relative_size="unspecified", related_object="None", relationship="none", target_subject=1, previous_subjects=None, subject_details=None, unique_id=None, subject_style="Default", creator_settings=None, object_settings=None):
        if subject_type not in c.ENTITY_TYPES or relationship not in RELATIONSHIPS:
            raise client.GreymonkeyError("Invalid subject type or relationship.")
        previous = []
        if previous_subjects is not None:
            recipe = c.scene(previous_subjects)
            if recipe["mode"] != "subjects":
                raise client.GreymonkeyError("Connect a Scene Subject chain, not a Random Scene, to previous_subjects.")
            previous = recipe["subjects"]
        ref = "node:" + str(unique_id) if unique_id is not None else "subject:" + str(len(previous) + 1)
        if any(e["ref"] == ref for e in previous):
            raise client.GreymonkeyError("A subject node cannot occur twice in the same chain.")
        ids = []
        for group, value in [("identities", identity), ("ethnicities", ethnicity), ("hair_colors", hair_color), ("hair_lengths", hair_length), ("magic", magic)]:
            if subject_type != "person" and group != "identities":
                # Hidden remembered person choices do not apply to other entity types.
                continue
            item = c.lookup(group, value, subject_type)
            if item: ids.append(item["id"])
        if subject_type == "person":
            resolved_gender = GENDER.get(gender, gender)
            if resolved_gender not in ("random", "female", "male", "nonbinary"):
                raise client.GreymonkeyError("Choose a valid gender.")
            if resolved_gender != "random": ids.append("subject_gender_" + resolved_gender)
        if subject_style not in ("Default", "Influencer"):
            raise client.GreymonkeyError("Choose Default or Influencer subject style.")
        if subject_type == "person" and subject_style == "Influencer":
            ids.append("subject_direction_influencer")
        if relationship == "kissing" and (subject_type != "person" or related_object not in ("None", "none")):
            raise client.GreymonkeyError("Kissing requires another person in the subject chain, not a related object.")
        owned = c.details(subject_details)
        colors, weights = {}, {}
        related_ids, related_colors, related_weights, related_slots = [], {}, {}, {}
        related_identity = c.lookup("identities", related_object, "product") if related_object not in ("None", "none", "Random", "random") else None
        slots = {e.get("slot"): e["id"] for e in c.entries("details") if e["id"] in ids and e.get("slot")}
        for item in owned:
            entry = c.lookup("details", item["id"])
            types = entry.get("types", [entry.get("type")])
            if subject_type not in types and "product" in types and related_identity is not None:
                slot = entry.get("slot")
                if slot == "object_identity":
                    raise client.GreymonkeyError("Choose the related object's identity in Related Object, not in the person's detail chain.")
                if slot and slot in related_slots and related_slots[slot] != item["id"]:
                    raise client.GreymonkeyError(f"Related object details both specify {slot}; keep one explicit choice.")
                if slot: related_slots[slot] = item["id"]
                related_ids.append(item["id"])
                if item.get("color"): related_colors[item["id"]] = {"hex": item["color"]}
                if item.get("weight", 1) != 1: related_weights[item["id"]] = item["weight"]
                continue
            entry = c.lookup("details", item["id"], subject_type)
            slot = entry.get("slot")
            if slot and slot in slots and slots[slot] != item["id"]:
                raise client.GreymonkeyError(f"Subject controls and details both specify {slot}; keep one explicit choice.")
            if slot: slots[slot] = item["id"]
            ids.append(item["id"])
            if item.get("color"): colors[item["id"]] = {"hex": item["color"]}
            if item.get("weight", 1) != 1: weights[item["id"]] = item["weight"]
        if magic in ("None", "none") and any(c.lookup("details", i["id"]).get("slot", "").startswith("magic_") for i in owned):
            raise client.GreymonkeyError("Magic is None but a connected detail selects magic. Enable a discipline or choose Random.")
        actor = dict(ref=ref, type=subject_type, selected_ids=list(dict.fromkeys(ids)), colors=colors, weights=weights, details={}, interactions=[], allow_random_props=related_object not in ("None", "none"), allow_random_magic=subject_type == "person" and magic not in ("None", "none"))
        if creator_settings is not None:
            if not isinstance(creator_settings, dict) or set(creator_settings) != {"schema_version", "kind", "settings"} or creator_settings.get("kind") != "creator" or creator_settings.get("schema_version") != 1:
                raise client.GreymonkeyError("Connect a valid Influencer Settings node.")
            actor["creator_settings"] = creator.settings(creator_settings["settings"])
        if position != "unspecified": actor["details"]["position"] = position
        if relative_size != "unspecified": actor["details"]["dimensions"] = relative_size
        added = []
        if object_settings is not None:
            if related_object not in ("None", "none") or related_ids:
                raise client.GreymonkeyError("A Scene Object is connected: keep the legacy Related Object dropdown at None and put object details on Scene Object.")
            data = c.check(object_settings, "object", {"subject", "relationship"})
            obj = data.get("subject")
            c.scene(c.envelope("scene", mode="subjects", subjects=[obj]))
            action = data.get("relationship")
            if action not in RELATIONSHIPS or action == "kissing":
                raise client.GreymonkeyError("Invalid Scene Object relationship.")
            if relationship != "none" and relationship != action:
                raise client.GreymonkeyError("Relationship is set twice; keep Scene Subject relationship None and choose it on Scene Object.")
            if obj["ref"] == ref or any(a["ref"] == obj["ref"] for a in previous):
                raise client.GreymonkeyError("This object already occurs in the chain. Target its existing subject position instead of inserting it twice.")
            actor["allow_random_props"] = True
            added.append(copy.deepcopy(obj))
            if action != "none": actor["interactions"].append(dict(target_ref=obj["ref"], action=action))
            held_position = obj.get("details", {}).get("position", "")
            if action.startswith("holding") and held_position.startswith("held "):
                height = held_position.removeprefix("held ").removesuffix(" by the person holding it")
                name = c.lookup("identities", obj["selected_ids"][0], "product")["name"]
                grip = {"holding_two_handed": "with both hands", "holding_left_hand": "in the left hand", "holding_right_hand": "in the right hand", "holding_delicately": "with a delicate fingertip grip", "holding_on_palm": "on an open palm"}.get(action, "in the hands")
                placement = f"Holding the {name} {grip} {height}."
                if height == "at stomach height":
                    placement += " The center of the object is directly in front of the abdomen at navel level, with the hands alongside the stomach and the chest visible above the object."
                elif height == "at waist height":
                    placement += " The object is centered at the waistline, with the hands lowered to waist level and the chest visible above it."
                prior = actor["details"].get("interaction", "")
                actor["details"]["interaction"] = " ".join(filter(None, [prior, placement]))

        elif related_object in ("Random", "random"):
            actor["random_related"] = {"action": relationship}
        elif related_object not in ("None", "none"):
            obj = related_identity
            related_ref = ref + ":related"
            added.append(dict(ref=related_ref, type="product", selected_ids=list(dict.fromkeys([obj["id"], *related_ids])), colors=related_colors, weights=related_weights, details={}, interactions=[], allow_random_props=False, allow_random_magic=False))
            if relationship != "none": actor["interactions"].append(dict(target_ref=related_ref, action=relationship))
        elif relationship != "none":
            if type(target_subject) is not int or not 1 <= target_subject <= len(previous):
                raise client.GreymonkeyError("Select a preceding subject as the relationship target, or choose a related object. Self/forward links are invalid.")
            actor["interactions"].append(dict(target_ref=previous[target_subject - 1]["ref"], action=relationship))
        return (c.scene(c.envelope("scene", mode="subjects", subjects=[*previous, actor, *added])),)


class GreymonkeyPromptGeneratorV2:
    CATEGORY = "Greymonkey"
    FUNCTION = "generate"
    RETURN_TYPES = ("STRING", "STRING", "INT", "STRING", RESULT)
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "prompt_seed", "generation_info", "generation_result")
    DESCRIPTION = "Generate from Scene Subject or Random Scene. Model switches reuse the last resolved scene without refilling."

    def __init__(self):
        self._cached = None
        self._generation_lock = threading.Lock()

    @classmethod
    def INPUT_TYPES(cls):
        data = client.catalog()
        return {"required": {"model_id": ([m["id"] for m in data["models"] if m.get("comfyui", True)], {"default": data["defaults"]["model_id"]}), "content_mode": (list(CONTENT),), "generation_theme": (data["settings"].get("generation_theme", ["mixed", "everyday", "fantasy"]),), "art_style": (style_choices(data),), "detail_level": (["rich", "standard"],), "background": (["environment", "white"],), "pose_mode": (["random", "static"],), "aspect_ratio": (data["settings"]["aspect_ratio"],), "quality": (["recommended", "quick", "quality"],), "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647, "control_after_generate": True}), "scene": (SCENE,)}, "optional": {"capture_settings": ("GREYMONKEY_CAPTURE",)}}

    @classmethod
    def VALIDATE_INPUTS(cls, model_id):
        return True if isinstance(model_id, str) and model_id else "Choose a model ID"

    def generate(self, model_id, content_mode, generation_theme, art_style, detail_level, background, pose_mode, aspect_ratio, quality, seed, scene, capture_settings=None):
        if type(seed) is not int or not 0 <= seed <= 2147483647:
            raise client.GreymonkeyError("Prompt seed must be between 0 and 2147483647.")
        recipe = c.scene(scene)
        payload = c.request_scene(recipe, seed, generation_theme)
        # Random colors are sampled once from the same seed and remain owner-scoped.
        import random
        rng = random.Random(seed)
        for actor in payload.get("subject_overrides", []):
            for value in actor.get("colors", {}).values():
                if value.get("hex") == "random": value["hex"] = rng.choice(list(c.COLORS.values()))
        payload.update(model_id=model_id, content_mode=CONTENT.get(content_mode) or CONTENT_ALIASES.get(content_mode, content_mode), generation_theme="mixed" if generation_theme == "random" else generation_theme, art_style=c.entry_id(art_style) or "random", detail_level=detail_level, background=background, pose_mode=pose_mode, aspect_ratio=aspect_ratio, quality=quality, seed=seed, global_detail_ids=[])
        if capture_settings is not None:
            if not isinstance(capture_settings, dict):
                raise client.GreymonkeyError("Connect a supported Camera Style output.")
            if capture_settings.get("kind") == "capture":
                selected_capture = c.check(capture_settings, "capture", {"global_detail_ids", "preset", "choices"})
            else:
                # Published legacy camera output adapter.
                if set(capture_settings) != {"global_detail_ids"}:
                    raise client.GreymonkeyError("Unknown fields in legacy capture input.")
                selected_capture = capture_settings
            ids = selected_capture.get("global_detail_ids")
            if not isinstance(ids, list) or len(ids) > 32 or any(not isinstance(i, str) for i in ids):
                raise client.GreymonkeyError("Malformed Camera Style output.")
            payload["global_detail_ids"] = list(dict.fromkeys(ids))
        cat = client.catalog()
        dataset = cat.get("dataset_version") or cat.get("catalog_pagination", {}).get("dataset_version", "bundled")
        key = c.cache_key(payload, [dataset, cat.get("generator_version")])
        with self._generation_lock:
            if self._cached and self._cached["key"] == key:
                old = self._cached["result"]
                result = client.format_scene(dict(model_id=model_id, scene=old["scene"], seed=seed, dataset_version=old["dataset_version"], generator_version=old.get("generator_version"), quality=quality))
            else:
                result = client.generate(payload)
            self._cached = {"key": key, "result": copy.deepcopy(result)}
        warnings = list(result["validation"]["warnings"])
        info = {k: result[k] for k in ("api_version", "model_id", "profile_version", "dataset_version", "generator_version", "seed", "validation", "model_settings") if k in result}
        info["creator_decisions"] = [{"subject_id": actor["id"], **actor["creator_resolution"]} for actor in result["scene"].get("subjects", []) if actor.get("creator_resolution")]
        structured = c.envelope("result", submitted_recipe=recipe, submitted_request=payload, resolved_scene=result["scene"], response=result, capture_settings=capture_settings)
        return {"ui": {"greymonkey_text": [result["positive_prompt"], result["negative_prompt"]], "greymonkey_warnings": warnings}, "result": (result["positive_prompt"], result["negative_prompt"], seed, json.dumps(info, ensure_ascii=False, indent=2), structured)}


class GreymonkeyCameraStyleV2:
    CATEGORY = "Greymonkey"
    FUNCTION = "build"
    RETURN_TYPES = ("GREYMONKEY_CAPTURE",)
    RETURN_NAMES = ("capture_settings",)

    @classmethod
    def INPUT_TYPES(cls):
        data = capture.catalog()
        return {"required": {"preset": (list(data["presets"]),)}, "optional": {key: (list(value),) for key, value in data["dimensions"].items()}}

    def build(self, preset="Unspecified", **choices):
        return (capture.resolve(preset, **choices),)
