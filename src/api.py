import os
from dotenv import load_dotenv
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
import constants as ct
from loader import load_normalizer

def create_app() -> FastAPI:

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        raise FileNotFoundError(f"missing configuration file: {env_path}")

    load_dotenv(env_path, override=True)

    app = FastAPI(title=ct.API_NAME)
    normalizer_name = os.getenv("AUTH_NORMALIZER") or "default"
    app.state.normalizer = load_normalizer(normalizer_name)
    app.state.identifier_prefix = os.getenv("AUTH_IDENTIFIER") or None

    return app

app = create_app()

class SearchRequest(BaseModel):

    type: str
    text: str
    fields: list[str]
    normalize: bool = False

class IdentifierRequest(BaseModel):

    identifier: str

@contextmanager
def get_db_connection() -> Generator[sqlite3.Connection, None, None]:

    conn = sqlite3.connect(ct.DB_FILE)
    conn.row_factory = sqlite3.Row

    try:
        yield conn
    finally:
        conn.close()

def prepare_entry(row: sqlite3.Row) -> dict:

    entry = {
        "autType": row["autType"],
        "ind1": row["ind1"],
        "ind2": row["ind2"],
        "authority": row["authority"],
        "years": row["years"],
        "preferred": row["preferred"],
        "preferredA": row["preferredA"],
        "preferredB_list": json.loads(row["preferredB_list"]),
        "preferredB": row["preferredB"]
    }

    return {key: value for key, value in entry.items() if value is not None}

@app.post("/identifier")
def identifier(payload: IdentifierRequest):

    identifier = payload.identifier

    with get_db_connection() as conn:
        row = conn.execute(
            f'SELECT * FROM "{ct.TABLE_NAME}" WHERE authority = ? LIMIT 1',
            (identifier,)
        ).fetchone()

        if row is None and app.state.identifier_prefix and not identifier.startswith(app.state.identifier_prefix):
            row = conn.execute(
                f'SELECT * FROM "{ct.TABLE_NAME}" WHERE authority = ? LIMIT 1',
                (app.state.identifier_prefix + identifier,)
            ).fetchone()

    return prepare_entry(row) if row else []

@app.post("/search")
def search(payload: SearchRequest):

    fields = []
    for field in payload.fields:
        if field in ct.ALLOWED_SEARCH_FIELDS and field not in fields:
            fields.append(field)

    rows = []

    with get_db_connection() as conn:

        for field in fields:
            matches = conn.execute(
                f'SELECT * FROM "{ct.TABLE_NAME}" WHERE autType = ? AND "{field}" = ? ORDER BY id',
                (payload.type, payload.text)
            ).fetchall()
            rows.extend(matches)

        if payload.normalize:
            normalized_text = app.state.normalizer(payload.text)

            for field in fields:
                norm_field = f"{field}Norm"
                matches = conn.execute(
                    f'SELECT * FROM "{ct.TABLE_NAME}" WHERE autType = ? AND "{norm_field}" = ? ORDER BY id',
                    (payload.type, normalized_text)
                ).fetchall()
                rows.extend(matches)

    authorities = {}

    for row in rows:
        if row["authority"] not in authorities:
            authorities[row["authority"]] = prepare_entry(row)

    results = list(authorities.values())

    if not results:
        return {"results": 0}

    return {
        "unique": len(results) == 1,
        "results": len(results),
        "data": results
    }

def main() -> None:

    uvicorn.run(app, host="127.0.0.1", port=ct.API_PORT+1)

if __name__ == "__main__":
    main()