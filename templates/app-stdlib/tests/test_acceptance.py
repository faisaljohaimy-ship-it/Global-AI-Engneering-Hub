"""Acceptance tests: every criterion of the specification, executed over real HTTP.

app/acceptance.json holds the criteria in the grammar
`METHOD /path [condition] returns NNN [and expectation]`, already matched by the build
engine to one of the condition/expectation forms handled below (a criterion the engine
could not match is not listed and is reported as unmapped instead). Each criterion runs
against its own fresh server and database.
"""
import datetime
import html.parser
import http.cookies
import json
import pathlib
import unittest

from tests.support import ADMIN, SCHEMA, Running, sample

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKS = json.loads((ROOT / "app" / "acceptance.json").read_text(encoding="utf-8"))["checks"]
MISSING_ID = 999999999
MAX = SCHEMA.limits["max_page_size"]


class _Inputs(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.controls, self.labels, self.depth, self.root = [], set(), 0, {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "html":
            self.root = attrs
        if tag == "label":
            self.depth += 1
            if attrs.get("for"):
                self.labels.add(attrs["for"])
        if tag in ("input", "select", "textarea") and attrs.get("type") not in ("hidden", "submit", "button"):
            self.controls.append((attrs.get("id"), self.depth > 0))

    def handle_endtag(self, tag):
        if tag == "label":
            self.depth = max(0, self.depth - 1)


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.server = Running()
        self.addCleanup(self.server.close)

    # -- helpers ---------------------------------------------------------------
    def entity(self, name):
        return SCHEMA.by_name[name]

    def make(self, entity, n=1, **values):
        refs = {key: value for key, value in values.items() if entity.reference(key)}
        plain = {key: value for key, value in values.items() if not entity.reference(key)}
        return self.server.create(entity, n, refs, **plain)

    def other_value(self, entity, field, value):
        options = [v for v in entity.field(field)["values"] if v != value]
        return options[0]

    def role_for(self, check):
        if check["condition_id"] == "without-session":
            return None
        if check["condition_id"] == "as-role":
            return check["condition"]["role"]
        return ADMIN

    def body_for(self, check, entity, subject=None):
        cond, groups = check["condition_id"], check["condition"]
        partial = check["method"] == "PATCH"
        if partial:
            base = {}
        else:
            refs = {ref["field"]: self.server.create(self.entity(ref["entity"]), 1)["id"]
                    for ref in entity.references if ref.get("required")}
            base = sample(entity, 5, refs)
        if cond == "valid-body":
            if partial:
                fresh = sample(entity, 6)
                return {field["name"]: fresh[field["name"]] for field in entity.fields}
            return base
        if cond == "without-field":
            base.pop(groups["field"], None)
            return base
        if cond in ("field-value", "field-value-while-linked"):
            return {**base, groups["field"]: groups["value"]}
        if cond == "longer-than":
            return {**base, groups["field"]: "x" * (int(groups["n"]) + 1)}
        if cond == "missing-reference":
            return {**base, groups["field"]: MISSING_ID}
        if cond == "duplicate":
            existing = self.make(entity, 7)
            return {**base, groups["field"]: existing[groups["field"]]}
        if cond == "reference-existing":
            target = self.make(self.entity(groups["entity"]), 8)
            return {**base, groups["field"]: target["id"]}
        return base

    def expect_record(self, body, record):
        for key, value in body.items():
            self.assertEqual(record[key], value, key)

    def ordered(self, values):
        present = [value for value in values if value is not None]
        self.assertEqual(present, sorted(present))
        self.assertEqual(values, present + [None] * (len(values) - len(present)))

    # -- routes ----------------------------------------------------------------
    def check_page(self, check):
        status, headers, page = self.server.request(check["method"], check["path"], role=None)
        self.assertEqual(status, check["status"])
        parser = _Inputs()
        parser.feed(page.decode("utf-8"))
        if check["expect_id"] == "html-dir-lang":
            self.assertEqual((parser.root.get("dir"), parser.root.get("lang")),
                             (check["expect"]["dir"], check["expect"]["lang"]))
        elif check["expect_id"] == "html-labels":
            self.assertTrue(parser.controls, "the page has form inputs")
            for control, wrapped in parser.controls:
                self.assertTrue(wrapped or control in parser.labels, f"input {control!r} has no label")

    def check_login(self, check):
        email, password = self.server.account(ADMIN)
        if check["condition_id"] == "wrong-password":
            password += "-wrong"
        status, headers, body = self.server.request("POST", check["path"], {"email": email, "password": password}, role=None)
        self.assertEqual(status, check["status"], body)
        if check["expect_id"] == "session-cookie":
            cookie = headers["set-cookie"]
            jar = http.cookies.SimpleCookie(cookie)
            self.assertTrue(jar["session"].value)
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=Strict", cookie)

    def check_logout(self, check):
        session = self.server.login(ADMIN)
        status, _, _ = self.server.request("POST", check["path"], session=session)
        self.assertEqual(status, check["status"])
        if check["expect_id"] == "session-revoked":
            self.assertEqual(self.server.request("GET", "/api/session", session=session)[0], 401)
            self.assertEqual(self.server.request("GET", "/api/schema", session=session)[0], 401)

    def check_collection(self, check):
        entity = self.entity(check["route"]["entity"])
        role = self.role_for(check)
        if check["method"] == "POST":
            body = self.body_for(check, entity)
            status, _, record = self.server.request("POST", check["path"], body, role=role)
            self.assertEqual(status, check["status"], record)
            if check["expect_id"] == "record":
                self.expect_record(body, record)
            return
        exp, groups = check["expect_id"], check["expect"]
        query = check["query"]
        keep, drop = [], []
        if exp == "lists-created":
            keep = [self.make(entity, n)["id"] for n in (1, 2)]
        elif exp == "only-field-value":
            keep = [self.make(entity, 1, **{groups["field"]: groups["value"]})["id"]]
            drop = [self.make(entity, 2, **{groups["field"]: self.other_value(entity, groups["field"], groups["value"])})["id"]]
        elif exp == "only-assigned":
            target = self.make(self.entity(groups["target"]), 1)
            keep = [self.make(entity, 1, **{groups["fk"]: target["id"]})["id"]]
            drop = [self.make(entity, 2)["id"]]
            query = query.replace("{" + groups["placeholder"] + "}", str(target["id"]))
        elif exp == "only-overdue":
            today = datetime.datetime.now(datetime.timezone.utc).date()
            past, future = (today - datetime.timedelta(days=3)).isoformat(), (today + datetime.timedelta(days=3)).isoformat()
            other = self.other_value(entity, groups["field"], groups["value"])
            keep = [self.make(entity, 1, **{groups["date"]: past, groups["field"]: other})["id"]]
            drop = [self.make(entity, 2, **{groups["date"]: past, groups["field"]: groups["value"]})["id"],
                    self.make(entity, 3, **{groups["date"]: future, groups["field"]: other})["id"],
                    self.make(entity, 4, **{groups["date"]: None, groups["field"]: other})["id"]]
        elif exp == "ordered-nulls-last":
            for n, value in enumerate(("2026-03-01", None, "2026-01-01", "2026-02-01")):
                self.make(entity, n, **{groups["field"]: value})
        path = check["route"]["base"] + ("?" + query if query else "")
        separator = "&" if "?" in path else "?"
        if exp is not None and "limit=" not in query:
            path += f"{separator}limit={MAX}"
        status, _, page = self.server.request("GET", path, role=role)
        self.assertEqual(status, check["status"], page)
        if exp is None:
            return
        ids = [row["id"] for row in page["items"]]
        self.assertTrue(set(keep) <= set(ids), (keep, ids))
        self.assertFalse(set(drop) & set(ids), (drop, ids))
        if exp == "only-field-value":
            self.assertTrue(all(row[groups["field"]] == groups["value"] for row in page["items"]))
        elif exp == "only-assigned":
            self.assertTrue(all(row[groups["fk"]] == int(query.split("=")[-1]) for row in page["items"]))
        elif exp == "only-overdue":
            today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
            self.assertTrue(all(row[groups["date"]] is not None and row[groups["date"]] < today
                                and row[groups["field"]] != groups["value"] for row in page["items"]))
        elif exp == "ordered-nulls-last":
            self.ordered([row[groups["field"]] for row in page["items"]])

    def check_item(self, check):
        entity = self.entity(check["route"]["entity"])
        cond, groups = check["condition_id"], check["condition"]
        subject = None if cond == "unknown-id" else self.make(entity, 1)
        record_id = MISSING_ID if subject is None else subject["id"]
        if cond == "field-value-while-linked":
            child = self.entity(groups["child"])
            value = self.other_value(child, groups["child_field"], groups["child_value"])
            self.make(child, 1, **{groups["fk"]: record_id, groups["child_field"]: value})
        path = check["path"].replace("{id}", str(record_id))
        body = self.body_for(check, entity, subject) if check["method"] in ("PUT", "PATCH") else None
        status, _, record = self.server.request(check["method"], path, body, role=self.role_for(check))
        self.assertEqual(status, check["status"], record)
        if check["expect_id"] == "record":
            self.expect_record(body, record)

    def check_progress(self, check):
        parent = self.entity(check["route"]["entity"])
        rule = check["route"]["rule"]
        child = self.entity(rule["child"])
        subject = self.make(parent, 1)
        expected = {f"total_{rule['key']}": 0, f"done_{rule['key']}": 0, "percent": 0}
        if check["expect_id"] == "progress":
            other = self.other_value(child, rule["field"], rule["done"][0])
            for n, value in enumerate((rule["done"][0], other, other)):
                self.make(child, n, **{rule["fk"]: subject["id"], rule["field"]: value})
            expected = {f"total_{rule['key']}": 3, f"done_{rule['key']}": 1, "percent": 33}
        status, _, body = self.server.request("GET", check["path"].replace("{id}", str(subject["id"])))
        self.assertEqual(status, check["status"], body)
        for key, value in expected.items():
            if check["expect_id"] == "progress" or key == "percent":
                self.assertEqual(body[key], value, key)

    def check_children(self, check):
        parent = self.entity(check["route"]["entity"])
        child = self.entity(check["route"]["child"])
        fk, order = check["route"]["fk"], check["expect"].get("order")
        mine, other = self.make(parent, 1), self.make(parent, 2)
        dates = ("2026-03-01", "2026-01-01", "2026-02-01")
        keep = [self.make(child, n, **{fk: mine["id"], **({order: dates[n]} if order else {})})["id"] for n in range(3)]
        drop = [self.make(child, 4, **{fk: other["id"]})["id"]]
        path = check["path"].replace("{id}", str(mine["id"]))
        status, _, page = self.server.request("GET", path + f"?limit={MAX}")
        self.assertEqual(status, check["status"])
        ids = [row["id"] for row in page["items"]]
        self.assertEqual(sorted(ids), sorted(keep))
        self.assertFalse(set(drop) & set(ids))
        if order:
            self.ordered([row[order] for row in page["items"]])

    def check_link(self, check):
        source = self.entity(check["route"]["entity"])
        link = check["route"]["link"]
        subject = self.make(source, 1)
        target = self.make(self.entity(link["entity"]), 1)
        path = check["path"].replace("{id}", str(subject["id"]))
        body = {link["target_key"]: target["id"]}
        if check["condition_id"] == "link-duplicate":
            self.assertEqual(self.server.request("POST", path, body)[0], 201)
        status, _, reply = self.server.request("POST", path, body)
        self.assertEqual(status, check["status"], reply)
        if check["expect_id"] == "membership":
            self.assertEqual(reply, {link["source_key"]: subject["id"], link["target_key"]: target["id"]})


def _bind(check):
    def test(self):
        getattr(self, "check_" + check["route"]["kind"])(check)
    test.__doc__ = check["criterion"]
    return test


for _check in CHECKS:
    setattr(AcceptanceTests, _check["test"], _bind(_check))


if __name__ == "__main__":
    unittest.main()
