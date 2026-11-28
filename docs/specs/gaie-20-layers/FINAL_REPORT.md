# GAIE OS — final report (draft skeleton) · التقرير النهائي (هيكل مسودة)

Status of this file: a draft written at `5805d31` on `claude/eager-feynman-kztjo4`, with
the facts of the release-prep merge `8d29263`. Every statement is true at that base and
names a path or a test. Parts that lanes are still building carry the marker
**[to be completed at the final head]** / **[يُستكمل عند الرأس النهائي]**. Arabic comes
first, then English, with the same content. `tests/test_status_docs.py` checks the
scenario matrix in both languages against the test files and against
`docs/specs/gaie-20-layers/RESUME.md`.

---

## العربية

### 1. النطاق

يغطي هذا التقرير دمج نظام GAIE ذي الطبقات العشرين في الفرع
`claude/eager-feynman-kztjo4` (طلب الدمج #31، مسودة، قاعدته `main` عند `65c84fe`). لم
يصل شيء منه إلى `main` بعد. لم يُنشر شيء، ولم يُعدَّل أي منتج، ولم يُنشأ أي مستودع، ولم
تُضف خدمة مدفوعة. الحالة الخاصة (الإيصالات والذاكرة والسجلات) تبقى خارج Git في
`$GAIE_HOME`. صفحة الاستئناف هي `docs/specs/gaie-20-layers/RESUME.md`، وحالة كل طبقة
في `docs/OPERATING_SYSTEM_STATUS.md`.

### 2. ما دُمج، مع معرّفات الالتزامات

| الالتزام | ما هو | الدليل |
|---|---|---|
| `0986919` | طلب الدمج #27 عند `b7097df` مدموجًا فوق `main` `65c84fe`: الطبقات العشرون، وحزمة السرب المجمّدة (`b7097df`)، ومحركات الحركة الأصلية (`6bee21a`)، وذكاء الجيل التالي (`e72a98a`)، وتحسين السياق (`f366bf0`) | 9 من 9 فحوص GitHub ناجحة على `0986919` (`RESUME.md`) |
| `7aedd71` | طلب الدمج #27 عند `7f77665`: عدة المشاهد الرقمية، الإصدار السينمائي الثاني، إصلاح SEC-08 | `RESUME.md`، "Lineage of the branch" |
| `ff3368e` | التقوية الأمنية في طلب الدمج #30 (`df35563`)، محلولة في `077a934` و`79a5e8d` و`30c7bfd` و`e3f4c8d` | `docs/specs/gaie-20-layers/MASTER_SECURITY_ACCEPTANCE.md` |
| `f95b85e` | مسار سياسة الحركة الهادفة (`b644cb1` و`9373f04` و`a57a35f`) | `tests/test_motion_policy.py` (33 ناجحًا عند هذه القاعدة) |
| `8d29263` | مسار تجهيز الإصدار (`2bf7bb1` و`d44c871` و`6f0e73f` و`8a4e01e`): وسم SDK ‏1.0.1، وقائمة فحوص الإصدار، وسجل التغييرات، وقائمة ما بعد الدمج | `scripts/verify_release.py`، `docs/specs/gaie-20-layers/RELEASE_CHECKLIST.md` |

ما زالت المسارات التالية تعمل: تسجيل المحركات، وربط الطبقات بالسيناريوهات، ووحدة الضمان
L20، والسيناريو G، وعزل الأمن، والنتائج الأمنية، وفريق الوكلاء العشرين، ووثائق MASTER،
والتثبيت، والتكامل المستمر، والتفعيل، ونقل الحركات، وإصلاحات المراجعة، ووثائق الحالة.
**[يُستكمل عند الرأس النهائي]**: معرّف كل دمج وما أثبته.

### 3. الطبقات العشرون

السجل هو `governance/layers.json` (20 طبقة) والمحركات في `governance/engines.json`
(18 محركًا؛ `python3 hub.py engine-health` أعاد `ok: true` عند هذه القاعدة). عمود
"السيناريو" يذكر الطبقة التي يقع فيها كود السيناريو؛ السجل لا يربط أي سيناريو بعد
(`"scenarios": []` في كل طبقة).

| الطبقة | المحركات | السيناريو | المفتوح عند هذه القاعدة |
|---|---|---|---|
| L01 المالك والسياسات والحوكمة | security-governor | E | سياسة الفريق وبيان وثائق MASTER قيد العمل |
| L02 الذكاء الاصطناعي وتوجيه النماذج | context-intelligence | — | لا إصدار نموذج تشغيلي ولا استدعاء مزوّد |
| L03 التنسيق التكيّفي للوكلاء | master-router، agent-swarm، adaptive-scheduler | H | `orchestrator` خارج مستوى التحكم؛ النتيجة M3 |
| L04 مستوى التحكم الهندسي | capability-registry، layers | — | ستة محركات من الموجة الثانية خارج مستوى التحكم |
| L05 ذكاء التكامل الشامل | لا يوجد | — | A2A وACP غير منفّذين؛ النتيجة F1 |
| L06 هندسة البرمجيات | master-upgrade | B | `upgrade_engine` خارج مستوى التحكم؛ النتيجة F3 |
| L07 ذكاء البيانات والمعرفة | لا يوجد | — | لا قاعدة بيانات مشتركة |
| L08 السينما والحركة ومعالجة الرسوميات | motion-sdk | — | لا تشغيل GPU أو ثلاثي الأبعاد مُثبت؛ نقل الحركات قيد العمل |
| L09 ذكاء الأمن والجودة | quality-assurance | — | SEC-07 وSEC-10 وSEC-12 و`private-mode`؛ مستوى العزل في CI هو `plain` |
| L10 منظومة المنتجات المستقلة | لا يوجد | — | مستودعات المنتجات الخاصة غير مسجلة |
| L11 ذكاء السحابة والنشر | master-release | G (جزئي) | محرك الإصدار قيد العمل |
| L12 الذكاء التقني المستمر | master-audit | — | الاكتشاف لا يثبّت ولا يعتمد |
| L13 الاستدلال الهندسي المتقدم | reasoning | — | النتيجتان M5 وL6 |
| L14 الذاكرة الهندسية الدائمة | memory | D | النتائج M1 وM2 وF2 وSEC-10 |
| L15 ذكاء المتطلبات والمواصفات | لا يوجد | — | `requirements` خارج مستوى التحكم |
| L16 مصنع البرمجيات الذاتي | master-build | A، I (جزئي) | `build_engine` خارج مستوى التحكم |
| L17 ذكاء الإصلاح الذاتي والتعافي | self-healing | F | النتيجة H1 (عالية) وSEC-07 |
| L18 الذكاء السينمائي المتقدم | master-cinematic | C | `video_pipeline` خارج مستوى التحكم |
| L19 اقتصاديات الهندسة وذكاء الموارد | economics | — | محاسبة دون اتصال فقط |
| L20 الضمان الهندسي المستقل | لا يوجد | — | `engineering_os/assurance.py` غير مدمج بعد |

يسجّل `RESUME.md` (قسم "Acceptance scenarios") أن `python3 hub.py layers --verify` أعطى
20 من 20 طبقة `VERIFIED`. السجل يذكر 35 ملف اختبار من 104 في `tests/` عند هذه القاعدة
ولا يربط أي سيناريو، فهذه النتيجة ليست حكمًا على السيناريوهات A–I. **[يُستكمل عند الرأس النهائي]**: الربط ونتيجة التحقق الجديدة.

### 4. مصفوفة سيناريوهات القبول A–I

قيست عند `5805d31` بتشغيل كل ملف وحده: `python3 -m unittest tests.<module>` مع
`TMPDIR=/tmp` و`GAIE_HOME` خارج Git، على مضيف لينكس بأربعة معالجات.

<!-- scenario-matrix:ar -->
| السيناريو | الموضوع | الحالة | ملف الاختبار | أصناف الاختبار | المقيس عند هذه القاعدة |
|---|---|---|---|---|---|
| A | البناء الرئيسي | ناجح (`passing`) | `tests/test_build_engine_e2e.py` | `ScenarioATests` | 4 ناجحة في 90.7 ثانية مع تشغيل المتصفح؛ `tests/test_build_engine.py` ‏31 ناجحًا |
| B | الترقية الرئيسية | ناجح (`passing`) | `tests/test_upgrade_engine.py` | `ScenarioB` | 49 ناجحًا |
| C | خط إنتاج الفيديو | ناجح (`passing`) | `tests/test_video_pipeline.py` | `ScenarioCTests` | 48 ناجحًا، وتخطٍّ واحد: الوسائط النموذجية محفوظة خارج Git |
| D | استئناف الذاكرة | ناجح (`passing`) | `tests/test_memory_unified.py` | `ScenarioDTests` | 26 ناجحًا |
| E | الحاكم الأمني | ناجح (`passing`) | `tests/test_governor.py` | `CheckTests`, `AuditTests`, `StrictSandboxTests`, `SandboxTests` | 56 ناجحًا؛ اختبارات العزل تُتخطّى في CI |
| F | الإصلاح الذاتي | ناجح (`passing`) | `tests/test_self_healing_loop.py` | `ScenarioF` | 20 ناجحًا؛ النتيجة H1 العالية مفتوحة |
| G | محرك الإصدار | جزئي (`partial`) | `tests/test_release_provenance.py` | `ReleaseProvenanceTests` | 6 ناجحة للأجزاء القرائية فقط؛ لا اختبار قبول بعد. **[يُستكمل عند الرأس النهائي]** |
| H | التنسيق التكيّفي | ناجح (`passing`) | `tests/test_orchestrator.py` | `ScenarioHTests` | 38 ناجحًا، وتخطٍّ واحد: ملف القياسات الحية خارج المستودع |
| I | التثبيت الدائم في Claude Code | جزئي (`partial`) | `tests/test_gaie_factory.py` | `BootstrapTests` | 21 ناجحًا لآليات التثبيت فقط؛ لا اختبار قبول ولا إثبات في جلسة جديدة. **[يُستكمل عند الرأس النهائي]** |
<!-- /scenario-matrix -->

النجاح في الاختبار لا يغلق نتائج المراجعة المذكورة في القسم 9.

### 5. النتائج الأمنية والعزل كما قيسا

`docs/evidence/gaie-20-layers/security-findings.json` (ناتج
`python3 -m engineering_os.security_audit`): 7 مُصلحة، 1 مخففة، 4 صامدة، 6 مقبولة
بسبب مسجّل، 4 مفتوحة، ولا نتيجة حرجة أو عالية مفتوحة. المفتوحة:

- SEC-07 (متوسطة): `detectors.Sandbox` حارس على مستوى بايثون دون عزل نظام التشغيل.
- SEC-10 (منخفضة): سجل `gaie_memory` المجمّد يُلحَق دون فحص المالك أو الوضع أو الروابط الصلبة.
- SEC-12 (متوسطة): `layers.verify` يعلن `exec:sandbox` لكنه يشغّل الاختبارات خارج صندوق
  الحاكم وببيئة المستدعي.
- `private-mode` (متوسطة): `engineering_os/build_engine.py:1425` ينشئ مجلدًا بالوضع 0o755.

العزل: `docs/evidence/gaie-20-layers/isolation.json` قيس على مضيف واحد في 2026-11-28
بالمستوى `full` (مساحة PID وشبكة خاصتان، بيئة فارغة، الكتابة في المسارات المسموحة فقط)،
ويذكر ما لا يُفرض (عدد العمليات عند الربط بالمستخدم 0، ومقابس يونكس داخل المسارات
المسموحة، وغياب مرشح seccomp). في GitHub CI المستوى `plain` (`RESUME.md`، قسم "What the mapping
stage established")، فتُتخطّى `SandboxTests` في `tests/test_governor.py`. وجد المراجع أن هذا الملف قديم بعد الدمج الأمني
(pr30-merge-quality F3). **[يُستكمل عند الرأس النهائي]**: إصلاح SEC-07 وSEC-10 وSEC-12،
وملف عزل مُعاد توليده، ووظيفة CI تفرض المستوى `full`.

### 6. السياسات الدائمة

- فريق العشرين وكيلًا: `governance/agent-roles.json` يحوي 20 دورًا في 8 فرق. لا يوجد
  ملف سياسة مركزي للفريق عند هذه القاعدة. **[يُستكمل عند الرأس النهائي]**
- الحركة الهادفة: `governance/policies/motion-purpose.json` (الإصدار 1.0.0، نافذ من
  2026-11-28) يشترط أن تذكر كل حركة معناها بجملة في كل لغة. المدقق
  `engineering_os/motion_policy.py`؛ `python3 -m engineering_os.motion_policy` أعاد
  `ok: true`: 47 هادفة، 37 قديمة غير مصنفة، 400 مرجعية، 156 فهرس مواصفات، 5 مسحوبة، 0
  بلا تصنيف. الاختبارات: `tests/test_motion_policy.py` (33 ناجحًا)
  و`packages/motion-engines/test/purpose.test.mjs` (12 ناجحًا).
- وثائق MASTER: `prompts/MASTER_BUILD.md` و`prompts/MASTER_UPGRADE.md` موجودتان، ويضع
  `scripts/gaie_bootstrap.py` نسخة منهما في مهارتي `gaie-build` و`gaie-upgrade` المثبتتين. البيان المركزي بالإصدار
  والبصمة واختبار الانحراف قيد العمل. **[يُستكمل عند الرأس النهائي]**

### 7. التثبيت

التفاصيل في `docs/GAIE_FACTORY.md`، قسم "Installation in Claude Code". عند هذه القاعدة:
النسخ الملتزمة في هذا المستودع تطابق المصادر (`tests/test_gaie_factory.py`)؛ وتثبيت
المشروع بـ `scripts/gaie_bootstrap.py` جُرّب في مشروع Git مستقل (16 ملفًا، كلها `current`،
والموجّه المنسوخ يوجّه)، لكن مهارة الموجّه المثبتة تذكر ثلاثة مسارات غير موجودة بعد هذا
التثبيت؛ وتسجيل `pack:gaie-factory` يُرفض أمام `main` ‏`65c84fe`؛ والتثبيت كإضافة من
GitHub يحتاج الملفات على `main`. لا توجد طريقة تثبيت مُثبتة في جلسة حقيقية عند هذه القاعدة.
**[يُستكمل عند الرأس النهائي]**: السيناريو I وإثباته.

### 8. التكامل المستمر

تسعة ملفات سير عمل في `.github/workflows/`. يشترط `scripts/verify_release.py` (عند
`8d29263`) نجاح تسع وظائف في ستة منها على التزام الإصدار نفسه. تشغّل `verify.yml`
و`operating-system.yml` حزمة الاختبارات كاملة (`python3 -m unittest discover -s tests`).
مستوى العزل في CI هو `plain`. **[يُستكمل عند الرأس النهائي]**: حدود الوقت، واختبارات node
غير المشغّلة، ووظيفة العزل الإيجابية، ونتيجة CI على الرأس النهائي.

### 9. المراجعة المستقلة

كل نتيجة يصلحها مسار لم يراجعها، ثم يعيد المراجع فحصها. السجل في `RESUME.md` قسم
"Independent review register" (عند `8d29263`).

| المراجعة | الحكم | النتائج |
|---|---|---|
| pr30-authz | موافقة مع إصلاحات | F1 متوسطة (تجاوز `checkout_guard` عبر إعداد وحدة فرعية يشغّل مرشحًا مزروعًا)، F2 وF3 منخفضتان |
| pr30-merge-quality | موافقة مع إصلاحات | لم يضع الدمج شيئًا ولم يضعف شيئًا؛ F1–F4 منخفضة (مجسّا SEC-09 وSEC-11 ووثائق قديمة) |
| w2-memory-heal-orch | موافقة مع إصلاحات | H1 عالية (الإصلاح الذاتي يعلن "أُصلح" وتصحيحه يضيف خللًا)، M1–M5 متوسطة، L1–L7 منخفضة |
| pr30-isolation | قيد التشغيل | **[يُستكمل عند الرأس النهائي]** |
| w2-build-upgrade | قيد التشغيل | **[يُستكمل عند الرأس النهائي]** |

النتيجة H1 تمنع الإصدار حتى تُصلح ويُعاد فحصها. **[يُستكمل عند الرأس النهائي]**: المراجعة
الهندسية المستقلة للفرع كله.

### 10. حالة الإصدار: مسجّل، والوسم معلّق

الإصدار هو دمج طلب #31 في `main` ثم إصدار GitHub بوسم جديد `engineering-os-vX.Y.Z`
على التزام الدمج نفسه (`docs/specs/gaie-20-layers/RELEASE_CHECKLIST.md` عند `8d29263`).
الوسوم الموجودة: `engineering-os-v0.1.0` حتى `engineering-os-v0.1.4` و`engineering-sdk-v1.0.0`،
ولا وسم للإصدار الحالي. وسم Engineering SDK ‏1.0.1 لأن ملفاته تغيّرت بعد وسم
`engineering-sdk-v1.0.0`، ويُشحن داخل إصدار النظام بلا وسم خاص. الحالة: **مسجّل، والوسم
معلّق**. لم يُنشر شيء.

### 11. قرارات المالك المفتوحة

- رقم الإصدار، وجعل طلب #31 جاهزًا ودمجه، ونشر إصدار GitHub (`RELEASE_CHECKLIST.md`،
  الخطوة 6).
- تسجيل مستودعات BILTIX والمحفظة الشخصية وKPI والمختبر الأمني في السجل الخاص
  (`docs/specs/gaie-20-layers/ROUTER.md`، جدول المشاريع).
- الموافقة على مستودع التطبيق المولَّد وترخيصه ومكان نشره (`publish` في
  `docs/specs/gaie-20-layers/BUILD_ENGINE.md`؛ الملف المولَّد `LICENSE-PENDING.md`).
- ترقية أو سحب الحركات القديمة غير المصنفة (37)، حركةً حركة (`owner_decisions` في
  `governance/policies/motion-purpose.json`، ولا سجل فيه بعد).
- الشروط التجارية لصوت السرد والموسيقى المقدَّمة: أبلغت بها الجلسة السابقة، ولم تُكتب في
  الشجرة بعد.
- إثبات التثبيت في جلسة Claude Code جديدة يستهلك من حصة الخطة؛ يقرر المالك تشغيله.

### 12. كيفية الاستئناف

ابدأ من `docs/specs/gaie-20-layers/RESUME.md` (قسم "How to pick up") والفرع
`claude/eager-feynman-kztjo4`. اجعل `GAIE_HOME` خارج Git و`TMPDIR=/tmp`، وشغّل
`python3 -m unittest discover -s tests` و`python3 hub.py audit` و
`python3 scripts/security_scan.py scan` و`python3 hub.py layers --verify`. الإيصالات
والذاكرة ليست على جهاز جديد؛ أعد التحقق في كل بيئة جديدة.

---

## English

### 1. Scope

This report covers the GAIE twenty-layer integration on branch
`claude/eager-feynman-kztjo4` (PR #31, draft, base `main` at `65c84fe`). None of it is
on `main` yet. Nothing was deployed, no product was modified, no repository was created
and no paid service was added. Private state (receipts, memory, ledgers) stays outside
Git in `$GAIE_HOME`. The pick-up page is `docs/specs/gaie-20-layers/RESUME.md`; the
per-layer status is in `docs/OPERATING_SYSTEM_STATUS.md`.

### 2. What was integrated, with commit SHAs

| Commit | What it is | Evidence |
|---|---|---|
| `0986919` | PR #27 at `b7097df` merged onto `main` `65c84fe`: the twenty layers, the frozen swarm stack (`b7097df`), native motion engines (`6bee21a`), next-generation intelligence (`e72a98a`), context optimization (`f366bf0`) | 9 of 9 GitHub checks green on `0986919` (`RESUME.md`) |
| `7aedd71` | PR #27 at `7f77665`: digital-shows scene kit, cinematic edition 2, SEC-08 fix | `RESUME.md`, "Lineage of the branch" |
| `ff3368e` | Security hardening of PR #30 (`df35563`), resolved as `077a934`, `79a5e8d`, `30c7bfd`, `e3f4c8d` | `docs/specs/gaie-20-layers/MASTER_SECURITY_ACCEPTANCE.md` |
| `f95b85e` | Purposeful motion policy lane (`b644cb1`, `9373f04`, `a57a35f`) | `tests/test_motion_policy.py` (33 OK at this base) |
| `8d29263` | Release-prep lane (`2bf7bb1`, `d44c871`, `6f0e73f`, `8a4e01e`): SDK label 1.0.1, release gate list, changelog, post-merge checklist | `scripts/verify_release.py`, `docs/specs/gaie-20-layers/RELEASE_CHECKLIST.md` |

Still working: engine registration, layer-to-scenario binding, the L20 assurance module,
scenario G, security isolation, security findings, the twenty-agent team, the MASTER
documents, installation, CI, activation, the motion port, review fixes and these status
documents. **[to be completed at the final head]**: each merge SHA and what it proved.

### 3. The twenty layers

The registry is `governance/layers.json` (20 layers); engines are in
`governance/engines.json` (18 engines; `python3 hub.py engine-health` returned
`ok: true` at this base). The "Scenario" column names the layer that holds a scenario's
code; the registry binds no scenario yet (`"scenarios": []` on every layer).

| Layer | Engines | Scenario | Open at this base |
|---|---|---|---|
| L01 Owner, Policy & Governance | security-governor | E | team policy and MASTER manifest in progress |
| L02 AI Intelligence & Model Routing | context-intelligence | — | no operational model version, no provider call |
| L03 Adaptive Agent Orchestration | master-router, agent-swarm, adaptive-scheduler | H | `orchestrator` outside the control plane; finding M3 |
| L04 Engineering Control Plane | capability-registry, layers | — | six wave-2 engines outside the control plane |
| L05 Universal Integration Intelligence | none | — | A2A and ACP not implemented; finding F1 |
| L06 Software Engineering | master-upgrade | B | `upgrade_engine` outside the control plane; finding F3 |
| L07 Data & Knowledge Intelligence | none | — | no shared database |
| L08 Cinematic, Motion & GPU | motion-sdk | — | no GPU or 3D runtime verified; motion port in progress |
| L09 Security & Quality Intelligence | quality-assurance | — | SEC-07, SEC-10, SEC-12, `private-mode`; CI sandbox tier `plain` |
| L10 Independent Product Ecosystem | none | — | private product repositories not registered |
| L11 Cloud & Deployment Intelligence | master-release | G (partial) | release engine in progress |
| L12 Continuous Technology Intelligence | master-audit | — | discovery never installs or approves |
| L13 Advanced Engineering Reasoning | reasoning | — | findings M5, L6 |
| L14 Persistent Engineering Memory | memory | D | findings M1, M2, F2, SEC-10 |
| L15 Requirements & Specification Intelligence | none | — | `requirements` outside the control plane |
| L16 Autonomous Software Factory | master-build | A, I (partial) | `build_engine` outside the control plane |
| L17 Self-Healing & Recovery Intelligence | self-healing | F | finding H1 (high), SEC-07 |
| L18 Advanced Cinematic Intelligence | master-cinematic | C | `video_pipeline` outside the control plane |
| L19 Engineering Economics & Resource Intelligence | economics | — | offline accounting only |
| L20 Independent Engineering Assurance | none | — | `engineering_os/assurance.py` not yet integrated |

`RESUME.md` ("Acceptance scenarios") records 20 of 20 layers `VERIFIED` from
`python3 hub.py layers --verify`. The registry lists 35 of the 104 test files in
`tests/` at this base and binds no scenario, so that result is not a verdict on
scenarios A–I. **[to be completed at the final head]**: the binding and a
fresh verification result.

### 4. Acceptance scenarios A–I

Measured at `5805d31` by running each file alone: `python3 -m unittest tests.<module>`
with `TMPDIR=/tmp` and `GAIE_HOME` outside Git, on a 4-CPU Linux host.

<!-- scenario-matrix:en -->
| Scenario | Subject | State | Test file | Test classes | Measured at this base |
|---|---|---|---|---|---|
| A | Master build | `passing` | `tests/test_build_engine_e2e.py` | `ScenarioATests` | 4 OK in 90.7 s with the browser run; `tests/test_build_engine.py` 31 OK |
| B | Master upgrade | `passing` | `tests/test_upgrade_engine.py` | `ScenarioB` | 49 OK |
| C | Video pipeline | `passing` | `tests/test_video_pipeline.py` | `ScenarioCTests` | 48 OK, 1 skip: the sample media is kept outside Git |
| D | Memory resume | `passing` | `tests/test_memory_unified.py` | `ScenarioDTests` | 26 OK |
| E | Security governor | `passing` | `tests/test_governor.py` | `CheckTests`, `AuditTests`, `StrictSandboxTests`, `SandboxTests` | 56 OK; the sandbox tests skip in CI |
| F | Self-healing | `passing` | `tests/test_self_healing_loop.py` | `ScenarioF` | 20 OK; high finding H1 open |
| G | Release engine | `partial` | `tests/test_release_provenance.py` | `ReleaseProvenanceTests` | 6 OK for the read-only pieces only; no acceptance test yet. **[to be completed at the final head]** |
| H | Adaptive orchestration | `passing` | `tests/test_orchestrator.py` | `ScenarioHTests` | 38 OK, 1 skip: the live metrics file is outside the repository |
| I | Permanent Claude Code install | `partial` | `tests/test_gaie_factory.py` | `BootstrapTests` | 21 OK for install mechanics only; no acceptance test and no new-session proof. **[to be completed at the final head]** |
<!-- /scenario-matrix -->

A passing test does not close the review findings in section 9.

### 5. Security findings and isolation as measured

`docs/evidence/gaie-20-layers/security-findings.json` (output of
`python3 -m engineering_os.security_audit`): 7 fixed, 1 mitigated, 4 held, 6 accepted
with a recorded reason, 4 open, and no open critical or high finding. Open:

- SEC-07 (medium): `detectors.Sandbox` is a Python-level guard without OS isolation.
- SEC-10 (low): the frozen `gaie_memory` journal is appended without an owner, mode or
  hard-link check.
- SEC-12 (medium): `layers.verify` declares `exec:sandbox` but runs tests outside the
  governor sandbox with the caller's environment.
- `private-mode` (medium): `engineering_os/build_engine.py:1425` creates a directory
  with mode 0o755.

Isolation: `docs/evidence/gaie-20-layers/isolation.json` was measured on one host on
2026-11-28 at tier `full` (own PID and network namespace, empty environment, writes only
in allowed paths) and lists what is not enforced (process count when mapped to uid 0,
Unix sockets inside allowed paths, no seccomp filter). In GitHub CI the tier is `plain`
(`RESUME.md`, "What the mapping stage established"), so `SandboxTests` in
`tests/test_governor.py` skip there. The reviewer found that file
out of date after the security merge (pr30-merge-quality F3). **[to be completed at the
final head]**: fixes for SEC-07, SEC-10 and SEC-12, a regenerated isolation file, and a
CI job that requires tier `full`.

### 6. Standing policies

- Twenty-agent team: `governance/agent-roles.json` holds 20 roles in 8 teams. There is
  no central team policy file at this base. **[to be completed at the final head]**
- Purposeful motion: `governance/policies/motion-purpose.json` (version 1.0.0, effective
  2026-11-28) requires every motion to state its meaning in one sentence per language.
  Validator `engineering_os/motion_policy.py`; `python3 -m engineering_os.motion_policy`
  returned `ok: true`: 47 purposeful, 37 legacy-unclassified, 400 reference, 156
  specification index, 5 withdrawn, 0 unclassified. Tests: `tests/test_motion_policy.py`
  (33 OK) and `packages/motion-engines/test/purpose.test.mjs` (12 pass).
- MASTER documents: `prompts/MASTER_BUILD.md` and `prompts/MASTER_UPGRADE.md` exist;
  `scripts/gaie_bootstrap.py` copies them into the installed `gaie-build` and
  `gaie-upgrade` skills. The central
  manifest with version, digest and drift test is in progress. **[to be completed at the
  final head]**

### 7. Installation

Details: `docs/GAIE_FACTORY.md`, "Installation in Claude Code". At this base the
committed copies in this repository match their sources (`tests/test_gaie_factory.py`);
a project install with `scripts/gaie_bootstrap.py` was run in an independent Git project
(16 files, all `current`, the copied router routes), but the installed router skill names
three paths that do not exist after that install; registering `pack:gaie-factory` is
refused against `main` `65c84fe`; a plugin install from GitHub needs the files on
`main`. No install mechanism is proven in a real session at this base. **[to be completed
at the final head]**: scenario I and its proof.

### 8. CI

Nine workflow files in `.github/workflows/`. `scripts/verify_release.py` (at `8d29263`)
requires nine jobs in six of them to succeed at the release commit. `verify.yml` and
`operating-system.yml` run the whole suite (`python3 -m unittest discover -s tests`).
The CI sandbox tier is `plain`. **[to be completed at the final head]**: time limits,
node tests that no workflow runs, the positive isolation job, and the CI result on the
final head.

### 9. Independent review

Each finding is fixed by a lane that did not review it, then re-checked by its reviewer.
Register: `RESUME.md`, "Independent review register" (at `8d29263`).

| Review | Verdict | Findings |
|---|---|---|
| pr30-authz | approve-with-fixes | F1 medium (a submodule config bypasses `checkout_guard` and runs a planted filter), F2 and F3 low |
| pr30-merge-quality | approve-with-fixes | nothing lost or weakened by the merge; F1–F4 low (SEC-09 and SEC-11 probes, stale docs) |
| w2-memory-heal-orch | approve-with-fixes | H1 high (self-healing reports "repaired" while its patch adds a defect), M1–M5 medium, L1–L7 low |
| pr30-isolation | running | **[to be completed at the final head]** |
| w2-build-upgrade | running | **[to be completed at the final head]** |

H1 blocks the release until it is fixed and re-checked. **[to be completed at the final
head]**: the independent engineering review of the whole branch.

### 10. Release state: recorded, tag pending

A release is the merge of PR #31 into `main`, then a GitHub Release with a new tag
`engineering-os-vX.Y.Z` on that exact merge commit
(`docs/specs/gaie-20-layers/RELEASE_CHECKLIST.md` at `8d29263`). Existing tags:
`engineering-os-v0.1.0` to `engineering-os-v0.1.4` and `engineering-sdk-v1.0.0`; none
for this release. The Engineering SDK is labelled 1.0.1 because its files changed after
the `engineering-sdk-v1.0.0` tag; it ships inside the OS release with no tag of its own.
State: **recorded, tag pending**. Nothing was deployed.

### 11. Owner decisions still open

- The version number, marking PR #31 ready and merging it, and publishing the GitHub
  Release (`RELEASE_CHECKLIST.md`, step 6).
- Registering the BILTIX, portfolio, KPI and security-lab repositories in the private
  registry (`docs/specs/gaie-20-layers/ROUTER.md`, project table).
- Approval, licence and deployment target for the generated application's repository
  (`publish` in `docs/specs/gaie-20-layers/BUILD_ENGINE.md`; the generated
  `LICENSE-PENDING.md`).
- Promoting or withdrawing the 37 legacy-unclassified motions, one at a time
  (`owner_decisions` in `governance/policies/motion-purpose.json`, no record yet).
- Commercial terms of the narration voice and the supplied music: reported by the
  earlier session, not yet written in the tree.
- A new-session Claude Code install proof uses plan quota; the owner decides whether to
  run it.

### 12. How to resume

Start from `docs/specs/gaie-20-layers/RESUME.md` ("How to pick up") and the branch
`claude/eager-feynman-kztjo4`. Keep `GAIE_HOME` outside Git and `TMPDIR=/tmp`, then run
`python3 -m unittest discover -s tests`, `python3 hub.py audit`,
`python3 scripts/security_scan.py scan` and `python3 hub.py layers --verify`. Receipts
and memory are not on a fresh machine; verify again in each new environment.
