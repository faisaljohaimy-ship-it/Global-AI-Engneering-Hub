"""Regressions for the w2-build-upgrade review of engineering_os.requirements (L15): W2-RQ-01..03.

Commands are parsed for real (Arabic and English); a change command runs against the
upgrade fixture specification (tests/fixtures/upgrade/taskapp/gaie-spec.json) or the real
specification of the reference command. Nothing is written and no network is used.
"""
import copy
import json
import pathlib
import unittest

from engineering_os import build_engine
from engineering_os import requirements as rq

ROOT = pathlib.Path(__file__).resolve().parents[1]
PM_COMMAND = "ابنِ نظامًا جديدًا لإدارة المشاريع"


def fixture():
    return json.loads((ROOT / "tests/fixtures/upgrade/taskapp/gaie-spec.json").read_text(encoding="utf-8"))


def questions(spec):
    return [question["id"] for question in spec["open_questions"]]


def role_ids(spec):
    return [role["id"] for role in spec["roles"]]


class LocaleRemovalTests(unittest.TestCase):
    """W2-RQ-01: removing or negating a locale is honoured or becomes an open question, never ignored."""

    def test_removing_a_locale_of_an_existing_system_is_applied_and_breaking(self):
        base = fixture()
        self.assertEqual(base["locales"], ["ar", "en"])
        for command, left in (("Upgrade the task management system and remove the Arabic locale", ["en"]),
                              ("طور نظام إدارة المهام واحذف اللغة العربية", ["en"]),
                              ("remove english", ["ar"]),
                              ("واحذف الإنجليزية", ["ar"])):
            with self.subTest(command):
                spec = rq.parse(command, base=base)
                self.assertEqual((spec["locales"], questions(spec)), (left, []))
                removed = sorted(set(base["locales"]) - set(left))
                self.assertIn({"kind": "locale-removed", "locales": removed}, rq.diff_specs(base, spec)["breaking"])
                self.assertEqual([item for item in spec["nfr"]["i18n"] if item in ("ar rtl", "en ltr")],
                                 [f"{left[0]} {'rtl' if left[0] == 'ar' else 'ltr'}"])

    def test_negating_a_locale_of_an_existing_system_asks_the_owner(self):
        base = fixture()
        for command in ("Upgrade the task management system without arabic", "طور نظام إدارة المهام بدون العربية"):
            with self.subTest(command):
                spec = rq.parse(command, base=base)
                self.assertEqual((spec["locales"], questions(spec)), (["ar", "en"], ["locale_removal:ar"]))
                self.assertFalse(rq.is_ready(spec))
                removed = rq.refine(spec, {"locale_removal:ar": "remove"})
                self.assertEqual((removed["locales"], questions(removed)), (["en"], []))
                kept = rq.refine(spec, {"locale_removal:ar": "keep"})
                self.assertEqual((kept["locales"], questions(kept)), (["ar", "en"], []))

    def test_a_new_system_without_a_locale_does_not_get_it(self):
        for command in ("build a new project management system without english",
                        "ابنِ نظامًا جديدًا لإدارة المشاريع بدون الإنجليزية"):
            with self.subTest(command):
                spec = rq.parse(command)
                self.assertEqual((spec["locales"], questions(spec)), (["ar"], []))
                ui = next(f for f in spec["features"] if f["id"] == "ui-locales")["acceptance"]
                self.assertFalse(any("lang=en" in criterion for criterion in ui))
                self.assertIn("excluded:locale-en", {item["id"] for item in spec["assumptions"]})
                self.assertEqual(build_engine.plan(spec)["unmapped_criteria"], {})

    def test_the_only_locale_is_never_dropped_silently(self):
        base = fixture()
        base["locales"] = ["en"]
        base["nfr"]["i18n"] = [item for item in base["nfr"]["i18n"] if item != "ar rtl"]
        for features in base["features"]:
            features["acceptance"] = [c for c in features["acceptance"] if "lang=ar" not in c]
        rq.validate_spec(base)
        spec = rq.parse("Upgrade the task management system and remove english", base=base)
        self.assertEqual((spec["locales"], questions(spec)), (["en"], ["locale_needed:en"]))
        self.assertEqual(spec["open_questions"][0]["choices"], ["keep"])
        contradiction = rq.parse("build a new project management system, english only, without english")
        self.assertEqual((contradiction["locales"], questions(contradiction)), (["en"], ["locale_needed:en"]))

    def test_a_language_word_that_names_something_else_is_not_a_removal(self):
        spec = rq.parse("build a new project management system where tasks have no arabic title")
        self.assertEqual((spec["locales"], questions(spec)), (["en", "ar"], []))
        plain = rq.parse("Build a new project management system")
        self.assertEqual(spec["locales"], plain["locales"])


class RoleRemovalTests(unittest.TestCase):
    """W2-RQ-01: removing or negating a role is honoured or becomes an open question, never ignored."""

    @classmethod
    def setUpClass(cls):
        cls.pm = rq.parse(PM_COMMAND)

    def test_removing_a_role_of_an_existing_system_is_applied_and_breaking(self):
        for command, role in (("Upgrade the project management system and remove the manager role", "manager"),
                              ("احذف دور المدير", "manager"),
                              ("remove the member role", "member"),
                              ("طور نظام إدارة المشاريع واحذف دور عضو الفريق", "member")):
            with self.subTest(command):
                spec = rq.parse(command, base=self.pm)
                self.assertEqual((role_ids(spec), questions(spec)),
                                 ([r for r in role_ids(self.pm) if r != role], []))
                self.assertIn({"kind": "role-removed", "role": role}, rq.diff_specs(self.pm, spec)["breaking"])
                self.assertEqual([e["name"] for e in spec["entities"]], [e["name"] for e in self.pm["entities"]],
                                 "a role name is not an entity removal")
                rbac = next(f for f in spec["features"] if f["id"] == "rbac")["acceptance"]
                self.assertFalse(any(f" as {role} " in criterion for criterion in rbac))

    def test_negating_a_role_of_an_existing_system_asks_the_owner(self):
        for command in ("upgrade the project management system without the manager role",
                        "طور نظام إدارة المشاريع بدون دور المدير"):
            with self.subTest(command):
                spec = rq.parse(command, base=self.pm)
                self.assertEqual((role_ids(spec), questions(spec)), (role_ids(self.pm), ["role_removal:manager"]))
                self.assertEqual(role_ids(rq.refine(spec, {"role_removal:manager": "remove"})), ["admin", "member"])

    def test_required_roles_are_never_dropped_silently(self):
        spec = rq.parse("remove the admin role", base=self.pm)
        self.assertEqual((role_ids(spec), questions(spec)), (role_ids(self.pm), ["role_needed:admin"]))
        only = rq.parse("remove the user role", base=fixture())
        self.assertEqual((role_ids(only), questions(only)), (["user"], ["role_needed:user"]))
        arabic = rq.parse("احذف دور المستخدم", base=fixture())
        self.assertEqual(questions(arabic), ["role_needed:user"])

    def test_a_new_system_without_a_role_does_not_get_it(self):
        for command in ("build a project management system without managers",
                        "ابنِ نظامًا جديدًا لإدارة المشاريع بدون مدراء"):
            with self.subTest(command):
                spec = rq.parse(command)
                self.assertEqual((role_ids(spec), questions(spec)), (["admin", "member"], []))
        kept = rq.parse("build a project management system without manager approval")
        self.assertIn("manager", role_ids(kept))

    def test_removing_an_absent_role_adds_nothing(self):
        spec = rq.parse("Upgrade the project management system and remove the auditor role", base=self.pm)
        self.assertEqual((role_ids(spec), questions(spec)), (role_ids(self.pm), []))


if __name__ == "__main__":
    unittest.main()
