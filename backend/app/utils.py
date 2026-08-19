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
