"""Reading a multipart/form-data upload (one file plus small fields) safely.

The body is streamed to a file inside the upload's private directory, in chunks, with the
size checked as it arrives, so a large upload is never held in memory. Parts are then
located with mmap. Only the file's own bytes are kept, under a cleaned-up name; the
client's file name can't choose where anything is written.
"""
import mmap
import re
from dataclasses import dataclass, field
from email.parser import BytesHeaderParser
from email.policy import HTTP
from pathlib import Path

from .errors import ApiError, invalid

CHUNK = 64 * 1024
FIELD_LIMIT = 64 * 1024  # small form fields such as "kind"
OVERHEAD = 1024 * 1024  # room for multipart boundaries and fields around the file


@dataclass
class Upload:
    fields: dict[str, str] = field(default_factory=dict)
    filename: str | None = None  # the client's name for the file, cleaned up for display
    path: Path | None = None  # where the file's bytes were saved
    size: int = 0


def too_large(limit: int) -> ApiError:
    megabytes = limit / (1024 * 1024)
    size = f"{megabytes:g} MB" if megabytes >= 1 else f"{limit} bytes"
    return ApiError(413, "too_large", f"That file is larger than this server accepts ({size}). Choose a smaller file.")


def display_name(raw: str | None) -> str:
    """The last part of the client's file name, printable and at most 120 characters."""
    name = re.split(r"[\\/]", raw or "")[-1]
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    if len(name) > 120:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 110] + dot + ext[:9]) if dot and len(ext) <= 9 else name[:120]
    return name


def safe_file_name(name: str) -> str:
    """A name that is safe on any file system and can't leave its directory."""
    cleaned = re.sub(r"[^\w .()\[\]-]", "_", name).strip(" .") or "document"
    return cleaned if not cleaned.startswith(".") else "document" + cleaned


def read_upload(handler, directory: Path, limit: int, file_field: str = "file") -> Upload:
    """Read the request body into `directory` and return its fields and file."""
    content_type = handler.headers.get("Content-Type", "")
    boundary = re.search(r'boundary="?([^";,]+)"?', content_type)
    if not content_type.lower().startswith("multipart/form-data") or not boundary:
        raise invalid("Send the document as multipart/form-data with a \"file\" field.")
    length = handler.headers.get("Content-Length")
    if length is None or not length.isdigit():
        raise invalid("The upload's size (Content-Length) is missing.")
    length = int(length)
    if length > limit + OVERHEAD:  # refuse before reading anything
        handler.close_connection = True
        raise too_large(limit)

    raw = directory / "request.body"
    try:
        _receive(handler, raw, length)
        return _parse(raw, b"--" + boundary[1].encode("latin-1"), directory, limit, file_field)
    finally:
        raw.unlink(missing_ok=True)


def _receive(handler, target: Path, length: int) -> None:
    remaining = length
    with open(target, "wb") as out:
        while remaining:
            chunk = handler.rfile.read(min(CHUNK, remaining))
            if not chunk:  # the client stopped sending: an aborted upload
                handler.close_connection = True
                raise invalid("The upload was interrupted. Try again.")
            out.write(chunk)
            remaining -= len(chunk)


def _parse(raw: Path, delimiter: bytes, directory: Path, limit: int, file_field: str) -> Upload:
    upload = Upload()
    if raw.stat().st_size == 0:
        raise invalid("The upload was empty.")
    with open(raw, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as body:
        position = body.find(delimiter)
        if position == -1:
            raise invalid("The upload isn't valid multipart/form-data.")
        while True:
            position += len(delimiter)
            if body[position:position + 2] == b"--":  # the closing delimiter
                break
            position += 2  # CRLF after the delimiter
            headers_end = body.find(b"\r\n\r\n", position)
            if headers_end == -1 or headers_end - position > FIELD_LIMIT:
                raise invalid("The upload isn't valid multipart/form-data.")
            headers = BytesHeaderParser(policy=HTTP).parsebytes(body[position:headers_end])
            start = headers_end + 4
            end = body.find(b"\r\n" + delimiter, start)
            if end == -1:
                raise invalid("The upload isn't valid multipart/form-data.")
            name = headers.get_param("name", header="content-disposition")
            filename = headers.get_filename()
            if filename is not None and name == file_field and upload.path is None:
                size = end - start
                if size > limit:
                    raise too_large(limit)
                upload.filename = display_name(filename) or "document"
                upload.path = directory / safe_file_name(upload.filename)
                with open(upload.path, "wb") as out:
                    for offset in range(start, end, CHUNK):
                        out.write(body[offset:min(offset + CHUNK, end)])
                upload.size = size
            elif filename is None and isinstance(name, str):
                if end - start > FIELD_LIMIT:
                    raise invalid(f"The form field \"{name[:40]}\" is too long.")
                upload.fields[name] = body[start:end].decode("utf-8", errors="replace")
            position = end + 2  # skip the CRLF before the next delimiter
    return upload
