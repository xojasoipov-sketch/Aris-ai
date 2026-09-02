"""Agent Runtime — agentni ishga tushirish va boshqarish (Bo'lim 3).

Runtime oqimi:
    1. context_assembly() — system prompt + conversation context
    2. tool_loop() — LLM chaqiruv → tool bajarish → natija qaytarish (takrorlash)
    3. verify() — natijani tekshirish
    4. report() — hisobot tuzish

A-07 tormozlar:
    - max_steps: qadamlar soni cheklangan
    - max_tool_calls: tool chaqiruvlari cheklangan
    - timeout_s: vaqt cheklangan

Bog'liq qarorlar:
    A-02 — agent = ma'lumot
    A-07 — avtomatlashtirish tormozlari
    V-01 — har bir natija tekshiriladi
    V-31 — tool ruxsati
"""

from __future__ import annotations

import time

import structlog

from zet.domain.agent import AgentRunResult, AgentSpec
from zet.domain.tool import ToolResult
from zet.llm.base import ChatMessage, ImageBlock, LLMProvider, LLMResponse, ToolSpec, ToolUse
from zet.security.killswitch import KillSwitchEngagedError, KillSwitchState
from zet.security.permissions import PermissionPolicy
from zet.tools.base import ToolError
from zet.tools.registry import ToolNotFoundError, ToolRegistry

log = structlog.get_logger(__name__)


class AgentRuntimeError(Exception):
    """Agent runtime xatosi."""


class AgentMaxStepsError(AgentRuntimeError):
    """Maksimal qadamlar soniga yetildi (A-07)."""


class AgentMaxToolCallsError(AgentRuntimeError):
    """Maksimal tool chaqiruvlari soniga yetildi (A-07)."""


class AgentTimeoutError(AgentRuntimeError):
    """Agent vaqt chegarasini oshirdi (A-07)."""


class AgentRuntime:
    """Agent runtime — context assembly → tool loop → verify → report.

    Har bir agent o'zining AgentSpec'iga asoslangan holda ishlaydi.
    LLM va ToolRegistry tashqaridan beriladi (DI).
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        tool_registry: ToolRegistry,
        model: str = "fake",
        permission_policy: PermissionPolicy | None = None,
        killswitch: KillSwitchState | None = None,
    ) -> None:
        self._provider = provider
        self._tool_registry = tool_registry
        self._model = model
        self._permission_policy = permission_policy or PermissionPolicy()
        # JB-12 (audit topilmasi): ilgari `AgentRuntime` killswitch'ni
        # HECH QACHON tekshirmasdi — `Orchestrator`/`Executor` yo'lidan
        # farqli o'laroq (u har DAG batch'dan oldin `check()` chaqiradi).
        # Bu `AgentRuntime` orqali ishlaydigan HAMMA yo'llarni (TaskGraph
        # missionlar, AutomationDaemon/DailyScheduleDaemon/WatcherDaemon
        # scheduled fire'lar, HandoffDispatcher, `automation/goal.py`)
        # killswitch'dan "ko'r" qilib qo'yardi — emergency stop yoqilsa
        # ham, allaqachon boshlangan agent tool-loop'i to'xtamasdi.
        # Ixtiyoriy (`None` — eski xatti-harakat, chaqiruvchi hali
        # yangilanmagan bo'lsa ham NOL regressiya).
        self._killswitch = killswitch

    async def run(
        self,
        spec: AgentSpec,
        task: str,
        *,
        context: list[ChatMessage] | None = None,
    ) -> AgentRunResult:
        """Agentni ishga tushiradi.

        Args:
            spec: Agent spetsifikatsiyasi.
            task: Bajarilishi kerak bo'lgan vazifa.
            context: Qo'shimcha kontekst xabarlari.

        Returns:
            AgentRunResult — hisobot.
        """
        start_time = time.monotonic()
        tool_calls_count = 0
        steps_count = 0
        sources: list[str] = []
        # JB-15: HAR bir tool chaqiruvining XOM (raw) `ToolResult`i —
        # `AgentRunResult.output` (agentning matn xulosasi) EMAS,
        # `EvidenceProvider` shu ro'yxatga muhtoj (qarang: domain/agent.py
        # `AgentRunResult.tool_results` docstringi).
        tool_results: list[ToolResult] = []

        # 1. Context assembly
        messages = self._assemble_context(spec, task, context)
        tool_specs = self._build_tool_specs(spec)

        log.info(
            "agent.run.start",
            agent=spec.name,
            task=task[:100],
            tools=len(tool_specs),
            max_steps=spec.max_steps,
        )

        try:
            # 2. Tool loop
            for step in range(spec.max_steps):
                steps_count = step + 1

                # JB-12: har qadam boshida killswitch tekshiruvi —
                # `Executor`ning har DAG batch'dan oldingi `check()`i
                # bilan bir xil naqsh (core/executor.py). Emergency stop
                # o'rtada yoqilsa, keyingi LLM/tool qadami boshlanmaydi.
                if self._killswitch is not None:
                    self._killswitch.check()

                # A-07: timeout tekshiruvi
                elapsed = time.monotonic() - start_time
                if elapsed > spec.timeout_s:
                    raise AgentTimeoutError(
                        f"Agent '{spec.name}' {spec.timeout_s}s vaqt chegarasini oshirdi"
                    )

                # LLM chaqiruvi
                response = await self._call_llm(messages, tool_specs, spec)

                # Tool chaqiruv yo'q — javob tayyor
                if not response.wants_tools:
                    log.info(
                        "agent.run.complete",
                        agent=spec.name,
                        steps=steps_count,
                        tool_calls=tool_calls_count,
                    )
                    return AgentRunResult(
                        agent_name=spec.name,
                        success=True,
                        output=response.text,
                        sources=sources,
                        tool_calls_count=tool_calls_count,
                        steps_count=steps_count,
                        tool_results=tool_results,
                    )

                # Tool chaqiruvlarini bajarish
                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=response.text,
                        tool_uses=response.tool_uses,
                    )
                )

                for tool_use in response.tool_uses:
                    # A-07: max tool calls tekshiruvi
                    if tool_calls_count >= spec.max_tool_calls:
                        raise AgentMaxToolCallsError(
                            f"Agent '{spec.name}' {spec.max_tool_calls} tool chaqiruviga yetdi"
                        )

                    tool_result = await self._execute_tool(
                        spec,
                        tool_use,
                        sources,
                    )
                    tool_calls_count += 1
                    tool_results.append(tool_result)

                    # Tool natijasini kontekstga qo'shish
                    messages.append(
                        ChatMessage(
                            role="tool",
                            content=self._format_tool_result(tool_result),
                            tool_call_id=tool_use.id,
                        )
                    )

                    # Rasm bo'lsa — alohida user xabari sifatida qo'shish (A-05: kamera/
                    # skrinshot natijasi UNTRUSTED, lekin vision modelga ko'rinishi kerak).
                    # Provider-mustaqil: "tool" rolidagi rasm ba'zi provayderlarda
                    # qo'llab-quvvatlanmaydi, "user" roli esa har doim ishlaydi.
                    image = self._extract_image(tool_result)
                    if image is not None:
                        messages.append(
                            ChatMessage(
                                role="user",
                                content=f"[{tool_use.name} natijasidagi rasm]",
                                images=(image,),
                            )
                        )

            # A-07: max steps
            raise AgentMaxStepsError(f"Agent '{spec.name}' {spec.max_steps} qadamga yetdi")

        except KillSwitchEngagedError as exc:
            log.warning(
                "agent.run.killswitch_engaged",
                agent=spec.name,
                steps=steps_count,
                tool_calls=tool_calls_count,
            )
            return AgentRunResult(
                agent_name=spec.name,
                success=False,
                output="",
                sources=sources,
                tool_calls_count=tool_calls_count,
                steps_count=steps_count,
                error=f"Emergency stop yoqilgan: {exc}",
                tool_results=tool_results,
            )
        except AgentRuntimeError as exc:
            log.warning(
                "agent.run.limit_reached",
                agent=spec.name,
                error=str(exc),
                steps=steps_count,
                tool_calls=tool_calls_count,
            )
            return AgentRunResult(
                agent_name=spec.name,
                success=False,
                output="",
                sources=sources,
                tool_calls_count=tool_calls_count,
                steps_count=steps_count,
                error=str(exc),
                tool_results=tool_results,
            )
        except Exception as exc:
            log.exception("agent.run.error", agent=spec.name)
            return AgentRunResult(
                agent_name=spec.name,
                success=False,
                output="",
                sources=sources,
                tool_calls_count=tool_calls_count,
                steps_count=steps_count,
                error=f"Kutilmagan xato: {type(exc).__name__}: {exc}",
                tool_results=tool_results,
            )

    def _assemble_context(
        self,
        spec: AgentSpec,  # noqa: ARG002
        task: str,
        extra_context: list[ChatMessage] | None,
    ) -> list[ChatMessage]:
        """System prompt + task + extra context → xabarlar ro'yxati."""
        messages: list[ChatMessage] = []

        # Extra context (agar bor bo'lsa)
        if extra_context:
            messages.extend(extra_context)

        # Foydalanuvchi vazifasi
        messages.append(ChatMessage(role="user", content=task))

        return messages

    def _build_tool_specs(self, spec: AgentSpec) -> list[ToolSpec]:
        """Agent uchun ruxsat etilgan toollarning LLM spetsifikatsiyalari."""
        tool_specs: list[ToolSpec] = []
        for tool_name in spec.tool_allowlist:
            if self._tool_registry.has(tool_name):
                tool = self._tool_registry.get(tool_name)
                tool_specs.append(
                    ToolSpec(
                        name=tool.name,
                        description=tool.description,
                        input_schema=tool.input_schema,
                    )
                )
        return tool_specs

    async def _call_llm(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        spec: AgentSpec,
    ) -> LLMResponse:
        """LLM chaqiruvi — system prompt bilan."""
        return await self._provider.complete(
            model=self._model,
            messages=messages,
            system=spec.system_prompt,
            tools=tools,
            max_tokens=2048,
            temperature=0.0,
        )

    async def _execute_tool(
        self,
        spec: AgentSpec,
        tool_use: ToolUse,
        sources: list[str],
    ) -> ToolResult:
        """Tool chaqiruvini bajaradi — allowlist va permission tekshiruvi bilan."""
        # Allowlist tekshiruvi
        if tool_use.name not in spec.tool_allowlist:
            log.warning(
                "agent.tool.denied",
                agent=spec.name,
                tool=tool_use.name,
                reason="allowlist'da yo'q",
            )
            return ToolResult(
                tool_name=tool_use.name,
                success=False,
                error=f"Tool '{tool_use.name}' agent '{spec.name}' uchun ruxsat etilmagan",
            )

        # Ruxsat siyosati (V-31/V-32): yuqori xavfli yoki tasdiq talab
        # qiladigan toollar avtonom agent tomonidan bajarilmaydi — fail-closed.
        # Agent Runtime hozircha to'xtab-kutuvchi tasdiq oqimini
        # qo'llab-quvvatlamaydi (Orchestrator'dagidek), shuning uchun
        # tasdiq kerak bo'lsa — rad etiladi, avtomatik bajarilmaydi.
        if self._tool_registry.has(tool_use.name):
            tool = self._tool_registry.get(tool_use.name)
            # NEGA `requires_approval` (yangi metod): `check()` risk axis
            # ni ko'rmaydi. Yangi qaror tool.risk_level (LOW/MEDIUM/HIGH)
            # va autonomy darajasini ham hisobga oladi (V-32
            # kengaytmasi + ZET_ASS_AUTONOMY_AUDIT §2.8).
            decision = self._permission_policy.requires_approval(
                permission=tool.permission_level,
                trust=spec.trust_level,
                tool=tool,
            )
            if decision.needs_approval:
                log.warning(
                    "agent.tool.approval_required",
                    agent=spec.name,
                    tool=tool_use.name,
                    reason=decision.reason,
                )
                return ToolResult(
                    tool_name=tool_use.name,
                    success=False,
                    error=(
                        f"Tool '{tool_use.name}' tasdiq talab qiladi ({decision.reason}) — "
                        "avtonom agent runtime hozircha tasdiqni qo'llab-quvvatlamaydi"
                    ),
                )

        try:
            result = await self._tool_registry.execute(
                tool_use.name,
                tool_use.arguments,
                caller_permission=spec.permission_level,
            )

            # Manbalarni yig'ish (source tracking)
            if result.success and result.output:
                source = self._extract_source(tool_use.name, result)
                if source:
                    sources.append(source)

            return result

        except ToolNotFoundError:
            return ToolResult(
                tool_name=tool_use.name,
                success=False,
                error=f"Tool '{tool_use.name}' registry'da topilmadi",
            )
        except ToolError as exc:
            return ToolResult(
                tool_name=tool_use.name,
                success=False,
                error=str(exc),
            )

    def _extract_source(self, tool_name: str, result: ToolResult) -> str | None:
        """Tool natijasidan manba ma'lumotini ajratish."""
        if not result.output:
            return None

        # Oddiy euristik: output'da url yoki manba bo'lsa
        output_str = str(result.output)
        if "http" in output_str or "source" in output_str.lower():
            return f"{tool_name}: {output_str[:200]}"

        return None

    def _extract_image(self, result: ToolResult) -> ImageBlock | None:
        """Tool natijasidan rasm ajratish (agar mavjud bo'lsa).

        Konvensiya: `output` dict `has_image=True` va `image_b64` maydoniga
        ega bo'lsa — rasm sifatida qaraladi (masalan `camera.snapshot`).
        """
        if not result.success or not isinstance(result.output, dict):
            return None
        output = result.output
        image_b64 = output.get("image_b64")
        if not output.get("has_image") or not image_b64:
            return None
        return ImageBlock(data=image_b64, media_type=output.get("media_type", "image/jpeg"))

    def _format_tool_result(self, result: ToolResult) -> str:
        """Tool natijasini LLM uchun formatlash."""
        if result.success:
            if isinstance(result.output, dict) and result.output.get("has_image"):
                # Rasmning o'zi alohida xabar sifatida qo'shiladi (_extract_image) —
                # bu yerda katta base64 satrini takrorlamaslik uchun faqat metadata
                meta = {k: v for k, v in result.output.items() if k != "image_b64"}
                return f"Rasm olindi: {meta}"
            return str(result.output) if result.output is not None else "OK"
        return f"XATO: {result.error or 'nomalum xato'}"
