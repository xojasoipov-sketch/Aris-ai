"""O'rnatilgan agentlar (Bo'lim 3-4, 6-8, 12).

Agentlar:
    - Research — read-only tadqiqot agenti (Bo'lim 3)
    - CEO — strategik boshqaruv va monitoring (Bo'lim 4)
    - Operations — operatsion monitoring va tahlil (Bo'lim 4)
    - SMM — ijtimoiy tarmoq marketing (Bo'lim 6)
    - Sales — sotuvlar va CRM (Bo'lim 6)
    - Finance — moliya kuzatish, majburiy approval (Bo'lim 6)
    - Support — qo'llab-quvvatlash (Bo'lim 6)
    - Developer — GitHub issue/PR boshqaruvi (Bo'lim 7)
    - Vision — kamera snapshot tahlili, OCR (Bo'lim 8)
    - HR — kadrlar boshqaruvi (Bo'lim 12)
    - Security — xavfsizlik monitoringi (Bo'lim 12)
    - Analytics — ma'lumotlar tahlili (Bo'lim 12)
"""

from zet.agents.builtin.analytics import ANALYTICS_AGENT_SPEC
from zet.agents.builtin.ceo import CEO_AGENT_SPEC
from zet.agents.builtin.developer import DEVELOPER_AGENT_SPEC
from zet.agents.builtin.finance import FINANCE_AGENT_SPEC
from zet.agents.builtin.hr import HR_AGENT_SPEC
from zet.agents.builtin.operations import OPERATIONS_AGENT_SPEC
from zet.agents.builtin.research import RESEARCH_AGENT_SPEC
from zet.agents.builtin.sales import SALES_AGENT_SPEC
from zet.agents.builtin.security import SECURITY_AGENT_SPEC
from zet.agents.builtin.smm import SMM_AGENT_SPEC
from zet.agents.builtin.support import SUPPORT_AGENT_SPEC
from zet.agents.builtin.vision import VISION_AGENT_SPEC

__all__ = [
    "ANALYTICS_AGENT_SPEC",
    "CEO_AGENT_SPEC",
    "DEVELOPER_AGENT_SPEC",
    "FINANCE_AGENT_SPEC",
    "HR_AGENT_SPEC",
    "OPERATIONS_AGENT_SPEC",
    "RESEARCH_AGENT_SPEC",
    "SALES_AGENT_SPEC",
    "SECURITY_AGENT_SPEC",
    "SMM_AGENT_SPEC",
    "SUPPORT_AGENT_SPEC",
    "VISION_AGENT_SPEC",
]
