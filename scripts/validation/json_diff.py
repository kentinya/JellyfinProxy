"""Field-level JSON comparison with explicit dynamic-field whitelist.

The tool must be able to answer "did the proxy change a field that the
contract does not allow it to change?" without hiding differences behind a
generic "dynamic field" excuse. Differences are therefore reported with their
exact JSON location, and only locations declared here may be ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping, Sequence

from scripts.validation.common import sha256_bytes, url_digest

#: Locations that Jellyfin itself varies per request. Each entry documents why
#: the value can differ between two transactions of the *same* upstream input.
DYNAMIC_LOCATIONS: dict[str, str] = {
    "PlaySessionId": (
        "Jellyfin generates a new play session id per PlaybackInfo transaction; "
        "the proxy must never synthesise or reuse it."
    ),
    "MediaSources[].ETag": (
        "Jellyfin recomputes the ETag on each PlaybackInfo transaction for STRM sources."
    ),
}

#: Locations where a protocol adjustment used by the proxy is permitted while
#: the underlying path must still be identical.
REPRESENTATION_ADAPTATIONS: tuple[str, ...] = (
    "MediaSources[].Path",
)


@dataclass(frozen=True)
class Difference:
    location: str
    baseline: str
    candidate: str
    kind: str

    def as_dict(self) -> dict[str, str]:
        return {
            "location": self.location,
            "kind": self.kind,
            "baseline": self.baseline,
            "candidate": self.candidate,
        }


def _describe(value: Any) -> str:
    if isinstance(value, str):
        # Never leak a URL or credential: report digest + length only.
        return f"str:len{len(value)}:sha{sha256_bytes(value.encode('utf-8'))[:12]}"
    if isinstance(value, bool):
        return f"bool:{value}"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return f"num:{value}"
    if isinstance(value, (list, tuple)):
        return f"list:{len(value)}"
    if isinstance(value, Mapping):
        return f"dict:{len(value)}"
    return f"other:{type(value).__name__}"


def _explain(location: str, baseline: Any, candidate: Any) -> str:
    if location in DYNAMIC_LOCATIONS:
        return "dynamic"
    if location.endswith(".Path") or location == "Path":
        if isinstance(baseline, str) and isinstance(candidate, str):
            # Report equality of the URL itself, not the redacted rendering.
            if baseline == candidate:
                return "identical-url"
            if baseline.split("?", 1)[0] == candidate.split("?", 1)[0]:
                return "url-query-differs"
        return "url-differs"
    return "unexpected"


def compare_json(
    baseline: Any,
    candidate: Any,
    *,
    allow_suffixes: Sequence[str] = (),
) -> list[Difference]:
    """Return field-level differences between two JSON documents.

    ``allow_suffixes`` lets callers whitelist extra locations for a specific
    scenario; every entry must be an exact dotted path from the diff output.
    """

    differences: list[Difference] = []
    allowed = set(allow_suffixes)

    def walk(path: str, left: Any, right: Any) -> None:
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            for key in sorted(set(left) | set(right)):
                child = f"{path}.{key}" if path else str(key)
                if key not in left or key not in right:
                    differences.append(
                        Difference(child, _describe(left.get(key)), _describe(right.get(key)), "presence")
                    )
                    continue
                walk(child, left[key], right[key])
            return
        if isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                differences.append(
                    Difference(f"{path}[]", f"list:{len(left)}", f"list:{len(right)}", "length")
                )
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                walk(f"{path}[{index}]", left_item, right_item)
            return
        if left != right:
            differences.append(Difference(path, _describe(left), _describe(right), "value"))

    walk("", baseline, candidate)

    filtered: list[Difference] = []
    for difference in differences:
        normalized = _normalize_location(difference.location)
        if normalized in allowed:
            continue
        if _is_dynamic(normalized):
            continue
        filtered.append(difference)
    return filtered


_INDEX = re.compile(r"\[\d+\]")


def _normalize_location(location: str) -> str:
    """Turn ``MediaSources[0].Path`` into ``MediaSources[].Path``."""

    return _INDEX.sub("[]", location)


def _is_dynamic(location: str) -> bool:
    if location in DYNAMIC_LOCATIONS:
        return True
    for pattern in DYNAMIC_LOCATIONS:
        if "[]" in pattern and location.endswith(pattern.split("[]", 1)[1]) and location.startswith(
            pattern.split("[]", 1)[0] + "[]"
        ):
            return True
    return False


def summarize_differences(differences: Iterable[Difference]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for difference in differences:
        grouped.setdefault(_normalize_location(difference.location), []).append(difference.as_dict())
    return {
        "count": sum(len(items) for items in grouped.values()),
        "locations": grouped,
        "unexpected": sorted(grouped),
    }


def url_equality_report(baseline: str | None, candidate: str | None) -> dict[str, Any]:
    """Compare two URLs in memory and emit only redacted identity evidence."""

    def fingerprint(value: str | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return {
            "scheme": value.split(":", 1)[0] if ":" in value else "",
            "length": len(value),
            "digest": url_digest(value),
            "has_signed_query": "?" in value,
        }

    return {
        "equal": baseline == candidate,
        "baseline": fingerprint(baseline),
        "candidate": fingerprint(candidate),
    }


def extract_locations(document: Any, locations: Iterable[str]) -> dict[str, Any]:
    """Read whitelisted locations so their provenance can be checked."""

    result: dict[str, Any] = {}
    for location in locations:
        node = document
        for part in location.split("."):
            if node is None:
                break
            if part.endswith("[]"):
                key = part[:-2]
                items = node.get(key) if isinstance(node, Mapping) else None
                node = items if isinstance(items, list) else None
                if isinstance(node, list):
                    node = node[0] if node else None
                continue
            node = node.get(part) if isinstance(node, Mapping) else None
        result[location] = _describe(node)
    return result
