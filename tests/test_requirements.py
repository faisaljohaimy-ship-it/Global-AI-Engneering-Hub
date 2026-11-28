"""L15 Requirements & Specification Intelligence: bilingual parse, packs, validation, refine and diff."""
import contextlib
import copy
import hashlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

from engineering_os import gaie_router as router
from engineering_os import requirements as rq
from engineering_os.contracts import canonical

ROOT = pathlib.Path(__file__).resolve().parents[1]
PM_COMMAND = "ابنِ نظامًا جديدًا لإدارة المشاريع"
COMMANDS = {
    "project-management": (PM_COMMAND, "Build a new project management system"),
    "inventory": ("أنشئ نظامًا لإدارة المخزون والمستودعات", "Create an inventory management system"),
    "crm": ("ابنِ نظام إدارة علاقات العملاء", "Build a CRM for our sales team"),
    "hse-incident-reporting": ("ابنِ نظامًا للإبلاغ عن حوادث السلامة والصحة المهنية", "Build an HSE incident reporting system"),
    "kpi-dashboard": ("أنشئ لوحة مؤشرات الأداء الرئيسية", "Create a KPI dashboard"),
}


def names(spec):
    return [entity["name"] for entity in spec["entities"]]


def fields(spec, entity):
    return {field["name"]: field for field in next(e for e in spec["entities"] if e["name"] == entity)["fields"]}


def feature_ids(spec):
    return [feature["id"] for feature in spec["features"]]


def question_ids(spec):
    return [question["id"] for question in spec["open_questions"]]


def body(spec):
    """Everything but the source (command text and answers differ between equivalent inputs)."""
    return {key: value for key, value in spec.items() if key not in ("source", "assumptions")}


class NormalizationTests(unittest.TestCase):
    def test_reuses_router_normalization_for_arabic_variants(self):
        self.assertEqual(rq._words("إدارة"), router.normalize("إدارة"))
        self.assertEqual(rq._words("إدارة"), rq._words("ادارة"))
        self.assertEqual(rq._words("إدارة"), rq._words("اداره"))
        self.assertEqual(rq._words("مُؤَشِّرات"), rq._words("مؤشرات"))
        self.assertEqual(rq._words("الرئيسيـــة"), rq._words("الرئيسية"))
        self.assertEqual(rq._words("project-management"), ["project", "management"])
        self.assertIn("مهام", rq._variants("للمهام"))
        self.assertIn("مهام", rq._variants("وبالمهام"))
        self.assertIn("task", rq._variants("tasks"))
        self.assertIn("activity", rq._variants("activities"))

    def test_spelling_variants_give_the_same_spec(self):
        reference = rq.parse(PM_COMMAND)
        for variant in ("ابن نظاما جديدا لادارة المشاريع",          # no diacritics, bare alef
                        "ابنِ نظامـــاً جديـــداً لإدارة المشاريـــع",  # tatweel, tanween fath
                        "ابن نظاما جديدا لاداره المشاريع",           # taa marbuta written as haa
                        "اِبْنِ نِظَامًا جَدِيدًا لِإِدَارَةِ المَشَارِيعِ"):  # full diacritics
            spec = rq.parse(variant)
            self.assertEqual(body(spec), body(reference), variant)
            self.assertNotEqual(spec["source"]["sha256"], reference["source"]["sha256"])

    def test_language_detection_and_override(self):
        self.assertEqual(rq.parse(PM_COMMAND)["source"]["language"], "ar")
        english = rq.parse("Build a new project management system")
        self.assertEqual(english["source"]["language"], "en")
        self.assertEqual(english["locales"], ["en", "ar"])
        forced = rq.parse("Build a new project management system", language="ar")
        self.assertEqual(forced["locales"], ["ar", "en"])
        with self.assertRaises(rq.SpecError):
            rq.parse(PM_COMMAND, language="fr")

    def test_bad_input_is_refused(self):
        for value in ("", "   ", None, 42, "x" * (rq.MAX_INPUT + 1)):
            with self.assertRaises(rq.SpecError, msg=repr(value)[:20]):
                rq.parse(value)


class DomainPackTests(unittest.TestCase):
    def setUp(self):
        self.knowledge = rq.load_knowledge()

    def test_required_packs_exist_and_validate(self):
        self.assertTrue({"project-management", "inventory", "crm", "hse-incident-reporting", "kpi-dashboard"}
                        <= set(self.knowledge["packs"]))
        for pack in self.knowledge["packs"].values():
            rq.validate_pack(copy.deepcopy(pack))
            for lang in ("ar", "en"):
                self.assertTrue(pack["title"][lang] and pack["rationale"][lang] and pack["keywords"][lang])
            for feature in pack["features"]:
                for item in feature["acceptance"]:
                    rq.parse_acceptance(item["en"])
                    self.assertRegex(item["ar"], "[ء-ي]")

    def test_arabic_and_english_command_for_every_pack(self):
        for domain, commands in COMMANDS.items():
            pack = self.knowledge["packs"][domain]
            core = [e["name"] for e in pack["entities"] if not e.get("optional")]
            specs = []
            for command, language in zip(commands, ("ar", "en")):
                spec = rq.parse(command)
                report = rq.validate_spec(spec)
                self.assertTrue(report["ready"], (command, spec["open_questions"]))
                self.assertEqual((spec["domain"], spec["intent"], spec["source"]["language"]), (domain, "new-system", language), command)
                self.assertEqual(names(spec), core, command)
                self.assertEqual(spec["title"], pack["title"])
                self.assertEqual(spec["product_type"], pack["product_type"])
                self.assertTrue({f["id"] for f in pack["features"] if set(f["requires"]) <= set(core)} <= set(feature_ids(spec)), command)
                self.assertTrue({f"manage-{e['plural']}" for e in spec["entities"]} <= set(feature_ids(spec)))
                self.assertIn(f"{language} {'rtl' if language == 'ar' else 'ltr'}", spec["nfr"]["i18n"])
                self.assertEqual(spec["locales"][0], language)
                self.assertEqual(spec["constraints"], {"runtime": "python3-stdlib", "database": "sqlite", "no_paid_services": True})
                self.assertEqual(spec["mode"], "deterministic")
                self.assertEqual(spec["source"]["sha256"], hashlib.sha256(command.encode("utf-8")).hexdigest())
                for check in rq.acceptance_checks(spec)["checks"]:
                    self.assertIn(check["method"], ("GET", "POST", "PUT", "PATCH", "DELETE"))
                    self.assertTrue(check["path"].startswith("/"))
                specs.append(spec)
            self.assertEqual(body(specs[0])["entities"], body(specs[1])["entities"], domain)
            self.assertEqual(feature_ids(specs[0]), feature_ids(specs[1]), domain)

    def test_pack_entities_have_bilingual_labels_and_acceptance(self):
        spec = rq.parse(COMMANDS["hse-incident-reporting"][0])
        for entity in spec["entities"]:
            self.assertRegex(entity["label"]["ar"], "[ء-ي]")
            for field in entity["fields"]:
                self.assertTrue(field["label"]["ar"] and field["label"]["en"])
        for feature in spec["features"]:
            self.assertEqual(len(feature["acceptance"]), len(feature["acceptance_ar"]), feature["id"])

    def test_optional_entity_is_activated_by_mention_and_excluded_by_negation(self):
        with_comments = rq.parse("ابنِ نظام إدارة مشاريع مع تعليقات على المهام وبدون معالم")
        self.assertEqual(names(with_comments), ["Project", "Task", "Member", "Comment"])
        self.assertIn("task-comments", feature_ids(with_comments))
        self.assertNotIn("milestones", feature_ids(with_comments))
        self.assertFalse(any("Milestone" in (r["from"], r["to"]) for r in with_comments["relations"]))
        self.assertIn("excluded:Milestone", [a["id"] for a in with_comments["assumptions"]])
        self.assertNotIn("Comment", names(rq.parse("Build a project management system without comments")))
        self.assertIn("PurchaseOrder", names(rq.parse("Build an inventory system with purchase orders")))

    def test_cross_pack_entity_is_adopted_and_its_relation_asked(self):
        spec = rq.parse("Build an inventory system with customers")
        self.assertIn("Customer", names(spec))
        self.assertEqual(question_ids(spec), ["relation:Customer"])
        self.assertIn("none", spec["open_questions"][0]["choices"])
        ignored = rq.parse("Build a project management system that tracks deals")  # Deal is not portable
        self.assertNotIn("Deal", names(ignored))
        self.assertIn("ignored:Deal", [a["id"] for a in ignored["assumptions"]])

    def test_fields_features_roles_and_nfr_from_text(self):
        spec = rq.parse("Build a project management system where projects have a budget and tasks have estimated hours. "
                        "Add search and CSV export for tasks, an auditor role, and it must be fast and accessible")
        self.assertIn("budget", fields(spec, "Project"))
        self.assertIn("estimated_hours", fields(spec, "Task"))
        self.assertNotIn("budget", fields(spec, "Task"))
        self.assertTrue({"search-tasks", "export-csv-tasks"} <= set(feature_ids(spec)))
        self.assertIn("auditor", [r["id"] for r in spec["roles"]])
        self.assertIn("WCAG 2.1 AA colour contrast", spec["nfr"]["accessibility"])
        self.assertIn("p95 page render < 1 s locally with 10,000 records", spec["nfr"]["performance"])
        arabic = rq.parse("ابنِ نظامًا لإدارة المشاريع، المهام مع الأولوية وتاريخ الاستحقاق والمشاريع مع الميزانية")
        self.assertIn("budget", fields(arabic, "Project"))
        self.assertNotIn("budget", fields(arabic, "Task"))
        self.assertEqual(arabic["open_questions"], [])

    def test_list_items_do_not_become_owners(self):
        spec = rq.parse("Build a project management system with comments, search and CSV export")
        self.assertIn("search-tasks", feature_ids(spec))
        self.assertNotIn("search-comments", feature_ids(spec))

    def test_product_type_database_locales_from_text(self):
        mobile = rq.parse("ابنِ تطبيق جوال لإدارة المشاريع بالعربية فقط")
        self.assertEqual((mobile["product_type"], mobile["locales"]), ("mobile-app", ["ar"]))
        self.assertIn("mobile-pwa", [a["id"] for a in mobile["assumptions"]])
        self.assertNotIn("en ltr", mobile["nfr"]["i18n"])
        api = rq.parse("Build a CRM as a REST API with PostgreSQL")
        self.assertEqual((api["product_type"], api["constraints"]["database"]), ("api-service", "postgresql"))
        self.assertNotIn("ui-locales", feature_ids(api))


class ProjectManagementEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.spec = rq.parse(PM_COMMAND)

    def test_complete_project_management_spec(self):
        spec = self.spec
        self.assertEqual(spec["schema"], "gaie.spec/1")
        self.assertEqual(spec["mode"], "deterministic")
        self.assertEqual(spec["source"]["sha256"], hashlib.sha256(PM_COMMAND.encode("utf-8")).hexdigest())
        self.assertEqual(spec["source"]["knowledge_sha256"], rq.load_knowledge()["sha256"])
        self.assertEqual((spec["intent"], spec["domain"], spec["slug"], spec["product_type"]),
                         ("new-system", "project-management", "project-management", "web-app"))
        self.assertEqual(spec["title"], {"ar": "نظام إدارة المشاريع", "en": "Project Management System"})
        self.assertEqual(spec["locales"], ["ar", "en"])
        self.assertEqual(spec["open_questions"], [])
        self.assertTrue(rq.is_ready(spec))
        self.assertEqual(names(spec), ["Project", "Task", "Member", "Milestone"])
        task = fields(spec, "Task")
        self.assertEqual((task["title"]["type"], task["title"]["required"], task["title"]["max"]), ("text", True, 200))
        self.assertEqual((task["due_date"]["type"], task["due_date"]["required"]), ("date", False))
        self.assertEqual((task["status"]["type"], task["status"]["values"], task["status"]["default"]),
                         ("enum", ["todo", "in_progress", "done"], "todo"))
        self.assertEqual(task["priority"]["values"], ["low", "medium", "high"])
        self.assertEqual(fields(spec, "Member")["email"]["type"], "email")
        self.assertTrue(fields(spec, "Member")["email"]["unique"])
        self.assertEqual(fields(spec, "Milestone")["due_date"]["required"], True)
        relations = {(r["from"], r["field"]): r for r in spec["relations"]}
        self.assertEqual(relations[("Task", "project")], {"from": "Task", "to": "Project", "kind": "many-to-one", "required": True, "field": "project"})
        self.assertEqual(relations[("Task", "assignee")]["to"], "Member")
        self.assertFalse(relations[("Task", "assignee")]["required"])
        self.assertEqual(relations[("Milestone", "project")]["to"], "Project")
        self.assertEqual(relations[("Project", "members")]["kind"], "many-to-many")
        self.assertEqual([r["id"] for r in spec["roles"]], ["admin", "manager", "member"])
        self.assertEqual(spec["ai"], {"needed": False, "use_cases": [], "provider": None})
        self.assertEqual(spec["integrations"], [])
        self.assertIn("ar rtl", spec["nfr"]["i18n"])
        self.assertIn("parameterized SQL only", spec["nfr"]["security"])
        rationale = next(a for a in spec["assumptions"] if a["id"] == "pack-rationale")
        self.assertIn("Milestone", rationale["en"])
        self.assertIn("التعليقات", rationale["ar"])

    def test_features_and_machine_checkable_acceptance(self):
        ids = feature_ids(self.spec)
        for wanted in ("manage-projects", "manage-tasks", "manage-members", "manage-milestones", "assign-tasks",
                       "track-task-status", "task-due-dates", "project-tasks", "project-progress", "milestones",
                       "project-membership", "auth", "rbac", "ui-locales"):
            self.assertIn(wanted, ids)
        result = rq.acceptance_checks(self.spec)
        self.assertEqual(result["mode"], "deterministic")
        self.assertEqual(result["spec_sha256"], rq.validate_spec(self.spec)["spec_sha256"])
        checks = result["checks"]
        self.assertEqual(len(checks), sum(len(f["acceptance"]) for f in self.spec["features"]))
        self.assertEqual((len(self.spec["features"]), len(checks)), (14, 64))  # numbers quoted in REQUIREMENTS.md
        by = {(c["method"], c["path"], c["status"]) for c in checks}
        self.assertIn(("POST", "/api/tasks", 201), by)
        self.assertIn(("POST", "/api/tasks", 400), by)
        self.assertIn(("GET", "/api/tasks?overdue=true", 200), by)
        self.assertIn(("PATCH", "/api/tasks/{id}", 200), by)
        self.assertIn(("DELETE", "/api/tasks/{id}", 403), by)
        self.assertIn(("GET", "/api/tasks", 401), by)
        self.assertIn(("GET", "/?lang=ar", 200), by)
        assign = [c for c in checks if c["feature"] == "assign-tasks"]
        self.assertEqual(assign[0]["placeholders"], ["id"])
        self.assertIn("assignee_id", assign[0]["condition"])
        plurals = {e["plural"] for e in self.spec["entities"]}
        for check in checks:
            if check["path"].startswith("/api/") and check["feature"].startswith("manage-"):
                self.assertIn(check["path"].split("/")[2].split("?")[0], plurals)
        manage_tasks = next(f for f in self.spec["features"] if f["id"] == "manage-tasks")
        self.assertIn("POST /api/tasks with a project_id that does not exist returns 400", manage_tasks["acceptance"])
        self.assertIn("POST /api/tasks with status=not_a_value returns 400", manage_tasks["acceptance"])
        self.assertIn("POST /api/tasks with title longer than 200 characters returns 400", manage_tasks["acceptance"])
        members = next(f for f in self.spec["features"] if f["id"] == "manage-members")
        self.assertIn("POST /api/members with a duplicate email returns 409", members["acceptance"])

    def test_deterministic_across_calls_and_hash_seeds(self):
        self.assertEqual(rq.parse(PM_COMMAND), self.spec)
        expected = hashlib.sha256(canonical(self.spec).encode("utf-8")).hexdigest()
        code = ("import hashlib,sys;from engineering_os import requirements as rq;from engineering_os.contracts import canonical;"
                "print(hashlib.sha256(canonical(rq.parse(sys.argv[1])).encode()).hexdigest())")
        for seed in ("0", "1", "12345"):
            out = subprocess.run([sys.executable, "-c", code, PM_COMMAND], cwd=ROOT, capture_output=True, text=True,
                                 env={**os.environ, "PYTHONHASHSEED": seed}, check=True, timeout=60)
            self.assertEqual(out.stdout.strip(), expected, seed)

    def test_engine_facade_and_cli(self):
        result = rq.engine("parse", {"command": PM_COMMAND})
        self.assertTrue(result["ok"])
        self.assertEqual((result["mode"], result["engine"]), ("deterministic", "requirements"))
        self.assertEqual(result["result"]["spec"], self.spec)
        self.assertRegex(result["request_sha256"], "^[0-9a-f]{64}$")
        self.assertTrue(rq.engine("validate", {"spec": self.spec})["result"]["report"]["ready"])
        self.assertEqual(rq.health()["ok"], True)
        with self.assertRaises(rq.SpecError):
            rq.engine("deploy", {"command": PM_COMMAND})
        with self.assertRaises(rq.SpecError):
            rq.engine("parse", {"command": PM_COMMAND, "shell": "rm -rf /"})
        with self.assertRaises(rq.SpecError):
            rq.engine("parse", "not a dict")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(rq.main(["parse", PM_COMMAND]), 0)
        self.assertEqual(json.loads(buffer.getvalue()), self.spec)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(rq.main(["parse", "ابنِ نظامًا"]), 2)
            self.assertEqual(rq.main(["parse", " "]), 1)


class AmbiguityTests(unittest.TestCase):
    def test_build_a_system_without_domain_asks_instead_of_guessing(self):
        for command in ("ابنِ نظامًا", "Build a system", "أنشئ منصة"):
            spec = rq.parse(command)
            self.assertEqual(question_ids(spec), ["domain"], command)
            self.assertEqual(spec["open_questions"][0]["choices"], sorted(rq.load_knowledge()["packs"]))
            self.assertTrue(spec["open_questions"][0]["question"]["ar"])
            self.assertEqual((spec["domain"], spec["title"], spec["slug"], spec["entities"], spec["features"]),
                             (None, None, None, [], []))
            self.assertFalse(rq.is_ready(spec))
            self.assertEqual(spec["intent"], "new-system")

    def test_two_domains_ask_with_only_the_candidates(self):
        spec = rq.parse("Build an inventory system and a CRM")
        self.assertEqual(spec["open_questions"][0]["choices"], ["crm", "inventory"])

    def test_brief_without_a_verb_asks_for_the_intent(self):
        spec = rq.parse("A system for tracking tasks and milestones")
        self.assertEqual(question_ids(spec), ["intent"])
        self.assertIsNone(spec["intent"])
        self.assertEqual(spec["domain"], "project-management")
        self.assertIn("domain-weak", [a["id"] for a in spec["assumptions"]])

    def test_change_without_base_asks_for_the_base(self):
        spec = rq.parse("أضف حقل الأولوية إلى المشاريع")
        self.assertEqual((spec["intent"], question_ids(spec)), ("change", ["base"]))
        self.assertIsNone(spec["open_questions"][0]["choices"])

    def test_ai_and_paid_integrations_become_questions(self):
        spec = rq.parse("Build a CRM with AI and WhatsApp reminders")
        self.assertEqual(question_ids(spec), ["ai_use_case", "ai_provider", "integration:whatsapp"])
        summary = rq.parse("Build a CRM with AI to summarize customer calls and send SMS reminders")
        self.assertEqual(summary["ai"], {"needed": True, "use_cases": ["summarization"], "provider": None})
        self.assertEqual(question_ids(summary), ["ai_provider", "integration:sms"])
        self.assertIn("ai-summarization", feature_ids(summary))
        free = rq.parse("Build a project management system with Slack and email notifications")
        self.assertEqual([i["id"] for i in free["integrations"]], ["slack", "email"])
        self.assertTrue(all(i["approved"] for i in free["integrations"]))
        self.assertEqual(free["open_questions"], [])
        self.assertIn("integration credentials read from environment variables, never stored in the repository", free["nfr"]["security"])
        no_ai = rq.parse("ابنِ نظام إدارة علاقات العملاء بدون ذكاء اصطناعي")
        self.assertEqual((no_ai["ai"]["needed"], no_ai["open_questions"]), (False, []))

    def test_unowned_new_field_is_asked(self):
        spec = rq.parse("Build a project management system with budget")
        self.assertEqual(question_ids(spec), ["field_entity:budget"])
        self.assertEqual(spec["open_questions"][0]["choices"], ["Member", "Milestone", "Project", "Task"])
        self.assertFalse(any("budget" in fields(spec, n) for n in names(spec)))


class RefineTests(unittest.TestCase):
    def test_domain_answer_completes_the_spec(self):
        pending = rq.parse("ابنِ نظامًا")
        snapshot = copy.deepcopy(pending)
        spec = rq.refine(pending, {"domain": "project-management"})
        self.assertEqual(pending, snapshot)
        self.assertTrue(rq.is_ready(spec))
        self.assertEqual(spec["source"]["answers"], {"domain": "project-management"})
        self.assertEqual(spec["source"]["sha256"], pending["source"]["sha256"])
        reference = rq.parse(PM_COMMAND)
        self.assertEqual(names(spec), names(reference))
        self.assertEqual(spec["features"], reference["features"])
        self.assertEqual(spec["relations"], reference["relations"])

    def test_chained_answers_are_deterministic(self):
        pending = rq.parse("Build a CRM with AI and WhatsApp reminders")
        step = rq.refine(pending, {"ai_use_case": "summarization"})
        self.assertEqual(question_ids(step), ["ai_provider", "integration:whatsapp"])
        done = rq.refine(step, {"ai_provider": "local-model", "integration:whatsapp": "approve"})
        self.assertTrue(rq.is_ready(done))
        self.assertEqual(done["ai"], {"needed": True, "use_cases": ["summarization"], "provider": "local-model"})
        self.assertTrue(done["integrations"][0]["approved"])
        once = rq.refine(pending, {"ai_use_case": "summarization", "ai_provider": "local-model", "integration:whatsapp": "approve"})
        self.assertEqual(done, once)
        dropped = rq.refine(pending, {"ai_use_case": "forecasting", "ai_provider": "drop", "integration:whatsapp": "exclude"})
        self.assertEqual((dropped["ai"]["needed"], dropped["integrations"]), (False, []))
        self.assertNotIn("ai-forecasting", feature_ids(dropped))
        self.assertTrue(rq.is_ready(dropped))

    def test_field_and_relation_answers(self):
        spec = rq.refine(rq.parse("Build a project management system with budget"), {"field_entity:budget": "Project"})
        self.assertIn("budget", fields(spec, "Project"))
        self.assertTrue(rq.is_ready(spec))
        adopted = rq.refine(rq.parse("Build an inventory system with customers"), {"relation:Customer": "none"})
        self.assertTrue(rq.is_ready(adopted))
        self.assertIn("standalone:Customer", [a["id"] for a in adopted["assumptions"]])

    def test_base_question_is_answered_with_base(self):
        base = rq.parse(PM_COMMAND)
        pending = rq.parse("أضف حقل الأولوية إلى المشاريع")
        spec = rq.refine(pending, {}, base=base)
        self.assertIn("priority", fields(spec, "Project"))
        self.assertEqual(spec["source"]["base_sha256"], rq.validate_spec(base)["spec_sha256"])
        self.assertEqual(spec, rq.parse("أضف حقل الأولوية إلى المشاريع", base=base))

    def test_change_spec_refine_equals_fully_answered_parse(self):
        base = rq.parse(PM_COMMAND)
        pending = rq.parse("Add customers", base=base)
        self.assertEqual(question_ids(pending), ["relation:Customer"])
        spec = rq.refine(pending, {"relation:Customer": "Project"})
        self.assertEqual(spec, rq.parse("Add customers", base=base, answers={"relation:Customer": "Project"}))
        self.assertIn("POST /api/customers with a project_id that does not exist returns 400",
                      next(f for f in spec["features"] if f["id"] == "manage-customers")["acceptance"])

    def test_answer_made_moot_by_another_answer_is_dropped_and_recorded(self):
        pending = rq.parse("A system for tracking tasks and milestones, with WhatsApp")
        self.assertEqual(question_ids(pending), ["intent", "integration:whatsapp"])
        spec = rq.refine(pending, {"intent": "change", "integration:whatsapp": "approve"})
        self.assertEqual(question_ids(spec), ["base"])
        self.assertEqual(spec["source"]["answers"], {"intent": "change"})
        self.assertIn("answer-moot:integration:whatsapp", [a["id"] for a in spec["assumptions"]])
        with self.assertRaises(rq.SpecError):  # parse(answers=...) stays strict
            rq.parse(pending["source"]["command"], answers={"intent": "change", "integration:whatsapp": "approve"})

    def test_refine_refusals(self):
        pending = rq.parse("ابنِ نظامًا")
        cases = [({"domain": "library"}, "not one of"), ({"intent": "change"}, "not an open question"), ({}, "at least one"),
                 ({"base": "x"}, "base="), ({"domain": 3}, "map question ids")]
        for answers, message in cases:
            with self.assertRaises(rq.SpecError) as raised:
                rq.refine(pending, answers)
            self.assertIn(message, str(raised.exception), answers)
        with self.assertRaises(rq.SpecError):
            rq.refine(pending, {}, base=rq.parse(PM_COMMAND))
        with self.assertRaises(rq.SpecError):
            rq.parse("Build a system", answers={"intent": "new-system"})
        broken = copy.deepcopy(pending)
        broken["mode"] = "model"
        with self.assertRaises(rq.SpecError):
            rq.refine(broken, {"domain": "crm"})


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.spec = rq.parse(PM_COMMAND)

    def mutated(self, change):
        spec = copy.deepcopy(self.spec)
        change(spec)
        return spec

    def assertInvalid(self, change, message):
        with self.assertRaises(rq.SpecError) as raised:
            rq.validate_spec(self.mutated(change))
        self.assertTrue(any(message in error for error in raised.exception.errors), raised.exception.errors)
        return raised.exception

    def test_valid_spec_report(self):
        report = rq.validate_spec(self.spec)
        self.assertEqual((report["ok"], report["ready"], report["mode"], report["open_questions"]), (True, True, "deterministic", []))
        self.assertRegex(report["spec_sha256"], "^[0-9a-f]{64}$")

    def test_minimal_hand_written_spec_in_the_contract_shape(self):
        command = "Build a todo list"
        spec = {"schema": "gaie.spec/1", "mode": "deterministic",
                "source": {"command": command, "language": "en", "sha256": hashlib.sha256(command.encode()).hexdigest()},
                "title": {"ar": "قائمة مهام", "en": "Todo list"}, "slug": "todo", "product_type": "web-app", "domain": "todo",
                "locales": ["en"], "roles": [{"id": "admin", "permissions": ["*"]}],
                "entities": [{"name": "Task", "fields": [{"name": "title", "type": "text", "required": True, "max": 200},
                                                          {"name": "done", "type": "bool", "required": True, "default": False}]}],
                "relations": [], "features": [{"id": "F1", "title": {"ar": "المهام", "en": "Tasks"},
                                               "acceptance": ["POST /api/tasks with a valid body returns 201 and the record"]}],
                "nfr": {"security": [], "performance": [], "accessibility": [], "i18n": ["en ltr"]},
                "ai": {"needed": False, "use_cases": []}, "integrations": [],
                "constraints": {"runtime": "python3-stdlib", "database": "sqlite", "no_paid_services": True}, "open_questions": []}
        self.assertTrue(rq.validate_spec(spec)["ready"])

    def test_negative_cases(self):
        self.assertInvalid(lambda s: s["entities"][1]["fields"].__setitem__(0, {"name": "title", "type": "string", "required": True}),
                           "unknown field type 'string'")
        self.assertInvalid(lambda s: s["relations"].append({"from": "Task", "to": "Invoice", "kind": "many-to-one", "required": False, "field": "invoice"}),
                           "relation to a missing entity 'Invoice'")
        self.assertInvalid(lambda s: s["entities"].append(copy.deepcopy(s["entities"][0])), "duplicate entity 'Project'")
        self.assertInvalid(lambda s: s["entities"].append({**copy.deepcopy(s["entities"][0]), "name": "PROJECT", "plural": "projects-2"}),
                           "duplicate entity 'PROJECT'")
        self.assertInvalid(lambda s: s["features"][0].__setitem__("acceptance", []), "empty acceptance")
        self.assertInvalid(lambda s: s["features"][0]["acceptance"].__setitem__(0, "it works well"), "untestable acceptance criterion")
        task_status = lambda s: next(f for f in s["entities"][1]["fields"] if f["name"] == "status")
        self.assertInvalid(lambda s: task_status(s).__setitem__("values", []), "invalid enum")
        self.assertInvalid(lambda s: task_status(s).__setitem__("values", ["todo", "todo"]), "invalid enum")
        self.assertInvalid(lambda s: task_status(s).__setitem__("values", ["To Do", "done"]), "invalid enum")
        self.assertInvalid(lambda s: task_status(s).__setitem__("default", "archived"), "does not match type enum")
        self.assertInvalid(lambda s: s["entities"][1]["fields"].append({"name": "size", "type": "int", "required": False, "values": ["s"]}),
                           "values only allowed for enum")
        self.assertInvalid(lambda s: s["entities"][1]["fields"].append({"name": "id", "type": "int", "required": True}), "reserved")
        self.assertInvalid(lambda s: s["entities"][1]["fields"].append({"name": "assignee_id", "type": "int", "required": False}),
                           "collides with a field of Task")
        self.assertInvalid(lambda s: s["entities"][1]["fields"].append({"name": "due", "type": "date", "required": False, "default": "2026-02-30"}),
                           "does not match type date")
        self.assertInvalid(lambda s: s.__setitem__("mode", "model"), "mode: must be deterministic")
        self.assertInvalid(lambda s: s.pop("mode"), "missing keys ['mode']")
        self.assertInvalid(lambda s: s.__setitem__("extra", 1), "unknown keys ['extra']")
        self.assertInvalid(lambda s: s["source"].__setitem__("command", "ابنِ نظامًا آخر"), "source.sha256: does not match")
        self.assertInvalid(lambda s: s["nfr"].__setitem__("i18n", ["en ltr"]), "Arabic locale needs 'ar rtl'")
        self.assertInvalid(lambda s: s["features"].append(copy.deepcopy(s["features"][0])), "duplicate feature")
        self.assertInvalid(lambda s: s["features"][0]["acceptance_ar"].pop(), "one non-empty Arabic line per criterion")
        self.assertInvalid(lambda s: s["roles"][0]["permissions"].append("sudo"), "unknown ['sudo']")
        self.assertInvalid(lambda s: s["relations"][0].__setitem__("kind", "one-to-one"), "kind")
        self.assertInvalid(lambda s: s["integrations"].append({"id": "sms", "title": {"ar": "رسائل", "en": "SMS"}, "paid": True,
                                                              "network": True, "approved": False}), "paid service 'sms' is not approved")
        self.assertInvalid(lambda s: s["ai"].update(needed=True, use_cases=["forecasting"]), "needed but no provider")
        self.assertInvalid(lambda s: s.update(entities=[], relations=[], features=[]), "needs at least one entity")
        self.assertInvalid(lambda s: s.__setitem__("domain", None), "domain: invalid None (no open question explains it)")
        self.assertInvalid(lambda s: s.__setitem__("locales", ["fr"]), "locales")
        self.assertInvalid(lambda s: s["open_questions"].append({"id": "domain", "question": {"ar": "", "en": "x"}, "choices": None}),
                           "open_questions[0].question.ar: empty")

    def test_every_error_is_reported(self):
        def break_twice(spec):
            spec["entities"][0]["fields"][0]["type"] = "varchar"
            spec["features"][0]["acceptance"] = []
        error = self.assertInvalid(break_twice, "unknown field type")
        self.assertGreaterEqual(len(error.errors), 2)

    def test_non_object_spec(self):
        for value in (None, [], "spec"):
            with self.assertRaises(rq.SpecError):
                rq.validate_spec(value)

    def test_parse_acceptance_grammar(self):
        parsed = rq.parse_acceptance("GET /api/projects/{id}/progress for a project without tasks returns 200 and percent 0")
        self.assertEqual(parsed, {"method": "GET", "path": "/api/projects/{id}/progress", "condition": "for a project without tasks",
                                  "status": 200, "expect": "percent 0", "placeholders": ["id"]})
        for bad in ("", "returns 200", "FETCH /api returns 200", "GET api/tasks returns 200", "GET /api/tasks returns ok", None):
            with self.assertRaises(rq.SpecError):
                rq.parse_acceptance(bad)


class KnowledgeLoadingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name) / "domains"
        shutil.copytree(rq.DOMAINS, self.root)

    def edit(self, name, change):
        path = self.root / name
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def assertRefused(self, message):
        with self.assertRaises(rq.SpecError) as raised:
            rq.load_knowledge(self.root)
        self.assertIn(message, str(raised.exception))

    def test_copy_loads_and_parses_identically(self):
        self.assertEqual(rq.load_knowledge(self.root)["sha256"], rq.load_knowledge()["sha256"])
        self.assertEqual(rq.parse(PM_COMMAND, domains_dir=self.root), rq.parse(PM_COMMAND))

    def test_bad_packs_are_refused(self):
        self.edit("crm.json", lambda d: d["entities"][0]["fields"][0].__setitem__("type", "varchar"))
        self.assertRefused("unknown field type 'varchar'")

    def test_relation_to_missing_entity_in_pack(self):
        self.edit("inventory.json", lambda d: d["relations"].append({"from": "Product", "to": "Shelf", "kind": "many-to-one", "required": False}))
        self.assertRefused("relation to a missing entity 'Shelf'")

    def test_untestable_pack_acceptance(self):
        self.edit("kpi-dashboard.json", lambda d: d["features"][0]["acceptance"].__setitem__(0, {"en": "looks nice", "ar": "جميل"}))
        self.assertRefused("untestable acceptance criterion")

    def test_duplicate_json_key_and_id_mismatch(self):
        path = self.root / "crm.json"
        path.write_text(path.read_text(encoding="utf-8").replace('"version": 1,', '"version": 1, "version": 2,', 1), encoding="utf-8")
        self.assertRefused("duplicate JSON key 'version'")
        shutil.copy(rq.DOMAINS / "crm.json", path)
        shutil.copy(path, self.root / "crm-copy.json")
        self.assertRefused("must equal the file name")

    def test_phrase_claimed_by_two_packs(self):
        self.edit("crm.json", lambda d: d["keywords"]["en"].append("inventory"))
        self.assertRefused("claimed by packs")

    def test_symlink_and_missing_lexicon(self):
        (self.root / "link.json").symlink_to(self.root / "crm.json")
        self.assertRefused("symlinked")
        (self.root / "link.json").unlink()
        (self.root / "_common.json").unlink()
        self.assertRefused("lexicon is missing")
        with self.assertRaises(rq.SpecError):
            rq.load_knowledge(self.root / "nowhere")


class ChangeIntentTests(unittest.TestCase):
    def setUp(self):
        self.base = rq.parse(PM_COMMAND)

    def test_add_field_in_arabic_and_english(self):
        for command in ("أضف حقل الأولوية إلى المشاريع", "add a priority field to projects"):
            spec = rq.parse(command, base=self.base)
            self.assertEqual(spec["intent"], "change", command)
            self.assertIn("priority", fields(spec, "Project"))
            self.assertEqual(fields(spec, "Project")["priority"]["default"], "medium")
            self.assertEqual((spec["title"], spec["slug"], spec["domain"]), (self.base["title"], self.base["slug"], self.base["domain"]))
            self.assertIn("POST /api/projects with priority=not_a_value returns 400",
                          next(f for f in spec["features"] if f["id"] == "manage-projects")["acceptance"])

    def test_added_required_field_without_default_becomes_optional(self):
        spec = rq.parse("أضف البريد الإلكتروني للمشاريع", base=self.base)
        self.assertFalse(fields(spec, "Project")["email"]["required"])
        crm = rq.parse(COMMANDS["crm"][1])
        changed = rq.parse("add a severity field to deals", base=crm)
        self.assertFalse(fields(changed, "Deal")["severity"]["required"])
        self.assertIn("optional-field:Deal.severity", [a["id"] for a in changed["assumptions"]])

    def test_remove_entity_and_field(self):
        spec = rq.parse("add a budget to projects and remove the milestones", base=self.base)
        self.assertNotIn("Milestone", names(spec))
        self.assertIn("budget", fields(spec, "Project"))
        self.assertNotIn("milestones", feature_ids(spec))
        tasks = next(f for f in spec["features"] if f["id"] == "manage-tasks")
        self.assertFalse(any("milestone_id" in a for a in tasks["acceptance"]))
        arabic = rq.parse("احذف حقل الوصف من المهام", base=self.base)
        self.assertNotIn("description", fields(arabic, "Task"))
        self.assertIn("description", fields(arabic, "Project"))
        ambiguous = rq.parse("remove description", base=self.base)
        self.assertEqual(question_ids(ambiguous), ["remove_field:description"])
        self.assertEqual(ambiguous["open_questions"][0]["choices"], ["Project", "Task"])

    def test_permission_sentence_is_not_a_removal(self):
        spec = rq.parse("Build a project management system, members can delete their own tasks")
        self.assertEqual(names(spec), ["Project", "Task", "Member", "Milestone"])

    def test_optional_entity_and_pack_feature_follow(self):
        spec = rq.parse("طوّر نظام إدارة المشاريع وأضف تعليقات على المهام", base=self.base)
        self.assertIn("Comment", names(spec))
        self.assertTrue({"manage-comments", "task-comments"} <= set(feature_ids(spec)))
        self.assertEqual(feature_ids(spec)[:len(self.base["features"])], feature_ids(self.base))

    def test_base_refusals(self):
        with self.assertRaises(rq.SpecError):
            rq.parse("ابنِ نظامًا جديدًا لإدارة المشاريع", base=self.base)
        with self.assertRaises(rq.SpecError):
            rq.parse("add comments", base=rq.parse("ابنِ نظامًا"))
        broken = copy.deepcopy(self.base)
        broken["entities"][0]["fields"][0]["type"] = "blob"
        with self.assertRaises(rq.SpecError):
            rq.parse("add comments", base=broken)


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.base = rq.parse(PM_COMMAND)

    def test_identical(self):
        diff = rq.diff_specs(self.base, copy.deepcopy(self.base))
        self.assertTrue(diff["identical"])
        self.assertEqual(diff["summary"], {"added": 0, "removed": 0, "changed": 0, "breaking": 0})
        self.assertEqual((diff["schema"], diff["mode"]), ("gaie.spec-diff/1", "deterministic"))
        self.assertEqual(diff["old_sha256"], rq.validate_spec(self.base)["spec_sha256"])

    def test_additive_change_is_not_breaking(self):
        new = rq.parse("طوّر نظام إدارة المشاريع وأضف تعليقات على المهام وأضف الأولوية للمشاريع", base=self.base)
        diff = rq.diff_specs(self.base, new)
        self.assertEqual(diff["entities"]["added"], ["Comment"])
        self.assertEqual(diff["entities"]["changed"][0]["name"], "Project")
        self.assertEqual(diff["entities"]["changed"][0]["fields"]["added"], ["priority"])
        self.assertIn("task-comments", diff["features"]["added"])
        self.assertIn("manage-projects", [c["id"] for c in diff["features"]["changed"]])
        self.assertEqual({r["from"] for r in diff["relations"]["added"]}, {"Comment"})
        self.assertEqual(diff["breaking"], [])
        self.assertFalse(diff["identical"])
        self.assertEqual(diff, rq.diff_specs(self.base, new))

    def test_breaking_changes_are_flagged(self):
        removed = rq.parse("remove the milestones", base=self.base)
        diff = rq.diff_specs(self.base, removed)
        kinds = {b["kind"] for b in diff["breaking"]}
        self.assertTrue({"entity-removed", "relation-removed", "feature-removed"} <= kinds)
        self.assertEqual(diff["entities"]["removed"], ["Milestone"])
        edited = copy.deepcopy(self.base)
        status = next(f for f in edited["entities"][1]["fields"] if f["name"] == "status")
        status["values"] = ["todo", "done"]
        status["default"] = "todo"
        estimate = {"name": "estimate", "type": "int", "required": True}
        edited["entities"][1]["fields"].append(estimate)
        next(f for f in edited["entities"][0]["fields"] if f["name"] == "description")["type"] = "int"
        next(f for f in edited["entities"][0]["fields"] if f["name"] == "description").pop("max")
        edited["locales"] = ["ar"]
        edited["nfr"]["i18n"].remove("en ltr")
        edited["features"] = [f for f in edited["features"] if f["id"] != "ui-locales"]
        diff = rq.diff_specs(self.base, edited)
        kinds = [b["kind"] for b in diff["breaking"]]
        for kind in ("enum-values-removed", "required-field-added", "field-type-changed", "locale-removed", "feature-removed"):
            self.assertIn(kind, kinds)
        self.assertEqual(next(b for b in diff["breaking"] if b["kind"] == "enum-values-removed")["values"], ["in_progress"])
        self.assertIn("locales", diff["scalars"])
        self.assertEqual(diff["nfr"]["removed"], {"i18n": ["en ltr"]})

    def test_invalid_input_is_refused(self):
        with self.assertRaises(rq.SpecError):
            rq.diff_specs(self.base, {"schema": "gaie.spec/1"})
        result = rq.engine("diff", {"old": self.base, "new": self.base})
        self.assertTrue(result["result"]["diff"]["identical"])


if __name__ == "__main__":
    unittest.main()
