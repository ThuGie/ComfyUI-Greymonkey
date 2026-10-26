"""Image export with explicit codec controls and recoverable prompt metadata."""
import json
import os
import tempfile
from pathlib import Path


def _save_export(images, prefix, prompt, metadata, image_format="png", quality_percent=95,
                png_compression=6, webp_lossless=False, webp_method=4,
                jpeg_subsampling="4:4:4", jpeg_progressive=True,
                alpha_background="white", write_sidecar=True, _completed=None):
    import numpy as np
    import folder_paths
    from PIL import Image, PngImagePlugin, features
    from .client import GreymonkeyError

    if image_format not in ("png", "jpeg", "webp"):
        raise GreymonkeyError("Choose PNG, JPEG or WebP.")
    for name, value, lo, hi in (("quality_percent", quality_percent, 1, 100),
                                ("png_compression", png_compression, 0, 9),
                                ("webp_method", webp_method, 0, 6)):
        if type(value) is not int or not lo <= value <= hi:
            raise GreymonkeyError(f"{name} must be between {lo} and {hi}.")
    if jpeg_subsampling not in ("4:4:4", "4:2:2", "4:2:0") or alpha_background not in ("white", "black"):
        raise GreymonkeyError("Unsupported JPEG color or transparency setting.")
    if image_format == "webp" and not features.check("webp"):
        raise GreymonkeyError("This Pillow installation has no WebP codec support.")
    if len(images) == 0:
        raise GreymonkeyError("No images to save.")
    output = folder_paths.get_output_directory()
    folder, name, counter, subfolder, _ = folder_paths.get_save_image_path(
        prefix, output, images[0].shape[1], images[0].shape[0])
    resolved_folder = Path(folder).resolve()
    resolved_output = Path(output).resolve()
    if not resolved_folder.is_relative_to(resolved_output):
        raise GreymonkeyError("Export destination must remain inside the ComfyUI output directory.")
    full_metadata = dict(metadata)
    if prompt is not None:
        full_metadata["prompt"] = prompt
    export = dict(format=image_format, quality_percent=quality_percent if image_format != "png" else None,
                  png_compression=png_compression if image_format == "png" else None,
                  webp_lossless=webp_lossless if image_format == "webp" else None,
                  webp_method=webp_method if image_format == "webp" else None,
                  jpeg_subsampling=jpeg_subsampling if image_format == "jpeg" else None,
                  jpeg_progressive=jpeg_progressive if image_format == "jpeg" else None)
    full_metadata["greymonkey_export"] = export
    previews, records = [], (_completed if _completed is not None else [])
    for batch, tensor in enumerate(images):
        array = np.clip(np.nan_to_num(tensor.detach().cpu().numpy(), nan=0.0, posinf=1.0, neginf=0.0) * 255.0, 0, 255).astype(np.uint8)
        if array.ndim != 3 or array.shape[2] not in (3, 4):
            raise GreymonkeyError("Image export expects RGB or RGBA images.")
        img = Image.fromarray(array)
        options = {}
        if image_format == "png":
            pnginfo = PngImagePlugin.PngInfo()
            for key, value in full_metadata.items():
                pnginfo.add_itxt(str(key), json.dumps(value, ensure_ascii=False), zip=True)
            options = dict(pnginfo=pnginfo, compress_level=png_compression)
        else:
            embedded = full_metadata if image_format == "webp" else {
                "greymonkey_prompt": full_metadata["greymonkey_prompt"], "greymonkey_export": export}
            text = json.dumps(embedded, ensure_ascii=False)
            if image_format == "jpeg" and len(text.encode("utf-8")) > 58000:
                text = json.dumps({"metadata_sidecar": True, "message": "Full prompt and workflow in the adjacent .json file."})
            exif = Image.Exif()
            exif[0x010E] = "Greymonkey prompt metadata; see EXIF UserComment and adjacent JSON."
            # ASCII marker + ASCII-escaped JSON is Unicode-safe and portable in EXIF.
            comment = b"ASCII\0\0\0" + json.dumps(json.loads(text), ensure_ascii=True).encode("ascii")
            if image_format == "jpeg" and len(comment) > 58000:
                comment = b"ASCII\0\0\0" + b'{"metadata_sidecar":true,"message":"Full prompt and workflow in adjacent JSON."}'
            exif[0x9286] = comment
            if image_format == "jpeg":
                if img.mode == "RGBA":
                    background = Image.new("RGB", img.size, alpha_background)
                    background.paste(img, mask=img.getchannel("A"))
                    img = background
                else:
                    img = img.convert("RGB")
                options = dict(quality=quality_percent, subsampling={"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}[jpeg_subsampling],
                               progressive=jpeg_progressive, optimize=True, exif=exif.tobytes())
            else:
                options = dict(quality=quality_percent, lossless=webp_lossless, method=webp_method, exif=exif.tobytes())
        extension = "jpg" if image_format == "jpeg" else image_format
        batch_name = name.replace("%batch_num%", str(batch))
        reservation = None
        for _ in range(1000):
            stem = f"{batch_name}_{counter:05}_"
            filename = f"{stem}.{extension}"
            path = resolved_folder / filename
            # Reserve a stem across all codecs and concurrent saver executions.
            if any((resolved_folder / (stem + suffix)).exists() for suffix in (".png", ".jpg", ".webp", ".png.json", ".jpg.json", ".webp.json")):
                counter += 1
                continue
            reservation = resolved_folder / (stem + ".greymonkey-reserve")
            try:
                with reservation.open("xb"):
                    pass
            except FileExistsError:
                counter += 1
                continue
            break
        else:
            raise GreymonkeyError("Unable to reserve a unique image filename. Completed files: " + json.dumps(records))
        temporary_image = temporary_sidecar = None
        finalized_image = finalized_sidecar = False
        sidecar = Path(str(path) + ".json")
        try:
            with tempfile.NamedTemporaryFile("wb", dir=resolved_folder, prefix=".greymonkey-", suffix=".tmp", delete=False) as stream:
                temporary_image = Path(stream.name)
                img.save(stream, format=image_format.upper(), **options)
                stream.flush()
                os.fsync(stream.fileno())
            record = dict(filename=filename, subfolder=subfolder, format=image_format,
                          width=img.width, height=img.height, bytes=temporary_image.stat().st_size,
                          settings=export, sidecar=None)
            record["bytes_per_raw_pixel_ratio"] = record["bytes"] / (img.width * img.height * len(img.getbands()))
            # Finalize the complete metadata first. A visible image always has its
            # required sidecar. Hard links fail rather than overwrite a target.
            if write_sidecar or image_format == "jpeg":
                record["sidecar"] = sidecar.name
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=resolved_folder, prefix=".greymonkey-", suffix=".tmp", delete=False) as stream:
                    temporary_sidecar = Path(stream.name)
                    json.dump({"image": record, "metadata": full_metadata}, stream, ensure_ascii=False, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary_sidecar, sidecar)
                finalized_sidecar = True
            os.link(temporary_image, path)
            finalized_image = True
        except Exception as exc:
            for finalized, failed_path in ((finalized_image, path), (finalized_sidecar, sidecar)):
                if finalized:
                    try:
                        failed_path.unlink(missing_ok=True)
                    except OSError:
                        import logging
                        logging.exception("Could not remove a failed Greymonkey export: %s", failed_path)
            raise GreymonkeyError(
                f"Image export failed at batch item {batch + 1}: {exc}. "
                "Completed files were retained: " + json.dumps(records, ensure_ascii=False)
            ) from exc
        finally:
            for temporary in (temporary_image, temporary_sidecar, reservation):
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        import logging
                        logging.exception("Could not clean up Greymonkey temporary export: %s", temporary)
        previews.append(dict(filename=filename, subfolder=subfolder, type="output"))
        records.append(record)
        counter += 1
    return {"ui": {"images": previews}, "result": (images, json.dumps(records, ensure_ascii=False, indent=2))}


def save_export(*args, **kwargs):
    """Report completed batch files even for codec/tensor preparation failures."""
    from .client import GreymonkeyError
    completed = []
    try:
        return _save_export(*args, **kwargs, _completed=completed)
    except Exception as exc:
        raise GreymonkeyError(str(exc) + "\nRetained completed exports: " + json.dumps(completed, ensure_ascii=False)) from exc
