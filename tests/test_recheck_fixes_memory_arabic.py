"""recheck-authz M2: Arabic password and token labels in prose, at parity with the English rule.

The memory guard refused English "the password is X" but stored the Arabic "كلمة المرور هي X", the
common spelling "كلمه", a label with harakat or tatweel, words between the label and the colon, and the
loanwords التوكن / الباسورد. The Arabic rule now takes the same separators as the English one (":", "="
and the prose "is": هي / هو), up to three words in between, ة/ه and ي/ى spellings and a copy of the text
without Arabic marks. A label with no such separator is prose and stays storable. Every credential is a
synthetic look-alike.
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engineering_os import memory  # noqa: E402
from engineering_os.memory import MemoryStore, SecretRefused  # noqa: E402

VALUE = "Sup3r" + "S3cretValue"
REFUSED = {  # the value is always a separate literal, so this source file itself holds no labelled secret
    "password is (هي)": "كلمة المرور هي " + VALUE,
    "password is (هو)": "كلمة المرور هو " + VALUE,
    "ha spelling (كلمه)": "كلمه المرور: " + VALUE,
    "ha spelling, secret word": "كلمه السر = " + "hunter2hunter2",
    "harakat": "كلمةُ المرورِ: " + VALUE,
    "tatweel": "كلمـة المـرور: " + VALUE,
    "two spaces": "كلمة  المرور: " + VALUE,
    "suffix on the label": "كلمة مروري: " + VALUE,
    "words between, colon": "كلمة المرور الخاصة بي: " + VALUE,
    "words between, is": "كلمة المرور الجديدة للخادم هي " + VALUE,
    "token loanword": "التوكن: " + VALUE,
    "token loanword, is": "توكن الخادم هو " + VALUE,
    "password loanword": "الباسورد: " + VALUE,
    "password loanword, is": "الباسورد هو " + VALUE,
    "pin with alif maqsura": "الرقم السرى: " + "48151623",
    "secret code": "الرمز السري: " + "4815",
    "api key with tatweel article": "مفتاح الـAPI: " + "abcd1234efgh",
    "english control": "the password is " + VALUE,
}
STORABLE = (
    "كلمة المرور يجب أن تكون طويلة وفريدة",  # the existing controls of the first M2 fix
    "الرقم السري مطلوب لكل مستخدم",
    "مفتاح النجاح هو الاختبار المستمر",
    "رمز الحالة: 200 يعني أن الطلب نجح",
    "هل نسيت كلمة المرور؟ استخدم رابط الاستعادة",
    "التوكن يُخزن في متغير بيئة وليس في الذاكرة",
    "الباسورد لا يُحفظ في الذاكرة أبدًا",
    "غيّر كلمة المرور كل تسعين يومًا",
    "رمز التحقق يصل خلال دقيقة",
    "مفتاحُ الحلِّ هو الاختبار",
)
UI_STRINGS = "كلمة المرور غير صحيحة\",\n      \"min_length\": \"النص قصير\""  # in-between words never cross a line


def record(text):
    return {"project": "demo", "kind": "lesson", "title": "Arabic label probe", "summary": text, "tags": [], "symbols": [],
            "links": [], "provenance": {"engine": "codex", "source_sha256": "a" * 64}}


class ArabicProseLabels(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rf4-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.addCleanup(temporary.cleanup)
        self.tmp = pathlib.Path(temporary.name)
        os.chmod(self.tmp, 0o700)

    def test_each_variant_is_refused_by_the_guard(self):
        for name, text in REFUSED.items():
            with self.subTest(case=name), self.assertRaises(SecretRefused):
                memory._refuse_secrets(text)

    def test_labels_without_a_separator_stay_storable(self):
        for text in (*STORABLE, UI_STRINGS):
            with self.subTest(text=text):
                memory._refuse_secrets(text)

    def test_nothing_reaches_disk_through_the_store_or_the_engine_contract(self):
        store = MemoryStore.for_project(self.tmp / "state", "demo")
        store.put(record("baseline"))
        before = store.snapshot()
        for name, text in REFUSED.items():
            with self.subTest(case=name):
                with self.assertRaises(SecretRefused):
                    store.put(record(text))
                with self.assertRaises(SecretRefused):
                    memory.invoke("put", {"project": "demo", "record": record(text)}, {"state_dir": str(self.tmp / "state")})
        self.assertEqual(store.snapshot(), before)
        disk = b"".join(path.read_bytes() for path in (self.tmp / "state").rglob("*") if path.is_file())
        self.assertNotIn(VALUE.encode(), disk)
        for text in STORABLE:
            store.put(record(text))

    def test_the_command_line_refuses_the_reviewers_arabic_sentence(self):
        home = self.tmp / "home"
        home.mkdir(mode=0o700)
        env = {**os.environ, "GAIE_HOME": str(home)}
        cli = [sys.executable, str(ROOT / "engineering_os/gaie_memory.py"), "--project", "demo"]
        added = subprocess.run([*cli, "add", "--kind", "lesson", "--title", "k", "--body", REFUSED["password is (هي)"]],
                               capture_output=True, text=True, env=env, timeout=60, cwd=self.tmp)
        self.assertIn("refused", added.stdout + added.stderr)
        found = subprocess.run([*cli, "search", "المرور"], capture_output=True, text=True, env=env, timeout=60, cwd=self.tmp)
        self.assertNotIn(VALUE, found.stdout + found.stderr)
        self.assertNotIn(VALUE.encode(), b"".join(path.read_bytes() for path in home.rglob("*") if path.is_file()))


if __name__ == "__main__":
    unittest.main()
