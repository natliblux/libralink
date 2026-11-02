# LibraLink

![Status](https://img.shields.io/badge/status-work_in_progress-orange)

<p align="left">
  <img src="assets/logo.png" alt="LibraLink logo" width="400">
</p>

LibraLink processes **MARC 21 authority records** and provides a REST API for finding and retrieving authorities. It consists of two components:

* **[Indexing](#indexing)** - Reads MARCXML, builds a SQLite database, and optionally exports to Elasticsearch or JSONL.
* **[API](#api)** -  Searches the authority database and retrieves authorities by identifier.

## Table of contents

- [Setup](#setup)
  - [Terminology](#terminology)
  - [Installation](#installation)
  - [Normalizer](#normalizer)
  - [Identifier](#identifier)
- [Indexing](#indexing)
  - [CLI](#cli)
  - [Arguments](#arguments)
  - [Logic](#logic)
- [API](#api)
  - [Startup](#startup)
  - [POST /identifier](#post-identifier)
  - [POST /search](#post-search)
  - [Linking](#linking)

## Setup

### Terminology

* **Preferred heading**  
The authorized form of a name, typically stored in MARC fields such as `100` or `110`.

* **Variant heading**  
An alternative form of a name, typically stored in MARC fields such as `400` or `410`.

* **Authority identifier**  
A unique identifier associated with an authority record, extracted by LibraLink from `035 $a`.

### Installation

LibraLink requires **Python 3.12+** and a MARCXML authority file. To install the required dependencies:

```bash
pip install -r requirements.txt
```

A configuration file named `.env` **must** exist at the project root and is shared by both indexing and the API. Copy the example (`.env.example`) and adjust it accordingly:

```bash
cp .env.example .env
```

```bash
# normalizer module name from src/normalization/ (default if empty)
AUTH_NORMALIZER=bnl

# identifier prefix (first available 035$a if empty)
AUTH_IDENTIFIER=(LUBIBNET)
```

### Normalizer

A custom `normalize(text: str) -> str` function can be implemented in a custom module under `src/normalization/`. Those normalization rules are applied throughout LibraLink (indexing and API). `AUTH_NORMALIZER` defaults to `default`, which removes bracketed content (`[]`, `()`, `{}`), spaces, and angle brackets (`<>`), then converts the text to lowercase. Changing the normalizer requires rerunning indexing to rebuild the database.

### Identifier

The prefix used to select an authority identifier from potentially multiple `035 $a` subfields. If `AUTH_IDENTIFIER` is left empty or is omitted, the first nonempty `035 $a` subfield is picked automatically. Changing the prefix requires rerunning indexing to rebuild the database.

## Indexing

Indexing extracts preferred and variant headings from MARCXML and stores searchable entries in a SQLite database. The data can also optionally be made available to Elasticsearch and as a JSONL output (both not required to run the API). 

### CLI

Run `src/indexer.py` to import data into the database. For example, a two-step import for personal authorities (`100 & 400`), followed by corporate authorities (`110 & 410`).

```bash
python3 src/indexer.py --xml authorities.xml --type person --preferred 100 --variants 400 --clear
python3 src/indexer.py --xml authorities.xml --type corporate --preferred 110 --variants 410
```

The first command clears the database, the second adds another authority type without clearing it. The `--type` values can be chosen freely and will later be used as filters for the API.

### Arguments

| Short | Long | Required | Description |
| --- | --- | --- | --- |
| `-x` | `--xml` | Yes | Input MARCXML file path, e.g. `authorities.xml`. |
| `-t` | `--type` | Yes | Authority type label stored in the database, e.g. `person` or `corporate`. |
| `-p` | `--preferred` | Yes | Three-digit MARC tag for the preferred heading, e.g. `100` or `110`. |
| `-v` | `--variants` | Yes | Three-digit MARC tag for the variant headings, e.g. `400` or `410`. |
| `-e` | `--elastic` | No | Optional Elasticsearch URL including index, e.g. `http://localhost:9200/authorities`. |
| `-j` | `--jsonl` | No | Optional JSONL output path, e.g. `authorities.jsonl`. |
| `-c` | `--clear` | No | Clears/resets the database and, if provided, the Elasticsearch index and JSONL file. |

The **normalizer** and **identifier** settings come from the `.env` file and are not part of the CLI.

### Logic

For each MARCXML authority record, indexing:

1. Reads the first preferred heading (requires a nonempty `$a`), the corresponding `$b` and `$d` subfields and the indicators.
2. Selects an authority identifier from `035$a` according to `AUTH_IDENTIFIER` (records without a suitable identifier are skipped entirely).
3. Creates a searchable entry for each occurrence of the variant field, preserving `$a` and all `$b` values.
4. Adds the preferred heading as a searchable variant if it is not already among the variants.
5. Stores original and normalized text (according to `AUTH_NORMALIZER`), including combined headings and individual `$a` and `$b` representations.

An authority can occupy multiple database rows, but all its entries share one authority identifier. Imports without `--clear` replace rows with matching entry IDs but do not necessarily remove obsolete rows from earlier imports.

## API

The API reads the indexed SQLite database and exposes two JSON endpoints:

- **`POST /identifier`** - retrieve an authority by identifier.
- **`POST /search`** - find authorities by heading text, with selectable search fields.

### Startup

From the project root:

```bash
python3 src/api.py
```

For production, the application can be served with Gunicorn under Supervisor. Run Gunicorn with `src` as the working directory:

```bash
gunicorn --chdir /absolute/path/to/libralink/src api:app -k uvicorn_worker.UvicornWorker -w 4 -b 127.0.0.1:8000
```

### `POST /identifier`

Retrieves authorities by identifier.

**Request**

```json
{
  "identifier": "000055066"
}
```

| Parameter | Type | Description |
| --- | --- | --- |
| `identifier` | string (required) | Full or unprefixed authority identifier. |

The API first tries the identifier exactly as provided. If no result is found and `AUTH_IDENTIFIER` is configured, it tries prepending that prefix (unless already present). For example, `000055066` and `(LUBIBNET)000055066` can identify the same authority.

**Response when found:**

```json
{
  "autType": "person",
  "ind1": "1",
  "ind2": "#",
  "authority": "(LUBIBNET)000055066",
  "years": "1932-2005",
  "preferred": "Gaul, Charly",
  "preferredA": "Gaul, Charly",
  "preferredB_list": [],
  "preferredB": ""
}
```

**Response when not found:** `[]`

The `preferred` field contains the complete preferred heading, while `preferredA` contains only `$a`. The `preferredB_list` field contains all `$b` subfields as a list, whereas `preferredB` contains only the first `$b` value (or an empty string if none exists).

### `POST /search`

Searches authority headings in the requested fields and returns distinct matching authorities.

**Request**

```json
{
    "type": "corporate",
    "text": "european parliament",
    "fields": ["variant", "variantA", "variantB"],
    "normalize": true
}
```

| Parameter | Type | Description |
| --- | --- | --- |
| `type` | string (required) | Authority type label that was used with indexing `--type`. |
| `text` | string (required) | Text to search for. |
| `fields` | list of strings (required) | List of search fields to be used. |
| `normalize` | boolean (optional) | Also search normalized values, defaults to `false`. |

**Searchable fields**

| Field | Matches against |
| --- | --- |
| `variant` | `$a` followed by all `$b` values. |
| `variantA` | `$a` only. |
| `variantB` | the first `$b` only. |

The preferred heading is automatically searchable since it is included as a variant during indexing. With `"normalize": true`, the API additionally searches `variantNorm`, `variantANorm`, and/or `variantBNorm`, corresponding to the requested fields.

The API searches all requested fields (requiring exact matching), including their normalized counterparts when `normalize=true`. Results are combined and deduplicated by authority identifier. The `unique` flag indicates that exactly one distinct authority matched, which can be a useful signal when determining the intended real-world entity.

**Response with one match**

```json
{
  "unique": true,
  "results": 1,
  "authorities": [
    {
      "autType": "corporate",
      "ind1": "#",
      "ind2": "#",
      "authority": "(LUBIBNET)000002524",
      "preferred": "Communautés européennes Parlement européen",
      "preferredA": "Communautés européennes",
      "preferredB_list": [
        "Parlement européen"
      ],
      "preferredB": "Parlement européen"
    }
  ]
}
```

**Response with no matches:**  
`{"results": 0}`

**Response with multiple matches:**  
When multiple authorities match, `unique` is `false`.

### Linking

The `/search` endpoint returns candidate authorities without deciding which one should be linked. Clients can implement their own linking strategies using the available search fields, normalization options, and match counts.

#### Example: BnL Linking Strategy

The BnL, for example, currently uses a conservative three-step linking strategy designed to minimize false links:

1. **Exact match**: Search the combined `$a` and first `$b` using `fields=["variant"]` and `normalize=false`. Link if exactly one authority matches.
2. **Disambiguation**: If multiple authorities match, search `$a` using `fields=["variantA"]` and `normalize=false`. Link if the intersection with the initial Step 1 results contains exactly one authority.
3. **Normalized match**: If the initial search returns no matches, repeat Step 1 with `normalize=true`. Link if exactly one authority matches.

If no unique match is established, the record remains unlinked. Steps 2 and 3 are mutually exclusive.