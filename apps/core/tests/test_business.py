"""Bo'lim 6 — Biznes agentlari va CRM testlari.

Tekshiriladi:
    - SMM agent spec — kontent marketing
    - Sales agent spec — sotuvlar va CRM
    - Finance agent spec — moliya, majburiy approval
    - Support agent spec — qo'llab-quvvatlash
    - CRM: Contact, Lead, Deal CRUD
    - CRM: pipeline hisoboti va statistika
    - Builtin __init__ eksportlari
"""

from __future__ import annotations

import pytest

from zet.agents.builtin import (
    CEO_AGENT_SPEC,
    FINANCE_AGENT_SPEC,
    OPERATIONS_AGENT_SPEC,
    RESEARCH_AGENT_SPEC,
    SALES_AGENT_SPEC,
    SMM_AGENT_SPEC,
    SUPPORT_AGENT_SPEC,
)
from zet.agents.builtin.finance import FINANCE_AGENT_SPEC as FINANCE_DIRECT
from zet.agents.builtin.finance import FINANCE_SYSTEM_PROMPT
from zet.agents.builtin.sales import SALES_AGENT_SPEC as SALES_DIRECT
from zet.agents.builtin.sales import SALES_SYSTEM_PROMPT
from zet.agents.builtin.smm import SMM_AGENT_SPEC as SMM_DIRECT
from zet.agents.builtin.smm import SMM_SYSTEM_PROMPT
from zet.agents.builtin.support import SUPPORT_AGENT_SPEC as SUPPORT_DIRECT
from zet.agents.builtin.support import SUPPORT_SYSTEM_PROMPT
from zet.agents.eval import EvalRunner
from zet.business.crm import CRM, Contact, Deal, DealStage, Lead, LeadStatus
from zet.domain.enums import ModelTier, PermissionLevel, TrustLevel

# ── Builtin eksportlari ─────────────────────────────────────────


class TestBuiltinExports:
    """Builtin __init__.py barcha agentlarni eksport qiladi."""

    def test_all_seven_specs_exported(self) -> None:
        """7 ta agent spec eksport qilingan."""
        specs = [
            CEO_AGENT_SPEC,
            OPERATIONS_AGENT_SPEC,
            RESEARCH_AGENT_SPEC,
            SMM_AGENT_SPEC,
            SALES_AGENT_SPEC,
            FINANCE_AGENT_SPEC,
            SUPPORT_AGENT_SPEC,
        ]
        assert len(specs) == 7
        names = {s.name for s in specs}
        assert names == {"ceo", "operations", "research", "smm", "sales", "finance", "support"}

    def test_direct_import_matches_init(self) -> None:
        """To'g'ridan-to'g'ri import va __init__ orqali import bir xil."""
        assert SMM_AGENT_SPEC is SMM_DIRECT
        assert SALES_AGENT_SPEC is SALES_DIRECT
        assert FINANCE_AGENT_SPEC is FINANCE_DIRECT
        assert SUPPORT_AGENT_SPEC is SUPPORT_DIRECT


# ── SMM Agent ────────────────────────────────────────────────────


class TestSMMAgent:
    """SMM agent spec tekshiruvlari."""

    def test_spec_fields(self) -> None:
        """SMM agent asosiy maydonlari."""
        s = SMM_AGENT_SPEC
        assert s.name == "smm"
        assert s.division == "marketing"
        assert s.role == "writer"
        assert s.permission_level == PermissionLevel.WRITE
        assert s.trust_level == TrustLevel.SYSTEM
        assert s.model_policy == ModelTier.T1_FREE

    def test_tools(self) -> None:
        """SMM agent toollar ro'yxati."""
        assert "web.search" in SMM_AGENT_SPEC.tool_allowlist
        assert "time.now" in SMM_AGENT_SPEC.tool_allowlist
        assert "note.write" in SMM_AGENT_SPEC.tool_allowlist

    def test_brakes(self) -> None:
        """SMM agent tormozlari (A-07)."""
        s = SMM_AGENT_SPEC
        assert s.max_steps == 15
        assert s.max_tool_calls == 25
        assert s.timeout_s == 180

    def test_prompt_content(self) -> None:
        """SMM prompt asosiy elementlarni o'z ichiga oladi."""
        assert "SMM" in SMM_SYSTEM_PROMPT
        assert "RESEARCH" in SMM_SYSTEM_PROMPT
        assert "CONTENT" in SMM_SYSTEM_PROMPT
        assert "SCHEDULE" in SMM_SYSTEM_PROMPT
        assert "ANALYTICS" in SMM_SYSTEM_PROMPT
        assert "UNTRUSTED" in SMM_SYSTEM_PROMPT

    def test_eval_passes(self) -> None:
        """SMM spec eval dan o'tadi."""
        result = EvalRunner().run_eval(SMM_AGENT_SPEC)
        assert result.success
        assert result.passed == result.total

    def test_frozen(self) -> None:
        """SMM spec frozen — o'zgartirib bo'lmaydi."""
        with pytest.raises(Exception):  # noqa: B017
            SMM_AGENT_SPEC.name = "hacked"


# ── Sales Agent ──────────────────────────────────────────────────


class TestSalesAgent:
    """Sales agent spec tekshiruvlari."""

    def test_spec_fields(self) -> None:
        """Sales agent asosiy maydonlari."""
        s = SALES_AGENT_SPEC
        assert s.name == "sales"
        assert s.division == "marketing"
        assert s.role == "manager"
        assert s.permission_level == PermissionLevel.WRITE
        assert s.trust_level == TrustLevel.SYSTEM
        assert s.model_policy == ModelTier.T1_FREE

    def test_tools(self) -> None:
        """Sales agent toollar ro'yxati."""
        assert "web.search" in SALES_AGENT_SPEC.tool_allowlist
        assert "time.now" in SALES_AGENT_SPEC.tool_allowlist
        assert "note.write" in SALES_AGENT_SPEC.tool_allowlist

    def test_brakes(self) -> None:
        """Sales agent tormozlari (A-07)."""
        s = SALES_AGENT_SPEC
        assert s.max_steps == 15
        assert s.max_tool_calls == 25
        assert s.timeout_s == 180

    def test_prompt_content(self) -> None:
        """Sales prompt asosiy elementlarni o'z ichiga oladi."""
        assert "Sales" in SALES_SYSTEM_PROMPT
        assert "LEAD" in SALES_SYSTEM_PROMPT
        assert "QUALIFY" in SALES_SYSTEM_PROMPT
        assert "CRM" in SALES_SYSTEM_PROMPT
        assert "PIPELINE" in SALES_SYSTEM_PROMPT
        assert "BANT" in SALES_SYSTEM_PROMPT
        assert "UNTRUSTED" in SALES_SYSTEM_PROMPT

    def test_eval_passes(self) -> None:
        """Sales spec eval dan o'tadi."""
        result = EvalRunner().run_eval(SALES_AGENT_SPEC)
        assert result.success
        assert result.passed == result.total

    def test_frozen(self) -> None:
        """Sales spec frozen — o'zgartirib bo'lmaydi."""
        with pytest.raises(Exception):  # noqa: B017
            SALES_AGENT_SPEC.name = "hacked"


# ── Finance Agent ────────────────────────────────────────────────


class TestFinanceAgent:
    """Finance agent spec tekshiruvlari — majburiy approval."""

    def test_spec_fields(self) -> None:
        """Finance agent asosiy maydonlari."""
        s = FINANCE_AGENT_SPEC
        assert s.name == "finance"
        assert s.division == "finance"
        assert s.role == "analyst"
        # MUHIM: READ only — yozish uchun ega tasdig'i kerak
        assert s.permission_level == PermissionLevel.READ
        assert s.trust_level == TrustLevel.SYSTEM
        assert s.model_policy == ModelTier.T1_FREE

    def test_read_only_permission(self) -> None:
        """Finance faqat READ — WRITE emas (majburiy approval)."""
        assert FINANCE_AGENT_SPEC.permission_level == PermissionLevel.READ
        assert FINANCE_AGENT_SPEC.permission_level < PermissionLevel.WRITE

    def test_tools_minimal(self) -> None:
        """Finance agent minimal toollar — note.write YO'Q."""
        assert "web.search" in FINANCE_AGENT_SPEC.tool_allowlist
        assert "time.now" in FINANCE_AGENT_SPEC.tool_allowlist
        assert "note.write" not in FINANCE_AGENT_SPEC.tool_allowlist

    def test_brakes_strict(self) -> None:
        """Finance agent qattiq tormozlar (A-07)."""
        s = FINANCE_AGENT_SPEC
        assert s.max_steps == 10
        assert s.max_tool_calls == 15
        assert s.timeout_s == 120

    def test_prompt_approval(self) -> None:
        """Finance prompt MAJBURIY TASDIQ ni ta'kidlaydi."""
        assert "MAJBURIY" in FINANCE_SYSTEM_PROMPT
        assert "TASDIQ" in FINANCE_SYSTEM_PROMPT
        assert "$10" in FINANCE_SYSTEM_PROMPT
        assert "$0.50" in FINANCE_SYSTEM_PROMPT
        assert "$0.10" in FINANCE_SYSTEM_PROMPT
        assert "40%" in FINANCE_SYSTEM_PROMPT

    def test_prompt_budget_limits(self) -> None:
        """Finance prompt budjet chegaralarini o'z ichiga oladi."""
        assert "Oylik" in FINANCE_SYSTEM_PROMPT
        assert "Kunlik" in FINANCE_SYSTEM_PROMPT
        assert "Run" in FINANCE_SYSTEM_PROMPT

    def test_eval_passes(self) -> None:
        """Finance spec eval dan o'tadi."""
        result = EvalRunner().run_eval(FINANCE_AGENT_SPEC)
        assert result.success
        assert result.passed == result.total

    def test_frozen(self) -> None:
        """Finance spec frozen — o'zgartirib bo'lmaydi."""
        with pytest.raises(Exception):  # noqa: B017
            FINANCE_AGENT_SPEC.name = "hacked"


# ── Support Agent ────────────────────────────────────────────────


class TestSupportAgent:
    """Support agent spec tekshiruvlari."""

    def test_spec_fields(self) -> None:
        """Support agent asosiy maydonlari."""
        s = SUPPORT_AGENT_SPEC
        assert s.name == "support"
        assert s.division == "support"
        assert s.role == "assistant"
        assert s.permission_level == PermissionLevel.READ
        assert s.trust_level == TrustLevel.SYSTEM
        assert s.model_policy == ModelTier.T1_FREE

    def test_read_only(self) -> None:
        """Support faqat READ — foydalanuvchi ma'lumotlarini o'zgartirmaydi."""
        assert SUPPORT_AGENT_SPEC.permission_level == PermissionLevel.READ

    def test_tools_minimal(self) -> None:
        """Support agent minimal toollar."""
        assert "web.search" in SUPPORT_AGENT_SPEC.tool_allowlist
        assert "time.now" in SUPPORT_AGENT_SPEC.tool_allowlist
        assert "note.write" not in SUPPORT_AGENT_SPEC.tool_allowlist

    def test_brakes(self) -> None:
        """Support agent tormozlari."""
        s = SUPPORT_AGENT_SPEC
        assert s.max_steps == 10
        assert s.max_tool_calls == 15
        assert s.timeout_s == 120

    def test_prompt_content(self) -> None:
        """Support prompt asosiy elementlarni o'z ichiga oladi."""
        assert "Support" in SUPPORT_SYSTEM_PROMPT
        assert "RECEIVE" in SUPPORT_SYSTEM_PROMPT
        assert "CLASSIFY" in SUPPORT_SYSTEM_PROMPT
        assert "RESPOND" in SUPPORT_SYSTEM_PROMPT
        assert "ESCALATE" in SUPPORT_SYSTEM_PROMPT
        assert "UNTRUSTED" in SUPPORT_SYSTEM_PROMPT

    def test_prompt_escalation_rules(self) -> None:
        """Support prompt eskalatsiya qoidalarini o'z ichiga oladi."""
        assert "SHOSHILINCH" in SUPPORT_SYSTEM_PROMPT
        assert "developer" in SUPPORT_SYSTEM_PROMPT
        assert "finance" in SUPPORT_SYSTEM_PROMPT

    def test_eval_passes(self) -> None:
        """Support spec eval dan o'tadi."""
        result = EvalRunner().run_eval(SUPPORT_AGENT_SPEC)
        assert result.success
        assert result.passed == result.total

    def test_frozen(self) -> None:
        """Support spec frozen — o'zgartirib bo'lmaydi."""
        with pytest.raises(Exception):  # noqa: B017
            SUPPORT_AGENT_SPEC.name = "hacked"


# ── CRM Models ───────────────────────────────────────────────────


class TestLeadStatus:
    """LeadStatus enum testlari."""

    def test_values(self) -> None:
        """4 ta lead holati mavjud."""
        assert LeadStatus.NEW == "new"
        assert LeadStatus.CONTACTED == "contacted"
        assert LeadStatus.QUALIFIED == "qualified"
        assert LeadStatus.UNQUALIFIED == "unqualified"

    def test_count(self) -> None:
        """4 ta holat."""
        assert len(LeadStatus) == 4


class TestDealStage:
    """DealStage enum testlari."""

    def test_values(self) -> None:
        """4 ta deal bosqichi mavjud."""
        assert DealStage.PROPOSAL == "proposal"
        assert DealStage.NEGOTIATION == "negotiation"
        assert DealStage.WON == "won"
        assert DealStage.LOST == "lost"

    def test_count(self) -> None:
        """4 ta bosqich."""
        assert len(DealStage) == 4


class TestContact:
    """Contact model testlari."""

    def test_create(self) -> None:
        """Contact yaratish."""
        c = Contact(name="Ali Valiyev")
        assert c.name == "Ali Valiyev"
        assert c.company == ""
        assert c.email == ""
        assert c.phone == ""
        assert c.telegram == ""
        assert c.notes == ""
        assert len(c.id) == 12

    def test_full_contact(self) -> None:
        """To'liq kontakt."""
        c = Contact(
            name="Ali Valiyev",
            company="TechCo",
            email="ali@tech.co",
            phone="+998901234567",
            telegram="@ali",
            notes="Asosiy mijoz",
        )
        assert c.company == "TechCo"
        assert c.email == "ali@tech.co"
        assert c.phone == "+998901234567"
        assert c.telegram == "@ali"

    def test_frozen(self) -> None:
        """Contact frozen — o'zgartirib bo'lmaydi."""
        c = Contact(name="Test")
        with pytest.raises(Exception):  # noqa: B017
            c.name = "Changed"

    def test_unique_ids(self) -> None:
        """Har bir kontakt unikal ID oladi."""
        c1 = Contact(name="A")
        c2 = Contact(name="B")
        assert c1.id != c2.id


class TestLead:
    """Lead model testlari."""

    def test_create(self) -> None:
        """Lead yaratish."""
        lead = Lead(contact_id="abc123")
        assert lead.contact_id == "abc123"
        assert lead.source == ""
        assert lead.status == LeadStatus.NEW
        assert lead.score == 0
        assert len(lead.id) == 12

    def test_with_score(self) -> None:
        """Lead bali bilan yaratish."""
        lead = Lead(contact_id="abc", source="telegram", score=75)
        assert lead.source == "telegram"
        assert lead.score == 75

    def test_score_bounds(self) -> None:
        """Score 0-100 oralig'ida bo'lishi kerak."""
        with pytest.raises(Exception):  # noqa: B017
            Lead(contact_id="abc", score=-1)
        with pytest.raises(Exception):  # noqa: B017
            Lead(contact_id="abc", score=101)

    def test_frozen(self) -> None:
        """Lead frozen — o'zgartirib bo'lmaydi."""
        lead = Lead(contact_id="abc")
        with pytest.raises(Exception):  # noqa: B017
            lead.status = LeadStatus.QUALIFIED


class TestDeal:
    """Deal model testlari."""

    def test_create(self) -> None:
        """Deal yaratish."""
        deal = Deal(lead_id="lead1", title="Cloud xizmat")
        assert deal.lead_id == "lead1"
        assert deal.title == "Cloud xizmat"
        assert deal.amount == 0.0
        assert deal.stage == DealStage.PROPOSAL
        assert len(deal.id) == 12

    def test_with_amount(self) -> None:
        """Deal summa bilan yaratish."""
        deal = Deal(lead_id="lead1", title="Loyiha", amount=5000.0)
        assert deal.amount == 5000.0

    def test_negative_amount(self) -> None:
        """Manfiy summa ruxsat etilmaydi."""
        with pytest.raises(Exception):  # noqa: B017
            Deal(lead_id="lead1", title="Test", amount=-100.0)

    def test_frozen(self) -> None:
        """Deal frozen — o'zgartirib bo'lmaydi."""
        deal = Deal(lead_id="lead1", title="Test")
        with pytest.raises(Exception):  # noqa: B017
            deal.stage = DealStage.WON


# ── CRM Operations ──────────────────────────────────────────────


class TestCRMContacts:
    """CRM kontakt operatsiyalari."""

    def setup_method(self) -> None:
        self.crm = CRM()

    def test_add_contact(self) -> None:
        """Kontakt qo'shish."""
        c = self.crm.add_contact(name="Ali Valiyev")
        assert c.name == "Ali Valiyev"
        assert self.crm.get_contact(c.id) is c

    def test_add_contact_full(self) -> None:
        """To'liq kontakt qo'shish."""
        c = self.crm.add_contact(
            name="Saidov",
            company="DevCo",
            email="s@dev.co",
        )
        assert c.company == "DevCo"
        assert c.email == "s@dev.co"

    def test_get_missing(self) -> None:
        """Mavjud bo'lmagan kontakt — None."""
        assert self.crm.get_contact("nonexistent") is None

    def test_list_contacts(self) -> None:
        """Kontaktlar ro'yxati."""
        self.crm.add_contact(name="A")
        self.crm.add_contact(name="B")
        self.crm.add_contact(name="C")
        assert len(self.crm.list_contacts()) == 3

    def test_list_empty(self) -> None:
        """Bo'sh CRM — bo'sh ro'yxat."""
        assert self.crm.list_contacts() == []

    def test_find_by_name(self) -> None:
        """Nom bo'yicha qidirish."""
        self.crm.add_contact(name="Ali Valiyev")
        self.crm.add_contact(name="Saidov")
        found = self.crm.find_contacts("ali")
        assert len(found) == 1
        assert found[0].name == "Ali Valiyev"

    def test_find_by_company(self) -> None:
        """Kompaniya bo'yicha qidirish."""
        self.crm.add_contact(name="Test", company="TechCo")
        self.crm.add_contact(name="Other", company="FinCo")
        found = self.crm.find_contacts("tech")
        assert len(found) == 1
        assert found[0].company == "TechCo"

    def test_find_by_email(self) -> None:
        """Email bo'yicha qidirish."""
        self.crm.add_contact(name="Test", email="ali@test.com")
        found = self.crm.find_contacts("ali@test")
        assert len(found) == 1

    def test_find_case_insensitive(self) -> None:
        """Qidirish katta-kichik harfga sezgir emas."""
        self.crm.add_contact(name="ALI VALIYEV")
        assert len(self.crm.find_contacts("ali")) == 1
        assert len(self.crm.find_contacts("ALI")) == 1

    def test_find_no_results(self) -> None:
        """Topilmadi — bo'sh ro'yxat."""
        self.crm.add_contact(name="Ali")
        assert self.crm.find_contacts("xyz") == []


class TestCRMLeads:
    """CRM lead operatsiyalari."""

    def setup_method(self) -> None:
        self.crm = CRM()
        self.contact = self.crm.add_contact(name="Lead Contact")

    def test_add_lead(self) -> None:
        """Lead qo'shish."""
        lead = self.crm.add_lead(contact_id=self.contact.id)
        assert lead.contact_id == self.contact.id
        assert lead.status == LeadStatus.NEW
        assert self.crm.get_lead(lead.id) is lead

    def test_add_lead_full(self) -> None:
        """To'liq lead qo'shish."""
        lead = self.crm.add_lead(
            contact_id=self.contact.id,
            source="telegram",
            score=60,
            notes="Qiziqarli",
        )
        assert lead.source == "telegram"
        assert lead.score == 60
        assert lead.notes == "Qiziqarli"

    def test_add_lead_missing_contact(self) -> None:
        """Mavjud bo'lmagan kontakt uchun lead — ValueError."""
        with pytest.raises(ValueError, match="topilmadi"):
            self.crm.add_lead(contact_id="nonexistent")

    def test_get_missing(self) -> None:
        """Mavjud bo'lmagan lead — None."""
        assert self.crm.get_lead("nonexistent") is None

    def test_list_all(self) -> None:
        """Barcha leadlar."""
        self.crm.add_lead(contact_id=self.contact.id)
        self.crm.add_lead(contact_id=self.contact.id)
        assert len(self.crm.list_leads()) == 2

    def test_list_by_status(self) -> None:
        """Holat bo'yicha filtrlash."""
        lead = self.crm.add_lead(contact_id=self.contact.id)
        self.crm.qualify_lead(lead.id, score=80)
        assert len(self.crm.list_leads(LeadStatus.QUALIFIED)) == 1
        assert len(self.crm.list_leads(LeadStatus.NEW)) == 0

    def test_qualify_high_score(self) -> None:
        """Yuqori ball — QUALIFIED."""
        lead = self.crm.add_lead(contact_id=self.contact.id)
        updated = self.crm.qualify_lead(lead.id, score=75)
        assert updated.status == LeadStatus.QUALIFIED
        assert updated.score == 75

    def test_qualify_low_score(self) -> None:
        """Past ball — UNQUALIFIED."""
        lead = self.crm.add_lead(contact_id=self.contact.id)
        updated = self.crm.qualify_lead(lead.id, score=30)
        assert updated.status == LeadStatus.UNQUALIFIED
        assert updated.score == 30

    def test_qualify_threshold(self) -> None:
        """Chegara ball (50) — QUALIFIED."""
        lead = self.crm.add_lead(contact_id=self.contact.id)
        updated = self.crm.qualify_lead(lead.id, score=50)
        assert updated.status == LeadStatus.QUALIFIED

    def test_qualify_below_threshold(self) -> None:
        """Chegaradan past (49) — UNQUALIFIED."""
        lead = self.crm.add_lead(contact_id=self.contact.id)
        updated = self.crm.qualify_lead(lead.id, score=49)
        assert updated.status == LeadStatus.UNQUALIFIED

    def test_qualify_missing_lead(self) -> None:
        """Mavjud bo'lmagan lead — ValueError."""
        with pytest.raises(ValueError, match="topilmadi"):
            self.crm.qualify_lead("nonexistent", score=50)

    def test_qualify_preserves_fields(self) -> None:
        """Kvalifikatsiya boshqa maydonlarni saqlaydi."""
        lead = self.crm.add_lead(
            contact_id=self.contact.id,
            source="web",
            notes="Original",
        )
        updated = self.crm.qualify_lead(lead.id, score=80)
        assert updated.id == lead.id
        assert updated.contact_id == self.contact.id
        assert updated.source == "web"
        assert updated.created_at == lead.created_at

    def test_qualify_with_notes(self) -> None:
        """Kvalifikatsiyada yangi izoh."""
        lead = self.crm.add_lead(contact_id=self.contact.id, notes="Eski")
        updated = self.crm.qualify_lead(lead.id, score=80, notes="Yangi izoh")
        assert updated.notes == "Yangi izoh"

    def test_qualify_preserves_old_notes(self) -> None:
        """Yangi izoh bo'lmasa, eski saqlanadi."""
        lead = self.crm.add_lead(contact_id=self.contact.id, notes="Eski izoh")
        updated = self.crm.qualify_lead(lead.id, score=80)
        assert updated.notes == "Eski izoh"


class TestCRMDeals:
    """CRM deal operatsiyalari."""

    def setup_method(self) -> None:
        self.crm = CRM()
        self.contact = self.crm.add_contact(name="Deal Contact")
        self.lead = self.crm.add_lead(contact_id=self.contact.id)

    def test_add_deal(self) -> None:
        """Deal qo'shish."""
        deal = self.crm.add_deal(lead_id=self.lead.id, title="Loyiha A")
        assert deal.lead_id == self.lead.id
        assert deal.title == "Loyiha A"
        assert deal.stage == DealStage.PROPOSAL
        assert self.crm.get_deal(deal.id) is deal

    def test_add_deal_with_amount(self) -> None:
        """Deal summa bilan."""
        deal = self.crm.add_deal(
            lead_id=self.lead.id,
            title="Katta loyiha",
            amount=10000.0,
        )
        assert deal.amount == 10000.0

    def test_add_deal_missing_lead(self) -> None:
        """Mavjud bo'lmagan lead uchun deal — ValueError."""
        with pytest.raises(ValueError, match="topilmadi"):
            self.crm.add_deal(lead_id="nonexistent", title="Test")

    def test_get_missing(self) -> None:
        """Mavjud bo'lmagan deal — None."""
        assert self.crm.get_deal("nonexistent") is None

    def test_list_all(self) -> None:
        """Barcha deallar."""
        self.crm.add_deal(lead_id=self.lead.id, title="A")
        self.crm.add_deal(lead_id=self.lead.id, title="B")
        assert len(self.crm.list_deals()) == 2

    def test_list_by_stage(self) -> None:
        """Bosqich bo'yicha filtrlash."""
        deal = self.crm.add_deal(lead_id=self.lead.id, title="A")
        self.crm.update_deal_stage(deal.id, DealStage.WON)
        assert len(self.crm.list_deals(DealStage.WON)) == 1
        assert len(self.crm.list_deals(DealStage.PROPOSAL)) == 0

    def test_update_stage(self) -> None:
        """Deal bosqichini yangilash."""
        deal = self.crm.add_deal(lead_id=self.lead.id, title="Test")
        updated = self.crm.update_deal_stage(deal.id, DealStage.NEGOTIATION)
        assert updated.stage == DealStage.NEGOTIATION

    def test_update_stage_preserves_fields(self) -> None:
        """Bosqich yangilash boshqa maydonlarni saqlaydi."""
        deal = self.crm.add_deal(
            lead_id=self.lead.id,
            title="Loyiha",
            amount=5000.0,
        )
        updated = self.crm.update_deal_stage(deal.id, DealStage.WON)
        assert updated.id == deal.id
        assert updated.lead_id == deal.lead_id
        assert updated.title == "Loyiha"
        assert updated.amount == 5000.0
        assert updated.created_at == deal.created_at

    def test_update_missing_deal(self) -> None:
        """Mavjud bo'lmagan deal — ValueError."""
        with pytest.raises(ValueError, match="topilmadi"):
            self.crm.update_deal_stage("nonexistent", DealStage.WON)

    def test_full_pipeline(self) -> None:
        """To'liq pipeline: PROPOSAL → NEGOTIATION → WON."""
        deal = self.crm.add_deal(
            lead_id=self.lead.id,
            title="Full pipeline",
            amount=3000.0,
        )
        assert deal.stage == DealStage.PROPOSAL
        deal = self.crm.update_deal_stage(deal.id, DealStage.NEGOTIATION)
        assert deal.stage == DealStage.NEGOTIATION
        deal = self.crm.update_deal_stage(deal.id, DealStage.WON)
        assert deal.stage == DealStage.WON


# ── CRM Statistics ───────────────────────────────────────────────


class TestCRMStats:
    """CRM statistikasi va pipeline hisoboti."""

    def setup_method(self) -> None:
        self.crm = CRM()

    def test_empty_stats(self) -> None:
        """Bo'sh CRM statistikasi."""
        stats = self.crm.stats
        assert stats["contacts"] == 0
        assert stats["leads"] == 0
        assert stats["qualified_leads"] == 0
        assert stats["deals"] == 0
        assert stats["pipeline_value"] == 0.0
        assert stats["won_value"] == 0.0

    def test_pipeline_value(self) -> None:
        """Pipeline qiymati — faqat faol deallar."""
        c = self.crm.add_contact(name="Test")
        lead = self.crm.add_lead(contact_id=c.id)
        self.crm.add_deal(lead_id=lead.id, title="A", amount=1000.0)
        self.crm.add_deal(lead_id=lead.id, title="B", amount=2000.0)
        assert self.crm.pipeline_value == 3000.0

    def test_pipeline_excludes_won(self) -> None:
        """Pipeline qiymati WON dalllarni hisoblamaydi."""
        c = self.crm.add_contact(name="Test")
        lead = self.crm.add_lead(contact_id=c.id)
        self.crm.add_deal(lead_id=lead.id, title="Active", amount=1000.0)
        d2 = self.crm.add_deal(lead_id=lead.id, title="Won", amount=2000.0)
        self.crm.update_deal_stage(d2.id, DealStage.WON)
        assert self.crm.pipeline_value == 1000.0

    def test_pipeline_excludes_lost(self) -> None:
        """Pipeline qiymati LOST deallarni hisoblamaydi."""
        c = self.crm.add_contact(name="Test")
        lead = self.crm.add_lead(contact_id=c.id)
        self.crm.add_deal(lead_id=lead.id, title="Active", amount=1000.0)
        d2 = self.crm.add_deal(lead_id=lead.id, title="Lost", amount=2000.0)
        self.crm.update_deal_stage(d2.id, DealStage.LOST)
        assert self.crm.pipeline_value == 1000.0

    def test_won_value(self) -> None:
        """Yutilgan deallar qiymati."""
        c = self.crm.add_contact(name="Test")
        lead = self.crm.add_lead(contact_id=c.id)
        d1 = self.crm.add_deal(lead_id=lead.id, title="Won1", amount=1000.0)
        d2 = self.crm.add_deal(lead_id=lead.id, title="Won2", amount=2000.0)
        self.crm.add_deal(lead_id=lead.id, title="Active", amount=500.0)
        self.crm.update_deal_stage(d1.id, DealStage.WON)
        self.crm.update_deal_stage(d2.id, DealStage.WON)
        assert self.crm.won_value == 3000.0

    def test_full_stats(self) -> None:
        """To'liq statistika."""
        c1 = self.crm.add_contact(name="A")
        c2 = self.crm.add_contact(name="B")
        lead1 = self.crm.add_lead(contact_id=c1.id)
        self.crm.add_lead(contact_id=c2.id)
        self.crm.qualify_lead(lead1.id, score=80)
        self.crm.add_deal(lead_id=lead1.id, title="D1", amount=1000.0)
        d2 = self.crm.add_deal(lead_id=lead1.id, title="D2", amount=2000.0)
        self.crm.update_deal_stage(d2.id, DealStage.WON)

        stats = self.crm.stats
        assert stats["contacts"] == 2
        assert stats["leads"] == 2
        assert stats["qualified_leads"] == 1
        assert stats["deals"] == 2
        assert stats["pipeline_value"] == 1000.0
        assert stats["won_value"] == 2000.0


# ── CRM init eksportlari ────────────────────────────────────────


class TestBusinessInit:
    """Business __init__.py eksportlari."""

    def test_all_exports(self) -> None:
        """Barcha CRM komponentlari eksport qilingan."""
        from zet.business import CRM, Contact, Deal, DealStage, Lead, LeadStatus

        assert CRM is not None
        assert Contact is not None
        assert Lead is not None
        assert Deal is not None
        assert LeadStatus is not None
        assert DealStage is not None


# ── Agent Security Checks ───────────────────────────────────────


class TestAgentSecurityInvariants:
    """Barcha biznes agentlari xavfsizlik invariantlari."""

    ALL_BUSINESS_SPECS: list = [  # noqa: RUF012
        SMM_AGENT_SPEC,
        SALES_AGENT_SPEC,
        FINANCE_AGENT_SPEC,
        SUPPORT_AGENT_SPEC,
    ]

    def test_all_system_trust(self) -> None:
        """Barcha biznes agentlari SYSTEM trust levelda."""
        for spec in self.ALL_BUSINESS_SPECS:
            assert spec.trust_level == TrustLevel.SYSTEM, f"{spec.name} trust != SYSTEM"

    def test_all_t1_free(self) -> None:
        """Barcha biznes agentlari T1_FREE model policy."""
        for spec in self.ALL_BUSINESS_SPECS:
            assert spec.model_policy == ModelTier.T1_FREE, f"{spec.name} model != T1_FREE"

    def test_no_execute_or_admin(self) -> None:
        """Hech bir biznes agenti EXECUTE yoki ADMIN ruxsatiga ega emas."""
        for spec in self.ALL_BUSINESS_SPECS:
            assert spec.permission_level <= PermissionLevel.WRITE, (
                f"{spec.name} permission too high: {spec.permission_level}"
            )

    def test_brakes_within_limits(self) -> None:
        """Barcha tormozlar o'rtacha chegarada."""
        for spec in self.ALL_BUSINESS_SPECS:
            assert spec.max_steps <= 20, f"{spec.name} max_steps too high"
            assert spec.max_tool_calls <= 30, f"{spec.name} max_tool_calls too high"
            assert spec.timeout_s <= 300, f"{spec.name} timeout too high"

    def test_unique_names(self) -> None:
        """Barcha agent nomlari unikal."""
        names = [s.name for s in self.ALL_BUSINESS_SPECS]
        assert len(names) == len(set(names))

    def test_prompts_have_rules(self) -> None:
        """Barcha promptlarda QOIDALAR bor."""
        prompts = {
            "smm": SMM_SYSTEM_PROMPT,
            "sales": SALES_SYSTEM_PROMPT,
            "finance": FINANCE_SYSTEM_PROMPT,
            "support": SUPPORT_SYSTEM_PROMPT,
        }
        for name, prompt in prompts.items():
            assert "QOIDALAR" in prompt, f"{name} prompt missing QOIDALAR"

    def test_finance_stricter_than_sales(self) -> None:
        """Finance agenti Sales dan qattiqroq cheklovlarga ega."""
        assert FINANCE_AGENT_SPEC.permission_level < SALES_AGENT_SPEC.permission_level
        assert FINANCE_AGENT_SPEC.max_steps <= SALES_AGENT_SPEC.max_steps
        assert FINANCE_AGENT_SPEC.max_tool_calls <= SALES_AGENT_SPEC.max_tool_calls
        assert FINANCE_AGENT_SPEC.timeout_s <= SALES_AGENT_SPEC.timeout_s
