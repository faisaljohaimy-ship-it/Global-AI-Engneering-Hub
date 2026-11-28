"""API integration tests: the real HTTP server on a free loopback port, generated per entity."""
import hashlib
import pathlib
import re
import secrets
import tempfile
import time
import unittest

from tests.support import ADMIN, SCHEMA, Running, sample
from app import db, model, seed as seeding

LIMITS = SCHEMA.limits
METHOD_NEED = (("GET", "read"), ("POST", "write"), ("DELETE", "delete"))
# "rate limit on sign-in (5 failures per 15 minutes)": the numbers test_login_lockout proves
# (the build engine maps that statement to the test only with these numbers)
STATED_SIGNIN_LIMIT = (5, 15 * 60)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Running()

    @classmethod
    def tearDownClass(cls):
        cls.server.close()

    def call(self, *args, **kwargs):
        return self.server.request(*args, **kwargs)

    def path(self, entity, record_id=None):
        base = f"/api/{entity.collection}"
        return base if record_id is None else f"{base}/{record_id}"

    def parents(self, entity, n=1):
        return {ref["field"]: self.server.create(SCHEMA.by_name[ref["entity"]], n)["id"] for ref in entity.references}

    # -- per-entity checks -----------------------------------------------------
    def _create(self, entity):
        body = sample(entity, 3, self.parents(entity))
        status, headers, record = self.call("POST", self.path(entity), body)
        self.assertEqual(status, 201, record)
        self.assertEqual(headers["location"], self.path(entity, record["id"]))
        for key, value in body.items():
            self.assertEqual(record[key], value, key)
        self.assertRegex(record["created_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertNotIn("created_by", record)

    def _list(self, entity):
        created = [self.server.create(entity, n, self.parents(entity))["id"] for n in (4, 5)]
        status, _, page = self.call("GET", self.path(entity) + f"?limit={LIMITS['max_page_size']}&sort=-id")
        self.assertEqual(status, 200)
        self.assertTrue(set(created) <= {item["id"] for item in page["items"]})
        status, _, page = self.call("GET", self.path(entity) + "?limit=1&offset=0")
        self.assertEqual((status, len(page["items"]), page["limit"]), (200, 1, 1))

    def _get(self, entity):
        record = self.server.create(entity, 6, self.parents(entity))
        status, _, fetched = self.call("GET", self.path(entity, record["id"]))
        self.assertEqual((status, fetched), (200, record))

    def _update(self, entity):
        record = self.server.create(entity, 7, self.parents(entity))
        body = sample(entity, 8, {ref["field"]: record[ref["field"]] for ref in entity.references})
        status, _, updated = self.call("PUT", self.path(entity, record["id"]), body)
        self.assertEqual(status, 200, updated)
        for key, value in body.items():
            self.assertEqual(updated[key], value, key)
        status, _, error = self.call("PUT", self.path(entity, record["id"]), {"__unknown__": 1})
        self.assertEqual((status, error["error"]["code"]), (400, "validation_failed"))
        self.assertEqual(self.call("PUT", self.path(entity, 999999999), body)[0], 404)

    def _patch(self, entity):
        record = self.server.create(entity, 7, self.parents(entity))
        field = entity.fields[0]
        change = {field["name"]: sample(entity, 9)[field["name"]]}
        status, _, updated = self.call("PATCH", self.path(entity, record["id"]), change)
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated[field["name"]], model.check_value(field, change[field["name"]], LIMITS))
        for other in entity.columns[1:]:
            self.assertEqual(updated[other], record[other], other)
        status, _, error = self.call("PATCH", self.path(entity, record["id"]), {"id": 5})
        self.assertEqual((status, error["error"]["fields"]), (400, {"id": "read_only"}))
        self.assertEqual(self.call("PATCH", self.path(entity, 999999999), change)[0], 404)

    def _delete(self, entity):
        record = self.server.create(entity, 9, self.parents(entity))
        status, _, body = self.call("DELETE", self.path(entity, record["id"]))
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(self.call("GET", self.path(entity, record["id"]))[0], 404)
        self.assertEqual(self.call("DELETE", self.path(entity, record["id"]))[0], 404)

    def _validation(self, entity):
        status, _, error = self.call("POST", self.path(entity), {"__unknown__": "x"})
        self.assertEqual(status, 400)
        self.assertEqual(error["error"]["code"], "validation_failed")
        self.assertEqual(error["error"]["fields"]["__unknown__"], "unknown_field")
        required = [f["name"] for f in entity.fields if f.get("required") and "default" not in f]
        required += [ref["field"] for ref in entity.references if ref.get("required")]
        for name in required:
            self.assertEqual(error["error"]["fields"].get(name), "required", name)
        before = self.call("GET", self.path(entity) + "?limit=1")[2]["total"]
        for field in entity.fields:
            body = sample(entity, 1, self.parents(entity))
            body[field["name"]] = [] if field["type"] != "text" else "x" * (field.get("max", LIMITS["max_text"]) + 1)
            status, _, error = self.call("POST", self.path(entity), body)
            self.assertEqual(status, 400, field["name"])
            self.assertIn(field["name"], error["error"]["fields"])
        self.assertEqual(self.call("GET", self.path(entity) + "?limit=1")[2]["total"], before)
        self._validation_on_update(entity, required)

    def _validation_on_update(self, entity, required):
        """PUT (full body) and PATCH (merged over the stored record) validate exactly like POST and
        change nothing when they are refused."""
        record = self.server.create(entity, 1, self.parents(entity))
        path = self.path(entity, record["id"])
        refs = {ref["field"]: record[ref["field"]] for ref in entity.references}
        for method in ("PUT", "PATCH"):
            status, _, error = self.call(method, path, {"__unknown__": "x", "id": 5, "created_by": 1})
            self.assertEqual((status, error["error"]["code"]), (400, "validation_failed"), method)
            self.assertEqual({key: error["error"]["fields"].get(key) for key in ("__unknown__", "id", "created_by")},
                             {"__unknown__": "unknown_field", "id": "read_only", "created_by": "read_only"}, method)
            for name in required:
                self.assertEqual(error["error"]["fields"].get(name), "required" if method == "PUT" else None, (method, name))
            for field in entity.fields:
                bad = [] if field["type"] != "text" else "x" * (field.get("max", LIMITS["max_text"]) + 1)
                body = {**sample(entity, 2, refs), field["name"]: bad} if method == "PUT" else {field["name"]: bad}
                status, _, error = self.call(method, path, body)
                self.assertEqual((status, error["error"]["code"]), (400, "validation_failed"), (method, field["name"]))
                self.assertIn(field["name"], error["error"]["fields"], method)
                if field.get("required"):
                    status, _, error = self.call(method, path, {**body, field["name"]: None})
                    self.assertEqual((status, error["error"]["fields"].get(field["name"])), (400, "required"),
                                     (method, field["name"]))
            for ref in entity.references:
                status, _, error = self.call("PATCH", path, {ref["field"]: "1"})
                self.assertEqual((status, error["error"]["fields"].get(ref["field"])), (400, "type"), ref["field"])
        self.assertEqual(self.call("GET", path)[2], record, "a refused update changes nothing")

    def _not_found(self, entity):
        for path in (self.path(entity, 999999999), self.path(entity) + "/0", self.path(entity) + "/abc",
                     self.path(entity) + "/1/nothing-here"):
            status, _, error = self.call("GET", path)
            self.assertEqual(status, 404, path)
            self.assertIn(error["error"]["code"], ("not_found",))

    # -- relations -------------------------------------------------------------
    def _reference_missing(self, entity, ref):
        refs = self.parents(entity)
        refs[ref["field"]] = 999999999
        status, _, error = self.call("POST", self.path(entity), sample(entity, 2, refs))
        self.assertEqual(status, 400, error)
        self.assertEqual(error["error"]["fields"], {ref["field"]: "not_found"})

    def _reference_delete_parent(self, entity, ref):
        parent_entity = SCHEMA.by_name[ref["entity"]]
        child = self.server.create(entity, 2, self.parents(entity))
        parent_id = child[ref["field"]]
        status, _, body = self.call("DELETE", self.path(parent_entity, parent_id))
        if ref.get("required"):
            self.assertEqual(status, 409, body)
            self.assertEqual(body["error"]["code"], "has_dependents")
            self.assertGreaterEqual(body["error"]["dependents"][entity.name], 1)
            self.assertEqual(self.call("DELETE", self.path(entity, child["id"]))[0], 204)
            self.assertEqual(self.call("DELETE", self.path(parent_entity, parent_id))[0], 204)
        else:
            self.assertIn(status, (204, 409), body)
            if status == 204:
                self.assertIsNone(self.call("GET", self.path(entity, child["id"]))[2][ref["field"]])

    def _unique(self, entity, field):
        first = self.server.create(entity, 1, self.parents(entity))
        body = sample(entity, 2, self.parents(entity), **{field["name"]: first[field["name"]]})
        status, _, error = self.call("POST", self.path(entity), body)
        self.assertEqual((status, error["error"]["fields"]), (409, {field["name"]: "duplicate"}))
        second = self.server.create(entity, 3, self.parents(entity))
        status, _, _ = self.call("PATCH", self.path(entity, second["id"]), {field["name"]: first[field["name"]]})
        self.assertEqual(status, 409)

    def _links(self, entity, link):
        source = self.server.create(entity, 1, self.parents(entity))
        target = self.server.create(SCHEMA.by_name[link["entity"]], 1)
        path = f"{self.path(entity, source['id'])}/{link['segment']}"
        status, _, body = self.call("POST", path, {link["target_key"]: target["id"]})
        self.assertEqual((status, body), (201, {link["source_key"]: source["id"], link["target_key"]: target["id"]}))
        self.assertEqual(self.call("POST", path, {link["target_key"]: target["id"]})[0], 409)
        self.assertEqual(self.call("POST", path, {link["target_key"]: 999999999})[0], 400)
        self.assertEqual(self.call("POST", path, {"other": 1})[0], 400)
        status, _, listing = self.call("GET", path)
        self.assertEqual((status, [row["id"] for row in listing["items"]]), (200, [target["id"]]))
        status, _, error = self.call("DELETE", f"{path}/{target['id']}", headers={"Origin": "https://attacker.example"})
        self.assertEqual((status, error["error"]["code"]), (403, "cross_origin"))
        self.assertEqual(self.call("DELETE", f"{path}/{target['id']}", csrf=False)[0], 403)
        self.assertEqual(self.call("DELETE", f"{path}/{target['id']}")[0], 204)
        self.assertEqual(self.call("DELETE", f"{path}/{target['id']}")[0], 404)
        self.assertEqual(self.call("GET", f"{self.path(entity, 999999999)}/{link['segment']}")[0], 404)
        self._link_permissions(entity, link)

    # -- helpers for per-role checks --------------------------------------------
    def _role_account(self, role):
        """A fresh signed-in account with `role`: (session, account id, its principal record or None)."""
        email = f"{role}.{time.time_ns()}@example.invalid"
        session = self.server.login(role, email=email)
        with db.session(self.server.db_path) as connection:
            account_id = db.account_by_email(connection, email)["id"]
        principal, me = SCHEMA.auth.get("principal"), None
        if principal:
            person = SCHEMA.by_name[principal["entity"]]
            me = self.server.create(person, 1, self.parents(person), **{principal["email_field"]: email})
        return session, account_id, me

    def _reach(self, entity, record, me):
        """Make `record` of the scoped entity visible to the account whose principal is `me`."""
        scoping = SCHEMA.auth.get("scoping")
        if scoping and me is not None and entity.name == scoping["entity"]:
            link = next(item for item in entity.links if item["link_table"] == scoping["link_table"])
            self.assertEqual(self.call("POST", f"{self.path(entity, record['id'])}/{link['segment']}",
                                       {link["target_key"]: me["id"]})[0], 201)

    def _own(self, entity, record, account_id):
        """Mark `record` as created by the account (what POST as that account records)."""
        with db.session(self.server.db_path) as connection:
            connection.execute("UPDATE " + db.ident(entity.table) + " SET created_by = ? WHERE id = ?",
                               (account_id, record["id"]))

    def _readable(self, entity, records, session):
        """Ids among `records` that GET /api/<collection>/{id} returns to this session."""
        return {row["id"] for row in records if self.call("GET", self.path(entity, row["id"]), session=session)[0] == 200}

    def _leads_to(self, entity, root, seen=frozenset()):
        """True when a chain of references leads from `entity` to the entity `root`."""
        return entity is root or any(self._leads_to(SCHEMA.by_name[ref["entity"]], root, seen | {entity.name})
                                     for ref in entity.references if ref["entity"] not in seen | {entity.name}
                                     or ref["entity"] == root.name)

    def _under(self, entity, root, root_id, n, seen=frozenset()):
        """A record of `entity` whose every reference chain leading to `root` ends at record `root_id`
        (for example a comment on a task of that project); other required parents are fresh."""
        refs = {}
        for ref in entity.references:
            parent = SCHEMA.by_name[ref["entity"]]
            if parent is root:
                refs[ref["field"]] = root_id
            elif parent.name not in seen | {entity.name} and self._leads_to(parent, root):
                refs[ref["field"]] = self._under(parent, root, root_id, n, seen | {entity.name})["id"]
        return self.server.create(entity, n, refs)

    def _non_admin_roles(self):
        return [(role, frozenset(perms)) for role, perms in sorted(SCHEMA.auth["roles"].items()) if "*" not in perms]

    def _link_permissions(self, entity, link):
        """Every non-admin role: adding a link needs write on the parent record, removing one needs
        write and delete; a :own permission covers only parent records the account created. Listing
        the links is readable exactly when the parent is and shows only targets the role can read."""
        target_entity = SCHEMA.by_name[link["entity"]]
        for role, permissions in self._non_admin_roles():
            session, account_id, me = self._role_account(role)
            write, remove = model.allowed(permissions, "write"), model.allowed(permissions, "delete")
            for owned in (False, True):
                source = self.server.create(entity, 1, self.parents(entity))
                if owned:
                    self._own(entity, source, account_id)
                self._reach(entity, source, me)
                path = f"{self.path(entity, source['id'])}/{link['segment']}"
                kept = self.server.create(target_entity, 2, self.parents(target_entity))
                self.assertEqual(self.call("POST", path, {link["target_key"]: kept["id"]})[0], 201)
                added = self.server.create(target_entity, 3, self.parents(target_entity))
                with db.session(self.server.db_path) as connection:
                    scope = db.Scope(SCHEMA, {"id": account_id, "role": role}, me["id"] if me else None)
                    source_seen = db.visible(connection, entity, source["id"], scope)
                    added_seen = db.visible(connection, target_entity, added["id"], scope)
                if write is None:
                    add_status = 403
                elif not source_seen:
                    add_status = 404
                elif write == "own" and not owned:
                    add_status = 403
                else:
                    add_status = 201 if added_seen else 400
                if None in (write, remove):
                    remove_status = 403
                elif not source_seen:
                    remove_status = 404
                else:
                    remove_status = 403 if "own" in (write, remove) and not owned else 204
                case = (role, "own record" if owned else "another account's record")
                status, _, reply = self.call("POST", path, {link["target_key"]: added["id"]}, session=session)
                self.assertEqual(status, add_status, (case, reply))
                status, _, reply = self.call("DELETE", f"{path}/{kept['id']}", session=session)
                self.assertEqual(status, remove_status, (case, reply))
                linked = self.call("GET", path)[2]["items"]
                listed = {row["id"] for row in linked}
                self.assertEqual((added["id"] in listed, kept["id"] in listed), (add_status == 201, remove_status != 204),
                                 case)
                status, _, page = self.call("GET", path, session=session)
                self.assertEqual(status, self.call("GET", self.path(entity, source["id"]), session=session)[0], case)
                if status == 200:
                    self.assertEqual({row["id"] for row in page["items"]}, self._readable(target_entity, linked, session),
                                     case)

    def _children(self, parent, child):
        entity = child["entity"]
        mine = self.server.create(parent, 1, self.parents(parent))
        other = self.server.create(parent, 2, self.parents(parent))
        refs = self.parents(entity)
        inside = [self.server.create(entity, n, {**refs, child["field"]: mine["id"]})["id"] for n in (1, 2)]
        outside = self.server.create(entity, 3, {**refs, child["field"]: other["id"]})["id"]
        status, _, page = self.call("GET", f"{self.path(parent, mine['id'])}/{child['collection']}?limit={LIMITS['max_page_size']}")
        self.assertEqual(status, 200)
        ids = {row["id"] for row in page["items"]}
        self.assertTrue(set(inside) <= ids)
        self.assertNotIn(outside, ids)
        self.assertTrue(all(row[child["field"]] == mine["id"] for row in page["items"]))
        self._children_for_roles(parent, child)

    def _children_for_roles(self, parent, child):
        """Every non-admin role: a child listing is readable exactly when the parent record is and
        lists exactly the children the role can read directly (read:own and scoping included)."""
        entity = child["entity"]
        for role, _ in self._non_admin_roles():
            session, account_id, me = self._role_account(role)
            for owned in (False, True):
                record = self.server.create(parent, 1, self.parents(parent))
                if owned:
                    self._own(parent, record, account_id)
                self._reach(parent, record, me)
                refs = self.parents(entity)
                kids = [self.server.create(entity, n, {**refs, child["field"]: record["id"]}) for n in (1, 2)]
                self._own(entity, kids[1], account_id)
                case = (role, "own record" if owned else "another account's record")
                status, _, page = self.call("GET", f"{self.path(parent, record['id'])}/{child['collection']}"
                                                   f"?limit={LIMITS['max_page_size']}", session=session)
                self.assertEqual(status, self.call("GET", self.path(parent, record["id"]), session=session)[0], case)
                if status == 200:
                    self.assertEqual({row["id"] for row in page["items"]}, self._readable(entity, kids, session), case)

    # -- authentication, authorization and security ---------------------------
    def test_health(self):
        self.assertEqual(self.call("GET", "/api/health", role=None)[:3:2], (200, {"ok": True}))
        status, _, schema = self.call("GET", "/api/schema")
        self.assertEqual((status, [e["name"] for e in schema["entities"]]), (200, [e.name for e in SCHEMA.entities]))

    def test_unauthenticated_requests_refused(self):
        entity = SCHEMA.entities[0]
        routes = [("GET", "/api/schema"), ("GET", self.path(entity)), ("POST", self.path(entity)),
                  ("GET", self.path(entity, 1)), ("PUT", self.path(entity, 1)), ("PATCH", self.path(entity, 1)),
                  ("DELETE", self.path(entity, 1)), ("GET", "/api/session"), ("POST", "/api/logout"),
                  ("GET", "/api/does-not-exist")]
        for parent in SCHEMA.entities:
            item = self.path(parent, 1)
            for link in parent.links:
                routes += [("GET", f"{item}/{link['segment']}"), ("POST", f"{item}/{link['segment']}"),
                           ("DELETE", f"{item}/{link['segment']}/1")]
            routes += [("GET", f"{item}/{child['collection']}") for child in parent.children]
            if any(rule["parent"] == parent.name for rule in SCHEMA.rules.get("progress", [])):
                routes.append(("GET", f"{item}/progress"))
        for method, path in routes:
            status, _, body = self.call(method, path, {} if method in ("POST", "PUT", "PATCH") else None, role=None)
            self.assertEqual((status, body["error"]["code"]), (401, "unauthenticated"), (method, path))
        bogus = {"cookie": "session=forged-token-value", "csrf": "x"}
        self.assertEqual(self.call("GET", self.path(entity), session=bogus)[0], 401)

    def test_role_check_on_every_endpoint(self):
        record = {entity.name: self.server.create(entity, 1, self.parents(entity)) for entity in SCHEMA.entities}
        for role, permissions in sorted(SCHEMA.auth["roles"].items()):
            granted = frozenset(permissions)
            for entity in SCHEMA.entities:
                for method, need in METHOD_NEED:
                    path = self.path(entity, 999999999) if method == "DELETE" else self.path(entity)
                    body = sample(entity, 1, {r["field"]: record[r["entity"]]["id"] for r in entity.references}) \
                        if method == "POST" else None
                    status, _, reply = self.call(method, path, body, role=role)
                    if model.allowed(granted, need) is None:
                        self.assertEqual((status, reply["error"]["code"]), (403, "forbidden"), (role, method, entity.name))
                    else:
                        self.assertNotIn(status, (401, 403), (role, method, entity.name, reply))
        self._item_writes_for_roles()

    def _reachable(self, entity, me, n):
        """A record of `entity` created by the administrator that the account whose principal is `me`
        may see (scoping included): a reached scoped record, or one under a reached scoped record."""
        scoping = SCHEMA.auth.get("scoping")
        root = SCHEMA.by_name[scoping["entity"]] if scoping else None
        if root is None or not self._leads_to(entity, root):
            return self.server.create(entity, n, self.parents(entity))
        top = self.server.create(root, n, self.parents(root))
        self._reach(root, top, me)
        return top if entity is root else self._under(entity, root, top["id"], n)

    def _item_writes_for_roles(self):
        """Every non-admin role on every entity: PUT, PATCH and DELETE of a record it can see need the
        role's write/delete permission, and a :own permission covers only records the account created."""
        principal = SCHEMA.auth.get("principal") or {}
        decided = 0
        for role, permissions in self._non_admin_roles():
            session, account_id, me = self._role_account(role)
            scope = db.Scope(SCHEMA, {"id": account_id, "role": role}, me["id"] if me else None)
            for entity in SCHEMA.entities:
                keep = principal.get("email_field") if entity.name == principal.get("entity") else None
                for owned in (False, True):
                    record = self._reachable(entity, me, 2 + owned)
                    if owned:
                        self._own(entity, record, account_id)
                    with db.session(self.server.db_path) as connection:
                        seen = db.visible(connection, entity, record["id"], scope)
                    field = next(f for f in entity.fields if f["name"] != keep)
                    refs = {ref["field"]: record[ref["field"]] for ref in entity.references}
                    bodies = {"PUT": sample(entity, 8, refs, **({keep: record[keep]} if keep else {})),
                              "PATCH": {field["name"]: sample(entity, 9)[field["name"]]}, "DELETE": None}
                    for method, need, done in (("PUT", "write", 200), ("PATCH", "write", 200), ("DELETE", "delete", 204)):
                        mode = model.allowed(permissions, need)
                        if mode is None or (seen and mode == "own" and not owned):
                            expected = (403, "forbidden")
                        else:
                            expected = (done, None) if seen else (404, "not_found")
                        decided += bool(seen and mode)
                        status, _, reply = self.call(method, self.path(entity, record["id"]), bodies[method],
                                                     session=session)
                        code = reply["error"]["code"] if isinstance(reply, dict) and "error" in reply else None
                        self.assertEqual((status, code), expected, (role, method, entity.name, owned, reply))
                    gone = self.call("GET", self.path(entity, record["id"]))[0] == 404
                    self.assertEqual(gone, expected == (204, None), (role, entity.name, owned))
        self.assertTrue(decided or not self._non_admin_roles(), "no role reached an ownership decision")

    def test_csrf_token_required(self):
        entity = SCHEMA.entities[0]
        body = sample(entity, 1, self.parents(entity))
        status, _, error = self.call("POST", self.path(entity), body, csrf=False)
        self.assertEqual((status, error["error"]["code"]), (403, "csrf"))
        status, _, _ = self.call("POST", self.path(entity), body, headers={"X-CSRF-Token": "wrong"})
        self.assertEqual(status, 403)
        other = self.server.login(ADMIN)
        status, _, _ = self.call("POST", self.path(entity), body, session={**other, "csrf": self.server.session(ADMIN)["csrf"]})
        self.assertEqual(status, 403, "a CSRF token is bound to its own session")
        self.assertEqual(self.call("POST", self.path(entity), body)[0], 201)

    def test_login_logout_cycle(self):
        email, password = self.server.account(ADMIN)
        status, headers, body = self.call("POST", "/api/login", {"email": email, "password": password}, role=None)
        self.assertEqual(status, 200)
        cookie = headers["set-cookie"]
        for flag in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, cookie)
        self.assertNotIn(password, cookie)
        self.assertEqual(body["account"], {"email": email, "role": ADMIN})
        session = {"cookie": cookie.split(";")[0], "csrf": body["csrf_token"]}
        self.assertEqual(self.call("GET", "/api/session", session=session)[0], 200)
        self.assertEqual(self.call("POST", "/api/logout", session=session)[0], 204)
        self.assertEqual(self.call("GET", "/api/session", session=session)[0], 401)
        for wrong in ({"email": email, "password": password + "x"}, {"email": "nobody@example.invalid", "password": password},
                      {"email": email}, {"email": email, "password": password, "role": "admin"}):
            self.assertIn(self.call("POST", "/api/login", wrong, role=None)[0], (400, 401), wrong)
        status, _, error = self.call("POST", "/api/login", {"email": email, "password": password}, role=None,
                                     headers={"Origin": "https://attacker.example"})
        self.assertEqual((status, error["error"]["code"]), (403, "cross_origin"))

    def test_login_lockout(self):
        """One e-mail from one client address: exactly 5 failed sign-ins are checked in any 15 minutes
        (sliding window); per client address and per e-mail across addresses, a ceiling."""
        from app import auth
        failures, window = STATED_SIGNIN_LIMIT
        self.assertEqual((auth.LOCKOUT_FAILURES, auth.LOCKOUT_SECONDS), (failures, window))
        email, password = self.server.account(ADMIN)
        for _ in range(failures):
            self.assertEqual(self.call("POST", "/api/login", {"email": email, "password": "wrong-" + password}, role=None)[0], 401)
        status, headers, error = self.call("POST", "/api/login", {"email": email, "password": password}, role=None)
        self.assertEqual((status, error["error"]["code"]), (429, "too_many_attempts"))
        self.assertRegex(headers.get("retry-after", ""), r"^[1-9][0-9]*$")
        self.assertLessEqual(int(headers["retry-after"]), window)
        sessions, now = auth.Sessions(SCHEMA), [1000.0]
        sessions.clock = lambda: now[0]
        calls, original = [], auth.hash_password
        auth.hash_password = lambda *args, **kwargs: calls.append(args[1]) or original(*args, **kwargs)

        def attempt(who, secret, source, at=None):
            """(status, hashes computed, Retry-After) of one sign-in through Sessions.login at time `at`."""
            if at is not None:
                now[0] = 1000.0 + at
            del calls[:]
            try:
                sessions.login(connection, who, secret, source=source)
                return 200, len(calls), None
            except auth.AuthError as error:
                return error.status, len(calls), error.retry_after
        email, password = self.server.account(ADMIN)
        target, secret = self.server.account(ADMIN)
        try:
            with db.session(self.server.db_path) as connection:
                # one wrong password per second for 30 minutes: exactly `failures` are checked in each window
                checked, refused = [], []
                for second in range(2 * window):
                    status, hashes, retry = attempt(email, "wrong-" + password, "198.51.100.7", at=second)
                    if status == 401:
                        checked.append(second)
                        self.assertEqual(hashes, 1)
                    else:
                        refused.append((status, hashes, retry, second))
                self.assertEqual(checked, list(range(failures)) + [window + n for n in range(failures)])
                for status, hashes, retry, second in refused:  # refused until the oldest failure is `window` old
                    self.assertEqual((status, hashes, retry), (429, 0, (window if second < window else 2 * window) - second))
                self.assertEqual(attempt(email, password, "198.51.100.7", at=2 * window - 1)[:2], (429, 0),
                                 "the right password is not checked while the window is full")
                self.assertEqual(attempt(email, password, "203.0.113.9")[0], 200, "another address is not refused")
                self.assertEqual(attempt(email, password, "198.51.100.7", at=2 * window)[0], 200)
                # the window slides: failures spread over 15 minutes still count together
                start = 3 * window
                for n in range(failures):
                    self.assertEqual(attempt(email, "wrong-" + password, "198.51.100.8", at=start + n * 200)[0], 401)
                self.assertEqual(attempt(email, password, "198.51.100.8", at=start + window - 50)[::2], (429, 50))
                self.assertEqual(attempt(email, "wrong-" + password, "198.51.100.8", at=start + window)[0], 401)
                self.assertEqual(attempt(email, password, "198.51.100.8", at=start + window + 1)[::2], (429, 199))
                # an unknown e-mail costs the same PBKDF2 work as a wrong password, and is counted the same
                stranger = f"nobody.{time.time_ns()}@example.invalid"
                for n in range(failures):
                    self.assertEqual(attempt(stranger, password, "x")[:2], (401, 1))
                    self.assertEqual(calls, [SCHEMA.auth["pbkdf2_iterations"]])
                self.assertEqual(attempt(stranger, password, "x")[:2], (429, 0))
                # one address rotating e-mails: ADDRESS_FAILURES failures, then refused before hashing
                now[0] += window
                auth.hash_password = lambda *args, **kwargs: calls.append(args[1]) or ("", "")
                for n in range(auth.ADDRESS_FAILURES):
                    self.assertEqual(attempt(f"spray.{n}@example.invalid", password, "192.0.2.1")[:2], (401, 1), n)
                self.assertEqual(attempt("spray.next@example.invalid", password, "192.0.2.1")[:2], (429, 0))
                self.assertEqual(attempt(email, "wrong-" + password, "192.0.2.2")[0], 401)
                # one e-mail from many addresses: ACCOUNT_FAILURES failures in all, then every address waits
                # except one that signed in to it before (it keeps its own pair and address limits)
                auth.hash_password = original
                self.assertEqual(attempt(target, secret, "198.20.0.1")[0], 200)
                for n in range(auth.ACCOUNT_FAILURES):
                    source = f"198.18.{n // failures}.1"
                    self.assertEqual(attempt(target.upper() if n % 2 else target, password, source)[0], 401, n)
                self.assertEqual(attempt(target, secret, "198.19.0.1")[:2], (429, 0), "the ceiling holds new addresses")
                self.assertEqual(attempt(target, secret, "198.20.0.1")[0], 200, "a known address is not held")
                for _ in range(failures):
                    self.assertEqual(attempt(target, "wrong-" + secret, "198.20.0.1")[0], 401)
                self.assertEqual(attempt(target, secret, "198.20.0.1")[:2], (429, 0), "but keeps its own pair limit")
                now[0] += window
                self.assertEqual(attempt(target, secret, "198.19.0.1")[0], 200, "the ceiling expires")
        finally:
            auth.hash_password = original
        for n in range(auth.MAX_TRACKED + 5):
            sessions._admit(sessions._keys(f"user{n}@example.invalid", f"10.{n // 65536}.{n // 256 % 256}.{n % 256}"))
        self.assertTrue(all(len(table) <= auth.MAX_TRACKED for table in sessions._failures.values()))

    def test_passwords_are_salted_pbkdf2(self):
        password = secrets.token_urlsafe(24)
        iterations = SCHEMA.auth["pbkdf2_iterations"]
        self.assertGreaterEqual(iterations, 600000)
        rows = []
        with db.session(self.server.db_path) as connection:
            for n in (1, 2):
                email = f"pbkdf2.{n}.{time.time_ns()}@example.invalid"
                from app import auth
                auth.create_account(connection, SCHEMA, email, ADMIN, password)
                rows.append(dict(db.account_by_email(connection, email)))
        for row in rows:
            self.assertEqual(row["password_iterations"], iterations)
            self.assertRegex(row["password_salt"], r"^[0-9a-f]{32}$")
            expected = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(row["password_salt"]), iterations).hex()
            self.assertEqual(row["password_hash"], expected)
            self.assertNotIn(password, "".join(str(value) for value in row.values()))
        self.assertNotEqual(rows[0]["password_salt"], rows[1]["password_salt"])
        self.assertNotEqual(rows[0]["password_hash"], rows[1]["password_hash"])

    def test_scoped_roles_see_only_their_records(self):
        config = SCHEMA.auth.get("scoping")
        if not config:
            self.assertIsNone(SCHEMA.auth.get("principal"))
            return
        scoped = SCHEMA.by_name[config["entity"]]
        principal = SCHEMA.by_name[SCHEMA.auth["principal"]["entity"]]
        role = next(r for r, perms in sorted(SCHEMA.auth["roles"].items()) if "*" not in perms and model.allowed(perms, "read"))
        email = f"scoped.{time.time_ns()}@example.invalid"
        session = self.server.login(role, email=email)
        member = self.server.create(principal, 1, **{SCHEMA.auth["principal"]["email_field"]: email})
        mine, theirs = (self.server.create(scoped, n, self.parents(scoped)) for n in (1, 2))
        link = next(item for item in scoped.links if item["link_table"] == config["link_table"])
        self.assertEqual(self.call("POST", f"{self.path(scoped, mine['id'])}/{link['segment']}",
                                   {link["target_key"]: member["id"]})[0], 201)
        status, _, page = self.call("GET", self.path(scoped) + f"?limit={LIMITS['max_page_size']}", session=session)
        self.assertEqual(status, 200)
        self.assertEqual({row["id"] for row in page["items"]}, {mine["id"]})
        self.assertEqual(self.call("GET", self.path(scoped, theirs["id"]), session=session)[0], 404)
        self.assertEqual(self.call("GET", self.path(scoped, mine["id"]), session=session)[0], 200)
        for child in SCHEMA.entities:
            if child is scoped or not self._leads_to(child, scoped):
                continue
            visible = self._under(child, scoped, mine["id"], 1)
            hidden = self._under(child, scoped, theirs["id"], 2)
            status, _, page = self.call("GET", self.path(child) + f"?limit={LIMITS['max_page_size']}", session=session)
            ids = {row["id"] for row in page["items"]}
            self.assertIn(visible["id"], ids)
            self.assertNotIn(hidden["id"], ids)
            self.assertEqual(self.call("GET", self.path(child, hidden["id"]), session=session)[0], 404)
        # the principal e-mail identifies the account: a role without '*' cannot re-point it
        field = SCHEMA.auth["principal"]["email_field"]
        other = self.server.create(principal, 2)
        self.assertEqual(self.call("POST", f"{self.path(scoped, theirs['id'])}/{link['segment']}",
                                   {link["target_key"]: other["id"]})[0], 201)
        for record, value in ((member, f"spare.{time.time_ns()}@example.invalid"), (other, email)):
            status, _, reply = self.call("PATCH", self.path(principal, record["id"]), {field: value}, session=session)
            self.assertEqual(status, 403, reply)
        status, _, page = self.call("GET", self.path(scoped) + f"?limit={LIMITS['max_page_size']}", session=session)
        self.assertEqual((status, {row["id"] for row in page["items"]}), (200, {mine["id"]}))
        self.assertEqual(self.call("PATCH", self.path(principal, member["id"]),
                                   {field: f"moved.{time.time_ns()}@example.invalid"})[0], 200, "an administrator may")
        status, _, page = self.call("GET", self.path(scoped) + f"?limit={LIMITS['max_page_size']}", session=session)
        self.assertEqual((status, page["items"]), (200, []))
        self.assertEqual(self.call("GET", self.path(scoped, mine["id"]), role=ADMIN)[0], 200)
        self.assertEqual(self.call("GET", self.path(scoped, theirs["id"]), role=ADMIN)[0], 200)

    def test_progress_uses_one_aggregate_query(self):
        for rule in SCHEMA.rules.get("progress", []):
            parent = SCHEMA.by_name[rule["parent"]]
            record = self.server.create(parent, 1, self.parents(parent))
            statements = []
            connection = db.connect(self.server.db_path)
            try:
                connection.set_trace_callback(statements.append)
                result = db.progress(connection, SCHEMA, rule, record["id"])
            finally:
                connection.close()
            self.assertEqual(result["percent"], 0)
            self.assertEqual(len([s for s in statements if s.lstrip().upper().startswith("SELECT")]), 1, statements)
            child = SCHEMA.by_name[rule["child"]]
            for role, _ in self._non_admin_roles():
                session, account_id, me = self._role_account(role)
                for owned in (False, True):
                    record = self.server.create(parent, 1, self.parents(parent))
                    if owned:
                        self._own(parent, record, account_id)
                    self._reach(parent, record, me)
                    refs = {**self.parents(child), rule["fk"]: record["id"]}
                    kids = [self.server.create(child, n, refs) for n in (1, 2)]
                    self._own(child, kids[1], account_id)
                    case = (role, "own record" if owned else "another account's record")
                    status, _, body = self.call("GET", f"{self.path(parent, record['id'])}/progress", session=session)
                    self.assertEqual(status, self.call("GET", self.path(parent, record["id"]), session=session)[0], case)
                    if status == 200:
                        self.assertEqual(body[f"total_{rule['key']}"], len(self._readable(child, kids, session)), case)

    def test_security_headers(self):
        for path, role in (("/", None), ("/static/app.js", None), ("/api/health", None), ("/api/nope", None),
                           ("/api/schema", ADMIN)):
            _, headers, _ = self.call("GET", path, role=role)
            policy = headers["content-security-policy"]
            self.assertIn("frame-ancestors 'none'", policy, path)
            self.assertIn("default-src 'self'", policy, path)
            self.assertNotIn("unsafe-inline", policy)
            self.assertNotIn("unsafe-eval", policy)
            self.assertEqual(headers["x-content-type-options"], "nosniff")
            self.assertEqual(headers["x-frame-options"], "DENY")
            self.assertEqual(headers["referrer-policy"], "no-referrer")
            self.assertNotIn("access-control-allow-origin", headers)
            self.assertNotIn("python", headers.get("server", "").lower())

    def test_pages_follow_requested_locale(self):
        directions = {"ar": "rtl", "en": "ltr"}
        for locale in SCHEMA.app["locales"]:
            status, _, page = self.call("GET", f"/?lang={locale}", role=None)
            self.assertEqual(status, 200)
            self.assertIn(f'<html lang="{locale}" dir="{directions[locale]}">', page.decode("utf-8"))
        default = SCHEMA.app["default_locale"]
        for query in ("?lang=xx", "?a=1&b=2&c=3&d=4&e=5&f=6&lang=en", "?lang=%00"):
            status, _, page = self.call("GET", "/" + query, role=None)
            self.assertEqual(status, 200, query)
            self.assertIn(f'lang="{default}"', page.decode("utf-8"), query)

    def test_cross_origin_write_refused(self):
        entity = SCHEMA.entities[0]
        body = sample(entity, 1, self.parents(entity))
        for headers in ({"Origin": "https://attacker.example"}, {"Origin": "null"},
                        {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):
            status, _, error = self.call("POST", self.path(entity), body, headers=headers)
            self.assertEqual((status, error["error"]["code"]), (403, "cross_origin"), headers)
        record = self.server.create(entity, 1, self.parents(entity))
        status, _, _ = self.call("DELETE", self.path(entity, record["id"]), headers={"Origin": "https://attacker.example"})
        self.assertEqual(status, 403)
        same = {"Origin": self.server.origin, "Sec-Fetch-Site": "same-origin"}
        self.assertEqual(self.call("POST", self.path(entity), body, headers=same)[0], 201)

    def test_wrong_content_type_refused(self):
        entity = SCHEMA.entities[0]
        for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data"):
            status, _, error = self.call("POST", self.path(entity), raw=b"{}", headers={"Content-Type": content_type})
            self.assertEqual((status, error["error"]["code"]), (415, "unsupported_media_type"))

    def test_oversized_body_refused(self):
        entity = SCHEMA.entities[0]
        raw = b'{"x": "' + b"a" * (LIMITS["max_body_bytes"] + 10) + b'"}'
        status, _, error = self.call("POST", self.path(entity), raw=raw)
        self.assertEqual((status, error["error"]["code"]), (413, "payload_too_large"))

    def test_invalid_json_refused(self):
        entity = SCHEMA.entities[0]
        for raw in (b"{", b"[1, 2]", b'{"a": 1, "a": 2}', b'{"a": NaN}', b"\xff\xfe"):
            status, _, error = self.call("POST", self.path(entity), raw=raw)
            self.assertEqual((status, error["error"]["code"]), (400, "invalid_json"), raw)

    def test_unknown_collection_404(self):
        for path in ("/api/does-not-exist", "/api/schema_migrations", "/api/app_account", "/api/sqlite_master", "/nowhere"):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_method_not_allowed(self):
        entity = SCHEMA.entities[0]
        for method, path in (("PATCH", self.path(entity)), ("DELETE", self.path(entity)),
                             ("OPTIONS", self.path(entity)), ("POST", "/api/health"), ("PUT", "/"), ("GET", "/api/login")):
            status, headers, _ = self.call(method, path, role=None if path in ("/", "/api/health", "/api/login") else ADMIN)
            self.assertEqual(status, 405, (method, path))
            self.assertIn("allow", headers)
            self.assertNotIn("access-control-allow-methods", headers)

    def test_bad_query_refused(self):
        entity = SCHEMA.entities[0]
        for query in ("?limit=0", f"?limit={LIMITS['max_page_size'] + 1}", "?offset=-1", "?unknown=1",
                      "?limit=1&limit=2", "?limit=abc", "?sort=nope", "?overdue=maybe"):
            self.assertEqual(self.call("GET", self.path(entity) + query)[0], 400, query)

    def test_pagination_limits(self):
        entity = SCHEMA.entities[0]
        for n in range(LIMITS["page_size"] + 2):
            self.server.create(entity, n, self.parents(entity))
        status, _, page = self.call("GET", self.path(entity))
        self.assertEqual((status, page["limit"], len(page["items"])), (200, LIMITS["page_size"], LIMITS["page_size"]))
        self.assertGreater(page["total"], LIMITS["page_size"])
        self.assertEqual(self.call("GET", self.path(entity) + f"?limit={LIMITS['max_page_size']}")[0], 200)
        self.assertEqual(self.call("GET", self.path(entity) + f"?limit={LIMITS['max_page_size'] + 1}")[0], 400)

    def test_sort_and_filters(self):
        for entity in SCHEMA.entities:
            refs = self.parents(entity)
            for field in entity.fields:
                if field["type"] == "enum":
                    for n in range(len(field["values"])):
                        self.server.create(entity, n, refs)
                    value = field["values"][0]
                    status, _, page = self.call("GET", self.path(entity) + f"?{field['name']}={value}&limit=200")
                    self.assertEqual(status, 200)
                    self.assertTrue(page["items"] and all(row[field["name"]] == value for row in page["items"]))
                if field["type"] in ("text", "date", "int", "number"):
                    status, _, page = self.call("GET", self.path(entity) + f"?sort={field['name']}&limit=200")
                    values = [row[field["name"]] for row in page["items"]]
                    present = [v for v in values if v is not None]
                    self.assertEqual(status, 200)
                    self.assertEqual(present, sorted(present), field["name"])
                    self.assertEqual(values, present + [None] * (len(values) - len(present)))

    def test_static_traversal_refused(self):
        for path in ("/static/../app/server.py", "/static/%2e%2e/app/db.py", "/static/../../etc/passwd",
                     "/static/", "/static/schema.json", "/app/schema.json", "/.git/config", "/data/app.sqlite3"):
            self.assertEqual(self.call("GET", path, role=None)[0], 404, path)

    def test_sql_injection_is_inert(self):
        entity = next((e for e in SCHEMA.entities if any(f["type"] == "text" for f in e.fields)), None)
        self.assertIsNotNone(entity, "the schema has at least one text field")
        field = next(f for f in entity.fields if f["type"] == "text")
        body = sample(entity, 1, self.parents(entity))
        payload = ("x'); DROP TABLE " + entity.table + "; --")[: field.get("max", 200)]
        body[field["name"]] = payload
        status, _, record = self.call("POST", self.path(entity), body)
        self.assertEqual((status, record[field["name"]]), (201, payload))
        self.assertEqual(self.call("GET", self.path(entity, record["id"]))[2][field["name"]], payload)
        query = "?" + (entity.references[0]["field"] + "=1%20OR%201=1" if entity.references else "limit=1%3B")
        self.assertEqual(self.call("GET", self.path(entity) + query)[0], 400)
        self.assertEqual(self.call("GET", self.path(entity) + "?sort=id%3BDROP")[0], 400)
        self.assertEqual(self.call("GET", self.path(entity))[0], 200)

    def test_list_latency_budget(self):
        budget = SCHEMA.nfr.get("p95_ms", 200)
        records = SCHEMA.nfr.get("latency_records", 1000)
        entity = next(e for e in SCHEMA.entities if not any(r.get("required") for r in e.references))
        rows = []
        for n in range(records):
            values = model.validate(entity, sample(entity, n), LIMITS)
            rows.append([values.get(column) for column in entity.columns] + [None, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"])
        columns = list(entity.columns) + ["created_by", "created_at", "updated_at"]
        with db.session(self.server.db_path) as connection:
            connection.executemany("INSERT INTO " + db.ident(entity.table) + " (" + ", ".join(db.ident(c) for c in columns)
                                   + ") VALUES (" + ", ".join("?" for _ in columns) + ")", rows)
        samples = []
        for _ in range(60):
            start = time.perf_counter()
            status, _, page = self.call("GET", self.path(entity))
            samples.append((time.perf_counter() - start) * 1000)
            self.assertEqual(status, 200)
        self.assertGreaterEqual(page["total"], records)
        p95 = sorted(samples)[int(len(samples) * 0.95) - 1]
        self.assertLess(p95, budget, f"p95 {p95:.1f} ms over the {budget} ms budget with {records} records")

    def test_seed_is_synthetic(self):
        data = seeding.load()
        self.assertEqual(data["label"], "synthetic")
        with tempfile.TemporaryDirectory() as tmp:
            counts = seeding.seed(pathlib.Path(tmp) / "seed.sqlite3")
            self.assertEqual(counts, {e.name: len(data["records"].get(e.name, [])) for e in SCHEMA.entities})
            connection = db.connect(pathlib.Path(tmp) / "seed.sqlite3")
            try:
                for entity in SCHEMA.entities:
                    total = connection.execute("SELECT COUNT(*) FROM " + db.ident(entity.table)).fetchone()[0]
                    self.assertEqual(total, counts[entity.name])
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM app_account").fetchone()[0], 0,
                                 "no default account may be seeded")
            finally:
                connection.close()


def _bind(check, *args):
    def test(self):
        getattr(self, "_" + check)(*args)
    return test


for _entity in SCHEMA.entities:
    for _check in ("create", "list", "get", "update", "patch", "delete", "validation", "not_found"):
        setattr(ApiTests, f"test_{_check}_{_entity.table}", _bind(_check, _entity))
    for _ref in _entity.references:
        setattr(ApiTests, f"test_reference_{_entity.table}_{_ref['field']}_missing", _bind("reference_missing", _entity, _ref))
        setattr(ApiTests, f"test_reference_{_entity.table}_{_ref['field']}_delete_parent",
                _bind("reference_delete_parent", _entity, _ref))
    for _field in _entity.fields:
        if _field.get("unique"):
            setattr(ApiTests, f"test_unique_{_entity.table}_{_field['name']}", _bind("unique", _entity, _field))
    for _link in _entity.links:
        setattr(ApiTests, f"test_links_{_entity.table}_{re.sub('-', '_', _link['segment'])}", _bind("links", _entity, _link))
    for _child in _entity.children:
        setattr(ApiTests, f"test_children_{_entity.table}_{re.sub('-', '_', _child['collection'])}",
                _bind("children", _entity, _child))


if __name__ == "__main__":
    unittest.main()
