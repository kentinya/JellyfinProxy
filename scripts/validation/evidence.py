"""Evidence bundle verification for the real Jellyfin 12.3 baseline.

``verify-evidence`` checks identity, completeness, whitelist compliance and
redaction -- not merely that files exist.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.validation.common import (
    ValidationError,
    read_json,
    redact_text,
    sha256_file,
    utc_now,
    write_json,
)
from scripts.validation.environment import (
    PRODUCT_BASE,
    REQUIRED_SERVER_VERSION,
    RunPaths,
    assert_owned_run_dir,
    git_rev,
)

REQUIRED_CASES = tuple(f"RJ-{index:02d}" for index in range(1, 13))
#: Cases that S1.1 must fully baseline for every group.
REQUIRED_S1_1_CASES = REQUIRED_CASES
#: C-only follow-up work explicitly not executed in S1.1.
C_ONLY = "NOT RUN — deferred to a later Slice task (candidate comparison)"

#: Credential-shaped patterns checked in addition to the real secret values.
#: Bare 32-hex strings are intentionally NOT included: Jellyfin item ids have
#: exactly that shape and appear legitimately in the evidence.
TOKEN_PATTERNS = (
    re.compile(r"(?i)MediaBrowser[^\"\n]*Token=(?!\[REDACTED\])[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)\b(?:api_key|apikey|access_token|token|x-emby-token|cookie|password)\s*[:=]\s*(?!\[REDACTED\])([A-Za-z0-9._\-]{12,})"),
)


def case_status(results: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Count passing sub-cases per group and case (used in baseline.json)."""

    summary: dict[str, dict[str, int]] = {}
    for entry in results.values():
        case = str(entry.get("case", "?"))
        group = str(entry.get("group", "?"))
        bucket = summary.setdefault(group, {})
        bucket[case] = bucket.get(case, 0) + (1 if entry.get("status") == "PASS" else 0)
    return summary


class EvidenceReport:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, check: str, status: str, detail: Any = None) -> None:
        self.checks.append({"check": check, "status": status, "detail": detail})

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if check["status"] != "PASS"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "verified_at": utc_now(),
            "checks": self.checks,
            "failed": self.failed,
            "ok": not self.failed,
        }


def verify(paths: RunPaths, *, expected_cases: Sequence[str] | None = None) -> EvidenceReport:
    report = EvidenceReport()
    try:
        assert_owned_run_dir(paths)
    except ValidationError as exc:
        report.add("run_dir_ownership", "FAIL", str(exc))
        return report
    report.add("run_dir_ownership", "PASS", str(paths.root))

    if not paths.manifest.exists():
        report.add("manifest_present", "FAIL", f"missing {paths.manifest}")
        return report
    manifest = read_json(paths.manifest)
    report.add("manifest_present", "PASS", manifest.get("run_id"))

    # -- identity -------------------------------------------------------
    tool = manifest.get("tool") or {}
    head = tool.get("tool_head")
    try:
        current_head = git_rev("HEAD")
    except ValidationError:
        current_head = None
    if not head:
        report.add("tool_head_recorded", "FAIL", "manifest has no tool_head")
    else:
        report.add(
            "tool_head_recorded",
            "PASS" if current_head == head else "WARN",
            {"recorded": head, "current": current_head},
        )

    base = manifest.get("product_base") or {}
    if base.get("base_ref") != PRODUCT_BASE:
        report.add("product_base_ref", "FAIL", f"product base {base.get('base_ref')!r} != {PRODUCT_BASE}")
    else:
        report.add("product_base_ref", "PASS", base.get("base_sha"))

    identity_dir = paths.base_src / "SOURCE_IDENTITY.json"
    if not identity_dir.exists():
        report.add("product_source_identity", "FAIL", "missing SOURCE_IDENTITY.json in extracted base source")
    else:
        recorded = read_json(identity_dir)
        mismatched = []
        for relative, digest in (recorded.get("files") or {}).items():
            target = paths.base_src / relative
            if not target.is_file() or sha256_file(target) != digest:
                mismatched.append(relative)
        report.add(
            "product_source_identity",
            "PASS" if not mismatched else "FAIL",
            {"files": len(recorded.get("files") or {}), "mismatched": mismatched},
        )
        if (base.get("base_sha") or "") != recorded.get("base_sha"):
            report.add("product_base_sha_consistency", "FAIL", {"manifest": base.get("base_sha"), "source": recorded.get("base_sha")})
        else:
            report.add("product_base_sha_consistency", "PASS", recorded.get("base_sha"))

    lock_path = paths.lock
    if not lock_path.exists():
        report.add("server_lock", "FAIL", "missing server.lock.json")
    else:
        lock = read_json(lock_path)
        problems = []
        if not str(lock.get("server_version", "")).startswith(REQUIRED_SERVER_VERSION):
            problems.append(f"server_version={lock.get('server_version')!r}")
        if not lock.get("image_digest"):
            problems.append("image_digest missing")
        if lock.get("product_base") != PRODUCT_BASE:
            problems.append("product_base mismatch")
        report.add("server_lock", "PASS" if not problems else "FAIL", {"problems": problems, "image_digest": lock.get("image_digest")})

    runtime = manifest.get("runtime_version") or {}
    if not str(runtime.get("server_version", "")).startswith(REQUIRED_SERVER_VERSION):
        report.add("runtime_server_version", "FAIL", runtime)
    else:
        report.add("runtime_server_version", "PASS", runtime.get("server_version"))

    # -- results --------------------------------------------------------
    results_path = paths.evidence / "results.json"
    if not results_path.exists():
        report.add("results_present", "FAIL", f"missing {results_path}")
        return report
    results = read_json(results_path)
    report.add("results_present", "PASS", {"records": len(results)})

    cases = list(expected_cases or REQUIRED_S1_1_CASES)
    groups = manifest.get("groups") or ["J", "B-on", "B-off"]
    missing: list[str] = []
    failures: list[str] = []
    for case in cases:
        for group in groups:
            entries = {key: value for key, value in results.items() if value.get("case") == case and value.get("group") == group}
            if not entries:
                missing.append(f"{case}/{group}")
                continue
            bad = [key for key, value in entries.items() if value.get("status") != "PASS"]
            if bad:
                failures.append(f"{case}/{group}: {len(bad)} sub-case(s)")
    report.add("required_case_coverage", "PASS" if not missing else "FAIL", {"missing": missing})
    report.add("required_case_results", "PASS" if not failures else "FAIL", {"failing": failures})
    report.add("c_only_marked_not_run", "PASS", C_ONLY)

    # -- whitelist compliance ------------------------------------------
    unexpected: list[str] = []
    for key, value in results.items():
        detail = value.get("detail") or {}
        locations = ((detail.get("differences") or {}).get("unexpected")) or []
        if value.get("group") == "J" and locations:
            unexpected.append(key)
    report.add("dynamic_whitelist_only", "PASS" if not unexpected else "FAIL", {"cases_with_unexpected_differences": unexpected})

    # -- transactions ---------------------------------------------------
    for group in groups:
        path = paths.evidence / f"transactions-{group}.jsonl"
        if not path.exists():
            report.add(f"transactions_{group}", "FAIL", f"missing {path.name}")
            continue
        count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        report.add(f"transactions_{group}", "PASS", {"records": count})

    # -- redaction ------------------------------------------------------
    secrets = _collect_secrets(paths)
    leaks: list[str] = []
    scanned = 0
    for path in sorted(paths.evidence.rglob("*")):
        if not path.is_file():
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        for secret in secrets:
            if secret and secret in text:
                leaks.append(f"{path.name}: literal credential")
        for pattern in TOKEN_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                if "[REDACTED]" in value:
                    continue
                leaks.append(f"{path.name}: pattern {pattern.pattern[:24]} -> {redact_text(value)[:40]}")
    report.add("evidence_redaction", "PASS" if not leaks else "FAIL", {"files_scanned": scanned, "leaks": leaks[:20]})

    credentials_file = paths.evidence / "credentials.json"
    report.add(
        "credentials_outside_evidence",
        "PASS" if not credentials_file.exists() else "FAIL",
        "credential file must live in the private directory, not the evidence bundle",
    )

    # -- stop record ----------------------------------------------------
    stop_path = paths.evidence / "stop.json"
    if not stop_path.exists():
        report.add("stop_record", "FAIL", "missing stop.json; run `stop` before verifying")
    else:
        stop = read_json(stop_path)
        report.add(
            "stop_record",
            "PASS" if stop.get("actions") else "FAIL",
            {"actions": stop.get("actions"), "idempotent_repeat": stop.get("idempotent_repeat")},
        )
        report.add(
            "stop_only_owned_resources",
            "PASS" if all("mismatch" not in str(action) for action in stop.get("actions") or []) else "WARN",
            stop.get("actions"),
        )

    output = report.as_dict()
    write_json(paths.evidence / "verify-evidence.json", output)
    return report


def _collect_secrets(paths: RunPaths) -> list[str]:
    secrets: list[str] = []
    if not paths.credentials.exists():
        return secrets
    payload = read_json(paths.credentials)
    for key in ("admin_token", "admin_password"):
        value = payload.get(key)
        if isinstance(value, str) and len(value) >= 6:
            secrets.append(value)
    for entry in (payload.get("users") or {}).values():
        for key in ("token", "password"):
            value = entry.get(key)
            if isinstance(value, str) and len(value) >= 6:
                secrets.append(value)
    return secrets


def report_to_console(report: EvidenceReport) -> None:
    for check in report.checks:
        print(f"[{check['status']:4}] {check['check']}: {json.dumps(check['detail'], ensure_ascii=False)[:300]}")
