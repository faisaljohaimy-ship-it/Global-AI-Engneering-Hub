"""Load the synthetic seed data (app/seed_data.json) into the database.

Every seeded record is synthetic: it describes no real person, project or customer.
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
                    elif isinstance(value, list) and value and isinstance(value[0], dict):
                        value = [created[item["$ref"][0]][item["$ref"][1]] for item in value]
                    payload[key] = value
                values, links = model.validate(entity, payload, schema.limits)
                db.check_references(connection, schema, entity, values, links)
                ids.append(db.insert(connection, entity, values, links, server.utc_now()))
            counts[entity.name] = len(ids)
    return counts
