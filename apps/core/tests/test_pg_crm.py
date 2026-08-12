"""PgCRM testlari — DB-backed CRM (Bo'lim 6, C-03).

`conftest.py`dagi `session`/`owner` fixture'lari orqali real (in-memory
sqlite) DB'ga yozadi/o'qiydi.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.business.crm import DealStage, LeadStatus
from zet.business.pg_crm import CRMNotFoundError, PgCRM
from zet.db.models.owner import Owner


@pytest.fixture
def crm(session: AsyncSession, owner: Owner) -> PgCRM:
    return PgCRM(session, owner_id=owner.id)


class TestContacts:
    async def test_add_contact(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali Valiyev", company="Acme", email="ali@acme.uz")
        assert contact.name == "Ali Valiyev"
        assert contact.company == "Acme"
        assert contact.id != ""

    async def test_get_contact(self, crm: PgCRM) -> None:
        created = await crm.add_contact(name="Ali")
        fetched = await crm.get_contact(created.id)
        assert fetched is not None
        assert fetched.name == "Ali"

    async def test_get_missing_contact_returns_none(self, crm: PgCRM) -> None:
        assert await crm.get_contact("00000000-0000-0000-0000-000000000000") is None

    async def test_get_invalid_id_returns_none(self, crm: PgCRM) -> None:
        assert await crm.get_contact("not-a-uuid") is None

    async def test_list_contacts(self, crm: PgCRM) -> None:
        await crm.add_contact(name="A")
        await crm.add_contact(name="B")
        contacts = await crm.list_contacts()
        assert len(contacts) == 2

    async def test_find_contacts_by_name(self, crm: PgCRM) -> None:
        await crm.add_contact(name="Ali Valiyev")
        await crm.add_contact(name="Boris Ivanov")
        results = await crm.find_contacts("ali")
        assert len(results) == 1
        assert results[0].name == "Ali Valiyev"

    async def test_find_contacts_by_company(self, crm: PgCRM) -> None:
        await crm.add_contact(name="Ali", company="Acme Corp")
        await crm.add_contact(name="Boris", company="Other")
        results = await crm.find_contacts("acme")
        assert len(results) == 1

    async def test_owner_isolation(self, session: AsyncSession, owner: Owner) -> None:
        crm_a = PgCRM(session, owner_id=owner.id)
        await crm_a.add_contact(name="Faqat A uchun")

        other_owner = Owner(external_id="other-owner")
        session.add(other_owner)
        await session.flush()
        crm_b = PgCRM(session, owner_id=other_owner.id)

        assert await crm_b.list_contacts() == []


class TestLeads:
    async def test_add_lead(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        lead = await crm.add_lead(contact_id=contact.id, source="telegram")
        assert lead.contact_id == contact.id
        assert lead.source == "telegram"
        assert lead.status == LeadStatus.NEW

    async def test_add_lead_missing_contact_raises(self, crm: PgCRM) -> None:
        with pytest.raises(CRMNotFoundError):
            await crm.add_lead(contact_id="00000000-0000-0000-0000-000000000000")

    async def test_get_lead(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        created = await crm.add_lead(contact_id=contact.id)
        fetched = await crm.get_lead(created.id)
        assert fetched is not None

    async def test_list_leads_filters_by_status(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        lead = await crm.add_lead(contact_id=contact.id)
        await crm.qualify_lead(lead.id, score=80)
        await crm.add_lead(contact_id=contact.id)  # NEW holatda qoladi

        qualified = await crm.list_leads(LeadStatus.QUALIFIED)
        assert len(qualified) == 1

    async def test_qualify_lead_high_score(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        lead = await crm.add_lead(contact_id=contact.id)
        qualified = await crm.qualify_lead(lead.id, score=75)
        assert qualified.status == LeadStatus.QUALIFIED
        assert qualified.score == 75

    async def test_qualify_lead_low_score(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        lead = await crm.add_lead(contact_id=contact.id)
        result = await crm.qualify_lead(lead.id, score=20)
        assert result.status == LeadStatus.UNQUALIFIED

    async def test_qualify_missing_lead_raises(self, crm: PgCRM) -> None:
        with pytest.raises(CRMNotFoundError):
            await crm.qualify_lead("00000000-0000-0000-0000-000000000000", score=80)


class TestDeals:
    async def test_add_deal(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        lead = await crm.add_lead(contact_id=contact.id)
        deal = await crm.add_deal(lead_id=lead.id, title="Kurs sotuvi", amount=500.0)
        assert deal.title == "Kurs sotuvi"
        assert deal.amount == 500.0
        assert deal.stage == DealStage.PROPOSAL

    async def test_add_deal_missing_lead_raises(self, crm: PgCRM) -> None:
        with pytest.raises(CRMNotFoundError):
            await crm.add_deal(lead_id="00000000-0000-0000-0000-000000000000", title="X")

    async def test_update_deal_stage(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        lead = await crm.add_lead(contact_id=contact.id)
        deal = await crm.add_deal(lead_id=lead.id, title="X", amount=100.0)
        updated = await crm.update_deal_stage(deal.id, DealStage.WON)
        assert updated.stage == DealStage.WON

    async def test_update_missing_deal_raises(self, crm: PgCRM) -> None:
        with pytest.raises(CRMNotFoundError):
            await crm.update_deal_stage("00000000-0000-0000-0000-000000000000", DealStage.WON)

    async def test_list_deals_filters_by_stage(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        lead = await crm.add_lead(contact_id=contact.id)
        d1 = await crm.add_deal(lead_id=lead.id, title="A", amount=100.0)
        await crm.add_deal(lead_id=lead.id, title="B", amount=200.0)
        await crm.update_deal_stage(d1.id, DealStage.WON)

        won = await crm.list_deals(DealStage.WON)
        assert len(won) == 1


class TestReports:
    async def test_pipeline_value_excludes_won_lost(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        lead = await crm.add_lead(contact_id=contact.id)
        d1 = await crm.add_deal(lead_id=lead.id, title="A", amount=100.0)
        await crm.add_deal(lead_id=lead.id, title="B", amount=200.0)
        await crm.update_deal_stage(d1.id, DealStage.WON)

        assert await crm.pipeline_value() == 200.0

    async def test_won_value(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        lead = await crm.add_lead(contact_id=contact.id)
        deal = await crm.add_deal(lead_id=lead.id, title="A", amount=300.0)
        await crm.update_deal_stage(deal.id, DealStage.WON)

        assert await crm.won_value() == 300.0

    async def test_stats(self, crm: PgCRM) -> None:
        contact = await crm.add_contact(name="Ali")
        lead = await crm.add_lead(contact_id=contact.id)
        await crm.qualify_lead(lead.id, score=90)
        deal = await crm.add_deal(lead_id=lead.id, title="A", amount=150.0)
        await crm.update_deal_stage(deal.id, DealStage.WON)

        stats = await crm.stats()
        assert stats["contacts"] == 1
        assert stats["leads"] == 1
        assert stats["qualified_leads"] == 1
        assert stats["deals"] == 1
        assert stats["won_value"] == 150.0
