"""Live corporate-registry and web-search OSINT.

GLEIF is used as the no-key corporate registry source. Tavily or Serper can be
configured for richer web search; DuckDuckGo HTML is the no-key fallback. All
failures degrade to the existing static vendor profile.
"""

from __future__ import annotations

import difflib
import html
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from core.models import VendorProfile

_CACHE: Dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()
_DDG_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.I | re.S,
)
_DDG_SNIPPET = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.I | re.S,
)
_TAG = re.compile(r"<[^>]+>")


def live_osint_enabled() -> bool:
    return os.environ.get("LIVE_OSINT_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _timeout() -> float:
    return float(os.environ.get("OSINT_TIMEOUT_SECONDS", "5"))


def _cache_get(key: str) -> Any:
    ttl = float(os.environ.get("OSINT_CACHE_TTL_SECONDS", "86400"))
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item and time.time() - item[0] < ttl:
            return item[1]
    return None


def _cache_set(key: str, value: Any) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)


_LEGAL_SUFFIXES = {
    "ag",
    "as",
    "ab",
    "bv",
    "co",
    "company",
    "corp",
    "corporation",
    "gmbh",
    "group",
    "holdings",
    "inc",
    "incorporated",
    "limited",
    "limitada",
    "llc",
    "ltda",
    "ltd",
    "nv",
    "oy",
    "plc",
    "private",
    "pvt",
    "sa",
    "sarl",
    "spa",
    "srl",
    "the",
}


_LEGAL_FORM_MARKERS = {
    "ab": "ab",
    "ag": "ag",
    "as": "as",
    "bv": "bv",
    "corp": "corp",
    "corporation": "corp",
    "gmbh": "gmbh",
    "inc": "inc",
    "incorporated": "inc",
    "limitada": "ltda",
    "limited": "ltd",
    "llc": "llc",
    "ltda": "ltda",
    "ltd": "ltd",
    "nv": "nv",
    "oy": "oy",
    "plc": "plc",
    "private": "pvt",
    "pvt": "pvt",
    "sa": "sa",
    "sarl": "sarl",
    "spa": "spa",
    "srl": "srl",
}


def _legal_form_marker(name: str) -> Optional[str]:
    markers = [
        _LEGAL_FORM_MARKERS[token]
        for token in _raw_company_name(name).split()
        if token in _LEGAL_FORM_MARKERS
    ]
    return markers[-1] if markers else None


def _raw_company_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    text = re.sub(r"\b(?:and|&)\b", " ", text, flags=re.I)
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _normalise_company_name(name: str) -> str:
    return " ".join(
        token
        for token in _raw_company_name(name).split()
        if token not in _LEGAL_SUFFIXES
    )


def _compact_name(name: str) -> str:
    return _normalise_company_name(name).replace(" ", "")


def _candidate_record(record: Dict[str, Any]) -> Dict[str, Any]:
    attributes = record.get("attributes", {})
    entity = attributes.get("entity", {})
    legal_name = (entity.get("legalName") or {}).get("name", "")
    address = entity.get("legalAddress") or {}
    return {
        "source": "GLEIF",
        "id": record.get("id", ""),
        "name": legal_name,
        "country": address.get("country", ""),
        "status": entity.get("status", ""),
        "registered_as": (entity.get("registeredAs") or ""),
        "legal_form": (entity.get("legalForm") or {}).get("id", ""),
        "url": f"https://search.gleif.org/#/record/{record.get('id', '')}",
    }


def score_gleif_candidate(
    query: str,
    candidate: Dict[str, Any],
    *,
    country: Optional[str] = None,
) -> Dict[str, Any]:
    """Score a GLEIF record against a possibly differently formatted name."""
    query_normalised = _normalise_company_name(query)
    candidate_normalised = _normalise_company_name(candidate.get("name", ""))
    query_compact = query_normalised.replace(" ", "")
    candidate_compact = candidate_normalised.replace(" ", "")
    raw_query_compact = _raw_company_name(query).replace(" ", "")
    raw_candidate_compact = _raw_company_name(candidate.get("name", "")).replace(" ", "")

    if not query_compact or not candidate_compact:
        score = 0.0
    elif query_compact == candidate_compact:
        score = 1.0
    else:
        ratio = difflib.SequenceMatcher(None, query_compact, candidate_compact).ratio()
        q_tokens = set(query_normalised.split())
        c_tokens = set(candidate_normalised.split())
        union = q_tokens | c_tokens
        jaccard = len(q_tokens & c_tokens) / len(union) if union else 0.0
        score = 0.65 * ratio + 0.35 * jaccard
        if query_compact in candidate_compact or candidate_compact in query_compact:
            score = max(score, 0.88)
        if q_tokens and q_tokens.issubset(c_tokens):
            score = max(score, 0.84)

    country_match = bool(
        country
        and candidate.get("country")
        and country.upper() == candidate["country"].upper()
    )
    if country_match:
        score = min(1.0, score + 0.03)
    query_form = _legal_form_marker(query)
    candidate_form = _legal_form_marker(candidate.get("name", ""))
    legal_form_match = bool(query_form and candidate_form and query_form == candidate_form)

    if raw_query_compact == raw_candidate_compact:
        match_type = "exact"
    elif query_compact == candidate_compact:
        match_type = "normalized"
    else:
        match_type = "fuzzy"

    scored = dict(candidate)
    scored["match_score"] = round(score, 3)
    scored["match_type"] = match_type
    scored["normalized_name"] = candidate_normalised
    scored["country_match"] = country_match
    scored["legal_form_match"] = legal_form_match
    return scored


def rank_gleif_candidates(
    query: str,
    records: List[Dict[str, Any]],
    *,
    country: Optional[str] = None,
    threshold: float = 0.72,
    limit: int = 5,
) -> Optional[Dict[str, Any]]:
    """Rank records, detect ambiguity, and return the best match with alternatives."""
    candidates: Dict[str, Dict[str, Any]] = {}
    for record in records:
        candidate = _candidate_record(record)
        if not candidate["name"]:
            continue
        scored = score_gleif_candidate(query, candidate, country=country)
        previous = candidates.get(candidate["id"])
        if previous is None or scored["match_score"] > previous["match_score"]:
            candidates[candidate["id"]] = scored

    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            item["match_score"],
            item.get("country_match", False),
            item.get("legal_form_match", False),
        ),
        reverse=True,
    )
    if not ranked or ranked[0]["match_score"] < threshold:
        return None
    best = ranked[0]
    alternatives = ranked[1:limit]
    country_disambiguates = bool(
        country
        and best.get("country_match")
        and alternatives
        and not alternatives[0].get("country_match")
    )
    legal_form_disambiguates = bool(
        best.get("legal_form_match")
        and alternatives
        and not alternatives[0].get("legal_form_match")
    )
    best["ambiguous"] = bool(
        alternatives
        and (best["match_score"] - alternatives[0]["match_score"]) < 0.08
        and not country_disambiguates
        and not legal_form_disambiguates
    )
    best["candidates"] = [
        {
            "id": item["id"],
            "name": item["name"],
            "country": item["country"],
            "status": item["status"],
            "match_score": item["match_score"],
            "match_type": item["match_type"],
        }
        for item in ranked[:limit]
    ]
    return best


def _query_gleif(query: str) -> List[Dict[str, Any]]:
    key = f"gleif-query:{query.lower()}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        response = httpx.get(
            "https://api.gleif.org/api/v1/lei-records",
            params={"filter[entity.legalName]": query, "page[size]": 20},
            timeout=_timeout(),
            headers={"User-Agent": "RedLiner academic project"},
        )
        response.raise_for_status()
        records = response.json().get("data") or []
    except Exception:
        records = []
    _cache_set(key, records)
    return records


def gleif_lookup(
    name: str,
    *,
    country: Optional[str] = None,
    domain: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Find the best GLEIF legal entity for a similarly formatted vendor name.

    GLEIF's filter is a name contains-match, not a canonical resolver. We query
    the original name, then progressively broader normalized forms, score every
    candidate, and report ambiguity instead of silently selecting the first row.
    """
    key = f"gleif:{name.lower()}:{country or ''}:{domain or ''}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    tokens = _normalise_company_name(name).split()
    queries = [name]
    for query in [
        _normalise_company_name(name),
        " ".join(tokens[:3]),
        " ".join(tokens[:2]),
    ]:
        if query and query.lower() not in {item.lower() for item in queries}:
            queries.append(query)

    records: Dict[str, Dict[str, Any]] = {}
    for query in queries:
        for record in _query_gleif(query):
            records[record.get("id", "")] = record
        # An exact normalized hit is enough; avoid extra registry calls.
        current = rank_gleif_candidates(
            name, list(records.values()), country=country
        )
        if current and current["match_type"] == "exact" and not current["ambiguous"]:
            break

    result = rank_gleif_candidates(name, list(records.values()), country=country)
    _cache_set(key, result)
    return result


def _tavily_search(query: str) -> List[Dict[str, str]]:
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": 5,
                "search_depth": "basic",
            },
            timeout=_timeout(),
        )
        response.raise_for_status()
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", "")[:500],
                "provider": "Tavily",
            }
            for item in response.json().get("results", [])[:5]
        ]
    except Exception:
        return []


def _serper_search(query: str) -> List[Dict[str, str]]:
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        response = httpx.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 5},
            timeout=_timeout(),
        )
        response.raise_for_status()
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", "")[:500],
                "provider": "Serper",
            }
            for item in response.json().get("organic", [])[:5]
        ]
    except Exception:
        return []


def _duckduckgo_search(query: str) -> List[Dict[str, str]]:
    try:
        response = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 RedLinerResearch/1.0"},
            timeout=_timeout(),
        )
        response.raise_for_status()
        links = _DDG_RESULT.findall(response.text)
        snippets = _DDG_SNIPPET.findall(response.text)
        results = []
        for index, (href, title) in enumerate(links[:5]):
            parsed = urlparse(href)
            if "duckduckgo.com" in parsed.netloc:
                href = unquote(parse_qs(parsed.query).get("uddg", [href])[0])
            snippet = snippets[index] if index < len(snippets) else ""
            results.append(
                {
                    "title": html.unescape(_TAG.sub("", title)).strip(),
                    "url": href,
                    "snippet": html.unescape(_TAG.sub("", snippet)).strip()[:500],
                    "provider": "DuckDuckGo",
                }
            )
        return results
    except Exception:
        return []


def web_search(query: str) -> List[Dict[str, str]]:
    key = f"web:{query.lower()}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    results = _tavily_search(query) or _serper_search(query) or _duckduckgo_search(query)
    _cache_set(key, results)
    return results


def enrich_profile(profile: VendorProfile, query: str) -> VendorProfile:
    """Add live registry/search provenance to a vendor profile.

    This does not silently replace deterministic risk scores with web claims.
    It records provenance and adds clearly-labelled warnings/notes.
    """
    if not live_osint_enabled():
        return profile

    lookup_name = profile.company_name or query
    registry = gleif_lookup(
        lookup_name,
        country=profile.country or None,
        domain=profile.domain or None,
    )
    sources = web_search(f"{lookup_name} official company registry sanctions")

    if registry:
        profile.registry_source = registry.get("source")
        profile.registry_id = registry.get("id")
        profile.registry_status = registry.get("status")
        profile.registry_url = registry.get("url")
        profile.registry_match_score = registry.get("match_score")
        profile.registry_match_type = registry.get("match_type")
        profile.registry_ambiguous = bool(registry.get("ambiguous"))
        profile.registry_candidates = registry.get("candidates", [])
        if not profile.registration_number:
            profile.registration_number = registry.get("id", "")
        if not profile.country:
            profile.country = registry.get("country", "")
        status = str(registry.get("status", "")).lower()
        if profile.registry_ambiguous:
            profile.flags.append(
                "Live registry match is ambiguous: similar legal entities were found "
                f"({registry.get('match_score')} top score); review candidates manually."
            )
        elif status and status != "active":
            profile.flags.append(
                f"Live registry status is {registry.get('status')} "
                f"({registry.get('match_type')} match)."
            )
        else:
            profile.flags.append(
                f"Live registry match: GLEIF {registry.get('match_type')} match "
                f"(score {registry.get('match_score')})."
            )
    else:
        profile.flags.append("Live registry check: no confident GLEIF legal-entity match found.")

    if sources:
        profile.web_sources = sources
        profile.flags.append(
            f"Live web OSINT: {len(sources)} source(s) checked; review provenance manually."
        )
    else:
        profile.flags.append("Live web OSINT: no search results returned.")

    profile.live_osint = True
    profile.osint_checked_at = datetime.now(timezone.utc).isoformat()
    if profile.notes:
        profile.notes = f"{profile.notes} Live OSINT checked at {profile.osint_checked_at}."
    else:
        profile.notes = f"Live OSINT checked at {profile.osint_checked_at}."
    return profile
