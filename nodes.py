import json
from . import client

CONTENT = {"Safe": "safe", "Adult / suggestive": "semi_nsfw", "NSFW · adult explicit": "nsfw"}
# Saved workflows may still carry the pre-explicit-pack label.
CONTENT_ALIASES = {"NSFW · adult nude figure study": "nsfw"}
GENDER = {"Random / varied": "random", "Female / woman": "female", "Male / man": "male", "Nonbinary": "nonbinary"}


def style_choices(data):
    return ["Random"] + [f"{item['name']} [{item['id']}]" for item in data.get("art_styles", [])]


def control_choices(data, group, subject_type=None):
    return ["Random"] + [f"{item['name']} [{item['id']}]" for item in data.get("controls", {}).get(group, []) if subject_type is None or item.get("type") == subject_type]


def choice_id(value):
    return "random" if value in ("Random", "random") else value.rsplit("[", 1)[-1].removesuffix("]")


SPECIES = {"All supported humanoid races": "mixed", "Humans only": "human", "Non-human humanoids only": "fantasy"}


class GreymonkeyPromptGenerator:
    CATEGORY = "Greymonkey"
    FUNCTION = "generate"
    RETURN_TYPES = ("STRING", "STRING", "INT", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt", "prompt_seed", "generation_info")
    DESCRIPTION = "Generate model-specific prompt text through greymonkeys.nl. No image models are loaded."

    @classmethod
    def INPUT_TYPES(cls):
        data = client.catalog()
        return {"required": {
            "model_id": ([m["id"] for m in data["models"] if m.get("comfyui", True)], {"default": data["defaults"]["model_id"]}),
            "scene_type": (["person", "animal", "product", "landscape", "architecture", "poster"], {"tooltip": "Used only without a Scene Subject connection. Landscape, architecture and poster describe the entire image, not an entity."}),
            "subject_count": ("INT", {"default": 1, "min": 0, "max": 8, "tooltip": "Random-only fallback. A connected Scene Subject chain sets the actual subject count."}),
            "content_mode": (list(CONTENT),),
            "detail_level": (["rich", "standard"],),
            "background": (["environment", "white"],),
            "pose_mode": (["random", "static"],),
            "aspect_ratio": (data["settings"]["aspect_ratio"],),
            "quality": (["recommended", "quick", "quality"],),
            "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647, "control_after_generate": True}),
        }, "optional": {
            "art_style": (style_choices(data),),
            "generation_theme": (["mixed", "influencer", "everyday", "urban", "home", "nature", "coastal", "work", "sport", "historical", "fantasy", "dark_fantasy", "fairytale", "scifi", "cyberpunk"],),
            "subjects": ("STRING", {"forceInput": True}),
            "capture_settings": ("GREYMONKEY_CAPTURE",),
        }}

    @classmethod
    def VALIDATE_INPUTS(cls, model_id, generation_theme="mixed"):
        # Live catalogs may evolve. Let the API validate saved model IDs instead of
        # rejecting a workflow because its ID is absent from the bundled snapshot.
        if not isinstance(model_id, str) or not model_id:
            return "Choose a model ID"
        themes = {"mixed", "random", "influencer", "everyday", "urban", "home", "nature", "coastal", "work", "sport", "historical", "fantasy", "dark_fantasy", "fairytale", "scifi", "cyberpunk"}
        return True if generation_theme in themes else "Choose a supported generation theme"

    def generate(self, model_id, scene_type, subject_count, content_mode, detail_level, background, pose_mode, aspect_ratio, quality, seed, species_pool="All supported humanoid races", gender="Random / varied", art_style="Random", hybrid_type="random", location="Random", time_of_day="Random", identity="Random", magic="Random", color_palette="varied", prop_frequency=30, magic_frequency=33, fantasy_frequency=100, subjects="", include_category="Random", exclude_category="Random", global_detail_1="Random", global_detail_2="Random", expression_family="random", movement="random", generation_theme="mixed", capture_settings=None):
        if type(seed) is not int or not 0 <= seed <= 2147483647:
            raise client.GreymonkeyError("Prompt seed must be between 0 and 2147483647.")
        if not subjects and scene_type in ["person", "animal", "product"] and not 1 <= subject_count <= 8:
            raise client.GreymonkeyError("Choose 1–8 subjects for person, animal or product scenes.")
        payload = dict(model_id=model_id, scene_type=scene_type, subject_count=subject_count if scene_type in ["person", "animal", "product"] else 0,
                       content_mode=CONTENT.get(content_mode) or CONTENT_ALIASES.get(content_mode, content_mode), species_pool=SPECIES.get(species_pool, species_pool), detail_level=detail_level,
                       background=background, pose_mode=pose_mode, aspect_ratio=aspect_ratio, quality=quality, seed=seed)
        generation_theme = "mixed" if generation_theme == "random" else generation_theme
        payload["generation_theme"] = generation_theme
        payload["hybrid_type"] = "none" if generation_theme == "everyday" else hybrid_type
        payload["gender"] = GENDER.get(gender, gender)
        payload["art_style"] = "random" if art_style in ("Random", "random") else art_style.rsplit("[", 1)[-1].removesuffix("]")
        if scene_type != "person":
            payload["gender"] = "random"
        # Creative details are sampled server-side. Ignore legacy advanced widget values.
        payload.update(location_id="random", time_id="random", identity_id="random", magic_id="random",
                       color_palette="varied", prop_frequency=30, magic_frequency=33, fantasy_frequency=100,
                       movement="random", expression_family="random", global_detail_ids=[], include_menus=[], exclude_menus=[])
        if subjects:
            try:
                overrides = json.loads(subjects)
            except (ValueError, TypeError) as exc:
                raise client.GreymonkeyError("Connect a valid Greymonkey Scene Subject output.") from exc
            if not isinstance(overrides, list) or not 1 <= len(overrides) <= 8:
                raise client.GreymonkeyError("Subject chain must contain 1–8 subjects.")
            if any(not isinstance(item, dict) for item in overrides):
                raise client.GreymonkeyError("Every subject chain entry must be a subject object.")
            if any(item.get("type") not in ("person", "animal", "product") for item in overrides):
                raise client.GreymonkeyError("Every chained subject must be a person, animal or object.")
            if any("random_related" in item for item in overrides):
                from .contracts import envelope, request_scene
                for index, actor in enumerate(overrides):
                    actor["ref"] = "subject-" + str(index + 1)
                    actor["interactions"] = [{"target_ref": link["target_id"], "action": link["action"]} for link in actor.get("interactions", [])]
                materialized = request_scene(envelope("scene", mode="subjects", subjects=overrides), seed)
                overrides = materialized["subject_overrides"]
            # The connected chain owns scene type as well as count and identities.
            chain_type = "person" if any(item["type"] == "person" for item in overrides) else overrides[0]["type"]
            payload.update(scene_type=chain_type, subject_overrides=overrides, subject_count=len(overrides),
                           gender="random", hybrid_type="random", identity_id="random", magic_id="random")
        if capture_settings is not None:
            if not isinstance(capture_settings, dict) or not isinstance(capture_settings.get("global_detail_ids"), list):
                raise client.GreymonkeyError("Connect a Greymonkey Camera Style output.")
            capture_ids = capture_settings["global_detail_ids"]
            if len(capture_ids) > 32 or any(not isinstance(item, str) for item in capture_ids):
                raise client.GreymonkeyError("Invalid camera-style selections.")
            payload["global_detail_ids"] = list(dict.fromkeys(capture_ids))
        result = client.generate(payload)
        info = json.dumps({k: result[k] for k in ["api_version", "model_id", "profile_version", "dataset_version", "generator_version", "seed", "validation", "model_settings"] if k in result}, ensure_ascii=False, indent=2)
        return {"ui": {"greymonkey_text": [result["positive_prompt"], result["negative_prompt"]]},
                "result": (result["positive_prompt"], result["negative_prompt"], result["seed"], info)}


class GreymonkeySceneSubject:
    CATEGORY = "Greymonkey"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("subjects",)
    DESCRIPTION = "Chain up to eight individually configured subjects, then connect to the generator's subjects input."

    @classmethod
    def INPUT_TYPES(cls):
        data = client.catalog()
        return {"required": {
            "subject_type": (["person", "animal", "product"],),
            "identity": (control_choices(data, "identities"), {"greymonkeyEntries": data.get("controls", {}).get("identities", [])}),
            "gender": (list(GENDER),),
            "magic": (["None"] + control_choices(data, "magic"), {"default": "None"}),
            "position": (["unspecified", "left", "center", "right", "foreground", "middle distance", "background"],),
            "relative_size": (["unspecified", "small within the frame", "medium within the frame", "large within the frame"],),
            "relationship": (["none", "kissing", "next_to", "in_front_of", "behind", "looking_at", "leaning_against", "inside", "sitting_driver", "sitting_passenger", "driving", "entering", "exiting", "sitting_hood"],),
            "target_subject": ("INT", {"default": 1, "min": 1, "max": 8, "tooltip": "Used only for a relationship to another chained subject. A selected related object is targeted automatically; None never creates an object."}),
            "detail_1": (control_choices(data, "details"), {"greymonkeyEntries": data.get("controls", {}).get("details", [])}),
            "detail_2": (control_choices(data, "details"), {"greymonkeyEntries": data.get("controls", {}).get("details", [])}),
            "detail_3": (control_choices(data, "details"), {"greymonkeyEntries": data.get("controls", {}).get("details", [])}),
            "detail_4": (control_choices(data, "details"), {"greymonkeyEntries": data.get("controls", {}).get("details", [])}),
        }, "optional": {"previous_subjects": ("STRING", {"forceInput": True}), "related_object": (["None"] + control_choices(data, "identities", "product"), {"default": "None"}), "ethnicity": (control_choices(data, "ethnicities"), {"tooltip": "Human ancestry / regional background, separate from species. Random chooses during filling."}), "hair_color": (control_choices(data, "hair_colors"),), "hair_length": (control_choices(data, "hair_lengths"),), "subject_style": (["Default", "Influencer"],)}}

    def build(self, subject_type, identity, gender, magic, position, relative_size, relationship, target_subject, detail_1="Random", detail_2="Random", detail_3="Random", detail_4="Random", previous_subjects="", related_object="None", ethnicity="Random", hair_color="Random", hair_length="Random", subject_style="Default"):
        try:
            subjects = json.loads(previous_subjects) if previous_subjects else []
        except (ValueError, TypeError) as exc:
            raise client.GreymonkeyError("Invalid subject chain.") from exc
        if not isinstance(subjects, list) or len(subjects) >= 8:
            raise client.GreymonkeyError("Maximum eight subjects.")
        if any(not isinstance(item, dict) for item in subjects):
            raise client.GreymonkeyError("Invalid subject chain entry.")
        object_id = "random" if related_object in ("None", "none") else choice_id(related_object)
        actor_number = len(subjects) + 1
        if related_object in ("None", "none") and relationship != "none" and target_subject == actor_number:
            raise client.GreymonkeyError("A relationship cannot target this subject itself. Choose another subject or set relationship to none.")
        ids = []
        selected = choice_id(identity)
        if selected != "random":
            entry = next((item for item in client.catalog().get("controls", {}).get("identities", []) if item["id"] == selected), None)
            if entry and subject_type not in entry.get("types", [entry.get("type")]):
                raise client.GreymonkeyError(f"Identity {entry['name']} is incompatible with {subject_type}. Review the saved type/identity pair; neither was replaced.")
            ids.append(selected)
        if subject_type == "person":
            chosen_gender = GENDER.get(gender, gender)
            if chosen_gender != "random":
                ids.append("subject_gender_" + chosen_gender)
            if magic not in ("None", "none") and choice_id(magic) != "random":
                ids.append(choice_id(magic))
        elif magic not in ("None", "none") and choice_id(magic) != "random":
            raise client.GreymonkeyError("Character magic requires a person subject.")
        for value in [detail_1, detail_2, detail_3, detail_4]:
            selected_detail = choice_id(value)
            if selected_detail != "random":
                entry = next((item for item in client.catalog().get("controls", {}).get("details", []) if item["id"] == selected_detail), None)
                if entry and subject_type not in entry.get("types", [entry.get("type")]):
                    raise client.GreymonkeyError("Choose a detail matching this subject type.")
                ids.append(selected_detail)
        ancestry = choice_id(ethnicity)
        if ancestry != "random":
            if subject_type != "person":
                raise client.GreymonkeyError("Human ancestry / background requires a person subject.")
            # The dedicated selector replaces ancestry chosen in generic detail slots.
            ancestry_ids = {entry["id"] for entry in client.catalog().get("controls", {}).get("ethnicities", [])}
            ids = [selected_id for selected_id in ids if selected_id not in ancestry_ids and not selected_id.startswith(("ethnicity_", "subj_ethnicity_"))]
            ids.append(ancestry)
        for selection, group in [(hair_color, "hair_colors"), (hair_length, "hair_lengths")]:
            if choice_id(selection) == "random":
                continue
            if subject_type != "person":
                raise client.GreymonkeyError("Hair controls require a person subject.")
            property_ids = {entry["id"] for entry in client.catalog().get("controls", {}).get(group, [])}
            ids = [item for item in ids if item not in property_ids]
            ids.append(choice_id(selection))
        if subject_style not in ("Default", "Influencer"):
            raise client.GreymonkeyError("Choose Default or Influencer subject style.")
        if subject_type == "person" and subject_style == "Influencer":
            ids.append("subject_direction_influencer")
        ids = list(dict.fromkeys(ids))
        details = {}
        if position != "unspecified":
            details["position"] = "positioned in the " + position + " of the scene"
        if relative_size != "unspecified":
            details["dimensions"] = relative_size
        if object_id != "random":
            if len(subjects) > 6:
                raise client.GreymonkeyError("Adding this subject and its related object would exceed eight subjects.")
            entry = next((item for item in client.catalog().get("controls", {}).get("identities", []) if item["id"] == object_id and item.get("type") == "product"), None)
            if entry is None:
                raise client.GreymonkeyError("Choose a related object from the object catalog.")
            actor_number = len(subjects) + 1
            object_number = actor_number + 1
            links = [] if relationship == "none" else [{"target_id": "subject-" + str(object_number), "action": relationship}]
            subjects.append({"type": subject_type, "selected_ids": ids, "details": details, "interactions": links, "allow_random_magic": magic not in ("None", "none"), "allow_random_props": related_object not in ("None", "none")})
            subjects.append({"type": "product", "selected_ids": [object_id], "details": {}, "interactions": []})
            return (json.dumps(subjects, ensure_ascii=False),)
        if related_object in ("Random", "random"):
            subjects.append({"type": subject_type, "selected_ids": ids, "details": details, "interactions": [], "random_related": {"action": relationship}, "allow_random_props": True, "allow_random_magic": magic not in ("None", "none")})
            return (json.dumps(subjects, ensure_ascii=False),)
        links = [] if relationship == "none" else [{"target_id": "subject-" + str(target_subject), "action": relationship}]
        subjects.append({"type": subject_type, "selected_ids": ids, "details": details, "interactions": links, "allow_random_magic": magic not in ("None", "none"), "allow_random_props": related_object not in ("None", "none")})
        return (json.dumps(subjects, ensure_ascii=False),)


class GreymonkeyCameraStyle:
    CATEGORY = "Greymonkey"
    FUNCTION = "build"
    RETURN_TYPES = ("GREYMONKEY_CAPTURE",)
    RETURN_NAMES = ("capture_settings",)
    DESCRIPTION = "Phone/amateur capture presets and framing. Connect to the generator capture_settings input. Camera-model appearance is selected separately in Scene Subject."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "preset": (["Older iPhone snapshot", "Budget phone amateur", "Compressed social upload", "Clean phone photograph", "Polished creator photograph"],),
            "capture_method": (["Unspecified", "Front-camera selfie", "Rear-camera mirror selfie", "Rear-camera candid", "Phone timer"],),
            "noise": (["Preset", "Clean", "Mild", "Heavy"],),
            "focus": (["Preset", "Imperfect focus", "Eyes and phone in focus"],),
            "framing": (["Random", "Full body", "Three-quarter body", "Medium shot", "Close-up portrait"],),
        }, "optional": {
            'device': (['Unspecified', 'iPhone 11 Pro Max', 'Older iPhone', 'Modern iPhone', 'Budget Android', 'Compact digital camera', 'Disposable film camera'],),
            'lens': (['Unspecified', 'Ultrawide', 'Standard wide', 'Portrait telephoto', 'Front selfie lens'],),
            'flash': (['Unspecified', 'Direct phone flash', 'Soft window light', 'Dim ceiling light', 'Screen glow', 'Mixed LED room light', 'Available night light'],),
            'processing': (['Unspecified', 'Natural processing', 'Phone HDR', 'Soft low contrast', 'Harsh digital sharpening', 'Film color'],),
            'white_balance': (['Unspecified', 'Neutral', 'Warm indoor', 'Cool indoor', 'Mixed color cast'],),
            'compression': (['Preset', 'Clean', 'Light social compression', 'Heavy social compression'],),
            'camera_angle': (['Unspecified', 'Eye level', 'Low angle', 'High angle', 'Tilted / Dutch angle'],),
        }}

    def build(self, preset, capture_method="Unspecified", noise="Preset", focus="Preset", framing="Random", device='Unspecified', lens='Unspecified', flash='Unspecified', processing='Unspecified', white_balance='Unspecified', compression='Preset', camera_angle='Unspecified'):
        from .capture import resolve
        return (resolve(preset, capture_method=capture_method, noise=noise, focus=focus, framing=framing, device=device, lens=lens, flash=flash, processing=processing, white_balance=white_balance, compression=compression, camera_angle=camera_angle),)


class GreymonkeySaveImage:
    CATEGORY = "Greymonkey"
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "saved_files_info")
    DESCRIPTION = "Save PNG, JPEG or WebP with quality/compression controls, actual prompt metadata, workflow and JSON sidecars."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE",),
            "positive_prompt": ("STRING", {"forceInput": True}),
            "negative_prompt": ("STRING", {"forceInput": True}),
            "generation_info": ("STRING", {"forceInput": True}),
            "filename_prefix": ("STRING", {"default": "Greymonkey"}),
        }, "optional": {
            "encoded_negative_prompt": ("STRING", {"forceInput": True, "tooltip": "Optional final negative caption connected to the downstream encoder."}),
            "generation_result": ("GREYMONKEY_RESULT",),
            "encoded_positive_prompt": ("STRING", {"forceInput": True, "tooltip": "Optional final caption after another prompt rewriter. Leave unconnected when encoding Greymonkey's positive output directly."}),
            "image_format": (["png", "jpeg", "webp"], {"default": "png"}),
            "quality_percent": ("INT", {"default": 95, "min": 1, "max": 100, "tooltip": "JPEG/WebP quality, not a guaranteed file-size reduction percentage. PNG ignores this."}),
            "png_compression": ("INT", {"default": 6, "min": 0, "max": 9, "tooltip": "PNG lossless compression effort: 0 fastest/largest, 9 slower/smaller. Image quality is unchanged."}),
            "webp_lossless": ("BOOLEAN", {"default": False}),
            "webp_method": ("INT", {"default": 4, "min": 0, "max": 6}),
            "jpeg_subsampling": (["4:4:4", "4:2:2", "4:2:0"],),
            "jpeg_progressive": ("BOOLEAN", {"default": True}),
            "alpha_background": (["white", "black"], {"tooltip": "JPEG background when flattening transparency."}),
            "write_sidecar": ("BOOLEAN", {"default": True, "tooltip": "Write complete prompt/workflow JSON alongside the image. Always enabled for JPEG."}),
        }, "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"}}

    def save_images(self, images, positive_prompt, negative_prompt, generation_info,
                    filename_prefix="Greymonkey", encoded_positive_prompt=None,
                    prompt=None, extra_pnginfo=None, image_format="png", quality_percent=95,
                    png_compression=6, webp_lossless=False, webp_method=4,
                    jpeg_subsampling="4:4:4", jpeg_progressive=True,
                    alpha_background="white", write_sidecar=True, encoded_negative_prompt=None, generation_result=None):
        from comfy.cli_args import args
        if getattr(args, "disable_metadata", False):
            raise client.GreymonkeyError("ComfyUI metadata saving is disabled. Remove --disable-metadata to save prompt text with images.")
        try:
            info = json.loads(generation_info)
        except (ValueError, TypeError):
            info = {"raw_generation_info": generation_info}
        if not isinstance(info, dict):
            info = {"raw_generation_info": generation_info}
        record = {
            "schema_version": 1,
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "generation_info": info,
            "prompt_seed": info.get("seed"),
            "model_id": info.get("model_id"),
            "caption_source": "Greymonkey generator output",
            "caption_sources": {"positive": "final encoder connection" if encoded_positive_prompt is not None else "generator output", "negative": "final encoder connection" if encoded_negative_prompt is not None else "generator output"},
        }
        if encoded_positive_prompt is not None:
            record["encoded_positive_prompt"] = encoded_positive_prompt
            record["caption_source"] = "Generator output and explicitly connected final encoder caption"
        if encoded_negative_prompt is not None:
            record["encoded_negative_prompt"] = encoded_negative_prompt
        if generation_result is not None:
            from .contracts import check
            structured = check(generation_result, "result", {"submitted_recipe", "submitted_request", "resolved_scene", "response", "capture_settings"})
            record["generation_result"] = structured
        # Copy existing metadata: keep workflow and other extensions' records intact.
        metadata = dict(extra_pnginfo or {})
        metadata["greymonkey_prompt"] = record
        metadata["positive_prompt"] = positive_prompt
        metadata["negative_prompt"] = negative_prompt
        if encoded_positive_prompt is not None:
            metadata["encoded_positive_prompt"] = encoded_positive_prompt
        if encoded_negative_prompt is not None:
            metadata["encoded_negative_prompt"] = encoded_negative_prompt
        from .image_export import save_export
        return save_export(images, filename_prefix, prompt, metadata, image_format,
                           quality_percent, png_compression, webp_lossless, webp_method,
                           jpeg_subsampling, jpeg_progressive, alpha_background, write_sidecar)


NODE_CLASS_MAPPINGS = {"GreymonkeyPromptGenerator": GreymonkeyPromptGenerator, "GreymonkeySceneSubject": GreymonkeySceneSubject, "GreymonkeySaveImage": GreymonkeySaveImage, "GreymonkeyCameraStyle": GreymonkeyCameraStyle}
NODE_DISPLAY_NAME_MAPPINGS = {"GreymonkeyPromptGenerator": "Greymonkey Prompt Generator", "GreymonkeySceneSubject": "Greymonkey Scene Subject", "GreymonkeySaveImage": "Greymonkey Save Image", "GreymonkeyCameraStyle": "Greymonkey Camera Style"}

# ComfyUI supplies aiohttp and PromptServer. Unit tests can import this package
# without either; importing never performs a remote request.
try:
    from server import PromptServer
    from aiohttp import web
except ImportError:
    pass
else:
    @PromptServer.instance.routes.post("/greymonkey/models/refresh")
    async def refresh_models(request):
        import asyncio
        try:
            data = await asyncio.to_thread(client.refresh_catalog)
            return web.json_response(data)
        except client.GreymonkeyError as exc:
            return web.json_response({"success": False, "error": str(exc)}, status=502)


# New layouts use versioned class IDs. Legacy IDs are intentionally retained.
from .creator import GreymonkeyInfluencerSettingsV2
from .v2_nodes import (GreymonkeyPromptGeneratorV2, GreymonkeySceneSubjectV2,
    GreymonkeyRandomSceneV2, GreymonkeySubjectDetailV2, GreymonkeyCameraStyleV2)


class GreymonkeySaveImageV2(GreymonkeySaveImage):
    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        for name in ("positive_prompt", "negative_prompt", "generation_info"):
            schema["optional"][name] = schema["required"].pop(name)
        return schema

    def save_images(self, images, positive_prompt=None, negative_prompt=None, generation_info=None, generation_result=None, **kwargs):
        if generation_result is not None:
            from .contracts import check
            result = check(generation_result, "result", {"submitted_recipe", "submitted_request", "resolved_scene", "response", "capture_settings"})
            response = result.get("response")
            if not isinstance(response, dict):
                raise client.GreymonkeyError("Malformed generation result.")
            response = client.validate_result(response, {"seed": response.get("seed"), "model_id": response.get("model_id")})
            positive_prompt, negative_prompt = response["positive_prompt"], response["negative_prompt"]
            generation_info = json.dumps(response, ensure_ascii=False)
        elif not all(isinstance(v, str) for v in (positive_prompt, negative_prompt, generation_info)):
            raise client.GreymonkeyError("Connect generation_result, or all three legacy prompt/metadata strings.")
        return super().save_images(images, positive_prompt, negative_prompt, generation_info,
                                  generation_result=generation_result, **kwargs)


class GreymonkeyLegacySceneAdapterV2:
    CATEGORY = "Greymonkey/Legacy"
    FUNCTION = "build"
    RETURN_TYPES = ("GREYMONKEY_SCENE",)
    RETURN_NAMES = ("scene",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"subjects": ("STRING", {"forceInput": True})}}

    def build(self, subjects):
        from .contracts import envelope, scene
        try:
            actors = json.loads(subjects)
        except (ValueError, TypeError) as exc:
            raise client.GreymonkeyError("Invalid legacy subject JSON.") from exc
        if not isinstance(actors, list) or not 1 <= len(actors) <= 8:
            raise client.GreymonkeyError("Legacy chain must contain 1–8 subjects.")
        for index, actor in enumerate(actors):
            if not isinstance(actor, dict):
                raise client.GreymonkeyError("Invalid legacy subject entry.")
            actor["ref"] = "subject-" + str(index + 1)
            actor["interactions"] = [{"target_ref": link.get("target_id"), "action": link.get("action")} for link in actor.get("interactions", [])]
        return (scene(envelope("scene", mode="subjects", subjects=actors)),)


for legacy_name in ("GreymonkeyPromptGenerator", "GreymonkeySceneSubject", "GreymonkeyCameraStyle", "GreymonkeySaveImage"):
    NODE_CLASS_MAPPINGS[legacy_name].CATEGORY = "Greymonkey/Legacy"
    NODE_DISPLAY_NAME_MAPPINGS[legacy_name] += " (Legacy)"

for cls, name in [(GreymonkeyInfluencerSettingsV2, "Greymonkey Influencer Settings"), (GreymonkeyPromptGeneratorV2, "Greymonkey Prompt Generator"),
                  (GreymonkeySceneSubjectV2, "Greymonkey Scene Subject"),
                  (GreymonkeyRandomSceneV2, "Greymonkey Random Scene"),
                  (GreymonkeySubjectDetailV2, "Greymonkey Subject Detail"),
                  (GreymonkeyCameraStyleV2, "Greymonkey Camera Style"),
                  (GreymonkeySaveImageV2, "Greymonkey Save Image"),
                  (GreymonkeyLegacySceneAdapterV2, "Greymonkey Legacy Scene Adapter")]:
    NODE_CLASS_MAPPINGS[cls.__name__] = cls
    NODE_DISPLAY_NAME_MAPPINGS[cls.__name__] = name
# Subclass inherited legacy category is overridden after registration.
GreymonkeySaveImageV2.CATEGORY = "Greymonkey"


class GreymonkeyLegacyRandomSceneV2(GreymonkeyRandomSceneV2):
    CATEGORY = "Greymonkey/Legacy"
    DESCRIPTION = "Migration adapter for historical generator-level gender/hybrid preferences. New workflows should use Scene Subject."

    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        schema["required"]["gender"] = (list(GENDER),)
        schema["required"]["hybrid_type"] = (["none", "random", "scorpion_body", "scorpion", "arachnid", "serpent", "dragon", "moth", "mantis", "avian", "aquatic", "beetle", "crab", "lobster", "centipede", "wasp", "butterfly", "cicada", "bat", "raven", "owl", "shark", "octopus", "jellyfish", "crocodile", "gecko", "chameleon", "pangolin", "armadillo", "wolf", "fox", "deer", "ram", "fungal", "botanical", "crystalline", "biomechanical", "tiger", "lion", "snow_leopard", "lynx", "rabbit", "hare", "bear", "red_panda", "otter", "squirrel", "horse", "zebra", "bison", "gazelle", "peacock", "kingfisher", "hummingbird", "swan", "dragonfly", "firefly", "snail", "axolotl", "frog", "seahorse"],)
        return schema

    def build(self, scene_type, subject_count=1, species_pool="All supported humanoid races", gender="Random / varied", hybrid_type="none"):
        scene = super().build(scene_type, subject_count, species_pool)[0]
        scene["legacy_choices"] = {"gender": GENDER.get(gender, gender), "hybrid_type": hybrid_type}
        return (scene,)


NODE_CLASS_MAPPINGS["GreymonkeyLegacyRandomSceneV2"] = GreymonkeyLegacyRandomSceneV2
NODE_DISPLAY_NAME_MAPPINGS["GreymonkeyLegacyRandomSceneV2"] = "Greymonkey Legacy Random Preferences"

from .v2_nodes import GreymonkeySceneObjectV2, GreymonkeyObjectDetailV2
for cls, label in [(GreymonkeySceneObjectV2, "Greymonkey Scene Object"), (GreymonkeyObjectDetailV2, "Greymonkey Object Detail")]:
    NODE_CLASS_MAPPINGS[cls.__name__] = cls
    NODE_DISPLAY_NAME_MAPPINGS[cls.__name__] = label
