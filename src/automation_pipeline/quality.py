"""Deterministic quality checks; no automatic factual certification."""

import re
from urllib.parse import urlsplit
from markdown_it import MarkdownIt
from .evidence import build


def audit(outputs, sources, config):
    ledger = build(outputs["research"], sources)
    errors = list(ledger["blockers"])
    warnings = []
    known = {c["id"] for c in outputs["research"]["claims"]}
    draft = outputs["write"]["markdown"]
    refs = re.findall(r"\[\[claim:([^]\n]+)\]\]", draft)
    if not refs:
        errors.append("missing_claim_references")
    if set(refs) - known:
        errors.append("unknown_claim_reference")
    for section in outputs["outline"]["sections"]:
        if set(section["claim_ids"]) - known:
            errors.append("unknown_outline_claim")
    if re.search(r"FACT_CHECK_NEEDED|STAT_NEEDED|EMBED_NEEDED|REPLACE_SLUG", draft, re.I):
        errors.append("unresolved_placeholder")
    if not re.search(r"^#{1,3} ", draft, re.M):
        errors.append("missing_heading")
    links = []
    for token in MarkdownIt("commonmark", {"html": False}).parse(draft):
        for child in token.children or []:
            if child.type == "image":
                errors.append("images_not_supported")
            if child.type == "link_open":
                links.append(child.attrGet("href") or "")
    # The parser deliberately refuses dangerous URLs, so inspect raw destinations too.
    links += re.findall(r"\]\(\s*([^\s)]+)", draft)
    for link in links:
        parsed = urlsplit(link)
        if parsed.scheme not in {"https"} or not parsed.hostname or parsed.username or parsed.password:
            errors.append("unsafe_url")
    if not any(s["origin_url"] in links for s in sources):
        errors.append("missing_source_link")
    words = len(re.findall(r"\b[\w'-]+\b", draft))
    tolerance = config["word_count_tolerance"]
    if not config["target_words"] * (1 - tolerance) <= words <= config["target_words"] * (1 + tolerance):
        warnings.append("word_count_outside_range")
    report = {
        "schema_version": 1,
        "status": "RED" if errors else "AMBER" if warnings else "GREEN",
        "errors": sorted(set(errors)),
        "warnings": warnings,
        "word_count": words,
        "human_review_required": True,
    }
    return report, ledger
