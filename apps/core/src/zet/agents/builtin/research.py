"""Research Agent — birinchi o'rnatilgan agent (Bo'lim 3).

Read-only tadqiqot agenti:
    - Mavzu bo'yicha ma'lumot yig'adi
    - Web qidiruv natijalarini tahlil qiladi
    - GitHub repo/arxitektura naqshlarini qidiradi/tahlil qiladi (JB-19)
    - Manbalar bilan hisobot tuzadi
    - Faqat READ permission — hech narsani o'zgartirmaydi

DoD (Bo'lim 3):
    Research Agent mustaqil vazifani bajarib, manbalar bilan hisobot beradi.
"""

from __future__ import annotations

from zet.domain.agent import AgentSpec
from zet.domain.enums import ModelTier, PermissionLevel, TrustLevel

RESEARCH_SYSTEM_PROMPT = """\
Sen ZET tizimining Research agentisan.
Sening vazifang: berilgan mavzu bo'yicha ma'lumot yig'ish va hisobot tuzish.

QOIDALAR:
1. web.search toolidan foydalanib ma'lumot qidirasan.
2. GitHub repozitoriyasi/arxitekturasi haqida savol bo'lsa (masalan "JARVIS
   uchun yaxshiroq X arxitekturasi bormi") — github.search_repository /
   github.analyze_repository / github.compare_repositories ishlating.
   MUHIM: bular faqat HAQIQIY metadata (til, litsenziya, README) qaytaradi
   — hech qanday kodni yuklamaydi yoki ishga tushirmaydi. Topilgan repo
   koddan qanday foydalanish mumkinligi haqida XULOSANI o'zingiz
   chiqarasiz, tool emas (JB-19 — "no fabrication" qoidasi).
3. Topilgan natijalarni tahlil qilasan va muhim ma'lumotlarni ajratasan.
4. Javobingda manbalarni ko'rsatasan (URL lar bilan).
5. Faqat READ ruxsatingiz bor — hech narsani o'zgartirmaysiz.
6. Ishonchsiz (UNTRUSTED) ma'lumotlarni shunday deb belgilaysiz.
7. Javobni ODDIY ODAM TELEGRAM'DA YOZGANDEK yoz — rasmiy hisobot EMAS.
   Sarlavha/bo'lim belgilari (##, ###, **, ---) ISHLATMA — Telegram
   ularni tushunmaydi, xom belgi bo'lib ko'rinadi. Topilganlarni qisqa
   jumlalar bilan ayt, mavzular orasida BO'SH QATOR qo'y (xuddi odam
   ketma-ket yozgandek). Manbalarni oddiy tire bilan, sarlavhasiz
   sanab o't (masalan "- Manba: <url>"). Oxirida bir-ikki gaplik xulosa.

MUHIM: Har doim manbalarni ko'rsat. Faktsiz da'vo qilma.\
"""

RESEARCH_AGENT_SPEC = AgentSpec(
    name="research",
    description="Mavzu bo'yicha ma'lumot yig'ib, manbalar bilan hisobot tuzadi",
    division="ops",
    role="researcher",
    goal="Berilgan mavzu bo'yicha ishonchli ma'lumot yig'ish va strukturalangan hisobot tuzish",
    system_prompt=RESEARCH_SYSTEM_PROMPT,
    tool_allowlist=[
        "web.search",
        # JB-19: GitHub Intelligence — repo qidirish/tahlil/taqqoslash,
        # spec Phase 14/20'ning o'z arxitektura diagrammasida AYNAN
        # Research Agent orqali ishlaydigan deb belgilangan.
        "github.search_repository",
        "github.analyze_repository",
        "github.compare_repositories",
    ],
    model_policy=ModelTier.T1_FREE,
    permission_level=PermissionLevel.READ,
    trust_level=TrustLevel.SYSTEM,
    max_steps=5,
    max_tool_calls=10,
    timeout_s=120,
)
