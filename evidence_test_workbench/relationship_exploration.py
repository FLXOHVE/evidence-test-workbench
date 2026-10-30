"""Read-only resource recall over sealed evidence, never product-rule inference.

The host names resources and ordered usage situations.  Matching source lines
only proposes material to investigate; it does not establish a relationship,
current applicability, a test oracle, or complete coverage of the product.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from . import evidence


POLICY = "relationship-exploration-v1"
RUN_FIELD = "relationship_exploration"
_POINTER_FIELDS = ("schema_version", "checked_at", "target", "bundle_id", "manifest_ref", "manifest_hash")
_BUNDLE_ID = re.compile(r"evidence-[0-9a-f]{32}\Z")
_MAX_MANIFEST_BYTES = 2_000_000
_SOURCE_FIELDS = (
    "source_id", "source_type", "version", "content_hash", "url", "raw_ref", "fetched_at",
    "source_updated_at", "status", "applicability", "comments_complete", "read_scope",
    "applicability_scope", "reading_boundary", "evidence_tier", "draft_only", "draft_scope",
    "archive_provenance",
)
BOUNDARY = (
    "Only integrity-verified sealed targeted bundles and the pinned baseline are scanned. "
    "Resource-text matches are unresearched candidates, not confirmed effects or no-effect findings. "
    "Unmatched resources and unscanned/rejected material remain unknown. "
    "This is neither a whole-knowledge-base search nor semantic or version completeness."
)


def fingerprint(value):
    """Canonical content fingerprint, excluding only the top-level fingerprint."""
    payload = {key: item for key, item in value.items() if key != "fingerprint"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _normal(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value).casefold())


def _text(value, *, limit=2000):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and not any(
        ord(char) < 32 and char not in "\r\n\t" for char in value)


def _strings(values, *, limit=1000, unique=True):
    return (isinstance(values, list) and len(values) <= limit
        and all(_text(value) for value in values)
        and (not unique or len(values) == len(set(values))))


def validate_profile(profile):
    """Validate host analysis without interpreting it as an approved product model."""
    if (not isinstance(profile, dict)
            or set(profile) != {"schema_version", "module", "resources", "usage_scenarios"}
            or type(profile.get("schema_version")) is not int or profile["schema_version"] != 1
            or not _text(profile.get("module"), limit=500) or evidence._contains_secret(profile)):
        raise ValueError("Invalid relationship exploration profile")
    resources = profile["resources"]
    if not isinstance(resources, list) or not resources or len(resources) > 1000:
        raise ValueError("Relationship exploration requires bounded resources")
    resource_ids = set()
    for resource in resources:
        if (not isinstance(resource, dict) or set(resource) != {"id", "terms", "reason"}
                or not _text(resource.get("id"), limit=128) or resource["id"] in resource_ids
                or not _text(resource.get("reason")) or not _strings(resource.get("terms"), limit=100)
                or not resource["terms"]
                or len({_normal(term) for term in resource["terms"]}) != len(resource["terms"])):
            raise ValueError("Invalid or duplicate resource definition")
        resource_ids.add(resource["id"])
    scenarios = profile["usage_scenarios"]
    if not isinstance(scenarios, list) or len(scenarios) > 1000:
        raise ValueError("Usage scenarios must be a bounded array")
    seen = set()
    for scenario in scenarios:
        if (not isinstance(scenario, dict)
                or set(scenario) != {"id", "user_task", "context", "resource_ids", "changes"}
                or not _text(scenario.get("id"), limit=128) or scenario["id"] in seen
                or not _text(scenario.get("user_task")) or not _text(scenario.get("context"))
                or not _strings(scenario.get("resource_ids")) or not scenario["resource_ids"]
                or set(scenario["resource_ids"]) - resource_ids
                or not _strings(scenario.get("changes"), unique=False)):
            raise ValueError("Invalid usage scenario or unknown resource")
        seen.add(scenario["id"])
    return deepcopy(profile)


def _binding(run):
    target, query = run.get("target"), run.get("query", "")
    if not isinstance(target, dict) or not target or not isinstance(query, str):
        raise ValueError("Exploration requires an explicit target and original query")
    baseline = run.get("baseline") or {}
    if not isinstance(baseline, dict) or not isinstance(baseline.get("sources", []), list):
        raise ValueError("Invalid exploration baseline")
    sources = []
    for source in baseline.get("sources", []):
        if (not isinstance(source, dict) or not _text(source.get("source_id"))
                or not isinstance(source.get("content_hash"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", source["content_hash"])):
            raise ValueError("Invalid exploration baseline identity")
        sources.append({key: deepcopy(source.get(key)) for key in ("source_id", "content_hash", "version")})
    result = {"target": deepcopy(target), "baseline_sources": sorted(sources,
        key=lambda item: (item["source_id"], item["content_hash"], str(item["version"]))), "query": query}
    if evidence._contains_secret(result):
        raise ValueError("Invalid exploration binding")
    return result


def _safe_directory(root, relative):
    """Reject links/junctions at every component, including the storage ancestors."""
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
            raise ValueError("Unsafe evidence directory")
    candidate.resolve().relative_to(root)
    return candidate


def _pointer(root, manifest):
    if manifest.stat().st_size > _MAX_MANIFEST_BYTES:
        raise ValueError("Oversized manifest")
    data = manifest.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict) or value.get("status") != "passed":
        raise ValueError("Unpassed manifest")
    pointer = {key: deepcopy(value.get(key)) for key in _POINTER_FIELDS if key not in {"manifest_ref", "manifest_hash"}}
    pointer.update(manifest_ref=manifest.relative_to(root).as_posix(),
        manifest_hash=hashlib.sha256(data).hexdigest())
    return pointer


def build_exploration(root, run, profile, *, max_bundles=250, max_candidates=1000, max_context_bytes=2_000_000):
    """Recall resource lines without changing evidence, pointers, or confirmed rules.

    The bounded archive inventory is deterministic.  The pinned baseline is
    attempted first, and every consumed body comes from ``evidence.load_bundle``.
    Invalid archives retain only non-sensitive rejection codes in the report.
    """
    for value, upper in ((max_bundles, 10000), (max_candidates, 100000), (max_context_bytes, 100_000_000)):
        if type(value) is not int or not 1 <= value <= upper:
            raise ValueError("Exploration limits must be bounded positive integers")
    if not isinstance(run, dict):
        raise ValueError("Exploration requires a run")
    root = Path(root).resolve()
    profile = validate_profile(profile)
    binding = _binding(run)
    scan = {"scanned": 0, "attempted": 0, "inventoried_bundles": 0,
        "rejected": 0, "source_count": 0, "truncated": False,
        "max_bundles": max_bundles, "max_candidates": max_candidates,
        "truncation_reasons": [], "rejections": [], "unmatched_resource_ids": [],
        "source_context_bytes": 0, "max_context_bytes": max_context_bytes,
        "scope": "sealed_targeted_evidence_only", "boundary": BOUNDARY}
    queue, seen_refs = [], set()
    baseline = run.get("baseline")
    if baseline:
        pointer = {key: deepcopy(baseline.get(key)) for key in _POINTER_FIELDS}
        # The evidence loader enforces canonical pointer fields and paths.
        queue.append((pointer, "pinned_baseline"))
        if isinstance(pointer.get("manifest_ref"), str):
            seen_refs.add(pointer["manifest_ref"])
    try:
        directory = _safe_directory(root, Path(evidence.NAMESPACE) / "generations")
        if directory.is_dir():
            for bundle in sorted(directory.iterdir(), key=lambda path: path.name):
                if not _BUNDLE_ID.fullmatch(bundle.name):
                    continue  # No arbitrary directory names or source text are echoed.
                ref = f"{evidence.NAMESPACE}/generations/{bundle.name}/manifest.json"
                if ref not in seen_refs:
                    queue.append((ref, "sealed_archive"))
                    seen_refs.add(ref)
    except (OSError, ValueError):
        scan["rejected"] += 1
        scan["rejections"].append({"bundle_ref": None, "code": "unsafe_or_unreadable_inventory"})
    scan["inventoried_bundles"] = len(queue)
    if len(queue) > max_bundles:
        scan["truncated"] = True
        scan["truncation_reasons"].append("bundle_limit")
    candidates, identities = [], set()
    source_contexts = {}
    normalized_terms = {resource["id"]: [(_normal(term), term) for term in resource["terms"]]
        for resource in profile["resources"]}
    matched_resources = set()
    for entry, origin in queue[:max_bundles]:
        scan["attempted"] += 1
        ref = entry.get("manifest_ref") if isinstance(entry, dict) else entry
        # Rejection metadata never repeats an untrusted baseline path.
        safe_ref = ref if isinstance(ref, str) and re.fullmatch(
            re.escape(evidence.NAMESPACE) + r"/generations/evidence-[0-9a-f]{32}/manifest\.json", ref) else None
        try:
            if isinstance(entry, str):
                path = _safe_directory(root, Path(entry))
                pointer = _pointer(root, path)
            else:
                pointer = entry
            bundle = evidence.load_bundle(root, pointer)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            scan["rejected"] += 1
            scan["rejections"].append({"bundle_ref": safe_ref, "code": "bundle_not_verified"})
            continue
        scan["scanned"] += 1
        for source in bundle["sources"]:
            scan["source_count"] += 1
            source_matched = False
            for line, quote in enumerate(source["body"].splitlines(), 1):
                if not quote.strip():
                    continue
                normal = _normal(quote)
                for resource_id, terms in normalized_terms.items():
                    hits = [original for normalized, original in terms if normalized in normal]
                    if not hits:
                        continue
                    source_matched = True
                    matched_resources.add(resource_id)
                    identity = (source["source_id"], source["content_hash"], resource_id, line)
                    if identity in identities:
                        continue
                    identities.add(identity)
                    if len(candidates) >= max_candidates:
                        scan["truncated"] = True
                        if "candidate_limit" not in scan["truncation_reasons"]:
                            scan["truncation_reasons"].append("candidate_limit")
                        continue
                    metadata = {key: deepcopy(source.get(key)) for key in _SOURCE_FIELDS}
                    metadata["latest_verified"] = False
                    candidates.append({"id": "RC-" + hashlib.sha256(json.dumps(identity,
                        ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()[:24],
                        "resource_id": resource_id, "matched_terms": hits, "quote": quote, "line": line,
                        "source": metadata, "bundle_ref": deepcopy(pointer), "origin": origin,
                        "evidence_status": "unresearched", "latest_verified": False})
            if source_matched:
                # The body has just passed evidence.load_bundle integrity
                # checks. Do not reconstruct an alleged page from hit lines.
                from .source_branch_contract import source_context
                context = source_context(source, origin="recalled_source")
                if context["id"] not in source_contexts:
                    size = len(context["body"].encode("utf-8"))
                    if scan["source_context_bytes"] + size > max_context_bytes:
                        scan["truncated"] = True
                        if "source_context_limit" not in scan["truncation_reasons"]:
                            scan["truncation_reasons"].append("source_context_limit")
                    else:
                        source_contexts[context["id"]] = context
                        scan["source_context_bytes"] += size
    scan["unmatched_resource_ids"] = [resource["id"] for resource in profile["resources"]
        if resource["id"] not in matched_resources]
    result = {"policy": POLICY, "profile": profile, "binding": binding,
        "candidates": candidates, "source_contexts": sorted(source_contexts.values(), key=lambda row: row["id"]),
        "scan": scan, "latest_verified": False,
        "semantic_verified": False, "complete": False}
    result["fingerprint"] = fingerprint(result)
    return result


def context_for_run(run, module):
    """Expose only a matching record; never silently refresh or reinterpret it."""
    absent = {"policy": POLICY, "status": "not_assessed", "latest_verified": False,
        "complete": False, "boundary": BOUNDARY}
    if not isinstance(run, dict) or RUN_FIELD not in run:
        return absent
    record = run[RUN_FIELD]
    try:
        valid = (isinstance(record, dict) and record.get("policy") == POLICY
            and record.get("fingerprint") == fingerprint(record)
            and record.get("binding") == _binding(run)
            and validate_profile(record.get("profile"))["module"] == module
            and record.get("latest_verified") is False and record.get("complete") is False
            and record.get("semantic_verified") is False
            and isinstance(record.get("candidates"), list) and isinstance(record.get("scan"), dict)
            and not evidence._contains_secret(record))
    except (ValueError, TypeError, KeyError, RecursionError):
        valid = False
    if not valid:
        return {**absent, "status": "stale"}
    return {**deepcopy(record), "status": "candidates_recalled"}
