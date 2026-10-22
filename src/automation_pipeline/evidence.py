"""Exact source provenance checks; these do not establish semantic truth."""

from .state import digest


def build(research, sources):
    by_id = {item["id"]: item for item in sources}
    claims, blockers, seen = [], [], set()
    for claim in research["claims"]:
        reasons = []
        source = by_id.get(claim["source_id"])
        if claim["id"] in seen:
            reasons.append("duplicate_claim_id")
        seen.add(claim["id"])
        if source is None:
            reasons.append("missing_source")
        elif claim["source_excerpt"] not in source["text"]:
            reasons.append("excerpt_mismatch")
        blockers.extend(reasons)
        claims.append(
            claim
            | {"fingerprint": digest(claim), "blockers": reasons, "review_status": "human_review_required"}
        )
    return {
        "schema_version": 1,
        "claims": claims,
        "blockers": blockers,
        "limitations": "Excerpt matching establishes provenance, not semantic truth or complete draft coverage.",
    }
