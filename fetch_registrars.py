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
import io
import json
import sys
import time

import requests

JSON_OUTPUT = "merged_registrars.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
            "website": None,
            "country": None,
            "contact_name": None,
            "contact_phone": None,
            "contact_email": None,
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
            merged[rid]["contact_name"] = pc.get("name") or None
            merged[rid]["contact_email"] = pc.get("email") or None
            merged[rid]["contact_phone"] = pc.get("phone") or None

    # Any ICANN-only entries (shouldn't happen, but be safe)
    for num, ic in icann_by_id.items():
        if num not in merged:
            pc = ic.get("publicContact") or {}
            merged[num] = {
                "iana_id": ic["ianaNumber"],
                "registrar_name": ic.get("name", ""),
                "status": "Accredited",
                "rdap_url": "",
                "website": ic.get("url") or None,
                "country": ic.get("country") or None,
                "contact_name": pc.get("name") or None,
                "contact_phone": pc.get("phone") or None,
                "contact_email": pc.get("email") or None,
            }

    return merged

# ---------------------------------------------------------------------------
# 4. Export JSON
# ---------------------------------------------------------------------------
def write_json(records, path):
    lst = sorted(records.values(), key=lambda r: r["iana_id"] if isinstance(r["iana_id"], int) else 0)
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

    write_json(merged, JSON_OUTPUT)

    accredited = sum(1 for r in merged.values() if r["status"] == "Accredited")
    terminated = sum(1 for r in merged.values() if r["status"] == "Terminated")
    with_website = sum(1 for r in merged.values() if r.get("website"))
    with_country = sum(1 for r in merged.values() if r.get("country"))
    print(file=sys.stderr)
    print(f"Summary:", file=sys.stderr)
    print(f"  Total:        {len(merged)}", file=sys.stderr)
    print(f"  Accredited:   {accredited}", file=sys.stderr)
    print(f"  Terminated:   {terminated}", file=sys.stderr)
    print(f"  With website: {with_website}", file=sys.stderr)
    print(f"  With country: {with_country}", file=sys.stderr)

if __name__ == "__main__":
    main()
