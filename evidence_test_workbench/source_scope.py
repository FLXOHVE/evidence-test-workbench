"""Explicit versioned excerpts: usable for fixed drafts, never a freshness grant.

Pure evidence semantics shared by capture, rules, methods and workflow gates.
Recorded reading judgments still require independent semantic review.
"""
from copy import deepcopy
import re
from urllib.parse import parse_qs, urlsplit

EXCERPT_TIER = "versioned_excerpt_draft"
ARCHIVED_TIER = "archived_excerpt_draft"


def is_archived(source):
    return source.get("evidence_tier") == ARCHIVED_TIER


def is_excerpt(source):
    return source.get("evidence_tier") in (EXCERPT_TIER, ARCHIVED_TIER)


def validate_excerpt_scope(source):
    """Return an error string without echoing untrusted source values."""
    tier = source.get("evidence_tier", "complete")
    if not isinstance(tier, str) or tier not in {"complete", EXCERPT_TIER, ARCHIVED_TIER}:
        return "Unknown evidence tier"
    if tier == "complete":
        if any(k in source for k in ("draft_scope", "draft_only", "archive_provenance")):
            return "Draft metadata requires the explicit excerpt tier"
        return None
    if tier == EXCERPT_TIER and source.get("source_type") != "confluence":
        return "Excerpt tier currently supports versioned Confluence pages only"
    if tier != ARCHIVED_TIER and "archive_provenance" in source:
        return "Archive provenance requires the archived excerpt tier"
    if tier == ARCHIVED_TIER:
        archive = source.get("archive_provenance")
        if not isinstance(archive, dict) or set(archive) != {"local_read_at", "artifacts", "extraction"}:
            return "Archived evidence needs local reading time, exact artifacts and extraction boundary"
        if not isinstance(archive["extraction"], str) or not archive["extraction"].strip():
            return "Archived extraction boundary must be explicit"
        artifacts = archive["artifacts"]
        if not isinstance(artifacts, list) or not artifacts:
            return "Archived evidence needs at least one original snapshot binding"
        refs = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {"ref", "sha256", "role"}:
                return "Archive artifact requires ref, SHA256 and role"
            if (not isinstance(artifact["ref"], str) or artifact["ref"] in refs
                    or not isinstance(artifact["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", artifact["sha256"])
                    or artifact["role"] not in ("source_snapshot", "selected_projection")):
                return "Invalid or repeated archived artifact binding"
            refs.add(artifact["ref"])
        if not any(a["role"] == "source_snapshot" for a in artifacts):
            return "A projection cannot replace the original source snapshot"
    if source.get("draft_only") is not True or source.get("latest_verified") is not False:
        return "Excerpt evidence must explicitly remain draft-only and not latest-verified"
    if not isinstance(source.get("comments_complete"), bool):
        return "Actual comment completeness must remain an explicit boolean"
    try:
        page_id = str(source.get("source_id", "")).removeprefix("confluence:")
        query = parse_qs(urlsplit(source["url"]).query)
        if source.get("source_type") == "confluence" and (not re.fullmatch(r"[1-9][0-9]*", page_id) or query.get("pageId") != [page_id]):
            return "Excerpt source identity must match the exact URL pageId"
    except (KeyError, ValueError, TypeError):
        return "Invalid excerpt source URL"
    scope = source.get("draft_scope")
    fields = {"read_boundary", "applicability_basis", "unread_parts", "excerpts", "objections"}
    if not isinstance(scope, dict) or set(scope) != fields:
        return "Excerpt scope requires exact reading, applicability and unresolved context fields"
    for key in ("read_boundary", "applicability_basis"):
        if not isinstance(scope[key], str) or not scope[key].strip():
            return "Reading and version applicability boundaries must be explicit"
    unread = scope["unread_parts"]
    if not isinstance(unread, list) or not unread or any(not isinstance(x, str) or not x.strip() for x in unread):
        return "Excerpt evidence must list remaining unread or unavailable metadata"
    if source["comments_complete"] is False and "comments" not in unread:
        return "Unread comments cannot be omitted from the boundary"
    if source.get("source_updated_at") is None and "source_updated_at" not in unread:
        return "Unknown source timestamp cannot be omitted from the boundary"
    if tier == ARCHIVED_TIER:
        for field in ("fetched_at", "version"):
            if source.get(field) is None and field not in unread:
                return "Unknown remote metadata must remain in the archive boundary"
    excerpts, known = scope["excerpts"], set()
    if not isinstance(excerpts, list) or not excerpts:
        return "At least one exact excerpt and its read context are required"
    body = source.get("body")
    for item in excerpts:
        if not isinstance(item, dict) or set(item) != {"id", "quote", "context"}:
            return "Excerpt must contain ID, exact quote and surrounding read context"
        if any(not isinstance(item[k], str) or not item[k].strip() for k in item) or item["id"] in known:
            return "Excerpt fields must be nonempty and IDs unique"
        known.add(item["id"])
        if not isinstance(body, str) or item["context"] not in body or item["quote"] not in item["context"]:
            return "Excerpt/context must be literal parts of the captured body"
    objections, seen = scope["objections"], set()
    if not isinstance(objections, list):
        return "Known objections must be an explicit list, even if none were read"
    for item in objections:
        if not isinstance(item, dict) or set(item) != {"id", "excerpt_ids", "reason"}:
            return "Objections need an ID, exact affected excerpts and a reason"
        if not isinstance(item["id"], str) or not item["id"].strip() or item["id"] in seen:
            return "Objection IDs must be nonempty and unique"
        seen.add(item["id"])
        if not isinstance(item["reason"], str) or not item["reason"].strip():
            return "Objections need a concrete reason"
        refs = item["excerpt_ids"]
        if not isinstance(refs, list) or not refs or any(not isinstance(x, str) or x not in known for x in refs):
            return "Objections must name existing excerpt IDs"
    return None


def excerpt_supports(source, quote):
    """A confirmed claim cannot expand into unread context or disputed excerpts."""
    if not is_excerpt(source):
        return True  # Normal source/accepted-comment matching remains with callers.
    if validate_excerpt_scope(source) or not isinstance(quote, str) or not quote.strip():
        return False
    scope = source["draft_scope"]
    blocked = {i for obj in scope["objections"] for i in obj["excerpt_ids"]}
    def spans(text):
        found, start = [], 0
        while (start := source["body"].find(text, start)) >= 0:
            found.append((start, start + len(text)))
            start += 1
        return found

    # Compare ranges in the actual body, not just complete substring containment.
    # Repeated identical quotes remain ambiguous: any disputed matching occurrence
    # blocks the claim rather than silently choosing the convenient occurrence.
    disputed = [span for e in scope["excerpts"] if e["id"] in blocked for span in spans(e["quote"])]
    candidates = spans(quote)
    if any(a < d and c < b for a, b in candidates for c, d in disputed):
        return False
    return any(quote in e["quote"] for e in scope["excerpts"] if e["id"] not in blocked)


def draft_source_labels(sources, source_ids=None):
    """Compact propagated boundary; source text remains in the sealed bundle."""
    return [{"source_id": s["source_id"], "evidence_tier": s["evidence_tier"],
             "comments_complete": s["comments_complete"], "source_updated_at": s.get("source_updated_at"),
             "read_boundary": s["draft_scope"]["read_boundary"],
             "unread_parts": deepcopy(s["draft_scope"]["unread_parts"]),
             "objections": deepcopy(s["draft_scope"]["objections"]),
             **({"archive_provenance": deepcopy(s["archive_provenance"]),
                 "fetched_at": s.get("fetched_at"), "version": s.get("version")} if is_archived(s) else {})}
            for s in sources if is_excerpt(s) and (source_ids is None or s["source_id"] in source_ids)]
