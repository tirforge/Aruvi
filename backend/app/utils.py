import re


def sanitize_filename(name: str) -> str:
    if not name:
        return "unnamed_file"

    name = name.replace("\x00", "").replace("/", "_").replace("\\", "_")
    name = re.sub(r'[<>:"|?*\x00-\x1f]', '_', name)
    name = name.strip(". ")

    if len(name) > 255:
        if "." in name:
            ext = name.rsplit(".", 1)[-1][:10]
            name = name[:255 - len(ext) - 1] + "." + ext
        else:
            name = name[:255]

    return name if name else "unnamed_file"


def md_safe(text: str) -> str:
    """Make user text safe to embed in Pyrogram's default Markdown parse mode.

    Backticks are the dangerous one: inside a `` `code span` `` an unbalanced
    backtick breaks the whole message parse (MessageParseError → send fails).
    Markdown action characters (**, [], etc.) only render oddly, so they stay.
    """
    return text.replace("`", "'") if text else text
