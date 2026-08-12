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

| # | Xususiyat | Talab | Hozirgi holat | Gap |
|---|---|---|---|---|
| 1 | **Vaqt** [Cron] | Belgilangan vaqtda o'zi uyg'onadi | ✅ `automation/scheduler.py` + `cron.py` + `deploy/automation_daemon.py` — real fon tsikli, minutlik aniqlik, `is_due()` | **Yo'q** |
| 2 | **Xodisa** [webhook] | Tashqi hodisa kelganda uyg'onadi | ✅ `automation/triggers.py` (`TriggerType.WEBHOOK`) + `POST /api/v1/automation/events` — mos triggerlarni haqiqatan bajaradi | **Yo'q** |
| 3 | **Kuzatuv** [watcher] | Metrikani kuzatadi, **o'zgarganda** uyg'onadi | ❌ Mavjud emas. `TriggerType`da `watcher` yo'q; hech qayerda "oldingi qiymat bilan solishtirish" mantiqi yo'q | **Bor — to'liq** |
| 4 | **Boshqa agent** [navbat] | Bir agent tugagach keyingisiga topshiradi | ⚠️ Qisman. `WorkflowChain` **oldindan tuzilgan** zanjirni bajaradi, lekin "agent X tugadi → shartga qarab Y uyg'onsin" degan **trigger** yo'q. Zanjir statik, reaktiv emas | **Bor — trigger qatlami** |
| 5 | **Mustaqillik** [self-planning] | Maqsad qo'yiladi; maqsadga yetmasa **qayta rejalashtiradi va o'zini yaxshilaydi**, yetguncha takrorlaydi | ❌ Mavjud emas. `deploy/selfimprove.py` faqat **tavsiya** yozadi (o'z docstringi: "Faqat TAVSIYA qiladi"). Yopiq maqsad tsikli yo'q | **Bor — to'liq** |

**Xulosa:** 2 ta xususiyat to'liq bor, 1 tasi qisman, 2 tasi umuman yo'q.

---

## 3. Avtonomiya darajalari L0–L4

| Daraja | Ta'rif (slayd) | ZET'da hozir |
|---|---|---|
| **L0** Chat | Savol-javob, hech narsa bajarilmaydi | ✅ `/api/v1/run` (READ tool'lar) |
| **L1** Bog'lash | Tool'larga ulanadi, ega buyurganda ishlatadi | ✅ Tool Registry + 16 builtin tool |
| **L2** Pipeline | Hodisa tushganda oldindan belgilangan zanjir ishlaydi | ✅ Trigger + Workflow |
| **L3** Agent | **Natija** aytiladi, yo'lni o'zi topadi | ⚠️ `AgentRuntime` plan qiladi, lekin daraja tushunchasi yo'q — hamma agent bir xil huquqda |
| **L4** Mustaqil agent | O'ziga buyruq beradi, o'zini yaxshilaydi, qaror qabul qiladi | ❌ Yo'q |

**Gap:** avtonomiya darajasi **birinchi darajali tushuncha emas**. Hozir
huquqni faqat `PermissionPolicy` (tool darajasi) va `V-32` (approval)
belgilaydi. Daraja yo'qligi ikki muammo beradi:

1. Yangi agent yaratilganda uning **qanchalik erkinligi** yozilmaydi.
2. L4 xavfli — chegarasiz o'z-o'ziga buyruq berish A-07 tormozlarini
   chetlab o'tishi mumkin. Daraja **tormoz** sifatida ham kerak.

---

## 4. 6 TIZIM retsepti — imkoniyat matritsasi

Har bir retsept: trigger → 3 qadam → natija. Ustunlar: ZET'da bor bo'lgan
qism va **yetishmayotgan tashqi imkoniyat**.

| # | Retsept | Trigger | Bor | Yetishmaydi |
|---|---|---|---|---|
| 01 | **Uchrashuv kotibi** — yozishmani o'qib, bo'sh slot topib, Zoom link bilan uchrashuv qo'yadi | xodisa | LLM tahlil, Telegram o'qish | **Google Calendar** (bo'sh slot, event yaratish), **Zoom/Meet** link API, eslatma yuborish |
| 02 | **Ovozdan rejaga** — ovozli xabar → vazifalar + deadline | xodisa | Telegram voice qabul qilish | **Haqiqiy STT** (`voice/stt.py` — hozir `StubSTT`, transkripsiya qilmaydi), **vazifa/kalendar yozuvi** |
| 03 | **Guruh razvedkasi** — 12 ta ish guruhini o'qib, vazifa/shikoyat/muammoni ajratadi | vaqt (19:00) | Cron, LLM tasniflash, Telegram yuborish | **Guruh tarixini o'qish** — Bot API bot qo'shilgan guruhdagina va faqat yangi xabarlarni beradi; to'liq tarix uchun **MTProto (Telethon)** kerak |
| 04 | **Kontent konveyeri** — post tayyorlaydi, ko'rsatadi, "to'xta" demasangiz 17:00da chop etadi | vaqt (10:00) | SMM agent, Instagram/YouTube/Telegram **publish tool'lari** ✅ | **"Sukut = rozilik" taymerli approval** — hozir V-32 faqat aniq tasdiqni biladi, kutish-va-davom-etish rejimi yo'q |
| 05 | **Lid yo'li** — izoh/Direct → savol berib ehtiyoj+budjet aniqlaydi → slot taklif qiladi | xodisa | CRM (kontakt→lid), LLM | **Instagram webhook** (izoh/Direct), **ko'p qadamli suhbat holati**, kalendar |
| 06 | **Kunlik puls** — doskalarni tekshirib, 3 qatorli hisobot | vaqt (09:20, 18:40) | Cron, Telegram yuborish | **Loyiha doskasi manbasi** (hozir ZET'da vazifa doskasi ma'lumot modeli yo'q) |

### Takrorlanuvchi yetishmovchiliklar

Oltita retseptdan **to'rttasi** bitta narsaga tayanadi — **kalendar**.
Uchtasi **ko'p qadamli, holatli suhbat**ga tayanadi. Ikkitasi **haqiqiy
STT**ga. Demak keyingi tashqi integratsiyalar tartibi shu og'irlikdan
kelib chiqadi:

1. Kalendar (4 retsept)
2. Holatli suhbat / taymerli approval (3 retsept)
3. STT (2 retsept)
4. Telegram MTProto guruh o'qish (1 retsept)
5. Loyiha doskasi modeli (1 retsept)

---

## 5. Nima birinchi quriladi

Retseptlar tashqi API'larga tayanadi (kalendar kaliti, MTProto sessiyasi,
Instagram webhook obunasi) — ularsiz retsept **yolg'on** bo'ladi. Shuning
uchun avval **dvigatel** quriladi, retseptlar esa **e'lon qilingan, lekin
imkoniyati yetishmasa ochiq "tayyor emas" deb ko'rsatiladigan** ro'yxat
sifatida yoziladi.

| Bosqich | Nima | Nega birinchi |
|---|---|---|
| **Z39** | `automation/autonomy.py` — L0–L4 | Qolgan hammasi darajaga tayanadi (watcher L2+, goal L4) |
| **Z40** | `automation/watcher.py` — kuzatuv triggeri | 3-xususiyat; TIZIM 06 shu ustida quriladi |
| **Z41** | `TriggerType.AGENT_HANDOFF` + `agent.completed` hodisasi | 4-xususiyat; zanjirni reaktiv qiladi |
| **Z42** | `automation/goal.py` — maqsad tsikli | 5-xususiyat; L4 shu bilan haqiqiy bo'ladi |
| **Z43** | `automation/recipes.py` — 6 retsept + imkoniyat tekshiruvi | Ega ko'radigan yakuniy mahsulot; yetishmovchilik ochiq |

**Qat'iy qoida:** hech bir retsept "ishlayapti" deb ko'rsatilmaydi, agar
uning imkoniyati (kalendar kaliti, STT provayderi) haqiqatan ulanmagan
bo'lsa. `RecipeStatus.MISSING_CAPABILITY` — halol holat, `CLAUDE.md`dagi
"Halol holatlar" standartining backend ko'rinishi.

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
