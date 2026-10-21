"""Explicit source framing, before layout. Never inferred from background colour."""


def crop_filter(shot):
    if shot.get("source_framing", "original") == "original":
        return ""
    return (
        "scale=w='max(2,trunc(iw*sar/2)*2)':h=ih,setsar=1,"
        "crop=w='trunc(min(iw,ih)/2)*2':h='trunc(min(iw,ih)/2)*2':"
        f"x='(iw-ow)*{shot['focus_x']}':y='(ih-oh)*{shot['focus_y']}',"
    )


def media_suffix(shot):
    if shot.get("source_framing", "original") == "original":
        return ""
    return f"-square-{shot['focus_x']}-{shot['focus_y']}"
