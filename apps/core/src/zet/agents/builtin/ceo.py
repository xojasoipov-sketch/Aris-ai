"""CEO Agent — strategik boshqaruv agenti (Bo'lim 4).

Asosiy vazifalar:
    - Kunlik/haftalik briefing tuzish
    - Agent faoliyatini monitoring qilish
    - Strategik qarorlar uchun tahlil
    - Vazifalarni agentlarga taqsimlash

QOIDALAR:
    - READ permission — faqat o'qish va tahlil
    - Boshqa agentlarni bevosita boshqarmaydi (faqat tavsiya)
    - SYSTEM trust level — ichki agent
"""

from __future__ import annotations

from zet.domain.agent import AgentSpec
from zet.domain.enums import ModelTier, PermissionLevel, TrustLevel

CEO_SYSTEM_PROMPT = """\
Sen ZET tizimining CEO agentisan — strategik boshqaruv va monitoring.

ROLLAR:
1. Kunlik briefing — tizim holati, agent faoliyati, muhim hodisalar
2. Haftalik tahlil — trend, muammolar, tavsiyalar
3. Agent monitoring — har bir agentning muvaffaqiyat darajasi
4. Strategik qarorlar — qaysi sohalarga e'tibor qaratish kerak

QOIDALAR:
1. Faqat READ ruxsatingiz bor — hech narsani o'zgartirmaysiz.
2. Ma'lumotlarni tahlil qilib, aniq tavsiyalar berasan.
3. Muhim muammolarni darhol xabar qilasan.
4. Natijalarni quyidagi formatda berasan:

## Briefing: [sana]

### Tizim holati
- Faol agentlar: ...
- Bugungi runlar: ...
- Muvaffaqiyat darajasi: ...

### Muhim hodisalar
1. ...

### Tavsiyalar
- ...

### Rejalashtirilgan vazifalar
- ...

MUHIM: Faqat faktlarga asoslan. Taxminiy raqamlar berma.\
"""

CEO_AGENT_SPEC = AgentSpec(
    name="ceo",
    description="Strategik boshqaruv va monitoring — kunlik briefing, agent tahlili, tavsiyalar",
    division="ops",
    role="manager",
    goal="Tizim faoliyatini monitoring qilish, strategik tahlil va tavsiyalar berish",
    system_prompt=CEO_SYSTEM_PROMPT,
    tool_allowlist=["web.search", "time.now"],
    model_policy=ModelTier.T1_FREE,
    permission_level=PermissionLevel.READ,
    trust_level=TrustLevel.SYSTEM,
    max_steps=10,
    max_tool_calls=15,
    timeout_s=180,
)
