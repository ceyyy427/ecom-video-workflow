"""Comparison-only cue normalization adapted from MoneyPrinterTurbo.

MIT Copyright (c) 2024 Harry; see docs/third-party/MoneyPrinterTurbo-LICENSE.
Based on voice.py::_match_script_line: canonical Unicode and punctuation-free
comparison, always preserving the original script. Scores suggest drafts only;
they never approve content or create measured timestamps.
"""

import re
import unicodedata
from difflib import SequenceMatcher


def comparison_text(text):
    return re.sub(r"[_\W]+", "", unicodedata.normalize("NFKC", text).casefold())


def match_score(script, transcript):
    a, b = comparison_text(script), comparison_text(transcript)
    if not a or not b:
        return 0.0
    # Require coverage in both directions: a short excerpt is not a full script.
    matched = sum(x.size for x in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    return round(min(matched / len(a), matched / len(b)), 3)


def matching_drafts(drafts, transcript, fact_ids):
    result = []
    for draft in drafts:
        if any(set(s["fact_ids"]) - fact_ids for s in draft["payload"]):
            continue
        score = match_score("\n".join(s["text"] for s in draft["payload"]), transcript)
        if score >= 0.8:
            result.append({"draft_id": draft["id"], "score": score})
    return sorted(result, key=lambda x: x["score"], reverse=True)[:3]
