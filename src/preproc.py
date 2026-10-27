import argparse
import os
import json
import sqlite3
import xml.etree.ElementTree as ET
from argparse import Namespace
from collections.abc import Callable
from itertools import batched
from pathlib import Path
from typing import Iterator, TextIO
from urllib.parse import urlparse
from dotenv import load_dotenv
from elasticsearch import Elasticsearch, helpers
from elasticsearch.exceptions import ElasticsearchWarning
from tqdm import tqdm
from authority import Authority
import constants as ct
from normalization.default import normalize
from loader import load_normalizer
import warnings
warnings.simplefilter("ignore", ElasticsearchWarning)

def load_config() -> tuple[Callable[[str], str], str | None]:

    env_path = Path(__file__).resolve().parent.parent / ".env"

    if not env_path.is_file():
        raise FileNotFoundError(f"missing configuration file: {env_path}")

    load_dotenv(env_path, override=True)

    normalizer_name = os.getenv("AUTH_NORMALIZER") or "default"
    normalizer = load_normalizer(normalizer_name)
    identifier = os.getenv("AUTH_IDENTIFIER") or None

    return normalizer, identifier

def create_indexes(conn: sqlite3.Connection) -> None:

    conn.execute(f'CREATE INDEX IF NOT EXISTS idx_authority ON "{ct.TABLE_NAME}" (authority)')

    for field in ct.ALLOWED_SEARCH_FIELDS:
        conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{field}" ON "{ct.TABLE_NAME}" (autType, "{field}")')
        conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{field}Norm" ON "{ct.TABLE_NAME}" (autType, "{field}Norm")')

    conn.commit()

def get_fields(record: ET.Element, field_tag: str, subfield_code: str | None = None) -> list[ET.Element]:

    fields = []

    for datafield in record.findall(f"./datafield[@tag='{field_tag}']"):
        if subfield_code:
            fields.extend(datafield.findall(f"subfield[@code='{subfield_code}']"))
        else:
            fields.append(datafield)

    return fields

def get_indicators(record: ET.Element, field_tag: str) -> tuple[str, str]:

    fields = get_fields(record, field_tag)

    if not fields:
        return "#", "#"

    field = fields[0]
    ind1 = field.attrib.get("ind1", " ").replace(" ", "#")
    ind2 = field.attrib.get("ind2", " ").replace(" ", "#")

    return ind1, ind2

def get_authorities(record: ET.Element, aut_type: str, preferred_field: str, variant_field: str, normalizer: Callable[[str], str], identifier: str | None = None) -> Iterator[Authority]:

    preferred_a_list = [subfield.text or "" for subfield in get_fields(record, preferred_field, "a")]

    if not preferred_a_list or not preferred_a_list[0].strip():
        return

    preferred_a = preferred_a_list[0]
    preferred_b = [subfield.text or "" for subfield in get_fields(record, preferred_field, "b")]
    preferred = f"{preferred_a.strip()} {' '.join(Authority._clean_list(preferred_b))}".strip()

    ind1, ind2 = get_indicators(record, preferred_field)

    ids = [subfield.text or "" for subfield in get_fields(record, "035", "a")]
    authority_id = next((s for s in ids if s and (identifier is None or s.startswith(identifier))), None)

    if authority_id is None:
        return

    years = "".join(subfield.text or "" for subfield in get_fields(record, preferred_field, "d"))

    fields = get_fields(record, variant_field)
    n_variants = len(fields)
    variants = []

    for entry_index, field in enumerate(fields):

        a = field.findall("subfield[@code='a']")
        b = field.findall("subfield[@code='b']")

        variant_a = (a[0].text or "") if a else ""
        variant_b = [subfield.text or "" for subfield in b]
        variant = f"{variant_a.strip()} {' '.join(Authority._clean_list(variant_b))}".strip()
        variants.append(variant)

        yield Authority(authority_id, entry_index, years, aut_type, ind1, ind2, preferred_a, preferred_b, variant_a, variant_b, n_variants, normalizer)

    if preferred not in variants:
        yield Authority(authority_id, n_variants, years, aut_type, ind1, ind2, preferred_a, preferred_b, preferred_a, preferred_b, n_variants, normalizer)

def parse_elastic_url(value: str) -> tuple[str, str]:

    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("invalid elasticsearch url")

    index = parsed.path.strip("/")
    if not index or "/" in index or parsed.query or parsed.fragment:
        raise ValueError("elasticsearch url must contain exactly one index")

    host = f"{parsed.scheme}://{parsed.netloc}"
    return host, index

def create_database(conn: sqlite3.Connection, clear: bool = False) -> None:

    if clear:
        conn.execute(f'DROP TABLE IF EXISTS "{ct.TABLE_NAME}"')

    conn.execute(f'''
        CREATE TABLE IF NOT EXISTS "{ct.TABLE_NAME}" (
            id TEXT PRIMARY KEY,
            autType TEXT,
            ind1 TEXT,
            ind2 TEXT,
            authority TEXT,
            entryIndex INTEGER,
            nVariants INTEGER,
            identical INTEGER,
            years TEXT,
            preferred TEXT,
            variant TEXT,
            preferredA TEXT,
            variantA TEXT,
            preferredNorm TEXT,
            variantNorm TEXT,
            preferredANorm TEXT,
            variantANorm TEXT,
            preferredB_list TEXT,
            variantB_list TEXT,
            preferredBNorm_list TEXT,
            variantBNorm_list TEXT,
            preferredB TEXT,
            variantB TEXT,
            preferredBNorm TEXT,
            variantBNorm TEXT
        )
    ''')

    conn.commit()

def handle_authorities(authorities: list[Authority], conn: sqlite3.Connection, elastic: tuple[Elasticsearch, str] | None = None, jsonl_file: TextIO | None = None) -> None:

    if not authorities:
        return

    documents = [authority.json() for authority in authorities]

    # sqlite
    columns = list(documents[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    column_names = ", ".join(f'"{col}"' for col in columns)

    values = [
        [json.dumps(doc[col]) if isinstance(doc[col], (list, dict)) else doc[col] for col in columns]
        for doc in documents
    ]

    conn.executemany(f'INSERT OR REPLACE INTO "{ct.TABLE_NAME}" ({column_names}) VALUES ({placeholders})', values)

    # elastic
    if elastic is not None:
        es, index = elastic
        actions = [{"_index": index, "_id": doc["id"], "_source": doc} for doc in documents]
        _, failed = helpers.bulk(es, actions, raise_on_error=False, stats_only=True)

        if failed:
            print(f"elasticsearch: {failed} documents failed to index")

    # jsonl
    if jsonl_file is not None:
        for doc in documents:
            jsonl_file.write(json.dumps(doc, ensure_ascii=False) + "\n")

def preproc(xml_path: Path, aut_type: str, preferred_field: str, variant_field: str, conn: sqlite3.Connection, elastic: tuple[Elasticsearch, str] | None = None, jsonl_file: TextIO | None = None, normalizer: Callable[[str], str] = normalize, identifier: str | None = None) -> int:

    count = 0

    with open(xml_path, "rb") as f, tqdm(total=xml_path.stat().st_size, unit="B", unit_scale=True, desc="preprocessing") as progress:

        context = ET.iterparse(f, events=("start", "end"))
        _, root = next(context)

        def authorities() -> Iterator[Authority]:

            for event, element in context:
                if event == "end" and element.tag == "record":
                    yield from get_authorities(element, aut_type, preferred_field, variant_field, normalizer, identifier)
                    root.clear()
                    progress.update(f.tell() - progress.n)

        for batch in batched(authorities(), ct.PREPROC_BATCH_SIZE):
            handle_authorities(batch, conn, elastic, jsonl_file)
            count += len(batch)

    conn.commit()
    return count

def print_statistics(conn: sqlite3.Connection, aut_type: str, processed: int) -> None:

    print(f"processed entries\n  {processed:>10,}  {aut_type}")

    rows = conn.execute(f'''
        SELECT autType, COUNT(DISTINCT authority), COUNT(*)
        FROM "{ct.TABLE_NAME}"
        GROUP BY autType
        ORDER BY autType
    ''').fetchall()

    print("\ndatabase entries")
    for name, authorities, entries in rows:
        print(f"  {entries:>10,}  {name}")
    print(f"  {sum(row[2] for row in rows):>10,}  total")

    print("\ndatabase authorities")
    for name, authorities, entries in rows:
        print(f"  {authorities:>10,}  {name}")
    print(f"  {sum(row[1] for row in rows):>10,}  total")

def parse_args() -> Namespace:

    parser = argparse.ArgumentParser(description="Preprocess MARC authority records")
    parser.add_argument("-x", "--xml", type=Path, required=True, help="input xml file")
    parser.add_argument("-t", "--type", required=True, help='authority type (e.g. "person")')
    parser.add_argument("-p", "--preferred", required=True, help="marc field that contains the preferred form")
    parser.add_argument("-v", "--variants", required=True, help="marc field that contains variants")
    parser.add_argument("-e", "--elastic", help="optional elasticsearch url including index")
    parser.add_argument("-j", "--jsonl", type=Path, help="optional jsonl output file")
    parser.add_argument("-c", "--clear", action="store_true", help="clear existing data before preprocessing")
    args = parser.parse_args()

    if not args.xml.is_file():
        parser.error(f"not a valid file: {args.xml}")
    if not args.type.strip():
        parser.error("authority type cannot be empty")
    if not args.preferred.isdigit() or len(args.preferred) != 3:
        parser.error("preferred field must be a three-digit tag")
    if not args.variants.isdigit() or len(args.variants) != 3:
        parser.error("variants field must be a three-digit tag")

    if args.elastic:
        try:
            args.elastic = parse_elastic_url(args.elastic)
        except ValueError as e:
            parser.error(str(e))

    if args.jsonl is not None and not str(args.jsonl).endswith(".jsonl"):
        args.jsonl = Path(str(args.jsonl) + ".jsonl")

    args.type = args.type.strip()

    return args

def run(args: Namespace) -> None:

    normalizer, identifier = load_config()
    print(f"normalizer: {os.getenv('AUTH_NORMALIZER') or 'default'}")
    print(f"identifier: {identifier or 'first available 035$a'}")

    conn = sqlite3.connect(ct.DB_FILE)
    es = None
    jsonl_file = None

    try:
        create_database(conn, args.clear)

        if args.elastic is not None:
            host, index = args.elastic
            es = Elasticsearch(host)

            if args.clear and es.indices.exists(index=index):
                es.delete_by_query(index=index, body={"query": {"match_all": {}}}, refresh=True, conflicts="proceed")

        if args.jsonl is not None:
            args.jsonl.parent.mkdir(parents=True, exist_ok=True)
            jsonl_file = open(args.jsonl, "w" if args.clear else "a", encoding="utf-8")

        elastic = (es, args.elastic[1]) if es is not None else None

        processed = preproc(args.xml, args.type, args.preferred, args.variants, conn, elastic, jsonl_file, normalizer, identifier)
        create_indexes(conn)
        print_statistics(conn, args.type, processed)

    finally:
        if jsonl_file is not None:
            jsonl_file.close()
        if es is not None:
            es.close()
        conn.close()

def main() -> None:

    run(parse_args())

if __name__ == "__main__":
    main()