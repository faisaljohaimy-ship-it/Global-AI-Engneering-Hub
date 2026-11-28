"""Review fix w2-memory-heal-orch M2: the memory secret guard and Arabic letters touching a key.

`\\b` counts an Arabic letter, a digit or "_" as part of a word, so "وAKIA…" (the conjunction wa- attached
to an AWS key), "aws_AKIA…" and Arabic-prefixed Stripe, Google, ElevenLabs and JWT shapes were stored,
as was "كلمة المرور: …". The token edges are now ASCII-aware and Arabic password labels are refused.
Every credential below is a synthetic look-alike built from fragments at run time.
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

AWS = "AKIA" + "IOSFODNN7EXAMPLE"
REFUSED = {
    "aws_arabic_prefix": "المفتاح" + AWS,
    "aws_conjunction": "و" + AWS,
    "aws_arabic_suffix": AWS + "هنا",
    "aws_underscore": "aws_" + AWS,
    "stripe_arabic": "مفتاح" + "sk_" + "live_" + "a1B2c3D4e5F6g7H8i9J0k1L2",
    "google_arabic": "مفتاح" + "AI" + "za" + "A" * 35,
    "github_arabic_short": "رمز" + "gh" + "p_" + "A" * 25,
    "elevenlabs_arabic": "مفتاح" + "sk_" + "a" * 48,
    "jwt_arabic": "رمز" + "ey" + "JhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0x" + "." + "abcdefghijklmnopqrstuvwxyz012",
    "bearer_arabic": "رأس" + "Bea" + "rer " + "d" * 24,
    "password_arabic": "كلمة المرور" + ": Sup3rS3cretValue",
    "password_arabic_no_article": "كلمة مرور" + "=Sup3rS3cretValue",
    "secret_word_arabic": "كلمة السر" + ": hunter2hunter2",
    "pin_arabic": "الرقم السري" + ": 48151623",
    "access_code_arabic": "رمز الدخول" + ": Zx81Qw77",
    "api_key_arabic": "مفتاح API" + ": abcd1234efgh",
    "marker_arabic": "وCONFI" + "DENTIAL خطة العميل",
}
STORABLE = (
    "Use integer cents for money.",
    "Keys that start with AKIA are AWS access keys; never paste one here.",
    "disk-usage-monitoring-dashboard-panel-view",
    "risk_live_dashboard_metrics_view_extra",
    "task_" + "0" * 48,
    "X" + AWS + "YZ",
    "مفتاح النجاح هو الاختبار المستمر",
    "كلمة المرور يجب أن تكون طويلة وفريدة",
    "رمز الحالة: 200 يعني أن الطلب نجح",
    "الرقم السري مطلوب لكل مستخدم",
    "تحسين الأمان والأداء في سديد",
    "Private state stays in a 0700 directory.",
)


def record(text):
    return {"project": "demo", "kind": "lesson", "title": "Secret guard probe", "summary": text, "tags": [], "symbols": [],
            "links": [], "provenance": {"engine": "codex", "source_sha256": "a" * 64}}


class ArabicAdjacentSecretTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gaie-m2-")
        self.addCleanup(temporary.cleanup)
        self.tmp = pathlib.Path(temporary.name)
        os.chmod(self.tmp, 0o700)

    def test_each_reviewed_shape_is_refused_by_the_guard(self):
        for name, text in REFUSED.items():
            with self.subTest(case=name), self.assertRaises(SecretRefused):
                memory._refuse_secrets(text)

    def test_ordinary_english_and_arabic_prose_is_still_storable(self):
        for text in STORABLE:
            with self.subTest(text=text[:30]):
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
        for text in REFUSED.values():
            self.assertNotIn(text.encode(), disk)
        for text in STORABLE:
            store.put(record(text))

    def test_the_command_line_refuses_the_reviewers_key_and_stores_nothing(self):
        home = self.tmp / "home"
        home.mkdir(mode=0o700)
        env = {**os.environ, "GAIE_HOME": str(home)}
        added = subprocess.run([sys.executable, str(ROOT / "engineering_os/gaie_memory.py"), "--project", "demo", "add",
                                "--kind", "decision", "--title", "aws key", "--body", REFUSED["aws_conjunction"]],
                               capture_output=True, text=True, env=env, timeout=60, cwd=self.tmp)
        self.assertIn("refused", added.stdout + added.stderr)
        found = subprocess.run([sys.executable, str(ROOT / "engineering_os/gaie_memory.py"), "--project", "demo", "search", "aws"],
                               capture_output=True, text=True, env=env, timeout=60, cwd=self.tmp)
        self.assertNotIn(AWS, found.stdout + found.stderr)
        disk = b"".join(path.read_bytes() for path in home.rglob("*") if path.is_file())
        self.assertNotIn(AWS.encode(), disk)


if __name__ == "__main__":
    unittest.main()
