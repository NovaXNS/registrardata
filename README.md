# ICANN & IANA Registrar Data

Consolidated registrar information from ICANN accreditation list and IANA registrar registry with JSON structure including accreditation status, contacts and RDAP endpoints.

## Data sources

| Source | Records | Fields |
|---|---|---|
| [ICANN GraphQL API](https://www.icann.org/graphql) | 3,022 (current accredited) | name, website, IANA number, country, contact name/email/phone |
| [IANA Registrar IDs CSV](https://www.iana.org/assignments/registrar-ids/) | 4,199 (all, including terminated) | ID, name, status, RDAP URL |

## Usage

```bash
pip install requests
python fetch_registrars.py
```

Output: `merged_registrars.json`

## Data structure

Each entry contains:

- `iana_id` — IANA registrar number
- `registrar_name` — official registrar name
- `status` — Accredited, Terminated, or Reserved
- `website` — registrar's website URL (optional)
- `rdap_url` — RDAP base URL (optional)
- `whois_server` — WHOIS server hostname (probed from RDAP port43, optional)
- `country` — country of registration (optional)
- `contact` — contact info (optional)
  - `name` — public contact person
  - `phone` — contact phone number
  - `email` — contact email address
