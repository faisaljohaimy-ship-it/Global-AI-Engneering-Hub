"""Load the synthetic seed data (app/seed_data.json) into the database.

Every seeded record is synthetic: it describes no real person, project or customer.
No sign-in account is seeded; create one with `python3 manage.py create-account`.
"""
import json
import pathlib

from . import db, model, server

ROOT = pathlib.Path(__file__).resolve().parent
SEED_PATH = ROOT / "seed_data.json"


def load(path=SEED_PATH):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if data.get("label") != "synthetic":
        raise ValueError("seed data must be labelled synthetic")
    return data


def seed(db_path, schema=None, path=SEED_PATH):
    """Insert the seed records in dependency order. Returns {entity: count}."""
    schema = schema or model.load_schema()
    data = load(path)
    created, counts = {}, {}
    with db.session(db_path) as connection:
        db.migrate(connection)
        for entity in schema.entities:
            ids = created.setdefault(entity.name, [])
            for row in data["records"].get(entity.name, []):
                payload = {}
                for key, value in row.items():
                    if isinstance(value, dict) and "$ref" in value:
                        target, index = value["$ref"]
                        value = created[target][index]
                    payload[key] = value
                values = model.validate(entity, payload, schema.limits)
                db.check_references(connection, schema, entity, values)
                db.check_unique(connection, entity, values)
                ids.append(db.insert(connection, entity, values, server.utc_now()))
            counts[entity.name] = len(ids)
        for row in data.get("links", []):
            entity = schema.by_name[row["source"][0]]
            link = next(item for item in entity.links if item["segment"] == row["segment"])
            db.add_link(connection, link, created[row["source"][0]][row["source"][1]],
                        created[row["target"][0]][row["target"][1]])
    return counts
