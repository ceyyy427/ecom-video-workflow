"""Versioned, server-owned narration directions shared by previews and customer production."""

VERSION = "voice-directions-v1"
PROFILES = {
    "cinema": {
        "name": "轻声克制",
        "speaker": "zh_female_vv_uranus_bigtts",
        "speech_rate": -5,
        "direction": "请用自然轻声对话的方式，温柔克制，句尾有自然呼吸，不要播音腔，不要夸张推销。",
    },
    "social": {
        "name": "朋友分享",
        "speaker": "zh_female_vv_uranus_bigtts",
        "speech_rate": 5,
        "direction": "请像向朋友分享日常一样亲切轻快，第一句带一点俏皮提醒，语调有起伏，不要播音腔和夸张叫卖。",
    },
    "lab": {
        "name": "自然讲解",
        "speaker": "zh_female_gaolengyujie_uranus_bigtts",
        "speech_rate": 0,
        "direction": "请像当面一起观察商品，清楚自然地讲解，短句有轻重和停顿，不要新闻播报腔，不要夸张推销。",
    },
}

# Existing three profiles stay byte-for-byte stable for old takes and boards.
for _style, _base, _name, _rate in (
    ("editorial", "cinema", "质感轻声", -4),
    ("quiet", "cinema", "温暖慢叙", -8),
    ("collage", "social", "亲切生活分享", 3),
    ("kinetic", "social", "轻快节奏", 8),
    ("evidence", "lab", "清晰细节解说", -2),
    ("bauhaus", "lab", "利落设计讲解", 2),
):
    PROFILES[_style] = {**PROFILES[_base], "name": _name, "speech_rate": _rate}
