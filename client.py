"""HTTPS-only client. No network or filesystem writes during module import."""
import json
from pathlib import Path
import threading
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).parent
MAX_RESPONSE = 2 * 1024 * 1024
TIMEOUT = 60
_catalog = None
_lock = threading.Lock()
_refresh_lock = threading.Lock()
REFRESH_TIMEOUT = 120


class GreymonkeyError(RuntimeError):
    pass


def base_url():
    path = ROOT / "config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        url = config.get("service_url", "https://greymonkeys.nl")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("service_url must be an HTTPS application URL without credentials, query or fragment")
        return url.rstrip("/")
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise GreymonkeyError(f"Invalid Greymonkey config.json: {exc}") from exc


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(endpoint, payload=None, query=None, deadline=None):
    if endpoint not in ("models", "generate", "format"):
        raise GreymonkeyError("Unsupported API endpoint.")
    refresh_deadline = deadline is not None
    deadline = deadline if deadline is not None else time.monotonic() + TIMEOUT
    url = base_url() + "/api/v1/" + endpoint + ".php"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if data is not None and len(data) > 32768:
        raise GreymonkeyError("Greymonkey request exceeds 32 KB. Reduce subject details.")
    req = urllib.request.Request(url, data=data, headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "ComfyUI-Greymonkey/2.1"}, method="GET" if payload is None else "POST")
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=min(TIMEOUT, max(0.1, deadline - time.monotonic())) if deadline else TIMEOUT) as response:
            blocks = []
            size = 0
            while size <= MAX_RESPONSE:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GreymonkeyError("Catalog refresh exceeded its 120-second total deadline." if refresh_deadline else "Generation request exceeded its 60-second deadline.")
                # Bound each individual socket receive by the remaining deadline.
                sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                if sock is not None: sock.settimeout(min(TIMEOUT, remaining))
                reader = getattr(response, "read1", response.read)
                block = reader(min(65536, MAX_RESPONSE + 1 - size))
                if not block: break
                blocks.append(block)
                size += len(block)
            raw = b"".join(blocks)
            if len(raw) > MAX_RESPONSE:
                raise GreymonkeyError("Greymonkey response exceeds 2 MB. For catalog refresh, deploy the paginated API update and reinstall the updated custom node.")
            if response.headers.get_content_type() != "application/json":
                raise GreymonkeyError("Greymonkey returned non-JSON content. Check service_url and deployment.")
            result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        message = f"HTTP {exc.code}"
        if 300 <= exc.code < 400:
            exc.close()
            raise GreymonkeyError("The service redirected the request. Configure its final HTTPS application URL; redirects are not followed.") from exc
        try:
            body = json.loads(exc.read(MAX_RESPONSE))
            error = body.get("error", {})
            message += ": " + (error.get("message", "Request failed") if isinstance(error, dict) else str(error))
            if exc.code == 400 and "Invalid scene interaction" in message and isinstance(payload, dict):
                actions = sorted({link.get("action", "") for actor in payload.get("subject_overrides", []) if isinstance(actor, dict) for link in actor.get("interactions", []) if isinstance(link, dict)})
                message += "\nSubmitted actions: " + ", ".join(actions)
                message += "\nThe hosted API rejected the interaction format or action. Deploy the matching website release, including options/v4/config/interaction-rules.json. Your selections were not changed."
            validation = body.get("validation", {})
            conflicts = validation.get("errors", []) if isinstance(validation, dict) else []
            if isinstance(conflicts, list):
                details = [item for item in conflicts if isinstance(item, str)]
                if details:
                    message += "\nConflicts:\n- " + "\n- ".join(details[:20])
            if isinstance(payload, dict) and "seed" in payload:
                message += f"\nPrompt seed: {payload['seed']}"

        except (ValueError, AttributeError, TypeError):
            message += ". Check the service URL and API deployment."
        finally:
            exc.close()
        if exc.code == 429:
            message += f" Retry after {exc.headers.get('Retry-After', 'the indicated')} seconds."
        raise GreymonkeyError(message) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GreymonkeyError(f"Cannot reach Greymonkey within {TIMEOUT}s. Check Internet access, TLS certificates and service_url: {exc}") from exc
    except (ValueError, UnicodeError) as exc:
        raise GreymonkeyError("Greymonkey returned malformed JSON.") from exc
    if not isinstance(result, dict) or result.get("success") is not True or not str(result.get("api_version", "")).startswith("1."):
        raise GreymonkeyError("Greymonkey returned an unsuccessful or incompatible API response.")
    return result


def validate_catalog(value):
    if not isinstance(value, dict) or not str(value.get("api_version", "")).startswith("1.") or not isinstance(value.get("models"), list) or not value["models"]:
        raise GreymonkeyError("Invalid Greymonkey model catalog.")
    if value.get("catalog_schema_version", 1) not in (1, 2):
        raise GreymonkeyError("Unsupported control catalog schema. Update the custom node package.")
    aliases = value.get("option_aliases", {})
    if not isinstance(aliases, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not k or not v for k, v in aliases.items()):
        raise GreymonkeyError("Invalid option migration catalog.")
    for start in aliases:
        visited = set()
        current = start
        while current in aliases:
            if current in visited:
                raise GreymonkeyError("Cyclic option migration catalog.")
            visited.add(current)
            current = aliases[current]
    seen = set()
    for model in value["models"]:
        if not isinstance(model, dict) or not isinstance(model.get("id"), str) or not model["id"] or not isinstance(model.get("name"), str) or model["id"] in seen:
            raise GreymonkeyError("Invalid Greymonkey model catalog entry.")
        seen.add(model["id"])
    defaults = value.get("defaults")
    settings = value.get("settings")
    if not isinstance(defaults, dict) or defaults.get("model_id") not in seen or not isinstance(settings, dict) or not isinstance(settings.get("aspect_ratio"), list) or not settings["aspect_ratio"] or not all(isinstance(ratio, str) and ratio for ratio in settings["aspect_ratio"]):
        raise GreymonkeyError("Greymonkey catalog is missing valid defaults or aspect ratios.")
    supported = {model["id"] for model in value["models"] if model.get("comfyui", True) is True}
    if defaults["model_id"] not in supported:
        raise GreymonkeyError("Greymonkey catalog default has no supported ComfyUI workflow.")
    controls = value.get("controls", {})
    if not isinstance(controls, dict):
        raise GreymonkeyError("Invalid Greymonkey control catalog.")
    groups = {"art_styles": value.get("art_styles", [])}
    for key, entries in controls.items():
        groups[key] = entries
    for group, entries in groups.items():
        if not isinstance(entries, list):
            raise GreymonkeyError(f"Invalid Greymonkey {group} catalog.")
        identifiers = set()
        for entry in entries:
            if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                    or not entry["id"] or not isinstance(entry.get("name"), str)
                    or not entry["name"] or entry["id"] in identifiers):
                raise GreymonkeyError(f"Invalid Greymonkey {group} entry.")
            identifiers.add(entry["id"])
            for key in ("slot", "category", "category_id"):
                if key in entry and not isinstance(entry[key], str):
                    raise GreymonkeyError(f"Invalid {key} in {group} catalog.")
            if "colorable" in entry and type(entry["colorable"]) is not bool:
                raise GreymonkeyError(f"Invalid color capability in {group}.")
            if "capabilities" in entry and not isinstance(entry["capabilities"], dict):
                raise GreymonkeyError(f"Invalid capability metadata in {group}.")
            if "type" in entry and entry["type"] not in (None, "person", "animal", "product"):
                raise GreymonkeyError(f"Invalid subject type in {group} catalog.")
            if "types" in entry and (not isinstance(entry["types"], list) or not entry["types"]
                    or any(kind not in (None, "person", "animal", "product", "landscape", "architecture", "poster") for kind in entry["types"])):
                raise GreymonkeyError(f"Invalid subject types in {group} catalog.")
    if "creator_catalog" in value:
        from .creator import validate_catalog as validate_creator
        validate_creator(value["creator_catalog"])
    return value


def cache_path():
    try:
        import folder_paths
        directory = Path(folder_paths.get_user_directory())
    except (ImportError, AttributeError):
        directory = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "ComfyUI"
    import hashlib
    service = hashlib.sha256(base_url().encode()).hexdigest()[:16]
    return directory / "greymonkey" / ("catalog-" + service + ".json")


def persist_catalog(value):
    destination = cache_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary and temporary.exists(): temporary.unlink()


def catalog():
    global _catalog
    with _lock:
        if _catalog is None:
            candidates = [cache_path(), ROOT / "models.json"]
            for path in candidates:
                try:
                    _catalog = validate_catalog(json.loads(path.read_text(encoding="utf-8-sig")))
                    break
                except (OSError, ValueError, UnicodeError, GreymonkeyError):
                    continue
            if _catalog is None:
                raise GreymonkeyError("Cannot load a valid cached or bundled catalog. Reinstall the node package.")
        return _catalog


def refresh_catalog():
    global _catalog
    deadline = time.monotonic() + REFRESH_TIMEOUT
    if not _refresh_lock.acquire(timeout=REFRESH_TIMEOUT):
        raise GreymonkeyError("Another catalog refresh is still running; retry after it completes.")
    try:
        updated = validate_catalog(request("models", deadline=deadline))
        paging = updated.get("catalog_pagination")
        if paging is not None:
            if (not isinstance(paging, dict) or paging.get("page") != 0
                    or type(paging.get("pages")) is not int or not 1 <= paging["pages"] <= 128
                    or not isinstance(paging.get("dataset_version"), str)):
                raise GreymonkeyError("Invalid catalog pagination metadata.")
            version = paging["dataset_version"]
            total = len(json.dumps(updated).encode("utf-8"))
            for page in range(1, paging["pages"]):
                if time.monotonic() >= deadline:
                    raise GreymonkeyError("Catalog refresh exceeded its total deadline.")
                part = validate_catalog(request("models", query={"controls_page": page}, deadline=deadline))
                meta = part.get("catalog_pagination", {})
                if (meta.get("page") != page or meta.get("pages") != paging["pages"]
                        or meta.get("dataset_version") != version or part["models"] != updated["models"]
                        or part.get("capture_catalog") != updated.get("capture_catalog")
                        or part.get("creator_catalog") != updated.get("creator_catalog")):
                    raise GreymonkeyError("The hosted catalog changed during refresh. Retry after deployment completes.")
                total += len(json.dumps(part).encode("utf-8"))
                if total > 32 * 1024 * 1024:
                    raise GreymonkeyError("Combined Greymonkey catalog exceeds 32 MB.")
                for group, entries in part.get("controls", {}).items():
                    updated.setdefault("controls", {}).setdefault(group, []).extend(entries)
            actual_count = sum(len(values) for values in updated.get("controls", {}).values())
            if actual_count != paging.get("total_entries"):
                raise GreymonkeyError("Incomplete model catalog: page entry count does not match.")
            updated["catalog_complete"] = True
            updated["dataset_version"] = version
        validate_catalog(updated)
        # A failed cache write must not publish half a refreshed catalog.
        try:
            persist_catalog(updated)
        except OSError as exc:
            raise GreymonkeyError(f"Cannot save the refreshed catalog in ComfyUI user storage: {exc}") from exc
        with _lock:
            _catalog = updated
        return updated
    finally:
        _refresh_lock.release()


def generate(payload):
    return validate_result(request("generate", payload), payload)


def format_scene(payload):
    return validate_result(request("format", payload), payload)


def validate_result(result, payload):
    if not isinstance(result.get("positive_prompt"), str) or not result["positive_prompt"].strip() or not isinstance(result.get("negative_prompt"), str):
        raise GreymonkeyError("Greymonkey response is missing prompt text.")
    if type(result.get("seed")) is not int or not 0 <= result["seed"] <= 2147483647 or result["seed"] != payload["seed"] or result.get("model_id") != payload["model_id"]:
        raise GreymonkeyError("Greymonkey returned a different model or seed.")
    validation = result.get("validation")
    if not isinstance(validation, dict) or validation.get("valid") is not True or not isinstance(validation.get("warnings"), list) or any(not isinstance(w, str) for w in validation.get("warnings", [])):
        raise GreymonkeyError("Greymonkey response has no successful scene validation.")
    if not isinstance(result.get("model_settings"), dict) or not isinstance(result.get("scene"), dict) or not all(isinstance(result.get(k), str) for k in ["profile_version", "dataset_version"]):
        raise GreymonkeyError("Greymonkey response is missing generation metadata.")
    return result
