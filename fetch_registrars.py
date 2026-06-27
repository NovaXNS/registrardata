#!/usr/bin/env python3
"""
Fetch and merge ICANN + IANA registrar lists into JSON.

Sources:
  - IANA  CSV: https://www.iana.org/assignments/registrar-ids/registrar-ids-1.csv
               → ID, Registrar Name, Status, RDAP Base URL
  - ICANN     : https://www.icann.org/graphql
               → name, url, ianaNumber, country, publicContact (name, email, phone)

Output: merged_registrars.json (list of objects)
"""

import csv
import concurrent.futures
import io
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

import requests

JSON_OUTPUT = os.path.join(SCRIPT_DIR, "merged_registrars.json")

HEADERS = {
    "User-Agent": "curl/8.21.0",
}

# ---------------------------------------------------------------------------
# 1. IANA CSV
# ---------------------------------------------------------------------------
IANA_CSV_URL = "https://www.iana.org/assignments/registrar-ids/registrar-ids-1.csv"

def fetch_iana():
    print("[1/3] Fetching IANA CSV ...", file=sys.stderr)
    resp = requests.get(IANA_CSV_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    records = {}
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        rid = row.get("ID", "").strip()
        records[rid] = {
            "iana_id": int(rid) if rid.isdigit() else rid,
            "registrar_name": row.get("Registrar Name", "").strip(),
            "status": row.get("Status", "").strip(),
            "rdap_url": row.get("RDAP Base URL", "").strip(),
            "whois_server": None,
            "website": None,
            "country": None,
            "contact": {"name": None, "phone": None, "email": None},
        }
    print(f"  → {len(records)} registrars from IANA", file=sys.stderr)
    return records

# ---------------------------------------------------------------------------
# 2. ICANN GraphQL
# ---------------------------------------------------------------------------
ICANN_GRAPHQL_URL = "https://www.icann.org/graphql"

QUERY = """fragment registrar on AccreditedRegistrar {
  name
  url
  ianaNumber
  country
  publicContact {
    name
    email
    phone
  }
}
query ($languageTag: String!) {
  accreditedRegistrarsOperations {
    registrars: search(languageTag: $languageTag) {
      ...registrar
    }
  }
}"""


def fetch_icann():
    print("[2/3] Fetching ICANN GraphQL ...", file=sys.stderr)
    payload = {"query": QUERY, "variables": {"languageTag": "en"}}
    resp = requests.post(
        ICANN_GRAPHQL_URL, json=payload, headers=HEADERS, timeout=60
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        print(f"  GraphQL errors: {data['errors']}", file=sys.stderr)
        return {}
    registrars = data.get("data", {}).get("accreditedRegistrarsOperations", {}).get("registrars", [])
    print(f"  → {len(registrars)} registrars from ICANN", file=sys.stderr)
    return registrars

# ---------------------------------------------------------------------------
# 3. Merge
# ---------------------------------------------------------------------------
def merge(iana_records, icann_list):
    print("[3/3] Merging ...", file=sys.stderr)

    # Index ICANN by ianaNumber
    icann_by_id = {}
    for r in icann_list:
        num = r.get("ianaNumber")
        if num is not None:
            icann_by_id[str(num)] = r

    merged = {}

    # Start with IANA records (all include terminated/reserved)
    for rid, rec in iana_records.items():
        merged[rid] = dict(rec)
        ic = icann_by_id.get(rid)
        if ic:
            merged[rid]["registrar_name"] = ic.get("name", merged[rid]["registrar_name"])
            merged[rid]["website"] = ic.get("url") or None
            merged[rid]["country"] = ic.get("country") or None
            pc = ic.get("publicContact") or {}
            merged[rid]["contact"]["name"] = pc.get("name") or None
            merged[rid]["contact"]["email"] = pc.get("email") or None
            merged[rid]["contact"]["phone"] = pc.get("phone") or None

    # Any ICANN-only entries (shouldn't happen, but be safe)
    for num, ic in icann_by_id.items():
        if num not in merged:
            pc = ic.get("publicContact") or {}
            merged[num] = {
                "iana_id": ic["ianaNumber"],
                "registrar_name": ic.get("name", ""),
                "status": "Accredited",
                "rdap_url": "",
                "whois_server": None,
                "website": ic.get("url") or None,
                "country": ic.get("country") or None,
                "contact": {
                    "name": pc.get("name") or None,
                    "phone": pc.get("phone") or None,
                    "email": pc.get("email") or None,
                },
            }

    return merged


# ---------------------------------------------------------------------------
# 3b. Attempt WHOIS server discovery via RDAP port43 field
# ---------------------------------------------------------------------------

def _extract_main_domain(url: str) -> str | None:
    """Extract the registrable domain from a URL (e.g. rdap.godaddy.com -> godaddy.com)."""
    import re
    from urllib.parse import urlparse
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return None
        # Handle rdap.example.co.uk type cases
        parts = hostname.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return hostname
    except Exception:
        return None


def _probe_port43(rdap_base: str, website: str | None = None) -> str | None:
    """Try to extract port43 from an RDAP server. Returns None on failure."""
    base = rdap_base.rstrip("/")

    # Build candidate domains to query: extract from RDAP URL, then website
    candidates = set()
    d = _extract_main_domain(rdap_base)
    if d:
        candidates.add(d)
    if website and website.startswith("http"):
        d2 = _extract_main_domain(website)
        if d2:
            candidates.add(d2)

    # Try /domain/{candidate_domain} for each candidate
    for domain in candidates:
        try:
            r = requests.get(
                f"{base}/domain/{domain}",
                timeout=10,
                headers=HEADERS,
            )
            ct = r.headers.get("content-type", "")
            if "json" not in ct and not r.text.startswith("{"):
                continue
            data = r.json()
            if isinstance(data, dict):
                port43 = data.get("port43")
                if port43 and isinstance(port43, str) and port43.strip():
                    return port43.strip()
        except Exception:
            pass

    # Fallback: try the root endpoint
    try:
        r = requests.get(
            f"{base}/",
            timeout=10,
            headers=HEADERS,
        )
        if r.headers.get("content-type", "").startswith("application/json") or r.text.startswith("{"):
            data = r.json()
            if isinstance(data, dict):
                port43 = data.get("port43")
                if port43 and isinstance(port43, str) and port43.strip():
                    return port43.strip()
    except Exception:
        pass

    return None


def fetch_whois_servers(records: dict) -> dict:
    """Try to get whois_server from each unique RDAP endpoint."""
    # Deduplicate by RDAP URL to avoid hammering the same server repeatedly
    rdap_to_records: dict[str, list[str]] = {}
    for rid, rec in records.items():
        url = rec.get("rdap_url")
        if url:
            rdap_to_records.setdefault(url, []).append(rid)

    print(f"  Probing {len(rdap_to_records)} unique RDAP endpoints for port43 ...", file=sys.stderr)

    found = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as ex:
        fut_map = {
            ex.submit(_probe_port43, url, records[rids[0]].get("website")): (url, rids)
            for url, rids in rdap_to_records.items()
        }
        for fut in concurrent.futures.as_completed(fut_map):
            url, rids = fut_map[fut]
            try:
                port43 = fut.result()
                if port43:
                    for rid in rids:
                        records[rid]["whois_server"] = port43
                    found += 1
            except Exception:
                pass

    print(f"    → {found}/{len(rdap_to_records)} endpoints returned port43", file=sys.stderr)
    return records

# ---------------------------------------------------------------------------
# 4. Export JSON
# ---------------------------------------------------------------------------
def _strip_empty(obj):
    """Recursively remove keys with None or '' values, and empty containers."""
    if isinstance(obj, dict):
        cleaned = {k: _strip_empty(v) for k, v in obj.items() if v is not None and v != ""}
        return {k: v for k, v in cleaned.items() if v != {} and v != []}
    if isinstance(obj, list):
        cleaned = [_strip_empty(i) for i in obj]
        return [i for i in cleaned if i != {} and i != []]
    return obj


def write_json(records, path):
    lst = sorted(records.values(), key=lambda r: r["iana_id"] if isinstance(r["iana_id"], int) else 0)
    lst = [_strip_empty(r) for r in lst]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lst, f, indent=2, ensure_ascii=False)
    print(f"  → {len(lst)} registrars written to {path}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    iana = fetch_iana()
    icann = fetch_icann()
    merged = merge(iana, icann)

    merged = fetch_whois_servers(merged)

    write_json(merged, JSON_OUTPUT)

    accredited = sum(1 for r in merged.values() if r["status"] == "Accredited")
    terminated = sum(1 for r in merged.values() if r["status"] == "Terminated")
    with_website = sum(1 for r in merged.values() if r.get("website"))
    with_country = sum(1 for r in merged.values() if r.get("country"))
    with_whois = sum(1 for r in merged.values() if r.get("whois_server"))
    print(file=sys.stderr)
    print(f"Summary:", file=sys.stderr)
    print(f"  Total:         {len(merged)}", file=sys.stderr)
    print(f"  Accredited:    {accredited}", file=sys.stderr)
    print(f"  Terminated:    {terminated}", file=sys.stderr)
    print(f"  With website:  {with_website}", file=sys.stderr)
    print(f"  With country:  {with_country}", file=sys.stderr)
    print(f"  With whois:    {with_whois}", file=sys.stderr)

if __name__ == "__main__":
    main()
