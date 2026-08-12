# ZET — Avtonomiya Gap Analizi (yangi ko'rsatmalar zip'i)

> Manba: ega yuborgan "Eslatma va qo'shimcha funksiyalar" zip (11 slayd,
> @umid.ikromboev). Sana: 2026-08-12.
> Bu hujjat **yangi talablarni** mavjud kod bilan qatorma-qator taqqoslaydi.
> Boshlang'ich zip (40 bo'lim) talablari `01-VISION-GAP.md`da — ular
> Bo'lim 1–12 orqali bajarilgan; bu hujjat **ustiga qo'shiladi**.

---

## 1. Slaydlarning mazmuni (qisqacha)

Zip uchta narsani belgilaydi:

1. **Agentning 5 ta xususiyati** — agent qanday "uyg'onadi".
2. **5 ta avtonomiya darajasi (L0–L4)** — agent qanchalik mustaqil.
3. **6 ta TIZIM retsepti** — tayyor, ishlaydigan avtomatlashtirishlar.

Yakuniy slayd (`XARITA`) maqsadni bir jumlada beradi:

> **"Sizga qoladi: faqat qaror qabul qilish. Qolgani — yozish, tekshirish,
> eslatish, chop etish — tizimda."**

Bu ZET uchun qabul qilinish mezoni: agar ega hali ham qo'lda yozayotgan,
tekshirayotgan yoki eslatayotgan bo'lsa — tizim tugallanmagan.

---

## 2. Agentning 5 xususiyati — gap matritsasi

| # | Xususiyat | Talab | Holat (Z39 dan keyin) |
|---|---|---|---|
| 1 | **Vaqt** [Cron] | Belgilangan vaqtda o'zi uyg'onadi | ✅ `automation/scheduler.py` + `cron.py` + `deploy/automation_daemon.py` |
| 2 | **Xodisa** [webhook] | Tashqi hodisa kelganda uyg'onadi | ✅ `automation/triggers.py` + `POST /api/v1/automation/events` |
| 3 | **Kuzatuv** [watcher] | Metrikani kuzatadi, **o'zgarganda** uyg'onadi | ✅ **Z39** `automation/watcher.py` — 6 taqqoslash turi, baza qiymat, cooldown |
| 4 | **Boshqa agent** [navbat] | Bir agent tugagach keyingisiga topshiradi | ✅ **Z39** `automation/handoff.py` — `agent.completed` + `AGENT_HANDOFF` trigger |
| 5 | **Mustaqillik** [self-planning] | Maqsadga yetmasa qayta rejalashtiradi | ✅ **Z39** `automation/goal.py` — yopiq tsikl, daraja bilan cheklangan |

**Z39 dan oldin:** 2 to'liq, 1 qisman, 2 yo'q. **Hozir:** beshtasi ham bor.

Beshtasi ham oxir-oqibat `AutomationEvent` chiqaradi va `process_event()`
dan o'tadi — ya'ni beshta xususiyat uchun **bitta** xavfsizlik yo'li bor,
beshta emas.

---

## 3. Avtonomiya darajalari L0–L4

✅ **Z39** — `automation/autonomy.py` darajani birinchi darajali
tushunchaga aylantirdi.

| Daraja | Ta'rif (slayd) | Ochadigan imkoniyat | Ruxsat shifti |
|---|---|---|---|
| **L0** Chat | Savol-javob | — | READ |
| **L1** Bog'lash | Tool'larga ulanadi, ega buyurganda | `use_tools` | WRITE |
| **L2** Pipeline | Hodisa oldindan belgilangan zanjirni ishga tushiradi | `+ triggered_run` | EXECUTE |
| **L3** Agent | Natija aytiladi, yo'lni o'zi topadi | `+ self_planning` | EXECUTE |
| **L4** Mustaqil | O'ziga buyruq beradi, o'zini yaxshilaydi | `+ self_command`, `self_improve` | EXECUTE |

**Eng muhim qaror — daraja RUXSAT BERMAYDI, RUXSATNI CHEKLAYDI.**

`effective_permission()` faqat pasaytiradi. L4 agent ham
`permission_level=READ` bo'lsa EXECUTE ga ko'tarilmaydi, va **ADMIN
hech bir daraja orqali berilmaydi** — u faqat eganing aniq sozlamasi.

Maqsad tsikli chegarasi ham shu yerdan: L0–L2 = 0 urinish (tsikl yo'q),
L3 = 1, L4 = 5. Ya'ni "yetguncha takrorlaydi" cheksiz emas.

V-32 hech bir darajada bekor qilinmaydi — test bilan qulflangan
(`test_autonomy.py::TestApprovalInvariant`).

---

## 4. 6 TIZIM retsepti — imkoniyat matritsasi

Har bir retsept: trigger → 3 qadam → natija. Ustunlar: ZET'da bor bo'lgan
qism va **yetishmayotgan tashqi imkoniyat**.

| # | Retsept | Trigger | Bor | Yetishmaydi |
|---|---|---|---|---|
| 01 | **Uchrashuv kotibi** — yozishmani o'qib, bo'sh slot topib, Zoom link bilan uchrashuv qo'yadi | xodisa | LLM tahlil, Telegram o'qish | **Google Calendar** (bo'sh slot, event yaratish), **Zoom/Meet** link API, eslatma yuborish |
| 02 | **Ovozdan rejaga** — ovozli xabar → vazifalar + deadline | xodisa | Telegram voice, **ElevenLabs Scribe STT** ✅, **`task.create`/`calendar.add`** ✅ | — **TAYYOR** (Z48) |
| 03 | **Guruh razvedkasi** — 12 ta ish guruhini o'qib, vazifa/shikoyat/muammoni ajratadi | vaqt (19:00) | Cron, LLM tasniflash, Telegram yuborish | **Guruh tarixini o'qish** — Bot API bot qo'shilgan guruhdagina va faqat yangi xabarlarni beradi; to'liq tarix uchun **MTProto (Telethon)** kerak |
| 04 | **Kontent konveyeri** — post tayyorlaydi, ko'rsatadi, "to'xta" demasangiz 17:00da chop etadi | vaqt (10:00) | SMM agent, Instagram/YouTube/Telegram **publish tool'lari** ✅ | **"Sukut = rozilik" taymerli approval** — hozir V-32 faqat aniq tasdiqni biladi, kutish-va-davom-etish rejimi yo'q |
| 05 | **Lid yo'li** — izoh/Direct → savol berib ehtiyoj+budjet aniqlaydi → slot taklif qiladi | xodisa | CRM (kontakt→lid), LLM | **Instagram webhook** (izoh/Direct), **ko'p qadamli suhbat holati**, kalendar |
| 06 | **Kunlik puls** — doskalarni tekshirib, 3 qatorli hisobot | vaqt (09:20, 18:40) | Cron, Telegram yuborish, **`task.pulse`** ✅ (siljidi/turib qoldi/qaror kutmoqda — kodda ajratiladi) | — **TAYYOR** (Z48) |

### Takrorlanuvchi yetishmovchiliklar

Oltita retseptdan **to'rttasi** bitta narsaga tayanadi — **kalendar**.
Uchtasi **ko'p qadamli, holatli suhbat**ga tayanadi. Ikkitasi **haqiqiy
STT**ga. Demak keyingi tashqi integratsiyalar tartibi shu og'irlikdan
kelib chiqadi:

1. ~~Kalendar (4 retsept)~~ — ✅ **Z48**: ichki kalendar
2. Holatli suhbat / taymerli approval (3 retsept)
3. ~~STT (2 retsept)~~ — ✅ **Z48**: ElevenLabs Scribe
4. Telegram MTProto guruh o'qish (1 retsept)
5. ~~Loyiha doskasi modeli (1 retsept)~~ — ✅ **Z46 jadval + Z48 tool**

---

## 5. Nima birinchi quriladi

Retseptlar tashqi API'larga tayanadi (kalendar kaliti, MTProto sessiyasi,
Instagram webhook obunasi) — ularsiz retsept **yolg'on** bo'ladi. Shuning
uchun avval **dvigatel** quriladi, retseptlar esa **e'lon qilingan, lekin
imkoniyati yetishmasa ochiq "tayyor emas" deb ko'rsatiladigan** ro'yxat
sifatida yoziladi.

✅ Bajarildi — **Z39** (dvigatel) va **Z40** (retseptlar).

**Qat'iy qoida:** hech bir retsept "ishlayapti" deb ko'rsatilmaydi, agar
uning imkoniyati (kalendar, STT provayderi) haqiqatan ulanmagan bo'lsa.
`RecipeStatus.MISSING_CAPABILITY` — halol holat, `CLAUDE.md`dagi
"Halol holatlar" standartining backend ko'rinishi.

`GET /api/v1/automation/recipes` har bir retsept uchun `status`,
`missing` (qaysi imkoniyat) va `blocked_steps` (qaysi qadam) qaytaradi.
`POST /recipes/{code}/install` chala retseptni **o'rnatmaydi** (409).

---

## 7. Keyingi ish — tashqi integratsiyalar

Dvigatel tayyor; retseptlarni yoqish uchun **faqat tashqi ulanishlar**
qoldi. Og'irlik tartibi (nechta retsept ochilishi bo'yicha):

| # | Imkoniyat | Nechta retsept ochiladi | Nima kerak |
|---|---|---|---|
| ~~1~~ | ~~`calendar`~~ | ✅ **Z48** | ICHKI kalendar: `calendar_event` jadvali + `calendar.add`/`calendar.list` |
| ~~2~~ | ~~`task_board`~~ | ✅ **Z48** | `project`/`task` jadvallari + `task.list`/`.create`/`.update`/`.pulse` |
| ~~4~~ | ~~`stt`~~ | ✅ **Z48** | `ElevenLabsSTT` (Scribe) — `ELEVENLABS_API_KEY` bo'lsa |
| 3 | `meeting_link` | 1 (T01) | Zoom/Meet API |
| 5 | `telegram.read_groups` | 1 (T03) | MTProto (Telethon) sessiyasi |
| 6 | `timed_approval` | 1 (T04) | "Sukut = rozilik" taymerli tasdiq (V-32 kengaytmasi) |
| 7 | `instagram.webhook` | 1 (T05) | Instagram webhook obunasi |

Har bir imkoniyat qo'shilganda `detect_capabilities()` ga bitta qator
yoziladi — retseptlarning o'zi **o'zgarmaydi** va avtomatik "ready"
bo'ladi.

✅ **Z48'da bajarildi.** "Eng tez g'alaba" aynan shunday chiqdi:
`task_board` tashqi API talab qilmadi va u bilan birga ICHKI kalendar
ham ochildi. Natijada **T02 va T06 READY** bo'ldi (ilgari ikkalasi ham
`MISSING_CAPABILITY` edi).

MUHIM DARS. Jadval qurish YETARLI EMAS edi. Z46'da `project`/`task`/
`calendar_event` jadvallari va 12 ta HTTP endpoint bor edi — ya'ni EGA
brauzerdan vazifa qo'sha olardi — lekin **ZET o'zi qo'sha olmasdi**,
chunki agent faqat registry'dagi tool'lar orqali ish qiladi. Imkoniyat
haqiqiy bo'lishi uchun uchta narsa kerak: jadval + tool + tool'ning DB'ga
ULANGANLIGI. Shuning uchun `detect_capabilities()` tool'ning ro'yxatda
turishiga emas, uning `connected` xossasiga qaraydi.

Qolgan to'rttasi tashqi ulanishga tayanadi: `meeting_link` (T01),
`telegram.read_groups` (T03), `timed_approval` (T04),
`instagram.webhook` (T05).

---

## 6. Xavfsizlik chegaralari (o'zgarmaydi)

Yangi imkoniyatlar mavjud tormozlarni **kengaytirmaydi**:

- **V-32** — EXECUTE amallar approval'siz bajarilmaydi. L4 ham bundan
  ozod emas; L4 faqat *rejalashtirishda* mustaqil, *bajarishda* emas.
- **A-07** — har run uchun `max_steps`, `timeout`, budjet. Maqsad tsikli
  uchun qo'shimcha: `max_iterations` va umumiy budjet shifti.
- **Kill-switch** — watcher va goal tsikli ham `KillSwitchState.check()`
  bilan to'xtaydi (Z38'dagi teshik yopilganidek).
- **A-05** — tashqi manba (izoh, Direct, guruh xabari) UNTRUSTED; retsept
  ichida ham u prompt sifatida bajarilmaydi, faqat ma'lumot sifatida.
