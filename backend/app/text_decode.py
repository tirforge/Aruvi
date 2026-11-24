"""Decode subtitle/text bytes that are not guaranteed to be UTF-8.

Subtitle providers are inconsistent: most serve UTF-8 today, but older
OpenSubtitles uploads are Windows-1252 and a few are Latin-1 or Cyrillic
codepages. The previous `bytes.decode("utf-8", errors="replace")` turned every
accented character in those files into U+FFFD (mojibake subtitles).

`chardet` (Mozilla's detector, pure Python) identifies both Windows-1252 and
Windows-1251 correctly on real subtitle prose, where charset-normalizer's
Latin-codepage ranking picks cp1257/cp1250 instead. Short or unrecognisable
inputs fall back to Windows-1252 -> Latin-1, which cannot fail.
"""

from __future__ import annotations

from chardet import detect


def decode_text(data: bytes) -> str:
    """Best-effort decode of provider-supplied text bytes."""
    if not data:
        return ""

    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass

    guess = detect(data)
    encoding = guess.get("encoding")
    if encoding:
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            text = ""
        if text and "\ufffd" not in text:
            return text.lstrip("\ufeff")

    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")
