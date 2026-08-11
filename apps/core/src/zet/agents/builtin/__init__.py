"""O'rnatilgan agentlar (Bo'lim 3-4).

Agentlar:
    - Research — read-only tadqiqot agenti (Bo'lim 3)
    - CEO — strategik boshqaruv va monitoring (Bo'lim 4)
    - Operations — operatsion monitoring va tahlil (Bo'lim 4)
"""

from zet.agents.builtin.ceo import CEO_AGENT_SPEC
from zet.agents.builtin.operations import OPERATIONS_AGENT_SPEC
from zet.agents.builtin.research import RESEARCH_AGENT_SPEC

__all__ = [
    "CEO_AGENT_SPEC",
    "OPERATIONS_AGENT_SPEC",
    "RESEARCH_AGENT_SPEC",
]
