# ICANN & IANA Registrar Data

Merged list of ICANN-accredited registrars and IANA registrar IDs.

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
- `website` — registrar's website URL
- `rdap_url` — RDAP base URL
- `country` — country of registration
- `contact_name` — public contact person
- `contact_phone` — contact phone number
- `contact_email` — contact email address
