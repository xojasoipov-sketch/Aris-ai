"""Agent Eval — avtomatik sinov tizimi (Bo'lim 4).

Agent yaratilganda avtomatik eval to'plami generatsiya qilinadi.
DRAFT → TESTING o'tishida eval yuritiladi.
Faqat muvaffaqiyatli eval dan keyin ACTIVE ga o'tish mumkin.

Eval tekshiruvlari:
    1. Spec validatsiyasi — barcha kerakli maydonlar to'ldirilgan
    2. Tool validatsiyasi — tool allowlist dagi toollar mavjud
    3. Permission validatsiyasi — toollar ruxsat darajasiga mos
    4. Prompt validatsiyasi — system prompt minimal sifat
    5. Brake validatsiyasi — tormozlar o'rnatilgan (A-07)

Bog'liq qarorlar:
    V-10 — Factory eval bosqichi
    A-07 — tormozlar tekshiruvi
    V-31 — ruxsat darajalari
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from zet.domain.agent import AgentSpec
from zet.domain.enums import PermissionLevel


class EvalCase(BaseModel, frozen=True):
    """Bitta eval test holati."""

    name: str
    """Test nomi."""

    description: str
    """Test tavsifi."""

    passed: bool = False
    """Test natijasi."""

    error: str | None = None
    """Xato xabari (agar o'tmagan bo'lsa)."""


class EvalResult(BaseModel, frozen=True):
    """Eval natijasi."""

    agent_name: str
    """Agent nomi."""

    cases: list[EvalCase] = Field(default_factory=list)
    """Test holatlari."""

    total: int = 0
    """Jami testlar."""

    passed: int = 0
    """O'tgan testlar."""

    failed: int = 0
    """O'tmagan testlar."""

    @property
    def success(self) -> bool:
        """Barcha testlar o'tdimi."""
        return self.total > 0 and self.failed == 0


# ── Tool ruxsat darajalari (mavjud toollar uchun) ─────────────

TOOL_PERMISSIONS: dict[str, PermissionLevel] = {
    "time.now": PermissionLevel.READ,
    "web.search": PermissionLevel.READ,
    "web.read": PermissionLevel.READ,
    "note.write": PermissionLevel.WRITE,
    "note.read": PermissionLevel.READ,
    "note.list": PermissionLevel.READ,
    "github.read": PermissionLevel.READ,
    "github.write": PermissionLevel.WRITE,
    # F8 (BLOCK-3 audit): lokal sayt fayl generatsiya (real hosting yo'q).
    "deploy.push": PermissionLevel.WRITE,
    "youtube.search": PermissionLevel.READ,
    "youtube.channel_stats": PermissionLevel.READ,
    "youtube.video_stats": PermissionLevel.READ,
    "youtube.publish": PermissionLevel.WRITE,
    "telegram.channel_stats": PermissionLevel.READ,
    "telegram.channel_post": PermissionLevel.WRITE,
    "telegram.delete_message": PermissionLevel.EXECUTE,
    "crm.contact_search": PermissionLevel.READ,
    "crm.contact_create": PermissionLevel.WRITE,
    "crm.lead_create": PermissionLevel.WRITE,
    "crm.deal_create": PermissionLevel.WRITE,
    "crm.stats": PermissionLevel.READ,
    "agent.list": PermissionLevel.READ,
    "agent.stats": PermissionLevel.READ,
    "agent.pause": PermissionLevel.EXECUTE,
    "agent.resume": PermissionLevel.EXECUTE,
    "agent.disable": PermissionLevel.EXECUTE,
    "product.search": PermissionLevel.READ,
    "product.list": PermissionLevel.READ,
    "product.create": PermissionLevel.WRITE,
    "order.list": PermissionLevel.READ,
    "order.set_status": PermissionLevel.WRITE,
    "sales.stats": PermissionLevel.READ,
    "instagram.account_stats": PermissionLevel.READ,
    "instagram.recent_media": PermissionLevel.READ,
    "instagram.publish_photo": PermissionLevel.WRITE,
    "camera.snapshot": PermissionLevel.READ,
    "vision.ocr": PermissionLevel.READ,
    "memory.search": PermissionLevel.READ,
    "memory.write": PermissionLevel.WRITE,
    # Jonli manbalar (Z50) — hammasi faqat o'qiydi.
    "weather.now": PermissionLevel.READ,
    "stocks.quote": PermissionLevel.READ,
    "news.headlines": PermissionLevel.READ,
    "currency.rate": PermissionLevel.READ,
    "video.learn": PermissionLevel.READ,
    # Ish maydoni (Z48) — doska ZET'ning ICHKI ma'lumoti, tashqi
    # dunyoga hech narsa yubormaydi, shuning uchun yozish WRITE
    # (EXECUTE emas).
    "task.list": PermissionLevel.READ,
    "task.create": PermissionLevel.WRITE,
    "task.update": PermissionLevel.WRITE,
    "task.pulse": PermissionLevel.READ,
    "project.list": PermissionLevel.READ,
    "project.create": PermissionLevel.WRITE,
    "calendar.list": PermissionLevel.READ,
    "calendar.add": PermissionLevel.WRITE,
    "desktop.screenshot": PermissionLevel.READ,
    "desktop.type_text": PermissionLevel.EXECUTE,
    "desktop.key_press": PermissionLevel.EXECUTE,
    "desktop.mouse_click": PermissionLevel.EXECUTE,
    "shell.exec": PermissionLevel.EXECUTE,
}


class EvalRunner:
    """Agent eval yurituvchi.

    Agent spec uchun avtomatik eval to'plami generatsiya qiladi va yuritadi.
    """

    def run_eval(self, spec: AgentSpec) -> EvalResult:
        """Agent spec uchun eval yuritish.

        Args:
            spec: Agent spetsifikatsiyasi.

        Returns:
            EvalResult — sinov natijasi.
        """
        cases: list[EvalCase] = []

        # 1. Spec validatsiyasi
        cases.append(self._eval_spec_valid(spec))

        # 2. Tool validatsiyasi
        cases.append(self._eval_tools_valid(spec))

        # 3. Permission validatsiyasi
        cases.append(self._eval_permissions_valid(spec))

        # 4. Prompt validatsiyasi
        cases.append(self._eval_prompt_valid(spec))

        # 5. Brake validatsiyasi (A-07)
        cases.append(self._eval_brakes_valid(spec))

        passed = sum(1 for c in cases if c.passed)
        failed = sum(1 for c in cases if not c.passed)

        return EvalResult(
            agent_name=spec.name,
            cases=cases,
            total=len(cases),
            passed=passed,
            failed=failed,
        )

    def _eval_spec_valid(self, spec: AgentSpec) -> EvalCase:
        """Spec validatsiyasi — kerakli maydonlar to'ldirilgan."""
        errors: list[str] = []

        if not spec.name or len(spec.name) < 1:
            errors.append("nom bo'sh")
        if not spec.description:
            errors.append("tavsif bo'sh")
        if not spec.system_prompt:
            errors.append("system prompt bo'sh")
        if spec.version < 1:
            errors.append("versiya 1 dan kichik")

        if errors:
            return EvalCase(
                name="spec_valid",
                description="Agent spec barcha kerakli maydonlari to'ldirilgan",
                passed=False,
                error="; ".join(errors),
            )
        return EvalCase(
            name="spec_valid",
            description="Agent spec barcha kerakli maydonlari to'ldirilgan",
            passed=True,
        )

    def _eval_tools_valid(self, spec: AgentSpec) -> EvalCase:
        """Tool validatsiyasi — allowlist dagi toollar ma'lum."""
        unknown: list[str] = []
        for tool_name in spec.tool_allowlist:
            if tool_name not in TOOL_PERMISSIONS:
                unknown.append(tool_name)

        if unknown:
            return EvalCase(
                name="tools_valid",
                description="Barcha toollar ma'lum va mavjud",
                passed=False,
                error=f"Noma'lum toollar: {', '.join(unknown)}",
            )
        return EvalCase(
            name="tools_valid",
            description="Barcha toollar ma'lum va mavjud",
            passed=True,
        )

    def _eval_permissions_valid(self, spec: AgentSpec) -> EvalCase:
        """Permission validatsiyasi — toollar ruxsat darajasiga mos.

        Agent ruxsat darajasidan yuqori toollar rad etiladi.
        """
        permission_order = {
            PermissionLevel.READ: 0,
            PermissionLevel.WRITE: 1,
            PermissionLevel.EXECUTE: 2,
            PermissionLevel.ADMIN: 3,
        }

        agent_level = permission_order.get(spec.permission_level, 0)
        violations: list[str] = []

        for tool_name in spec.tool_allowlist:
            tool_perm = TOOL_PERMISSIONS.get(tool_name)
            if tool_perm is not None:
                tool_level = permission_order.get(tool_perm, 0)
                if tool_level > agent_level:
                    violations.append(
                        f"{tool_name} ({tool_perm.value}) > agent ({spec.permission_level.value})"
                    )

        if violations:
            return EvalCase(
                name="permissions_valid",
                description="Toollar agent ruxsat darajasiga mos",
                passed=False,
                error=f"Ruxsat buzilishlari: {'; '.join(violations)}",
            )
        return EvalCase(
            name="permissions_valid",
            description="Toollar agent ruxsat darajasiga mos",
            passed=True,
        )

    def _eval_prompt_valid(self, spec: AgentSpec) -> EvalCase:
        """Prompt validatsiyasi — minimal sifat tekshiruvi."""
        errors: list[str] = []

        if len(spec.system_prompt) < 20:
            errors.append("system prompt juda qisqa (min 20 belgi)")

        # Muhim qoidalar borligini tekshirish
        prompt_lower = spec.system_prompt.lower()
        if "qoida" not in prompt_lower and "rule" not in prompt_lower:
            # Qoidalar bo'lmasligi mumkin lekin bu warning, xato emas
            pass

        if errors:
            return EvalCase(
                name="prompt_valid",
                description="System prompt minimal sifat standartlariga mos",
                passed=False,
                error="; ".join(errors),
            )
        return EvalCase(
            name="prompt_valid",
            description="System prompt minimal sifat standartlariga mos",
            passed=True,
        )

    def _eval_brakes_valid(self, spec: AgentSpec) -> EvalCase:
        """Brake validatsiyasi — A-07 tormozlar o'rnatilgan."""
        errors: list[str] = []

        if spec.max_steps < 1:
            errors.append("max_steps < 1")
        if spec.max_steps > 50:
            errors.append("max_steps > 50 (xavfli)")
        if spec.max_tool_calls < 1:
            errors.append("max_tool_calls < 1")
        if spec.max_tool_calls > 100:
            errors.append("max_tool_calls > 100 (xavfli)")
        if spec.timeout_s < 10:
            errors.append("timeout_s < 10 (juda kam)")
        if spec.timeout_s > 600:
            errors.append("timeout_s > 600 (xavfli)")

        if errors:
            return EvalCase(
                name="brakes_valid",
                description="A-07 tormozlar xavfsiz diapazonda",
                passed=False,
                error="; ".join(errors),
            )
        return EvalCase(
            name="brakes_valid",
            description="A-07 tormozlar xavfsiz diapazonda",
            passed=True,
        )
