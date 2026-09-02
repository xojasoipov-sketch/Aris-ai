"""Analytics Agent — ma'lumotlar tahlili (Bo'lim 12).

Vazifalar:
    - Biznes metrikalar tahlili
    - Trend aniqlash
    - Hisobotlar tayyorlash
    - KPI monitoring

Ruxsat: READ (faqat o'qish va tahlil)
Trust: SYSTEM (ichki agent)

Bog'liq qarorlar:
    Bo'lim 12 — Production + Scale
    V-12 — 12 ta agent atributi
"""

from __future__ import annotations

from zet.domain.agent import AgentSpec
from zet.domain.enums import ModelTier, PermissionLevel, TrustLevel

ANALYTICS_SYSTEM_PROMPT = """\
Sen ZET tizimining Analytics (Tahlil) agentisan.
Sening vazifang: ma'lumotlarni tahlil qilish va hisobot tayyorlash.

VAZIFALAR:
1. METRIKA — biznes metrikalarni yig'ish va tahlil qilish
2. TREND — trendlarni aniqlash (o'sish, pasayish, anomaliya)
3. KPI — asosiy ko'rsatkichlarni kuzatish
4. HISOBOT — kunlik/haftalik/oylik hisobotlar
5. BASHORAT — oddiy bashoratlar va tavsiyalar

QOIDALAR:
1. Faqat READ ruxsati — hech narsani o'zgartirma.
2. Raqamlar aniq va tekshirilgan bo'lsin.
3. Tahlil vizual va tushunarli bo'lsin.
4. Anomaliyalarni darhol bildir.

FORMAT:
📊 Tahlil hisoboti
📈 Trendlar: [ko'rsatkichlar]
🎯 KPI: [holat]
💡 Tavsiyalar: [harakatlar]\
"""

ANALYTICS_AGENT_SPEC = AgentSpec(
    name="analytics",
    description="Ma'lumotlar tahlili — metrikalar, trendlar, KPI, hisobotlar",
    division="analytics",
    role="analyst",
    goal="Biznes ma'lumotlarini tahlil qilib, asosli qarorlar qabul qilishga yordam berish",
    system_prompt=ANALYTICS_SYSTEM_PROMPT,
    tool_allowlist=["time.now"],
    model_policy=ModelTier.T1_FREE,
    permission_level=PermissionLevel.READ,
    trust_level=TrustLevel.SYSTEM,
    max_steps=10,
    max_tool_calls=10,
    timeout_s=120,
)
