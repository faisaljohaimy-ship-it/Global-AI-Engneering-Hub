"""Unit tests of record validation, generated per entity from app/schema.json."""
import unittest

from tests.support import SCHEMA, bad_format, sample, wrong_type
from app import model

LIMITS = SCHEMA.limits


def _errors(entity, payload):
    try:
        model.validate(entity, payload, LIMITS)
    except model.ValidationError as error:
        return error.fields
    return {}


class ValidationTests(unittest.TestCase):
    def _required(self, entity):
        refs = {ref["field"]: 1 for ref in entity.references}
        self.assertEqual(_errors(entity, sample(entity, 1, refs)), {})
        for field in entity.fields:
            if field.get("required") and "default" not in field:
                payload = sample(entity, 1, refs)
                del payload[field["name"]]
                self.assertEqual(_errors(entity, payload).get(field["name"]), "required", field["name"])
                payload[field["name"]] = None
                self.assertEqual(_errors(entity, payload).get(field["name"]), "required", field["name"])
        for ref in entity.references:
            if ref.get("required"):
                payload = sample(entity, 1, refs)
                del payload[ref["field"]]
                self.assertEqual(_errors(entity, payload).get(ref["field"]), "required")

    def _types(self, entity):
        refs = {ref["field"]: 1 for ref in entity.references}
        for field in entity.fields:
            payload = sample(entity, 1, refs)
            payload[field["name"]] = wrong_type(field)
            self.assertIn(_errors(entity, payload).get(field["name"]), ("type",), field["name"])
            if bad_format(field) is not None:
                payload[field["name"]] = bad_format(field)
                self.assertEqual(_errors(entity, payload).get(field["name"]), "format", field["name"])
        for ref in entity.references:
            payload = sample(entity, 1, refs)
            for bad in ("1", 0, -1, True, 1.5):
                payload[ref["field"]] = bad
                self.assertEqual(_errors(entity, payload).get(ref["field"]), "type", repr(bad))

    def _max_length(self, entity):
        refs = {ref["field"]: 1 for ref in entity.references}
        for field in entity.fields:
            if field["type"] in ("text", "email"):
                limit = field.get("max", LIMITS["max_text"])
                payload = sample(entity, 1, refs)
                payload[field["name"]] = "x" * (limit + 1)
                self.assertEqual(_errors(entity, payload).get(field["name"]), "max_length", field["name"])
            if field["type"] in ("int", "number") and "max" in field:
                payload = sample(entity, 1, refs)
                payload[field["name"]] = field["max"] + 1
                self.assertEqual(_errors(entity, payload).get(field["name"]), "max", field["name"])

    def _enum(self, entity):
        refs = {ref["field"]: 1 for ref in entity.references}
        for field in entity.fields:
            if field["type"] == "enum":
                for value in field["values"]:
                    payload = sample(entity, 1, refs)
                    payload[field["name"]] = value
                    self.assertEqual(_errors(entity, payload), {})
                payload[field["name"]] = "not-a-listed-value"
                self.assertEqual(_errors(entity, payload).get(field["name"]), "enum")

    def _unknown_field(self, entity):
        refs = {ref["field"]: 1 for ref in entity.references}
        payload = sample(entity, 1, refs)
        payload["__unknown__"] = 1
        payload["id"] = 5
        errors = _errors(entity, payload)
        self.assertEqual(errors.get("__unknown__"), "unknown_field")
        self.assertEqual(errors.get("id"), "read_only")
        self.assertEqual(_errors(entity, ["not", "an", "object"]), {"_body": "type"})

    def _defaults(self, entity):
        refs = {ref["field"]: 1 for ref in entity.references}
        for field in entity.fields:
            if "default" in field:
                payload = sample(entity, 1, refs)
                del payload[field["name"]]
                values, _ = model.validate(entity, payload, LIMITS)
                self.assertEqual(values[field["name"]], field["default"])

    def test_text_rejects_control_characters(self):
        field = {"name": "x", "type": "text", "required": True}
        with self.assertRaises(KeyError):
            model.check_value(field, "bad\x00value", LIMITS)
        self.assertEqual(model.check_value(field, "  مرحبا  ", LIMITS), "مرحبا")

    def test_dates_are_strict(self):
        field = {"name": "d", "type": "date"}
        for bad in ("2026-02-30", "26-01-01", "2026-1-1", "2026-01-01T00:00"):
            with self.assertRaises(KeyError):
                model.check_value(field, bad, LIMITS)
        self.assertEqual(model.check_value(field, "2026-02-28", LIMITS), "2026-02-28")

    def test_numbers_are_finite_and_not_booleans(self):
        for kind in ("int", "number"):
            with self.assertRaises(KeyError):
                model.check_value({"name": "n", "type": kind}, True, LIMITS)
        with self.assertRaises(KeyError):
            model.check_value({"name": "n", "type": "number"}, float("inf"), LIMITS)
        with self.assertRaises(KeyError):
            model.check_value({"name": "n", "type": "int"}, 2 ** 60, LIMITS)


def _bind(check, entity):
    def test(self):
        getattr(self, "_" + check)(entity)
    test.__doc__ = f"{check} validation for {entity.name}"
    return test


for _entity in SCHEMA.entities:
    for _check in ("required", "types", "max_length", "enum", "unknown_field", "defaults"):
        setattr(ValidationTests, f"test_{_check}_{_entity.table}", _bind(_check, _entity))


if __name__ == "__main__":
    unittest.main()
