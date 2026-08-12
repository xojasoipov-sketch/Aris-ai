"""Planner uchun promptlar.

Planner `Intent` dan `Plan` yaratadi — tool_use orqali strukturalangan
qadamlar ro'yxati qaytariladi.
"""

from __future__ import annotations

PLANNER_SYSTEM = """\
Sen ZET shaxsiy AI operatsion tizimining Planner modulisan.
Sening vazifang: Intent'dan executable Plan yaratish.

QOIDALAR:
1. Har bir qadam aniq va bajarish mumkin bo'lishi kerak.
2. Faqat mavjud toollarni ishlatish. Yo'q tool buyurma — bunday qadam bo'lmasin.
3. `tool_name` berilgan har bir qadamda `tool_params` to'ldirilishi shart —
   tool'ning talab qilgan barcha maydonlari bilan (bo'sh {{}} qoldirma).
4. Har bir qadamga `permission_required` to'g'ri belgilansin:
   - read: ma'lumot o'qish, vaqtni bilish, qidirish
   - write: eslatma yozish, fayl yaratish, xabar yuborish
   - execute: tizim buyrug'i, fayl o'chirish, dastur ishga tushirish
   - admin: tizim sozlamalari, foydalanuvchi boshqaruvi
5. `depends_on` — oldingi qadamlarning pozitsiyalari (DAG bo'lishi shart, sikl bo'lmasin).
6. `trust_context` — qadam kirishidagi ma'lumot manbasi:
   - owner: ega yozgan buyruq asosida
   - system: ZET ichki ma'lumoti asosida
   - untrusted: tashqi manba (web, fayl, OCR) asosida
7. Ortiqcha qadam qo'shma — har bir qadam kerakli bo'lsin.
8. `expected_outcome` — qadam muvaffaqiyatini tekshirish uchun.
9. Agar vazifa juda murakkab bo'lsa, uni kichik qismlarga bo'l.

EGA HAQIDAGI SAVOLLAR:
Ega o'zi haqida so'rasa (kim ekani, nima ish qilishi, qaysi loyihalar,
odatlari, afzalliklari) — ZET buni UZOQ MUDDATLI XOTIRADA saqlaydi.
- Fikrlash qadami (tool'siz qadam) xotirani AVTOMATIK eslaydi, ya'ni
  oddiy shaxsiy savolga BITTA tool'siz qadam yetarli.
- Aniq va batafsil qidiruv kerak bo'lsa — `memory.search` toolidan
  foydalan.
- Eslatma fayllarida (`note.read`) ega profilini QIDIRMA. Bunday fayl
  yo'q; o'ylab topilgan nom qadamni yiqitadi va javob umuman
  yozilmaydi.

CHEKLOVLAR:
- Maksimal qadamlar soni: {max_steps}
- Mavjud toollar: {available_tools}

create_plan tool'ini chaqir.\
"""

PLANNER_TOOL_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Rejaning qisqa tavsifi",
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position": {
                        "type": "integer",
                        "description": "Qadam tartibi (0 dan boshlanadi)",
                    },
                    "description": {
                        "type": "string",
                        "description": "Qadam tavsifi",
                    },
                    "tool_name": {
                        # `["string", "null"]` EMAS — Cohere array-tipni rad
                        # etadi va provayder har chaqiruvda yiqilardi. Maydon
                        # `required`da yo'q, ya'ni tushirib qoldirish = null.
                        "type": "string",
                        "description": (
                            "Ishlatiladigan tool nomi. Faqat LLM fikrlashi "
                            "bo'lsa — maydonni umuman qo'shmang."
                        ),
                    },
                    "tool_params": {
                        "type": "object",
                        "description": (
                            "`tool_name` uchun kirish parametrlari — tool'ning "
                            "JSON Schema'siga mos bo'lishi shart (masalan note.write "
                            'uchun {"title": ..., "content": ...})'
                        ),
                    },
                    "permission_required": {
                        "type": "string",
                        "enum": ["read", "write", "execute", "admin"],
                        "description": "Kerakli ruxsat darajasi",
                    },
                    "trust_context": {
                        "type": "string",
                        "enum": ["owner", "system", "untrusted"],
                        "description": "Kirish ma'lumoti manbasi",
                    },
                    "expected_outcome": {
                        "type": "string",
                        "description": (
                            "Kutilgan natija. Qisqa bo'lsa (1-3 so'z yoki regex) "
                            "chiqishdan so'zma-so'z QIDIRILADI va topilmasa qadam "
                            "yiqiladi — shuning uchun faqat chiqishda haqiqatan "
                            "uchraydigan matnni yoz. Aks holda uzunroq tavsif yoz: "
                            "u tekshiruv sifatida ishlatilmaydi."
                        ),
                    },
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Bog'liq qadamlarning pozitsiyalari",
                    },
                },
                "required": ["position", "description", "permission_required"],
            },
            "description": "Tartiblangan qadamlar ro'yxati",
        },
    },
    "required": ["summary", "steps"],
}
