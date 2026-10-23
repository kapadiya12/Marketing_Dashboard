import os

from django.conf import settings
from django.core.exceptions import ValidationError

IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

# Leading bytes for common types; used to reject files whose content does not match the extension.
_SIGNATURES = {
    "pdf": [b"%PDF"],
    "png": [b"\x89PNG"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],
    "zip": [b"PK\x03\x04", b"PK\x05\x06"],
    "docx": [b"PK\x03\x04"],
    "xlsx": [b"PK\x03\x04"],
    "pptx": [b"PK\x03\x04"],
    "odt": [b"PK\x03\x04"],
    "ods": [b"PK\x03\x04"],
    "odp": [b"PK\x03\x04"],
    "key": [b"PK\x03\x04"],
    "doc": [b"\xd0\xcf\x11\xe0"],
    "xls": [b"\xd0\xcf\x11\xe0"],
    "ppt": [b"\xd0\xcf\x11\xe0"],
}


def _extension(name):
    return os.path.splitext(name or "")[1].lower().lstrip(".")


def _check_signature(f, ext):
    signatures = _SIGNATURES.get(ext)
    if not signatures:
        return
    pos = f.tell() if hasattr(f, "tell") else None
    try:
        f.seek(0)
        head = f.read(8)
    finally:
        if pos is not None:
            f.seek(pos)
    if not any(head.startswith(sig) for sig in signatures):
        raise ValidationError(f"The file content does not match the .{ext} extension.")


def validate_file_size(f):
    if f.size and f.size > settings.MAX_UPLOAD_SIZE:
        raise ValidationError(f"File too large. Maximum size is {settings.MAX_UPLOAD_SIZE // (1024 * 1024)} MB.")


def validate_attachment_upload(f):
    ext = _extension(f.name)
    if ext not in settings.ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '.{ext}'. Allowed: {', '.join(settings.ALLOWED_ATTACHMENT_EXTENSIONS)}."
        )
    validate_file_size(f)
    _check_signature(f, ext)


def validate_image_upload(f):
    ext = _extension(f.name)
    if ext not in IMAGE_EXTENSIONS:
        raise ValidationError("Upload a PNG, JPG, GIF or WEBP image.")
    validate_file_size(f)
    _check_signature(f, ext)


def validate_csv_upload(f):
    ext = _extension(f.name)
    if ext not in {"csv", "txt"}:
        raise ValidationError("Upload a .csv file.")
    validate_file_size(f)
