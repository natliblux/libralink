# LibraLink

![Status](https://img.shields.io/badge/status-work_in_progress-orange)

LibraLink preprocesses **MARC 21 authority records** and provides a REST API for finding and retrieving authorities. It is divided in to two components:

1. **Preprocessing** — reads MARCXML, builds a SQLite3 database, and optionally exports to Elasticsearch or JSONL.
2. **API** — searches the authority database and retrieves authorities by identifier.

## Table of contents

- [Installation](#installation)
- [Preprocessing](#preprocessing)
  - [Example](#Example)
  - [Arguments](#arguments)
  - [Record Processing](#record-processing)
- [API](#api)
  - [Startup](#startup)
  - [POST /lookup](#post-lookup)
  - [POST /search](#post-search)
  - [Linking](#linking)

## Installation

LibraLink requires **Python 3.12+** and a MARCXML authority file. To install the required dependencies:

```bash
pip install -r requirements.txt
```

Copy the example configuration and adjust the required `.env` file (used by preprocessing and API)

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

An arbitrary `normalize(text: str) -> str` function can be introduced within `src/normalization/` and used throughout the project. The variable defaults to `default`, which removes bracketed content, spaces and converts text to lowercase. Changing the normalizer requires rerunning preprocessing.

### Identifier

The prefix used to select an authority identifier from all available 035$a subfields. If empty or omitted, the first nonempty 035$a subfield is used. Changing the prefix requires rerunning preprocessing.

## Preprocessing

Preprocessing extracts preferred and variant headings from MARCXML and stores searchable entries in a **SQLite3 database**. The database file and table are configured by `DB_FILE` and `TABLE_NAME` in `src/constants.py`. Elasticsearch and JSONL outputs are optional; neither is needed to run the API.

### Running preprocessing

For example, import personal authorities (`100` / `400`) and then corporate authorities (`110` / `410`) into the same database:

```bash
python3 src/preproc.py --xml data/persons.xml --type person --preferred 100 --variants 400 --clear
python3 src/preproc.py --xml data/entities.xml --type corporate --preferred 110 --variants 410
```

The first command clears the existing authority table; the second adds another authority type **without** clearing it. The `--type` values are labels you choose and must match the `type` supplied to `/search`.

### Arguments

| Short | Long | Required | Description |
| --- | --- | --- | --- |
| `-x` | `--xml` | Yes | Input MARCXML file path. |
| `-t` | `--type` | Yes | Authority type label stored in the database, e.g. `person` or `corporate`. |
| `-p` | `--preferred` | Yes | Three-digit MARC tag for the preferred heading, e.g. `100` or `110`. |
| `-v` | `--variants` | Yes | Three-digit MARC tag for variant headings, e.g. `400` or `410`. |
| `-e` | `--elastic` | No | Elasticsearch URL **including index**, e.g. `http://localhost:9200/authorities`. Indexes generated entries in addition to SQLite. |
| `-j` | `--jsonl` | No | Optional JSONL output path. Adds `.jsonl` if missing; writes one JSON object per entry. Appends unless `--clear` is used. |
| `-c` | `--clear` | No | Drops and recreates the SQLite authority table before importing. Also clears the specified Elasticsearch index and overwrites the specified JSONL file. **Destructive; use with care.** |

Normalizer and identifier settings come from `.env`, **not** CLI arguments.

### Record Processing

For each MARCXML authority record, preprocessing:

1. Reads the first preferred heading (requires a nonempty `$a`), its `$b` subfields, `$d` text (`years`), and indicators.
2. Selects an authority identifier from `035$a` according to `AUTH_IDENTIFIER`. Records without a suitable identifier are skipped.
3. Creates a searchable entry for each occurrence of the variant field, preserving `$a` and all `$b` values.
4. Adds the preferred heading as a searchable variant if it is not already among the variants.
5. Stores original and normalized text, including combined headings and individual `$a` and `$b` representations.

An authority can occupy multiple database rows, but all its entries share one authority identifier. Imports without `--clear` replace rows with matching entry IDs but do not necessarily remove obsolete rows from earlier imports.

## API

The API reads the preprocessed SQLite3 database and exposes two JSON endpoints:

- **`POST /identifier`** — retrieve an authority by identifier.
- **`POST /search`** — find authorities by heading text, with selectable search fields.

Interactive OpenAPI documentation is available at `/docs` after startup.

### Startup

From the project root:

```bash
python3 src/api.py
```

For production, the application can be served with Gunicorn under Supervisor. Run Gunicorn with `src` as the working directory so local imports resolve:

```bash
gunicorn --chdir src api:app -k uvicorn.workers.UvicornWorker -w 4 -b 127.0.0.1:8000
```

### `POST /identifier`

Retrieves authorities by identifier.

**Request**

```json
{
  "identifier": "000000715"
}
```

| Parameter | Type | Description |
| --- | --- | --- |
| `identifier` | string (required) | Full or unprefixed authority identifier. |

The API first tries the identifier exactly as supplied. If no result is found and `AUTH_IDENTIFIER` is configured, it tries prepending that prefix (unless already present). For example, `000000715` and `(LUBIBNET)000000715` can identify the same authority.

**Response when found:**

```json
{
  "autType": "person",
  "ind1": "1",
  "ind2": "#",
  "authority": "(LUBIBNET)000000715",
  "years": "1823-1891",
  "preferred": "La Fontaine, Edmond de",
  "preferredA": "La Fontaine, Edmond de",
  "preferredB_list": [],
  "preferredB": ""
}
```

**Response when not found:** `[]`.

### `POST /search`

Searches authority headings in the requested fields and returns distinct matching authorities.

**Request**

```json
{
  "type": "person",
  "text": "Dicks",
  "fields": ["variant", "variantA"],
  "normalize": true
}
```

| Parameter | Type | Description |
| --- | --- | --- |
| `type` | string (required) | Authority type label used with preprocessing `--type`. |
| `text` | string (required) | Text to search for. |
| `fields` | array of strings (required) | Search fields, evaluated in the specified order. Invalid or repeated values are ignored. |
| `normalize` | boolean (optional) | Also search normalized values; defaults to `false`. |

**Searchable fields**

| Field | Matches against |
| --- | --- |
| `variant` | `$a` followed by all `$b` values. |
| `variantA` | `$a` only. |
| `variantB` | `$b` only. |

The preferred heading is searchable too: preprocessing adds it as a variant when needed. With `"normalize": true`, the API additionally searches `variantNorm`, `variantANorm`, and/or `variantBNorm`, corresponding to the requested fields.

The API performs **exact searches first**, in field order, followed by normalized searches when enabled. Results are deduplicated by authority identifier, preserving the first match. The `unique` flag means only one distinct authority matched—not that the match is necessarily correct.

**Response with one match**

```json
{
  "unique": true,
  "results": 1,
  "data": [
    {
      "autType": "person",
      "ind1": "1",
      "ind2": "#",
      "authority": "(LUBIBNET)000000715",
      "years": "1823-1891",
      "preferred": "La Fontaine, Edmond de",
      "preferredA": "La Fontaine, Edmond de",
      "preferredB_list": [],
      "preferredB": ""
    }
  ]
}
```

**Response with no matches:** `{"results": 0}`. With multiple matches, `unique` is `false`, `results` gives the number of distinct authorities, and `data` contains one object per authority.

### Linking

`/search` returns candidates; **it does not select/link the correct authority**. Clients can implement their own matching or linking strategies by selecting which fields to search, choosing whether to normalize, and evaluating the number of matches returned. The API supplies the building blocks, the client controls the decision logic.