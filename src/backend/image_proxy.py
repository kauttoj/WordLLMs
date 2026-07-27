"""Server-side image fetching for the Word add-in.

The add-in runs inside a browser sandbox, so `fetch()` on an arbitrary image URL
fails on two things the add-in cannot influence:

  * CORS — most image hosts send no `Access-Control-Allow-Origin` header, so the
    browser discards the response before the add-in ever sees it.
  * Hotlink protection — a request carrying no `Referer` is answered with
    403/400 by many CDNs.

The backend has neither restriction. It also transcodes formats Word's image
decoder does not understand (WEBP, AVIF, ...) into PNG, so
`insertInlinePictureFromBase64` always receives something it can render.

This is a *fallback*, not the primary path. Some hosts do the opposite and
refuse server-side clients while serving browsers freely (Wikimedia answers 403
with a link to its robot policy), so the add-in tries its own `fetch()` first
and only comes here when that fails or yields a format Word cannot decode.

Because this endpoint makes the server fetch a caller-supplied URL, it is a
server-side request forgery surface. `assert_public_url` is the guard: only
http/https, and every address the host resolves to must be a public one.
"""

from __future__ import annotations

import base64
import io
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 20 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 20.0

# Formats Word's inline-picture decoder handles directly. Anything else is
# transcoded to PNG before it reaches Office.js.
WORD_NATIVE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/bmp", "image/tiff"})

# Some hosts serve a real image but label it octet-stream; Pillow decides.
_AMBIGUOUS_TYPES = frozenset({"application/octet-stream", "binary/octet-stream", ""})

# Enough to get past hotlink filters that reject header-less clients, while
# still identifying the client honestly. Impersonating Chrome buys nothing:
# Wikimedia answers 403 to every server-side User-Agent tried (browser string,
# descriptive string, and none at all), so the add-in tries the browser first
# and only falls back here — see fetchImageAsBase64 in wordTools.ts.
_REQUEST_HEADERS = {
    "User-Agent": "WordLLMs-ImageProxy/1.0 (Word add-in image fetcher; +https://github.com/kuingsmile/word-gpt-plus)",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


class ImageProxyError(Exception):
    """Raised with a message meant to be shown to the LLM and the user."""


@dataclass(frozen=True)
class FetchedImage:
    base64: str
    content_type: str
    source_content_type: str
    converted: bool
    byte_size: int


def assert_public_url(url: str) -> None:
    """Reject anything that is not an http(s) URL pointing at a public address.

    Every resolved address is checked, not just the first: a hostname that
    resolves to both a public and a loopback address must not slip through.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ImageProxyError(
            f"Only http and https image URLs can be fetched (got scheme '{parsed.scheme or 'none'}'). "
            "Pass a base64-encoded image instead for local files."
        )
    host = parsed.hostname
    if not host:
        raise ImageProxyError("The image URL has no host component.")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ImageProxyError(f"Could not resolve image host '{host}': {exc}") from exc

    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ImageProxyError(
                f"Refusing to fetch '{host}': it resolves to the non-public address {address}."
            )


def _transcode_to_png(payload: bytes, source_type: str) -> bytes:
    """Re-encode an image Word cannot decode as PNG.

    Import is local so the endpoint still serves natively-supported formats on
    an install without Pillow, instead of failing at import time.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise ImageProxyError(
            f"The image is {source_type}, which Word cannot display, and Pillow is not "
            "installed to convert it. Install Pillow or use a PNG/JPEG/GIF image."
        ) from exc

    try:
        with Image.open(io.BytesIO(payload)) as img:
            # PNG has no CMYK mode and palette images with transparency need RGBA.
            if img.mode in ("CMYK", "P", "LA"):
                img = img.convert("RGBA" if "A" in img.mode or img.mode == "P" else "RGB")
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            return buffer.getvalue()
    except Exception as exc:
        raise ImageProxyError(
            f"The image is {source_type}, which Word cannot display, and it could not be "
            f"converted to PNG: {exc}. Try a PNG or JPEG version of the image."
        ) from exc


async def fetch_image(url: str) -> FetchedImage:
    """Fetch `url` and return it base64-encoded in a format Word can render."""
    assert_public_url(url)

    try:
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS, headers=_REQUEST_HEADERS
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise ImageProxyError(f"Request to '{url}' failed: {exc}") from exc

    if response.status_code >= 400:
        raise ImageProxyError(
            f"The image host returned HTTP {response.status_code} for '{url}'. "
            "The URL may be wrong, private, or blocking automated requests."
        )

    payload = response.content
    if not payload:
        raise ImageProxyError(f"'{url}' returned an empty response body.")
    if len(payload) > MAX_IMAGE_BYTES:
        raise ImageProxyError(
            f"The image is {len(payload) // (1024 * 1024)} MB, over the "
            f"{MAX_IMAGE_BYTES // (1024 * 1024)} MB limit."
        )

    source_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not source_type.startswith("image/") and source_type not in _AMBIGUOUS_TYPES:
        raise ImageProxyError(
            f"'{url}' served content-type '{source_type}', not an image. "
            "Check that the URL points directly at an image file, not at a web page."
        )

    converted = False
    content_type = source_type
    if source_type not in WORD_NATIVE_TYPES:
        payload = _transcode_to_png(payload, source_type or "an unknown format")
        content_type = "image/png"
        converted = True
        logger.info("[image-proxy] converted %s -> image/png for %s", source_type or "unknown", url)

    return FetchedImage(
        base64=base64.b64encode(payload).decode("ascii"),
        content_type=content_type,
        source_content_type=source_type or "unknown",
        converted=converted,
        byte_size=len(payload),
    )
