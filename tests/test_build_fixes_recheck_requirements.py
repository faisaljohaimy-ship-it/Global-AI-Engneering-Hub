"""Regressions for the recheck-build review of engineering_os.requirements (L15): the W2-RQ-01 residual.

Locale and role removals or negations that were silently ignored (or removed the wrong thing)
are applied, or become an open question; a role name that is also an entity name is asked
about. Commands are parsed for real, in Arabic and English, against the upgrade fixture
specification or the real specification of the reference command. Controls keep working.
"""
import json
import pathlib
import unittest

from engineering_os import requirements as rq

ROOT = pathlib.Path(__file__).resolve().parents[1]
PM_COMMAND = "ابنِ نظامًا جديدًا لإدارة المشاريع"


def fixture():
    return json.loads((ROOT / "tests/fixtures/upgrade/taskapp/gaie-spec.json").read_text(encoding="utf-8"))


def questions(spec):
    return [question["id"] for question in spec["open_questions"]]


def role_ids(spec):
    return [role["id"] for role in spec["roles"]]


def entity_names(spec):
    return [entity["name"] for entity in spec["entities"]]


def breaking(old, new):
    return sorted({item["kind"] for item in rq.diff_specs(old, new)["breaking"]})


class LocaleWordingTests(unittest.TestCase):
    """Every wording of the recheck PoC names the locale; a negation in a change asks, a removal applies."""

    def test_negating_a_locale_of_an_existing_system_asks_the_owner(self):
        base = fixture()
        self.assertEqual(base["locales"], ["ar", "en"])
        for command in ("طور نظام إدارة المهام لا نريد الإنجليزية", "طور نظام إدارة المهام من غير الإنجليزية",
                        "طور نظام إدارة المهام لا نحتاج اللغة الإنجليزية", "طور نظام إدارة المهام والإنجليزية غير مطلوبة",
                        "Upgrade the task management system; english is not needed",
                        "upgrade the task management system, we dont need english",
                        "upgrade the task management system and the English interface is not required"):
            with self.subTest(command):
                spec = rq.parse(command, base=base)
                self.assertEqual((spec["locales"], questions(spec)), (["ar", "en"], ["locale_removal:en"]))
                self.assertEqual(rq.refine(spec, {"locale_removal:en": "remove"})["locales"], ["ar"])
                self.assertEqual(rq.refine(spec, {"locale_removal:en": "keep"})["locales"], ["ar", "en"])

    def test_removing_a_locale_of_an_existing_system_is_applied_and_breaking(self):
        base = fixture()
        for command, left in (("طور نظام إدارة المهام وإزالة اللغة الإنجليزية", ["ar"]),
                              ("طور نظام إدارة المهام وحذف العربية", ["en"]),
                              ("upgrade the task management system and remove the en locale", ["ar"]),
                              ("upgrade the task management system and remove the ar locale", ["en"]),
                              ("upgrade the task management system and stop supporting english", ["ar"]),
                              ("upgrade the task management system and discontinue arabic", ["en"])):
            with self.subTest(command):
                spec = rq.parse(command, base=base)
                self.assertEqual((spec["locales"], questions(spec)), (left, []))
                self.assertEqual(breaking(base, spec), ["locale-removed"])

    def test_a_new_system_without_a_locale_does_not_get_it(self):
        for command, left in (("ابنِ نظامًا جديدًا لإدارة المشاريع لا نريد اللغة العربية", ["en"]),
                              ("ابنِ نظامًا جديدًا لإدارة المشاريع من غير الإنجليزية", ["ar"]),
                              ("ابنِ نظامًا جديدًا لإدارة المشاريع والإنجليزية غير مطلوبة", ["ar"]),
                              ("build a new project management system; arabic is not required", ["en"]),
                              ("build a new project management system, we dont need english", ["ar"]),
                              ("build a new project management system and stop supporting arabic", ["en"])):
            with self.subTest(command):
                spec = rq.parse(command)
                self.assertEqual((spec["locales"], questions(spec)), (left, []))
                self.assertIn(f"excluded:locale-{({'ar', 'en'} - set(left)).pop()}", {a["id"] for a in spec["assumptions"]})

    def test_language_words_that_name_something_else_change_no_locale(self):
        base = fixture()
        for command in ("upgrade the task management system; english titles are not needed",
                        "upgrade the task management system and stop tasks from being deleted",
                        "طور نظام إدارة المهام وحذف المهام المكتملة"):
            with self.subTest(command):
                spec = rq.parse(command, base=base)
                self.assertEqual(spec["locales"], ["ar", "en"])
                self.assertNotIn("locale_removal:en", questions(spec))
        plain = rq.parse("Build a new project management system")
        for command in ("build a new project management system with an english title field",
                        "build a new project management system where tasks have no arabic title"):
            with self.subTest(command):
                spec = rq.parse(command)
                self.assertEqual((spec["locales"], questions(spec)), (plain["locales"], []))


class RoleWordingTests(unittest.TestCase):
    """Role names after a removal or negation: labels count, the role word decides, an entity is never removed instead."""

    @classmethod
    def setUpClass(cls):
        cls.pm = rq.parse(PM_COMMAND)

    def test_negating_the_project_manager_asks_like_without_managers(self):
        for command in ("طور نظام إدارة المشاريع بدون مدير المشروع", "upgrade the project management system without managers",
                        "upgrade the project management system without the project manager",
                        "upgrade the project management system; the manager role is not needed"):
            with self.subTest(command):
                spec = rq.parse(command, base=self.pm)
                self.assertEqual((role_ids(spec), questions(spec)), (role_ids(self.pm), ["role_removal:manager"]))
                self.assertEqual(entity_names(spec), entity_names(self.pm), "the Project entity is untouched")
        removed = rq.refine(rq.parse("طور نظام إدارة المشاريع بدون مدير المشروع", base=self.pm), {"role_removal:manager": "remove"})
        self.assertEqual((role_ids(removed), entity_names(removed)), (["admin", "member"], entity_names(self.pm)))

    def test_removing_the_member_role_removes_the_role_not_the_entity(self):
        for command, role in (("طور نظام إدارة المشاريع وأزل دور العضو", "member"),
                              ("طور نظام إدارة المشاريع واحذف دور العضو", "member"),
                              ("طور نظام إدارة المشاريع وإزالة دور المدير", "manager"),
                              ("upgrade the project management system and remove project managers", "manager"),
                              ("upgrade the project management system and stop the member role", "member")):
            with self.subTest(command):
                spec = rq.parse(command, base=self.pm)
                self.assertEqual((role_ids(spec), questions(spec)), ([r for r in role_ids(self.pm) if r != role], []))
                self.assertEqual(entity_names(spec), entity_names(self.pm))
                self.assertEqual(breaking(self.pm, spec), ["role-removed"])

    def test_a_new_system_without_the_project_manager_does_not_get_the_role(self):
        for command in ("ابنِ نظامًا جديدًا لإدارة المشاريع بدون مدير المشروع",
                        "build a new project management system without the project manager"):
            with self.subTest(command):
                spec = rq.parse(command)
                self.assertEqual((role_ids(spec), questions(spec)), (["admin", "member"], []))
                self.assertEqual(entity_names(spec), entity_names(self.pm))

    def test_a_name_of_both_a_role_and_an_entity_is_asked_about(self):
        for command in ("upgrade the project management system and remove members",
                        "upgrade the project management system and remove team members",
                        "upgrade the project management system without members"):
            with self.subTest(command):
                spec = rq.parse(command, base=self.pm)
                self.assertEqual((role_ids(spec), entity_names(spec), questions(spec)),
                                 (role_ids(self.pm), entity_names(self.pm), ["role_or_entity:member"]))
                self.assertFalse(rq.is_ready(spec))
                self.assertEqual(spec["open_questions"][0]["choices"], ["role", "entity"])
        spec = rq.parse("upgrade the project management system and remove members", base=self.pm)
        as_role = rq.refine(spec, {"role_or_entity:member": "role"})
        self.assertEqual((role_ids(as_role), entity_names(as_role), questions(as_role)),
                         (["admin", "manager"], entity_names(self.pm), []))
        as_entity = rq.refine(spec, {"role_or_entity:member": "entity"})
        self.assertEqual((role_ids(as_entity), questions(as_entity)), (role_ids(self.pm), []))
        self.assertNotIn("Member", entity_names(as_entity))
        new = rq.parse("build a new project management system without members")
        self.assertEqual(questions(new), ["role_or_entity:member"])

    def test_entity_and_unrelated_wordings_keep_their_meaning(self):
        for command, gone in (("upgrade the project management system and remove the member entity", "Member"),
                              ("طور نظام إدارة المشاريع واحذف المعالم", "Milestone"),
                              ("upgrade the project management system and remove the milestones", "Milestone")):
            with self.subTest(command):
                spec = rq.parse(command, base=self.pm)
                self.assertEqual((role_ids(spec), questions(spec)), (role_ids(self.pm), []))
                self.assertNotIn(gone, entity_names(spec))
        for command in ("upgrade the project management system, members can delete their own tasks",
                        "upgrade the project management system and remove the auditor role"):
            with self.subTest(command):
                spec = rq.parse(command, base=self.pm)
                self.assertEqual((role_ids(spec), entity_names(spec), questions(spec)),
                                 (role_ids(self.pm), entity_names(self.pm), []))
        kept = rq.parse("build a project management system without manager approval")
        self.assertEqual((role_ids(kept), questions(kept)), (["admin", "manager", "member"], []))


if __name__ == "__main__":
    unittest.main()
