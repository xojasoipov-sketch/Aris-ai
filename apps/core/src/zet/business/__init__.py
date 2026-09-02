"""Biznes tizimi — CRM, pipeline, kontaktlar (Bo'lim 6).

Komponentlar:
    - CRM: minimal mijozlar bazasi (Lead, Contact, Deal)
    - Pipeline: sotuvlar bosqichlari
    - ContentCalendar: kontent rejasi

Bog'liq qarorlar:
    Bo'lim 6 — biznes agentlari
    C-04 — ijtimoiy tarmoqlar boshqaruvi
"""

from zet.business.crm import CRM, Contact, Deal, DealStage, Lead, LeadStatus

__all__ = [
    "CRM",
    "Contact",
    "Deal",
    "DealStage",
    "Lead",
    "LeadStatus",
]
