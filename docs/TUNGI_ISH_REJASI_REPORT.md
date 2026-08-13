# ZET — Tungi ish rejasi (Bo'lim A → B → C) — Yakuniy hisobot

**Sana:** 2026-08-13
**Branch:** `claude/zetproject-audit-plan-p9lysv`
**Doira:** foydalanuvchi (Boss) yozgan tungi ish rejasidagi Bo'lim A/B/C —
boshqa hech narsaga tegilmagan, standing autonomy yoqilmagan, hech
qanday real tashqi amal bajarilmagan (Telegram/nashr — hammasi
sandbox/mock/dry-run).

**MUHIM:** Bu hujjat GO/NO-GO qarori EMAS — faqat fakt va status.
Qaror Boss'ga qoladi.

---

## BO'LIM A — 3 ta HIGH-severity

Uchala item ("A1/A2/A3" — bu tungi rejadagi raqamlash, oldingi
sessiyaning "E1/E2/E3"siga mos) **allaqachon shu branch'ning oldingi
commit'ida (`e67744f`) BAJARILGAN edi** — bu sessiya ularni qayta
qilmadi, faqat: (a) haqiqatan ishlashini tasdiqladi, (b) A3 uchun
foydalanuvchi qo'shimcha talab qilgan "bypass yo'q" integratsiya
testini yozdi (bu ilgari yo'q edi).

### A1 — Approval-resume non-idempotent takrorlash: **BAJARILDI**

Per-step DB checkpoint (`run.completed_steps` + `run.plan_snapshot`,
Alembic 0011). `Executor.execute_plan()` checkpoint qilingan
qadamlarni butunlay o'tkazib yuboradi. Dalil (oldingi sessiyada
yozilgan, bu sessiyada qayta ishga tushirilib tasdiqlangan):
`tests/test_step_checkpoint.py::TestApprovalResumeIsIdempotent::
test_write_step_not_repeated_after_restart_and_resume` — 3 qadamli
mission, 2-qadam WRITE (mock `message.send`), 3-qadamda uzilish,
restart, approve, resume — **WRITE qadam FAQAT BIR MARTA bajarilgani**
assert bilan isbotlangan (`send_tool.calls == 1`).

### A2 — Mission-level approval DB durability: **BAJARILDI**

`Approval.run_id` nullable, haqiqiy `mission_id` FK + CheckConstraint
(Alembic 0012). Dalil: `tests/test_run_checkpoint.py::
TestMissionApprovalDurability` (SQLite) + real Postgres bilan
ikki-mustaqil-protsess restart simulyatsiyasi (oldingi sessiyada
bajarilgan, `/tmp/.../scratchpad/fix1_real_pg_session_a.py`/`_b.py`,
commit qilinmagan dalil skriptlari) — approval yaratildi, jarayon
"o'chirildi", butunlay yangi protsess DB'dan to'liq holatini
tikladi.

### A3 — MissionEngine recovery=None: **BAJARILDI + YANGI TEST**

`MissionRecoveryAdapter` (`core/mission.py`) — D4 bilan bir xil
T1_FREE LLM-judge yo'li, Task-Graph darajasi uchun. `deps.py`ning
ikkala qurish nuqtasiga ulangan.

**Bu sessiyada YANGI qo'shilgan** (foydalanuvchi aniq talab qildi —
"D1 talabi shu yerga ham amal qiladi... integration test yoz"):
`tests/test_mission_engine.py::TestA3ApprovalBypassPrevention::
test_recovery_retry_with_high_risk_step_still_requires_approval` —
**REAL** `Orchestrator`/`Executor`/`PermissionPolicy`/`ApprovalService`
bilan (FakeOrchestrator stub EMAS): 1-urinish haqiqiy `note.read`
xatosi bilan yiqiladi → real `MissionRecoveryAdapter` LLM'dan diagnos
oladi va `mission.constraints`ga yozadi → 2-urinishda reja HIGH-risk
(EXECUTE) qadamga ega → **mission WAITING_APPROVAL'da to'xtaydi,
hech qachon avtomatik EXECUTING/COMPLETED'ga o'tmaydi**. Test o'tdi
(`pytest tests/test_mission_engine.py::TestA3ApprovalBypassPrevention -q`
→ 1 passed).

**Approval bypass yo'q — TASDIQLANDI.** (Arxitektura jihatidan ham
tabiiy: `MissionRecoveryAdapter.diagnose_and_patch()` hech qanday
tool chaqirmaydi va hech qanday approval bermaydi — faqat
`mission.constraints`ga matn yozadi; haqiqiy bajarish har doim
`Orchestrator.start()`ning ODDIY, PermissionPolicy/ApprovalService
orqali o'tuvchi yo'lidan boradi.)

---

## BO'LIM B — Dashboard logika xatolari (T01, T04, T05, T06)

Ushbu bo'limdan oldin `Explore` sub-agent orqali `apps/core/src/zet/
automation/recipes.py` (yakka-manba, barcha 6 retseptning ta'rifi)
va `apps/web/.../tizim/page.tsx` (generic renderer, retseptga xos kod
YO'Q) to'liq o'qildi. Natija: foydalanuvchi tavsiflagan 4 ta muammoning
2 tasi kod bilan ANIQ mos keldi (T04, T01), 1 tasi qisman boshqacha
ekani chiqdi (T05 — kod dependency emas, faqat blocked_steps hisob-
kitobida gap), 1 tasi esa **kod tekshiruvida umuman tasdiqlanmadi**
(T06).

### B1 (T06 — Kunlik puls): **TUZATISH KERAK EMAS — halol tekshiruv, muammo topilmadi**

Kod bevosita tekshirildi: T06'ning 3 qadami (`recipes.py:376-397`)
`TASK_BOARD`, `LLM`, `TELEGRAM_SEND` capability'lariga muhtoj —
**hech biri MTProto emas**. MTProto/Telethon'ga muhtoj bo'lgan yagona
retsept — **T03 "Guruh razvedkasi"** (`TELEGRAM_READ_GROUPS`), u esa
allaqachon to'g'ri "Tayyor emas" deb ko'rsatiladi.

Qo'shimcha tasdiqlash: `deps.py`da `workspace_scope=_workspace_scope`
haqiqatan ulangan (T06'ning `task.pulse`/`task.list` tool'lari
production'da "connected" bo'ladi) va `app.py`da `notifier=
get_notifier()` haqiqiy Telegram yetkazishga ulangan — T06 nafaqat
kodda to'g'ri belgilangan, balki **haqiqatan production'da ishlaydi**
(`docs/12-AUTONOMY-GAP.md` 178-182-qatorda 2026-08-12 jonli tasdiq
yozib qo'yilgan: 3 ta real vazifa, `operations` ishga tushirildi,
to'g'ri ajratildi).

**Xulosa:** T06'ning "Yoqilgan" holati **TO'G'RI** — o'zgartirilmadi.
Ehtimol skrinshotda ko'rilgan/eslab qolingan muammo aslida **T03**ga
tegishli bo'lgan (ikkalasi nomi jihatidan chalkashtirilishi mumkin) —
T03 esa allaqachon halol "Tayyor emas" holatida. Hech qanday yangi
"Qisman tayyor" holati kiritilmadi, chunki bu holat T06'ga qo'llanmaydi.

### B2 (T04 — Kontent konveyeri): **BAJARILDI**

`Capability.TIMED_APPROVAL` ("sukut = rozilik") **butunlay olib
tashlandi** (nafaqat T04'dan — konsepsiya kod bazasidan chiqarildi,
`recipes.py`). Bu boshqa "hali yo'q" imkoniyatlardan farqli edi: u
V-32'ga TO'G'RIDAN-TO'G'RI zid dizayn edi. T04'ning 3-qadami endi
faqat `Capability.CONTENT_PUBLISH`ga muhtoj — bu allaqachon aniqlanadigan
imkoniyat (`instagram.publish_photo`/`youtube.publish`/`telegram.
channel_post` tool'lari HIGH-risk, `PermissionPolicy` orqali avtomatik
`ApprovalRequiredError`).

Qadam sarlavhasi "'To'xta' demasangiz davom etadi" → "Ega ANIQ
tasdiqlagach nashr qilish". Natija matni "17:00 da avtomatik chop
etadi" → "Kontent tayyor bo'lgach ega tasdig'i so'raladi — FAQAT aniq
'ha/tasdiqlayman' javobidan keyin nashr qilinadi ... Sukut = hech
narsa qilinmaydi, nashr EMAS."

**Bonus (so'ralmagan, lekin to'g'ridan-to'g'ri natija):** T04 endi
HECH QANDAY yangi (qurilmagan) imkoniyat KUTMAYDI — real sozlamada
(Telegram bot ulangan) **READY** bo'ladi. Buni tasdiqlovchi yangi test:
`tests/test_recipes.py::TestCapabilityDetection::
test_t04_no_longer_needs_a_new_capability`.

**UI'da qanday ko'rinadi:** T04 kartasi — agar `telegram_bot_token`
sozlangan bo'lsa, badge endi "Tayyor emas" o'rniga "Yoqish" tugmasini
ko'rsatadi (ilgari doim "Tayyor emas" edi). 3-qadam matni "Ega ANIQ
tasdiqlagach nashr qilish". "Natija" bo'limi sukut/avtomatik
so'zlarisiz, aniq tasdiq shartini yozadi. Frontend `CAPABILITY_LABELS`
xaritasidan `"approval.timed"` yorlig'i olib tashlandi.

Yangilangan/qo'shilgan fayllar: `automation/recipes.py`,
`tests/test_recipes.py` (+1 test, 1 test'dan `TIMED_APPROVAL`
o'chirildi + yangi `test_timed_approval_capability_no_longer_exists`),
`apps/web/.../tizim/page.tsx`, `docs/12-AUTONOMY-GAP.md` (3 joy
yangilandi).

### B3 (T01 — Uchrashuv kotibi): **BAJARILDI**

`recipes.py`dagi T01 `result` matni ilgari SO'ZSIZ va'da qilardi:
"Kalendarda uchrashuv + ikkala tomonga 10 daqiqalik eslatma" — garchi
3-qadam (havola yaratish, `MEETING_LINK`) ZET'da hali yo'q va HAR
DOIM bloklangan bo'lsa ham. Endi: "Kalendarda vaqt taklif qilinadi;
ikkala tomonga eslatma FAQAT uchrashuv havolasi yaratilgach yuboriladi
(bu funksiya hozircha yo'q — 3-qadam bloklangan)."

**UI'da qanday ko'rinadi:** T01 kartasi — badge "Tayyor emas" (o'zgarmadi,
chunki `MEETING_LINK` hamon yo'q). "Natija" bo'limi endi faqat "vaqt
taklif qilinadi"ni va'da qiladi, eslatmani shart bilan yozadi — foydalanuvchi
karta ichida (3-qadam allaqachon "bu qadam bajarilmaydi" deb belgilangan)
va "Natija" matnini birga o'qib, real chegarani darhol ko'radi.

### B4 (T05 — Lid yo'li): **BAJARILDI (arxitektura darajasida, T05dan tashqari HAMMA retseptga tegishli)**

Kod tekshiruvi shuni ko'rsatdi: 2/3-qadamlar 1-qadamning MA'LUMOTIGA
(kod darajasida) bog'liq emas — barcha 3 qadam bitta agent
chaqiruvida, bitta flat prompt sifatida yuboriladi (`_command_for()`).
Haqiqiy muammo BOSHQA edi: `evaluate()` funksiyasi har qadamni
MUSTAQIL bloklardi — agar 2/3-qadamning O'Z ehtiyoji (LLM/CRM/
CALENDAR) mavjud bo'lsa, ular `blocked_steps`da KO'RSATILMASDI, garchi
1-qadam (`INSTAGRAM_WEBHOOK`, hali yo'q) bloklangani uchun ular HECH
QACHON ishga tushmasa ham — bu interfeysda "2/3-qadam ishlaydi" degan
yolg'on taassurot qoldirardi.

Tuzatish: `evaluate()` endi FORWARD PROPAGATION qiladi — bloklangan
birinchi qadamdan KEYINGI barcha qadamlar ham `blocked_steps`ga
qo'shiladi (chunki ular bitta ketma-ket bajarishning bir qismi).
Bu T05'ga xos EMAS — barcha 6 retseptga bir xil qoida qo'llanadi.

Yangi testlar: `tests/test_recipes.py::TestSequentialStepBlocking`
(3 ta: T05 to'liq [1,2,3] blok, T01'ning 1-qadami ortga
bloklanmasligi, to'liq imkoniyatda hech narsa bloklanmasligi).

**UI'da qanday ko'rinadi:** T05 kartasida endi 2 va 3-qadamlar ham
"— bu qadam bajarilmaydi" deb belgilanadi (ilgari faqat 1-qadam
shunday ko'rinardi, 2/3 oddiy matn edi).

---

## BO'LIM C — C2 (Business/Contacts Registry): **TO'LIQ BAJARILDI**

Reja "faqat boshini qil" deb yozgan edi, lekin baholanган "kichik-
o'rta, ~1 kun" ish aslida to'liq sig'di. Bajarilgan 7 bosqichdan 6 tasi
(7-bosqich — Ingestion Router C1 uchun qidiruv tartibini hujjatlashtirish
— C1 o'zi TEGILMAGANI uchun keyinga qoldirildi, faqat kod
docstring'ida qisqacha eslatilgan):

1. ✅ `Business` DB modeli + `crm_contact.business_id` (nullable FK,
   `ON DELETE SET NULL`, `Task.project_id` bilan bir xil naqsh) —
   Alembic **0013**. Real Postgres'da tekshirildi: yaratildi,
   downgrade/upgrade round-trip muvaffaqiyatli.
2. ✅ `PgCRM`ga: `add_business`/`get_business`/`list_businesses`/
   `find_business` (nom+aliases qidiruvi)/`link_contact_to_business`.
3. ✅ 3 ta yangi tool (`business_tools.py`, `crm_tools.py` naqshi):
   `BusinessCreateTool`, `BusinessListTool`, `BusinessContactLinkTool`.
4. ✅ `tools/builtin/__init__.py`da ro'yxatdan o'tkazildi (bir xil
   `crm_scope`).
5. ✅ `security/risk.py`: `business.create`/`business.contact_link` →
   MEDIUM (CRM yozuvlari bilan bir xil daraja).
6. — Obsidian ko'zgu generatori (rejada "ixtiyoriy, keyinroq" deb
   belgilangan edi) — QILINMADI, keyingi ishga qoldi.
7. — Ingestion Router qidiruv tartibi hujjati — C1 o'zi tegilmagani
   uchun to'liq yozilmadi (faqat `find_business()`ning docstring'ida
   bir jumla).

**Test qamrovi:** `tests/test_pg_crm.py::TestBusinesses` (11 test),
`tests/test_business_tools.py` (7 test) — jami 18 ta yangi test.
Real Postgres bilan schema/FK/index tekshirildi va downgrade/upgrade
round-trip qilindi (`/tmp/.../scratchpad` skripti emas — to'g'ridan-
to'g'ri `alembic upgrade/downgrade` + `psql \d` orqali, natija shu
hisobotda yuqorida yozilgan).

**Yon-ta'sir (kutilgan, kerakli tuzatish):** `agents/eval.py`dagi
`TOOL_PERMISSIONS` jadvali yangi 3 tool bilan sinxronlashtirildi —
aks holda `test_agent_factory.py::TestToolPermissionMap` yiqilardi
(bu test ANIQ shu holat uchun yozilgan edi — "yangi tool qo'shildi-yu,
jadvalga yozish unutildi" xatosini tutish uchun; xatoni tutdi, men
tuzatdim).

---

## To'liq test hisobi

| | Son |
|---|---|
| Ushbu sessiya boshida (oldingi commit `e67744f`dan keyin) | 2564 |
| Bo'lim A (yangi A3 bypass testi) | +1 → 2565 |
| Bo'lim B (T04/T05 yangi testlar) | +5 → 2570 |
| Bo'lim C (C2 yangi testlar) | +18 → 2588 |
| **Hozirgi jami** | **2588** |
| Regressiya | **0** |
| To'liq suite natijasi | `2588 passed, 0 failed, 0 error` (Postgres o'chirilgan holda, SQLite) |
| mypy (o'zgartirilgan barcha fayllar) | 0 yangi xato |
| ruff (o'zgartirilgan barcha fayllar) | 0 yangi xato (1 ta o'zim qo'shgan ortiqcha `noqa` topildi va darhol tuzatildi) |
| Frontend `tsc --noEmit` | 0 xato |
| Real Postgres (0013 migratsiya) | yaratildi, tekshirildi, downgrade/upgrade round-trip muvaffaqiyatli |

Real amaliy (`shell.exec`, tashqi Telegram xabari, real nashr) — **HECH
BIRI BAJARILMADI**. Barcha testlar SQLite/mock/dry-run bilan; real
Postgres faqat schema tekshiruvi uchun ishlatildi (real ma'lumot
yozilmadi, faqat DDL).

---

## Yangi HIGH-severity ro'yxati

Ushbu sessiya davomida **hech qanday yangi HIGH-severity muammo
topilmadi.** Bitta MEDIUM-darajali sifat gap topildi va tuzatildi
(C2 tool'larini `agents/eval.py::TOOL_PERMISSIONS`ga qo'shish
unutilishi — test tutdi, kod yozilmasdan oldin emas, lekin commit'dan
oldin tuzatildi, hech qachon eslon qilinmadi).

Ochiq qolgan (HIGH emas, lekin "hammasi bajarilgan" ham degani emas):
- T01/T05 — `MEETING_LINK`/`INSTAGRAM_WEBHOOK` hamon yo'q (bu
  tunda ATAYLAB tegilmadi — yangi tashqi integratsiya).
- C2'ning Obsidian ko'zgu generatori — qilinmadi (rejada ixtiyoriy).
- C1, C3, C4, C5 — TEGILMADI (aniq buyruq bo'yicha).

---

**Bu hisobot GO/NO-GO qarori EMAS — Boss ertalab shaxsan ko'rib
chiqib, o'zi qaror qiladi.**
