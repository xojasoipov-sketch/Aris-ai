"""Operations Agent — operatsion boshqaruv agenti (Bo'lim 4).

Asosiy vazifalar:
    - Tizim salomatligi monitoring
    - Resurs foydalanish tahlili (budjet, token, API)
    - Agent performance tracking
    - Xato va ogohlantirish boshqaruvi

QOIDALAR:
    - READ permission — monitoring va tahlil
    - SYSTEM trust level — ichki agent
    - Xavfsizlik hodisalarini darhol eskalashtirish
"""

from __future__ import annotations

from zet.domain.agent import AgentSpec
from zet.domain.enums import ModelTier, PermissionLevel, TrustLevel

OPERATIONS_SYSTEM_PROMPT = """\
Sen ZET tizimining Operations agentisan — operatsion monitoring va boshqaruv.

ROLLAR:
1. Tizim salomatligi — server holati, xotira, disk
2. Budjet monitoring — kunlik/oylik xarajatlar, limitlar
3. Agent performance — har bir agentning ishlash ko'rsatkichlari
4. Xato boshqaruvi — xatolarni aniqlash va tuzatish tavsiyalari

QOIDALAR:
1. Faqat READ ruxsatingiz bor — hech narsani o'zgartirmaysiz.
2. Kritik muammolarni darhol xabar qilasan.
3. Raqamlar va statistikalar aniq bo'lishi kerak.
4. Javobni ODDIY ODAM TELEGRAM'DA YOZGANDEK yoz — rasmiy hisobot EMAS.
   Sarlavha/bo'lim belgilari (##, ###, **, ---, jadval) ISHLATMA —
   Telegram ularni tushunmaydi, xom belgi (#, *, |) bo'lib ko'rinadi.
   Qisqa jumlalar yoz. Tizim holati, budjet, agent ishlashi, xatolar —
   har mavzu haqida alohida, lekin BO'SH QATOR bilan ajratilgan gap(lar)
   bilan yoz, xuddi odam ketma-ket yozgandek. Ro'yxat kerak bo'lsa —
   oddiy tire ("-") bilan, sarlavhasiz va jadvalsiz. Raqamni gap ichida
   tabiiy ayt ("Bugungi xarajat $2.10, oylik limitdan $7.90 qoldi" —
   jadval emas).

MUHIM: Budjet limitlarini doimo kuzatib tur. $10/oy limitdan oshmasin.\
"""

OPERATIONS_AGENT_SPEC = AgentSpec(
    name="operations",
    description="Operatsion monitoring — tizim salomatligi, budjet, agent performance, xatolar",
    division="ops",
    role="analyst",
    goal="Tizim operatsiyalarini monitoring qilish, budjet nazorati, xatolarni aniqlash",
    system_prompt=OPERATIONS_SYSTEM_PROMPT,
    tool_allowlist=[
        "web.search",
        "time.now",
        "memory.search",
        # Ish maydoni tool'lari (Z48.5) — T02 "Ovozdan rejaga" va T06
        # "Kunlik puls" AYNAN shu agentdan boshlanadi. Allowlist'siz
        # `AgentRuntime` chaqiruvni rad etadi ("allowlist'da yo'q") va
        # agent doskani umuman ko'rmagan holda hisobot YOZIB YUBORARDI —
        # ishonarli ko'rinishdagi to'qima. Bu vision agentdagi kamera
        # tool'i yo'qligining aynan takrori edi.
        "task.list",
        "task.create",
        "task.update",
        "task.pulse",
        "project.list",
        "project.create",
        "calendar.list",
        "calendar.add",
        # Jonli manbalar (Z50): "bugun havo qanday", "dollar qancha",
        # "yangiliklar" — bularsiz agent javobni O'YLAB TOPARDI.
        "weather.now",
        "news.headlines",
        "currency.rate",
    ],
    model_policy=ModelTier.T1_FREE,
    # WRITE: vazifa qo'shish va kalendarga yozish uchun. Doska ZET'ning
    # ICHKI ma'lumoti — tashqi dunyoga hech narsa yubormaydi, shuning
    # uchun EXECUTE emas.
    permission_level=PermissionLevel.WRITE,
    trust_level=TrustLevel.SYSTEM,
    max_steps=10,
    max_tool_calls=15,
    timeout_s=180,
)
