"""Offline, immutable evidence bundles from read-only connector results.

This module does not fetch sources or authenticate. A passing manifest proves
snapshot integrity, not that a source is currently fresh or approved.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4
from .source_scope import is_excerpt, is_archived, validate_excerpt_scope


NAMESPACE = "local_data/knowledge_base/targeted_evidence"
_DERIVED_FIELDS = {"content_hash", "raw_ref"}
_DIGEST_EXCLUDED = _DERIVED_FIELDS | {"fetched_at", "checked_at"}
_SECRET_KEYS = {
    "password", "passwd", "secret", "clientsecret", "token", "accesstoken",
    "refreshtoken", "idtoken", "apikey", "authorization", "proxyauthorization",
    "cookie", "cookies", "setcookie", "session", "sessionid", "credentials",
}
_REQUIRED = {
    "source_id", "source_type", "url", "version", "source_updated_at",
    "fetched_at", "body", "comments", "comments_complete", "applicability", "status",
}


class EvidenceError(ValueError):
    """Rejected input; errors deliberately contain no source values or secrets."""

    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("Evidence rejected: " + ", ".join(item["code"] for item in errors))


def _issue(code: str, message: str, **location: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **location}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        return any(not isinstance(k, str) or _key(k) in _SECRET_KEYS
                   or _contains_secret(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    if not isinstance(value, str):
        return False
    if re.search(r"(?im)\b(?:authorization|proxy-authorization|set-cookie|cookie)\s*:", value):
        return True
    if re.search(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}", value):
        return True
    for candidate in re.findall(r"https?://[^\s<>\"']+", value):
        try:
            parts = urlsplit(candidate)
            if parts.username is not None or parts.password is not None:
                return True
            if any(_key(k) in _SECRET_KEYS for k, _ in parse_qsl(parts.query)):
                return True
        except ValueError:
            return True
    return False


def source_digest(doc: dict) -> str:
    """Stable content identity; re-reading unchanged content changes no digest.

    Comments are a set keyed by their source IDs, so pagination order does not
    change the hash. Comment text, revisions and requirement-acceptance flags do.
    """
    if not isinstance(doc, dict) or _contains_secret(doc):
        raise EvidenceError([_issue("sensitive_or_invalid_source", "Source is invalid or contains credential material.")])
    payload = {k: copy.deepcopy(v) for k, v in doc.items() if k not in _DIGEST_EXCLUDED}
    try:
        if isinstance(payload.get("comments"), list):
            payload["comments"] = sorted(payload["comments"], key=lambda c: _json_bytes(c))
        return _sha(_json_bytes(payload))
    except (TypeError, ValueError) as exc:
        raise EvidenceError([_issue("invalid_json", "Source must contain JSON-compatible values.")]) from exc


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _version(value: Any) -> bool:
    return ((isinstance(value, int) and not isinstance(value, bool) and value > 0)
            or (isinstance(value, str) and bool(value.strip())))


def _confluence_version(value: Any) -> bool:
    return ((isinstance(value, int) and not isinstance(value, bool) and value > 0)
            or (isinstance(value, str) and bool(re.fullmatch(r"[1-9][0-9]*", value))))


def _validate_documents(documents: Any, checked_at: str) -> list[dict]:
    errors: list[dict] = []
    checked = _timestamp(checked_at)
    if checked is None:
        errors.append(_issue("invalid_checked_at", "checked_at must be an ISO-8601 timestamp with timezone."))
    if not isinstance(documents, list) or not documents:
        return errors + [_issue("empty_sources", "At least one source document is required.")]
    identities: set[tuple[str, str]] = set()
    for index, doc in enumerate(documents):
        def add(code: str, message: str) -> None:
            errors.append(_issue(code, message, source_index=index))
        if not isinstance(doc, dict):
            add("invalid_source", "Source must be an object.")
            continue
        if _contains_secret(doc):
            add("sensitive_material", "Source contains prohibited credential material.")
            continue
        if _REQUIRED - doc.keys():
            add("missing_metadata", "Required source metadata is missing.")
        scope_error = validate_excerpt_scope(doc)
        if scope_error:
            add("invalid_evidence_scope", scope_error)
        source_id, source_type = doc.get("source_id"), doc.get("source_type")
        if not isinstance(source_id, str) or not source_id.strip() or source_id != source_id.strip() or not isinstance(source_type, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", source_type):
            add("invalid_identity", "Source identity and type must be nonempty canonical strings.")
        else:
            identity = (source_type, source_id)
            if identity in identities:
                add("duplicate_source", "Source identity must be unique in a bundle.")
            identities.add(identity)
        try:
            url = urlsplit(doc.get("url", ""))
            if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None:
                add("invalid_url", "Source URL must be a complete HTTP(S) URL without userinfo.")
        except (TypeError, ValueError, AttributeError):
            add("invalid_url", "Source URL is invalid.")
        if not isinstance(doc.get("body"), str) or not doc["body"].strip():
            add("empty_body", "A URL or empty body is not complete source evidence.")
        if source_type == "confluence" and not _confluence_version(doc.get("version")) and not (is_archived(doc) and doc.get("version") is None):
            add("missing_version", "Confluence evidence requires an explicit version.")
        elif doc.get("version") is not None and not _version(doc.get("version")):
            add("invalid_version", "Version must be a positive integer or nonempty string.")
        fetched, updated = _timestamp(doc.get("fetched_at")), _timestamp(doc.get("source_updated_at"))
        if fetched is None and not (is_archived(doc) and doc.get("fetched_at") is None):
            add("invalid_fetched_at", "fetched_at must have an explicit timezone.")
        local_read = None
        if is_archived(doc):
            provenance = doc.get("archive_provenance")
            local_read = _timestamp(provenance.get("local_read_at")) if isinstance(provenance, dict) else None
            if local_read is None or (checked and local_read > checked):
                add("invalid_local_read_at", "Local archive reading time must be known and not later than sealing.")
            if local_read and ((fetched and fetched > local_read) or (updated and updated > local_read)):
                add("invalid_archive_time_order", "Known remote times cannot follow local archive reading.")
        if doc.get("source_updated_at") is not None and updated is None:
            add("invalid_source_updated_at", "source_updated_at must be null or a timezone-aware timestamp.")
        if source_type == "confluence" and updated is None and not is_excerpt(doc):
            add("missing_source_updated_at", "Confluence evidence requires its source revision timestamp.")
        if fetched and checked and fetched > checked:
            add("future_fetch", "fetched_at cannot be later than checked_at.")
        if updated and fetched and updated > fetched:
            add("future_source_update", "Source revision cannot be later than its read time.")
        if doc.get("comments_complete") is not True and not is_excerpt(doc):
            add("incomplete_comments", "Comment extraction must be explicitly complete.")
        if doc.get("applicability") not in {"confirmed", "unknown"}:
            add("invalid_applicability", "Applicability must be confirmed or unknown.")
        if doc.get("status") not in {"current", "unavailable"}:
            add("invalid_status", "Source status must be current or unavailable.")
        comments = doc.get("comments")
        if not isinstance(comments, list):
            add("invalid_comments", "Comments must be an explicit list, including when empty.")
            continue
        ids: set[str] = set()
        for comment in comments:
            if not isinstance(comment, dict) or not {"id", "body", "version", "updated_at", "accepted_as_requirement"} <= comment.keys():
                add("invalid_comment", "Comment metadata is incomplete.")
                continue
            comment_id = comment["id"]
            if not isinstance(comment_id, str) or not comment_id.strip() or comment_id in ids:
                add("duplicate_or_invalid_comment", "Comments require unique nonempty IDs.")
            else:
                ids.add(comment_id)
            if not isinstance(comment["body"], str) or not comment["body"].strip():
                add("empty_comment", "Comment content is missing.")
            if not (_confluence_version(comment["version"]) if source_type == "confluence" else _version(comment["version"])):
                add("invalid_comment_version", "Comment version is missing or invalid.")
            comment_updated = _timestamp(comment["updated_at"])
            read_limit = fetched or local_read
            if comment_updated is None or (read_limit and comment_updated > read_limit):
                add("invalid_comment_time", "Comment timestamp is invalid or later than its read time.")
            if not isinstance(comment["accepted_as_requirement"], bool):
                add("invalid_comment_acceptance", "Comment acceptance must be an explicit boolean.")
    return errors


def _git(project_root: Path, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(project_root), *args], input=input_text,
                              text=True, encoding="utf-8", capture_output=True, check=False)
    except OSError as exc:
        raise EvidenceError([_issue("git_unavailable", "Git is required to verify local-only storage exclusion.")]) from exc


def _check_excluded(project_root: Path) -> None:
    top = _git(project_root, "rev-parse", "--show-toplevel")
    if top.returncode or Path(top.stdout.strip()).resolve() != project_root:
        raise EvidenceError([_issue("invalid_project_root", "project_root must be the Git working-tree root.")])
    result = _git(project_root, "rev-parse", "--git-path", "info/exclude")
    if result.returncode:
        raise EvidenceError([_issue("missing_local_exclude", "Cannot resolve .git/info/exclude.")])
    exclude = Path(result.stdout.strip())
    exclude = (project_root / exclude).resolve() if not exclude.is_absolute() else exclude.resolve()
    probes = ["local_data/knowledge_base/",
              f"{NAMESPACE}/staging/__evidence_probe__/raw/source.json",
              f"{NAMESPACE}/generations/__evidence_probe__/manifest.json"]
    checked = _git(project_root, "check-ignore", "-v", "--no-index", "--stdin", input_text="\n".join(probes) + "\n")
    lines = checked.stdout.splitlines()
    valid = checked.returncode == 0 and len(lines) == len(probes)
    for line in lines:
        try:
            origin, _path = line.split("\t", 1)
            source, _line, pattern = origin.rsplit(":", 2)
            source_path = Path(source)
            if not source_path.is_absolute():
                source_path = project_root / source_path
            valid = valid and source_path.resolve() == exclude and not pattern.startswith("!")
        except ValueError:
            valid = False
    if not valid:
        raise EvidenceError([_issue("missing_local_exclude", "Add local_data/knowledge_base/ to .git/info/exclude before capture; no Git configuration was changed.")])


def _safe_relative(ref: Any, prefix: str) -> PurePosixPath:
    if not isinstance(ref, str) or "\\" in ref or ":" in ref:
        raise ValueError("Unsafe reference")
    parts = ref.split("/")
    if not ref or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Unsafe reference")
    path = PurePosixPath(ref)
    relative = path.relative_to(PurePosixPath(prefix))
    if not relative.parts:
        raise ValueError("Reference must name a file")
    return relative


def _safe_file(base: Path, relative: PurePosixPath) -> Path:
    candidate = base.joinpath(*relative.parts)
    resolved_base = base.resolve()
    candidate.resolve().relative_to(resolved_base)
    cursor = base
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise ValueError("Links are not permitted in evidence bundles")
    return candidate


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_json_bytes(value))


def _verify_archives(root, documents):
    """Bind original local snapshots, without treating local reads as remote fetches."""
    errors = []
    for index, doc in enumerate(documents):
        if not is_archived(doc):
            continue
        try:
            for artifact in doc["archive_provenance"]["artifacts"]:
                relative = _safe_relative(artifact["ref"], "local_data/knowledge_base")
                path = _safe_file(root, PurePosixPath("local_data/knowledge_base") / relative)
                data = path.read_bytes()
                if _sha(data) != artifact["sha256"] or path.read_bytes() != data:
                    raise ValueError("Archive changed")
        except (OSError, ValueError, TypeError, KeyError):
            errors.append(_issue("archive_binding_mismatch", "Original archive is absent, unsafe or changed.", source_index=index))
    return errors


def capture_bundle(project_root: Path, documents: list[dict], *, target: dict, checked_at: str) -> dict:
    """Validate and atomically seal one targeted bundle; never update KB state.

    Invalid payloads are not persisted. A failed staging directory retains a
    non-sensitive failure report and may contain already-validated snapshots.
    The caller owns actual source retrieval.
    """
    root = Path(project_root).resolve()
    _check_excluded(root)
    namespace = _safe_file(root, PurePosixPath(NAMESPACE))
    bundle_id = "evidence-" + uuid4().hex
    staging = _safe_file(namespace, PurePosixPath("staging") / bundle_id)
    generation = _safe_file(namespace, PurePosixPath("generations") / bundle_id)
    staging.mkdir(parents=True, exist_ok=False)
    prefix = f"{NAMESPACE}/generations/{bundle_id}"
    try:
        if not isinstance(target, dict) or not target or _contains_secret(target):
            raise EvidenceError([_issue("invalid_target", "Target must be a nonempty object without credentials.")])
        errors = _validate_documents(documents, checked_at)
        if not errors:
            errors.extend(_verify_archives(root, documents))
        if errors:
            raise EvidenceError(errors)
        try:
            _json_bytes({"documents": documents, "target": target})
        except (TypeError, ValueError) as exc:
            raise EvidenceError([_issue("invalid_json", "Evidence must be JSON-compatible.")]) from exc
        normalized = []
        for index, doc in enumerate(documents):
            raw = {k: copy.deepcopy(v) for k, v in doc.items() if k not in _DERIVED_FIELDS}
            local_ref = f"raw/{index:04d}.json"
            _write(staging / local_ref, raw)
            normalized.append({**raw, "content_hash": source_digest(raw), "raw_ref": f"{prefix}/{local_ref}"})
        _write(staging / "normalized/sources.json", {"sources": normalized})
        _write(staging / "validation.json", {"status": "passed", "errors": [], "source_count": len(normalized)})
        files = []
        for path in sorted(staging.rglob("*.json")):
            payload = path.read_bytes()
            files.append({"ref": f"{prefix}/{path.relative_to(staging).as_posix()}", "sha256": _sha(payload), "size": len(payload)})
        manifest = {
            "schema_version": 1, "bundle_id": bundle_id, "checked_at": checked_at,
            "target": copy.deepcopy(target), "status": "passed", "source_count": len(normalized),
            "normalized_ref": f"{prefix}/normalized/sources.json",
            "validation_ref": f"{prefix}/validation.json", "files": files,
        }
        _write(staging / "manifest.json", manifest)
        baseline = {
            "schema_version": 1, "checked_at": checked_at, "target": copy.deepcopy(target),
            "sources": normalized, "bundle_id": bundle_id,
            "manifest_ref": f"{prefix}/manifest.json",
            "manifest_hash": _sha((staging / "manifest.json").read_bytes()),
        }
        errors = _verify(root, baseline, directory=staging)
        if errors:
            raise EvidenceError(errors)
        generation.parent.mkdir(parents=True, exist_ok=True)
        if generation.exists():
            raise EvidenceError([_issue("generation_exists", "Existing evidence generations cannot be replaced.")])
        staging.rename(generation)
        return baseline
    except Exception as exc:
        # Do not echo payload values, exception messages, paths or credentials.
        errors = exc.errors if isinstance(exc, EvidenceError) else [_issue("capture_failed", "Bundle capture failed before publication.")]
        failure = staging / "failure.json"
        if staging.exists() and not failure.exists():
            _write(failure, {"status": "failed", "errors": errors})
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError(errors) from exc


def _verify(root: Path, baseline: dict, *, directory: Path | None = None) -> list[dict]:
    errors: list[dict] = []
    try:
        if not isinstance(baseline, dict) or _contains_secret(baseline):
            return [_issue("invalid_baseline", "Baseline is invalid or contains credential material.")]
        bundle_id = baseline.get("bundle_id")
        if not isinstance(bundle_id, str) or not re.fullmatch(r"evidence-[0-9a-f]{32}", bundle_id):
            return [_issue("invalid_bundle_id", "Bundle ID is invalid.")]
        prefix = f"{NAMESPACE}/generations/{bundle_id}"
        bundle_dir = _safe_file(root, PurePosixPath(prefix)) if directory is None else directory
        manifest_relative = _safe_relative(baseline.get("manifest_ref"), prefix)
        if manifest_relative.as_posix() != "manifest.json":
            raise ValueError("Manifest must be canonical")
        manifest_path = _safe_file(bundle_dir, manifest_relative)
        manifest_bytes = manifest_path.read_bytes()
        if baseline.get("manifest_hash") != _sha(manifest_bytes):
            return [_issue("manifest_hash_mismatch", "Manifest differs from the baseline's pinned hash.")]
        manifest = json.loads(manifest_bytes)
        if not isinstance(manifest, dict) or manifest.get("status") != "passed":
            return [_issue("manifest_not_passed", "Manifest has not passed validation.")]
        for field in ("schema_version", "bundle_id", "checked_at", "target"):
            if manifest.get(field) != baseline.get(field):
                errors.append(_issue("baseline_manifest_mismatch", "Baseline metadata differs from the sealed manifest.", field=field))
        if manifest.get("schema_version") != 1:
            errors.append(_issue("invalid_schema", "Unsupported evidence schema version."))
        inventory = manifest.get("files")
        if not isinstance(inventory, list) or not inventory:
            return errors + [_issue("invalid_inventory", "Manifest file inventory is missing.")]
        listed: set[str] = set()
        for item in inventory:
            if not isinstance(item, dict):
                raise ValueError("Invalid inventory entry")
            ref = item.get("ref")
            relative = _safe_relative(ref, prefix)
            if ref in listed:
                errors.append(_issue("duplicate_file", "Manifest repeats a file reference."))
            listed.add(ref)
            data = _safe_file(bundle_dir, relative).read_bytes()
            if len(data) != item.get("size") or _sha(data) != item.get("sha256"):
                errors.append(_issue("file_hash_mismatch", "A sealed evidence file differs from its manifest."))
        actual = {f"{prefix}/{p.relative_to(bundle_dir).as_posix()}" for p in bundle_dir.rglob("*") if p.is_file() and p != manifest_path}
        if actual != listed:
            errors.append(_issue("inventory_mismatch", "Bundle files do not match the complete manifest inventory."))
        for path in bundle_dir.rglob("*"):
            _safe_file(bundle_dir, PurePosixPath(path.relative_to(bundle_dir).as_posix()))
        normalized_ref, report_ref = manifest.get("normalized_ref"), manifest.get("validation_ref")
        if normalized_ref not in listed or report_ref not in listed:
            return errors + [_issue("missing_contract_file", "Normalized data and validation report must be inventoried.")]
        normalized = json.loads(_safe_file(bundle_dir, _safe_relative(normalized_ref, prefix)).read_bytes())
        report = json.loads(_safe_file(bundle_dir, _safe_relative(report_ref, prefix)).read_bytes())
        if not isinstance(report, dict) or report.get("status") != "passed" or report.get("errors") != []:
            errors.append(_issue("validation_not_passed", "Sealed validation report must explicitly pass."))
        sources = normalized.get("sources") if isinstance(normalized, dict) else None
        errors.extend(_validate_documents(sources, baseline.get("checked_at")))
        if isinstance(sources, list) and all(isinstance(s, dict) for s in sources):
            errors.extend(_verify_archives(root, sources))
        if sources != baseline.get("sources"):
            errors.append(_issue("baseline_sources_mismatch", "Baseline sources differ from the sealed normalized records."))
        if not isinstance(sources, list):
            return errors
        if len(sources) != manifest.get("source_count") or not isinstance(report, dict) or len(sources) != report.get("source_count"):
            errors.append(_issue("source_count_mismatch", "Source counts differ across the sealed bundle."))
        raw_refs: set[str] = set()
        for doc in sources:
            if not isinstance(doc, dict):
                continue
            raw_ref = doc.get("raw_ref")
            raw_relative = _safe_relative(raw_ref, prefix)
            if not raw_relative.as_posix().startswith("raw/") or raw_ref not in listed or raw_ref in raw_refs:
                errors.append(_issue("invalid_raw_ref", "Each source requires a distinct inventoried raw snapshot."))
                continue
            raw_refs.add(raw_ref)
            raw = json.loads(_safe_file(bundle_dir, raw_relative).read_bytes())
            expected = {k: v for k, v in doc.items() if k not in _DERIVED_FIELDS}
            if raw != expected or source_digest(doc) != doc.get("content_hash"):
                errors.append(_issue("source_hash_mismatch", "Source content or raw snapshot does not match its normalized digest."))
        return errors
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return errors + [_issue("invalid_bundle", "Bundle is missing, malformed, or contains an unsafe reference.")]


def verify_bundle(project_root: Path, baseline: dict) -> list[dict]:
    """Read-only integrity verification. An empty list is not a freshness grant."""
    return _verify(Path(project_root).resolve(), baseline)


def load_bundle(project_root: Path, reference: dict) -> dict:
    """Hydrate a content-free pointer and verify all evidence before returning.

    Workflow files outside the local knowledge base may store this pointer, not
    source bodies or normalized records. Loading never writes files.
    """
    fields = {"schema_version", "checked_at", "target", "bundle_id", "manifest_ref", "manifest_hash"}
    try:
        if not isinstance(reference, dict) or set(reference) != fields or _contains_secret(reference):
            raise EvidenceError([_issue("invalid_reference", "Evidence reference must contain only the six pointer fields.")])
        bundle_id = reference["bundle_id"]
        if not isinstance(bundle_id, str) or not re.fullmatch(r"evidence-[0-9a-f]{32}", bundle_id):
            raise ValueError("Invalid bundle ID")
        root = Path(project_root).resolve()
        prefix = f"{NAMESPACE}/generations/{bundle_id}"
        directory = _safe_file(root, PurePosixPath(prefix))
        manifest_relative = _safe_relative(reference["manifest_ref"], prefix)
        if manifest_relative.as_posix() != "manifest.json":
            raise ValueError("Invalid manifest reference")
        data = _safe_file(directory, manifest_relative).read_bytes()
        if _sha(data) != reference["manifest_hash"]:
            raise EvidenceError([_issue("manifest_hash_mismatch", "Manifest differs from the pointer's pinned hash.")])
        manifest = json.loads(data)
        if not isinstance(manifest, dict) or manifest.get("status") != "passed":
            raise EvidenceError([_issue("manifest_not_passed", "Manifest has not passed validation.")])
        normalized_path = _safe_file(directory, _safe_relative(manifest.get("normalized_ref"), prefix))
        normalized = json.loads(normalized_path.read_bytes())
        if not isinstance(normalized, dict) or not isinstance(normalized.get("sources"), list):
            raise ValueError("Invalid normalized records")
        baseline = {**copy.deepcopy(reference), "sources": normalized["sources"]}
        errors = verify_bundle(root, baseline)
        if errors:
            raise EvidenceError(errors)
        return baseline
    except EvidenceError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        raise EvidenceError([_issue("invalid_reference", "Evidence reference is missing, malformed, or unsafe.")]) from exc
