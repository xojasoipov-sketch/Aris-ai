"""ZET CLI — `z` buyrug'i (Z1.15).

Foydalanish:
    z run "Havo qanday?"     — yangi run boshlash
    z status                 — tizim holati
    z killswitch engage      — emergency stop yoqish
    z killswitch disengage   — emergency stop o'chirish
    z killswitch status      — killswitch holati
    z budget                 — budjet holati
    z version                — versiya

Bog'liq qarorlar:
    A-01 — run holat mashinasi
    V-33 — favqulodda to'xtatish
    A-07 — budjet chegaralari
"""

from __future__ import annotations

import sys

import structlog
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from zet.config import get_settings
from zet.observability.logging import configure_logging

log = structlog.get_logger(__name__)

app = typer.Typer(
    name="z",
    help="ZET — shaxsiy AI operatsion tizim",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console(stderr=True)
out = Console()


# ── Yordamchilar ──────────────────────────────────────────────────


def _setup() -> None:
    """Logging va muhitni sozlash."""
    settings = get_settings()
    configure_logging(
        json_output=False,
        log_level=settings.log_level,
    )


# ── z run ──────────────────────────────────────────────────────────


@app.command()
def run(
    message: str = typer.Argument(..., help="Buyruq matni"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Haqiqiy ish bajarmaslik"),
) -> None:
    """Yangi run boshlash — to'liq pipeline: intent → reja → bajarish → tekshirish.

    JB-13 Gap #5 AUDIT FIX: ilgari bu buyruq `Brain`ni chetlab o'tib,
    o'zining ICHKI (Telegram/HTTP'dan MUSTAQIL) `Orchestrator`ini
    qurardi va to'g'ridan-to'g'ri `.start()` chaqirardi — CLI orqali
    yuborilgan "goal" (masalan "Sayt qur") HECH QACHON Mission yo'liga
    tushmasdi, Scheduler-buyruqlar (`WORKFLOW_COMMAND`) ham tanilmasdi.
    Endi `z run` xuddi Telegram/HTTP kabi `build_brain_for_session()` +
    `Brain.handle()` orqali ishlaydi — BITTA kanonik kognitiv kirish
    nuqtasi, CLI'ga xos ijro mantig'i yo'q."""
    import asyncio

    _setup()

    from zet.observability.trace import bind_trace, unbind_trace

    trace_id = bind_trace()
    try:
        mode = " [dim](dry-run)[/dim]" if dry_run else ""
        out.print(
            Panel(
                f"[cyan]{message}[/cyan]",
                title=f"[bold]ZET Run[/bold]{mode}",
                subtitle=f"trace: {trace_id[:8]}…",
                border_style="cyan",
            )
        )
        out.print(f"  [green]✓[/green] Qabul qilindi — trace_id: [dim]{trace_id}[/dim]")

        try:
            result = asyncio.run(_run_pipeline(message, dry_run=dry_run))
        except Exception as exc:
            out.print(f"  [red]✗ Pipeline xatosi:[/red] {exc}")
            return

        # `result.run` — mavjud bo'lsa (RUN yo'li), eski (record-darajali)
        # tafsilotlar (status/pending_approval_id/spent_usd) shundan.
        run_record = result.run
        run_status = getattr(run_record, "status", None)
        run_status_value = getattr(run_status, "value", None)

        if result.mission_id is not None:
            # Mission (goal) yo'li — YANGI, `Brain`ning o'zi orqali.
            out.print(f"  [cyan]◆ Mission boshlandi[/cyan] — mission_id: [dim]{result.mission_id}[/dim]")
            out.print(f"  {result.text}")
        elif run_status_value == "awaiting_approval":
            pending_approval_id = getattr(run_record, "pending_approval_id", None)
            out.print(
                f"  [yellow]⏸ Tasdiq kerak[/yellow] — approval_id: [dim]{pending_approval_id}[/dim]"
            )
            # NOTA: bu holatdagi run CLI JARAYONida qoladi va API'da ko'rinmaydi
            # (RunStore singleton har jarayonda alohida). `z approve <id>` API'ga
            # murojaat qiladi va u yerda RUN yo'q, shu sabab XATO qaytadi. Ishonchli
            # tasdiq oqimi uchun ishga `z tg` (Telegram bot) yoki HTTP orqali
            # `POST /api/v1/run` — ikkalasi ham API jarayonida ishlaydi.
            out.print(
                "  [dim]Cross-process tasdiq: `z run` ni HTTP orqali ishga tushiring[/dim]\n"
                "  [dim]yoki Telegram inline tugmalari orqali tasdiqlang.[/dim]"
            )
            out.print(
                f"  [dim]Yoki: [/dim][cyan]z approve {pending_approval_id}[/cyan] "
                "[dim](API jarayonida ishlaydi)[/dim]"
            )
        elif result.ok:
            out.print(f"  [green]✓[/green] {result.text}")
            spent_usd = getattr(run_record, "spent_usd", None)
            if spent_usd is not None:
                out.print(f"  [dim]xarajat: ${spent_usd:.4f}[/dim]")
        else:
            out.print(f"  [red]✗[/red] {run_status_value or 'xato'}: {result.text}")
    finally:
        unbind_trace()


async def _run_pipeline(message: str, *, dry_run: bool):
    """`z run` uchun `Brain`ni qurib, buyruqni bajaradi (JB-13 Gap #5).

    `build_orchestrator_for_session`/`build_brain_for_session` — JB-11/
    JB-12'da FastAPI DI'siz, request kontekstidan tashqarida (`api/app.py`
    `lifespan()`, `AutomationDaemon`) ishlatish uchun yaratilgan, endi
    CLI ham aynan shu qurilishdan foydalanadi — Telegram/HTTP/Scheduler/
    CLI barchasi BIR XIL Brain qurilish yo'lidan o'tadi.
    """
    from zet.api.deps import build_brain_for_session, get_session_factory
    from zet.db.session import session_scope
    from zet.domain.command import Command

    settings = get_settings()
    async with session_scope(get_session_factory()) as session:
        brain = await build_brain_for_session(session, settings)
        return await brain.handle(Command(text=message, channel="cli"), dry_run=dry_run)


# ── z status ───────────────────────────────────────────────────────


@app.command()
def status() -> None:
    """Tizim holatini ko'rsatish."""
    _setup()
    settings = get_settings()

    table = Table(title="ZET Status", border_style="cyan")
    table.add_column("Parametr", style="bold")
    table.add_column("Qiymat")

    table.add_row("Muhit", settings.env.value)
    table.add_row("Kunlik budjet", f"${settings.budget_daily_usd:.2f}")
    table.add_row("Oylik budjet", f"${settings.budget_monthly_usd:.2f}")
    table.add_row("Run budjet", f"${settings.run_max_usd:.2f}")
    table.add_row("T3 kunlik limit", str(settings.tier3_daily_calls))
    table.add_row("Shell", "✓ Yoqilgan" if settings.enable_shell else "✗ O'chirilgan")

    llm_providers: list[str] = []
    if settings.ollama_base_url:
        llm_providers.append(f"Ollama ({settings.ollama_model})")
    if settings.google_api_key:
        llm_providers.append("Google")
    if settings.groq_api_key:
        llm_providers.append("Groq")
    if settings.mistral_api_key:
        llm_providers.append("Mistral")
    if settings.anthropic_api_key:
        llm_providers.append("Anthropic")
    if settings.openai_api_key:
        llm_providers.append("OpenAI")
    table.add_row("LLM provayderlar", ", ".join(llm_providers) or "Yo'q")

    out.print(table)


# ── z killswitch ──────────────────────────────────────────────────

killswitch_app = typer.Typer(
    name="killswitch",
    help="Emergency stop boshqaruvi",
    no_args_is_help=True,
)
app.add_typer(killswitch_app, name="killswitch")


@killswitch_app.command("engage")
def ks_engage(
    reason: str = typer.Option("Manual CLI engage", "--reason", "-r", help="Sabab"),
) -> None:
    """Emergency stop yoqish."""
    _setup()
    from zet.api.deps import get_killswitch

    ks = get_killswitch()
    ks.engage(reason=reason)
    out.print(f"[red bold]⚠ EMERGENCY STOP YOQILDI[/red bold]: {reason}")


@killswitch_app.command("disengage")
def ks_disengage() -> None:
    """Emergency stop o'chirish."""
    _setup()
    from zet.api.deps import get_killswitch

    ks = get_killswitch()
    try:
        ks.disengage()
        out.print("[green bold]✓ Emergency stop o'chirildi[/green bold]")
    except ValueError as exc:
        out.print(f"[yellow]⚠ {exc}[/yellow]")
        raise SystemExit(1) from exc


@killswitch_app.command("status")
def ks_status() -> None:
    """KillSwitch holati."""
    _setup()
    from zet.api.deps import get_killswitch

    ks = get_killswitch()
    data = ks.to_dict()

    if data["engaged"]:
        out.print(f"[red bold]⚠ YOQILGAN[/red bold]: {data['reason']}")
        out.print(f"  Vaqt: {data['engaged_at']}")
        out.print(f"  Kim: {data['engaged_by']}")
    else:
        out.print("[green]✓ Emergency stop o'chirilgan[/green]")


# ── z state (Sleep/Active) ────────────────────────────────────────

state_app = typer.Typer(
    name="state",
    help="AI Core rejimi — Sleep/Active",
    no_args_is_help=True,
)
app.add_typer(state_app, name="state")


@state_app.command("sleep")
def state_sleep(
    reason: str = typer.Option("Manual CLI sleep", "--reason", "-r", help="Sabab"),
) -> None:
    """Proaktiv ishlarni pauza qilish (kunlik jadval to'xtaydi)."""
    _setup()
    from zet.api.deps import get_core_state

    get_core_state().sleep(reason=reason, by="cli")
    out.print(f"[yellow bold]💤 SLEEPING[/yellow bold]: {reason}")


@state_app.command("wake")
def state_wake(
    reason: str = typer.Option("Manual CLI wake", "--reason", "-r", help="Sabab"),
) -> None:
    """ACTIVE rejimiga qaytish."""
    _setup()
    from zet.api.deps import get_core_state

    get_core_state().wake(reason=reason, by="cli")
    out.print("[green bold]✓ ACTIVE[/green bold]")


@state_app.command("status")
def state_status() -> None:
    """Joriy rejim."""
    _setup()
    from zet.api.deps import get_core_state

    data = get_core_state().to_dict()
    if data["mode"] == "sleeping":
        out.print(f"[yellow]💤 SLEEPING[/yellow]: {data['reason']}")
    else:
        out.print("[green]✓ ACTIVE[/green]")


# ── z memory ─────────────────────────────────────────────────────

memory_app = typer.Typer(
    name="memory",
    help="Xotira boshqaruvi (Bo'lim 2)",
    no_args_is_help=True,
)
app.add_typer(memory_app, name="memory")


async def _with_memory_store(fn):
    """DB sessiyasi + PgMemoryStore ochib, `fn(store)`ni bajaradi va commit qiladi.

    CLI va API bir xil ma'lumotni ko'rishi uchun (ikkalasi ham DB'ga
    yozadi) — `z run`dagi bilan bir xil naqsh.
    """
    # `get_or_create_owner` asl uyidan olinadi: uni `deps` orqali olish
    # qayta-eksportga tayanadi va u yerda faqat ichki foydalanish uchun
    # import qilingan.
    from zet.api.deps import get_embedding_provider, get_session_factory
    from zet.db.bootstrap import get_or_create_owner
    from zet.db.session import session_scope
    from zet.memory.pg_store import PgMemoryStore

    settings = get_settings()
    async with session_scope(get_session_factory()) as session:
        owner = await get_or_create_owner(session, external_id=settings.owner_id)
        store = PgMemoryStore(session, owner_id=owner.id, embedder=get_embedding_provider())
        return await fn(store)


def _run_memory_op(fn):
    """`_with_memory_store` chaqiruvini bajarib, DB xatosini chiroyli ko'rsatadi."""
    import asyncio

    try:
        return asyncio.run(_with_memory_store(fn))
    except Exception as exc:
        out.print(f"[red]✗ Xotira xatosi:[/red] {exc}")
        raise SystemExit(1) from None


@memory_app.command("add")
def mem_add(
    content: str = typer.Argument(..., help="Yozuv matni"),
    layer: str = typer.Option("knowledge", "--layer", "-l", help="Qatlam nomi"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Teglar"),
) -> None:
    """Yangi xotira yozuvi qo'shish."""
    _setup()
    from zet.domain.memory import MemoryLayer

    try:
        mem_layer = MemoryLayer(layer)
    except ValueError:
        out.print(f"[red]Noto'g'ri qatlam: {layer}[/red]")
        out.print(f"Mumkin: {', '.join(m.value for m in MemoryLayer)}")
        raise SystemExit(1) from None

    entry = _run_memory_op(lambda store: store.add(layer=mem_layer, content=content, tags=tags))
    out.print(f"[green]✓[/green] Yozuv qo'shildi: [dim]{entry.id}[/dim]")
    out.print(f"  Qatlam: [cyan]{entry.layer.value}[/cyan], versiya: {entry.version}")
    if entry.expires_at:
        out.print(f"  Muddati: {entry.expires_at.isoformat()}")


@memory_app.command("search")
def mem_search(
    text: str = typer.Argument(..., help="Qidiruv matni"),
    layer: str | None = typer.Option(None, "--layer", "-l", help="Qatlam filtri"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maksimal natijalar"),
) -> None:
    """Xotiradan qidirish."""
    _setup()
    from zet.domain.memory import MemoryLayer, MemoryQuery

    layers = None
    if layer:
        try:
            layers = [MemoryLayer(layer)]
        except ValueError:
            out.print(f"[red]Noto'g'ri qatlam: {layer}[/red]")
            raise SystemExit(1) from None

    query = MemoryQuery(text=text, layers=layers, limit=limit, min_similarity=0.0)
    results = _run_memory_op(lambda store: store.search(query))

    if not results:
        out.print("[yellow]Natija topilmadi[/yellow]")
        return

    table = Table(title=f"Qidiruv: '{text}'", border_style="cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Qatlam", style="cyan", width=14)
    table.add_column("Matn", max_width=60)
    table.add_column("Ball", justify="right", width=6)

    for r in results:
        content_preview = (
            r.entry.content[:57] + "..." if len(r.entry.content) > 60 else r.entry.content
        )
        table.add_row(
            str(r.rank),
            r.entry.layer.value if isinstance(r.entry.layer, MemoryLayer) else str(r.entry.layer),
            content_preview,
            f"{r.similarity:.2f}",
        )

    out.print(table)


@memory_app.command("list")
def mem_list(
    layer: str = typer.Argument(..., help="Qatlam nomi"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maksimal natijalar"),
) -> None:
    """Qatlam bo'yicha yozuvlar ro'yxati."""
    _setup()
    from zet.domain.memory import MemoryLayer

    try:
        mem_layer = MemoryLayer(layer)
    except ValueError:
        out.print(f"[red]Noto'g'ri qatlam: {layer}[/red]")
        out.print(f"Mumkin: {', '.join(m.value for m in MemoryLayer)}")
        raise SystemExit(1) from None

    entries = _run_memory_op(lambda store: store.list_by_layer(mem_layer, limit=limit))
    if not entries:
        out.print(f"[yellow]{mem_layer.value} qatlamida yozuv yo'q[/yellow]")
        return

    table = Table(title=f"Qatlam: {mem_layer.value}", border_style="cyan")
    table.add_column("ID", style="dim", width=10)
    table.add_column("Matn", max_width=50)
    table.add_column("Ver", justify="right", width=4)
    table.add_column("Teglar", style="cyan")

    for e in entries:
        content_preview = e.content[:47] + "..." if len(e.content) > 50 else e.content
        table.add_row(
            (e.id or "")[:10],
            content_preview,
            str(e.version),
            ", ".join(e.tags) if e.tags else "-",
        )

    out.print(table)


@memory_app.command("stats")
def mem_stats() -> None:
    """Xotira statistikasi."""
    _setup()

    count = _run_memory_op(lambda store: store.count())
    out.print(f"[bold cyan]Xotira[/bold cyan]: {count} faol yozuv")


# ── z agent ──────────────────────────────────────────────────────

agent_app = typer.Typer(
    name="agent",
    help="Agent boshqaruvi (Bo'lim 3)",
    no_args_is_help=True,
)
app.add_typer(agent_app, name="agent")


@agent_app.command("list")
def agent_list(
    status: str | None = typer.Option(None, "--status", "-s", help="Holat filtri"),
) -> None:
    """Agentlar ro'yxati."""
    _setup()
    from zet.api.deps import get_agent_registry
    from zet.domain.enums import AgentStatus

    registry = get_agent_registry()
    filter_status = None
    if status:
        try:
            filter_status = AgentStatus(status)
        except ValueError:
            out.print(f"[red]Noto'g'ri holat: {status}[/red]")
            out.print(f"Mumkin: {', '.join(s.value for s in AgentStatus)}")
            raise SystemExit(1) from None

    agents = registry.list_agents(status=filter_status)
    if not agents:
        out.print("[yellow]Agent topilmadi[/yellow]")
        return

    table = Table(title="Agentlar", border_style="cyan")
    table.add_column("Nom", style="bold")
    table.add_column("Bo'lim", style="cyan")
    table.add_column("Rol")
    table.add_column("Holat")
    table.add_column("Runlar", justify="right")
    table.add_column("Muvaffaqiyat", justify="right")

    for a in agents:
        status_style = {
            "active": "green",
            "draft": "dim",
            "testing": "yellow",
            "paused": "yellow",
            "disabled": "red",
            "archived": "dim",
        }.get(a.status.value, "")
        table.add_row(
            a.spec.name,
            a.spec.division,
            a.spec.role,
            f"[{status_style}]{a.status.value}[/{status_style}]",
            str(a.total_runs),
            f"{a.success_rate:.0%}" if a.total_runs > 0 else "-",
        )

    out.print(table)


@agent_app.command("register")
def agent_register(
    name: str = typer.Argument(..., help="Agent nomi"),
    description: str = typer.Option(..., "--desc", "-d", help="Tavsif"),
    prompt: str = typer.Option(..., "--prompt", "-p", help="System prompt"),
    division: str = typer.Option("general", "--division", help="Bo'lim"),
    role: str = typer.Option("assistant", "--role", help="Rol"),
) -> None:
    """Yangi agentni ro'yxatga olish."""
    _setup()
    from zet.api.deps import get_agent_registry
    from zet.domain.agent import AgentSpec

    registry = get_agent_registry()

    try:
        spec = AgentSpec(
            name=name,
            description=description,
            system_prompt=prompt,
            division=division,
            role=role,
        )
        state = registry.register(spec)
        out.print(f"[green]✓[/green] Agent ro'yxatga olindi: [bold]{state.spec.name}[/bold]")
        out.print(f"  Holat: [dim]{state.status.value}[/dim]")
        out.print(f"  Bo'lim: [cyan]{state.spec.division}[/cyan], rol: {state.spec.role}")
    except ValueError as exc:
        out.print(f"[red]Xato: {exc}[/red]")
        raise SystemExit(1) from None


@agent_app.command("create")
def agent_create(
    description: str = typer.Argument(..., help="Tabiy tilda agent tavsifi"),
    auto_activate: bool = typer.Option(
        False, "--auto-activate", "-a", help="Eval muvaffaqiyatli bo'lsa avtomatik ACTIVE"
    ),
) -> None:
    """Tabiy til buyrug'i bilan agent yaratish (V-10 Factory).

    Misol: z agent create "YouTube analitikasini kuzatadigan agent"
    """
    _setup()
    from zet.agents.eval import EvalRunner
    from zet.agents.factory import AgentFactory, FactoryRequest
    from zet.agents.lifecycle import AgentLifecycle
    from zet.api.deps import get_agent_registry

    registry = get_agent_registry()
    lifecycle = AgentLifecycle(registry)
    factory = AgentFactory(registry, lifecycle, EvalRunner())

    request = FactoryRequest(description=description, auto_activate=auto_activate)
    result = factory.create(request)

    if result.success:
        agent = result.agent_state
        out.print(f"[green]✓[/green] Agent yaratildi: [bold]{agent.spec.name}[/bold]")  # type: ignore[union-attr]
        out.print(f"  Holat: {agent.status.value}")  # type: ignore[union-attr]
        out.print(f"  Bo'lim: [cyan]{agent.spec.division}[/cyan], rol: {agent.spec.role}")  # type: ignore[union-attr]
        out.print(f"  Toollar: {', '.join(agent.spec.tool_allowlist) or 'yoq'}")  # type: ignore[union-attr]

        if result.eval_result:
            out.print(
                f"  Eval: {result.eval_result.passed}/{result.eval_result.total} "
                f"({'[green]✓[/green]' if result.eval_result.success else '[red]✗[/red]'})"
            )
    else:
        out.print("[red]✗ Agent yaratish muvaffaqiyatsiz[/red]")
        if result.error:
            out.print(f"  Xato: {result.error}")
        raise SystemExit(1)

    # Qadamlarni ko'rsatish
    if result.steps:
        out.print("\n[dim]Qadamlar:[/dim]")
        for step in result.steps:
            out.print(f"  [dim]→ {step}[/dim]")


@agent_app.command("info")
def agent_info(
    name: str = typer.Argument(..., help="Agent nomi"),
) -> None:
    """Agent ma'lumotlarini ko'rsatish."""
    _setup()
    from zet.agents.registry import AgentNotFoundError
    from zet.api.deps import get_agent_registry

    registry = get_agent_registry()

    try:
        state = registry.get(name)
    except AgentNotFoundError:
        out.print(f"[red]Agent '{name}' topilmadi[/red]")
        raise SystemExit(1) from None

    out.print(
        Panel(
            f"[bold]{state.spec.name}[/bold] — {state.spec.description}\n"
            f"  Bo'lim: [cyan]{state.spec.division}[/cyan], Rol: {state.spec.role}\n"
            f"  Holat: {state.status.value}\n"
            f"  Model: {state.spec.model_policy.value}, Ruxsat: {state.spec.permission_level.value}\n"
            f"  Tormozlar: max_steps={state.spec.max_steps}, "
            f"max_tools={state.spec.max_tool_calls}, timeout={state.spec.timeout_s}s\n"
            f"  Toollar: {', '.join(state.spec.tool_allowlist) or 'yoq'}\n"
            f"  Runlar: {state.total_runs} (✓{state.successful_runs} ✗{state.failed_runs})",
            title="Agent Info",
            border_style="cyan",
        )
    )


@agent_app.command("status")
def agent_status(
    name: str = typer.Argument(..., help="Agent nomi"),
    action: str = typer.Argument(
        ...,
        help="Amal: activate, start_testing, pause, disable, archive, reset_to_draft",
    ),
    reason: str = typer.Option("", "--reason", "-r", help="Sabab (disable uchun)"),
) -> None:
    """Agent holatini o'zgartirish (V-11 lifecycle)."""
    _setup()
    from zet.agents.lifecycle import AgentLifecycle, AgentLifecycleError
    from zet.agents.registry import AgentNotFoundError
    from zet.api.deps import get_agent_registry

    registry = get_agent_registry()
    lifecycle = AgentLifecycle(registry)

    action_map = {
        "activate": lifecycle.activate,
        "start_testing": lifecycle.start_testing,
        "pause": lifecycle.pause,
        "archive": lifecycle.archive,
        "reset_to_draft": lifecycle.reset_to_draft,
    }

    try:
        if action == "disable":
            state = lifecycle.disable(name, reason=reason)
        elif action in action_map:
            state = action_map[action](name)
        else:
            out.print(f"[red]Noto'g'ri amal: {action}[/red]")
            out.print(f"Mumkin: {', '.join([*action_map, 'disable'])}")
            raise SystemExit(1)

        out.print(f"[green]✓[/green] Agent '{name}' holati: [bold]{state.status.value}[/bold]")
    except AgentNotFoundError:
        out.print(f"[red]Agent '{name}' topilmadi[/red]")
        raise SystemExit(1) from None
    except AgentLifecycleError as exc:
        out.print(f"[red]Lifecycle xatosi: {exc}[/red]")
        raise SystemExit(1) from None


# ── z telegram ────────────────────────────────────────────────────

telegram_app = typer.Typer(
    name="telegram",
    help="Telegram bot boshqaruvi (Bo'lim 5)",
    no_args_is_help=True,
)
app.add_typer(telegram_app, name="telegram")


@telegram_app.command("status")
def telegram_status() -> None:
    """Telegram bot holati."""
    _setup()
    settings = get_settings()

    has_token = settings.telegram_bot_token is not None
    owner_ids = settings.telegram_owner_id_set

    table = Table(title="Telegram Bot", border_style="cyan")
    table.add_column("Parametr", style="bold")
    table.add_column("Qiymat")

    table.add_row("Token", "[green]✓ Sozlangan[/green]" if has_token else "[red]✗ Yo'q[/red]")
    table.add_row("Owner ID lar", str(owner_ids) if owner_ids else "[yellow]Bo'sh[/yellow]")
    table.add_row("Owner soni", str(len(owner_ids)))

    out.print(table)

    if not has_token:
        out.print("\n[yellow]⚠ ZET_TELEGRAM_BOT_TOKEN .env faylida sozlang[/yellow]")
    if not owner_ids:
        out.print("[yellow]⚠ ZET_TELEGRAM_OWNER_IDS .env faylida sozlang[/yellow]")


@telegram_app.command("test")
def telegram_test(
    message: str = typer.Argument("Salom, ZET!", help="Test xabar matni"),
) -> None:
    """Bot handlerini test qilish (Telegram ulanmasdan).

    Misol: z telegram test "Havo qanday?"
    """
    _setup()
    import asyncio

    from zet.telegram.bot import ZetBot
    from zet.voice.stt import StubSTT

    bot = ZetBot(
        owner_ids={0},  # Test user_id
        stt=StubSTT(),
    )

    result = asyncio.run(
        bot.process_message(
            user_id=0,
            chat_id=0,
            text=message,
        )
    )

    if result:
        # HTML teglarini tozalash (terminal uchun)
        clean_text = result.text.replace("<b>", "[bold]").replace("</b>", "[/bold]")
        clean_text = clean_text.replace("<code>", "[dim]").replace("</code>", "[/dim]")
        out.print(Panel(clean_text, title="Bot javobi", border_style="cyan"))
    else:
        out.print("[red]Bot javob bermadi[/red]")


# ── z approve / z reject ──────────────────────────────────────────
#
# GAP_ANALYSIS BROKEN #1: `z run` CLI da `AWAITING_APPROVAL` holatiga
# tushgan run — API serverning `RunStore`si (alohida jarayon, alohida
# xotira) buni HECH QACHON ko'rmasdi. CLI chop etgan "approve URL" 404
# berardi, `z approve` esa umuman yo'q edi. Endi `z approve`/`z reject`
# HTTP orqali API'ga so'rov yuboradi — bitta manba, cross-process
# muammosi yo'q. Bitta shart: API serverni oldindan `uvicorn` bilan
# ishga tushirish (Hetzner'da bu doim bajarilgan holat).


def _api_call(method: str, path: str, *, json_body: dict | None = None) -> tuple[int, dict]:
    """API'ga so'rov — tokenli, xato holatida (status, body) qaytaradi.

    Ilgari CLI faqat in-process ishlardi. Endi cross-process operatsiya
    uchun httpx bilan mahalliy (yoki masofaviy) API'ga chiqadi.
    """
    import httpx

    settings = get_settings()
    headers: dict[str, str] = {}
    if settings.api_token is not None:
        headers["Authorization"] = f"Bearer {settings.api_token.get_secret_value()}"

    url = settings.api_url.rstrip("/") + path
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.request(method, url, headers=headers, json=json_body)
    except httpx.HTTPError as exc:
        out.print(
            f"[red]✗ API'ga ulanib bo'lmadi:[/red] {exc}\n"
            f"  URL: [dim]{url}[/dim]\n"
            f"  API serveri ishlayapti? ([dim]uvicorn zet.api.app:create_app --factory[/dim])"
        )
        raise SystemExit(2) from exc

    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    return response.status_code, body


@app.command()
def approve(
    approval_id: str = typer.Argument(..., help="Tasdiq ID (z run chiqishida ko'rsatiladi)"),
    note: str | None = typer.Option(None, "--note", "-n", help="Ixtiyoriy izoh"),
) -> None:
    """API orqali kutayotgan tasdiqni ma'qullash va run'ni davom ettirish.

    NEGA HTTP orqali: `z run` va API alohida jarayonlar — ular xotira
    darajasida `RunStore`ni bo'lisha olmaydi. HTTP endpoint bitta manba
    hisoblanadi va Telegram/Web/CLI uchbalasidan ham bir xil so'ralgan
    tasdiq bilan ishlaydi.
    """
    _setup()
    payload = {"note": note} if note else {}
    status_code, body = _api_call(
        "POST", f"/api/v1/approvals/{approval_id}/approve", json_body=payload
    )
    if status_code == 200:
        run_id = body.get("run_id", "?")
        status = body.get("status", "?")
        summary = body.get("result_summary") or body.get("error") or "(bo'sh natija)"
        out.print(f"[green]✓ Tasdiqlandi[/green] — run [dim]{run_id}[/dim] → [bold]{status}[/bold]")
        out.print(f"  {summary}")
    else:
        detail = body.get("detail") or body
        out.print(f"[red]✗ HTTP {status_code}:[/red] {detail}")
        raise SystemExit(1)


@app.command()
def reject(
    approval_id: str = typer.Argument(..., help="Tasdiq ID"),
    note: str | None = typer.Option(None, "--note", "-n", help="Rad etish sababi"),
) -> None:
    """API orqali kutayotgan tasdiqni rad etish va run'ni bekor qilish."""
    _setup()
    payload = {"note": note} if note else {}
    status_code, body = _api_call(
        "POST", f"/api/v1/approvals/{approval_id}/reject", json_body=payload
    )
    if status_code == 200:
        run_id = body.get("run_id", "?")
        out.print(f"[yellow]⊘ Rad etildi[/yellow] — run [dim]{run_id}[/dim]")
    else:
        detail = body.get("detail") or body
        out.print(f"[red]✗ HTTP {status_code}:[/red] {detail}")
        raise SystemExit(1)


@app.command("approvals")
def approvals_list() -> None:
    """Kutayotgan tasdiqlarni ko'rsatish (barcha kanallar bo'yicha)."""
    _setup()
    status_code, body = _api_call("GET", "/api/v1/approvals")
    if status_code != 200:
        detail = body.get("detail") if isinstance(body, dict) else body
        out.print(f"[red]✗ HTTP {status_code}:[/red] {detail}")
        raise SystemExit(1)

    # Endpoint list qaytaradi (FastAPI response_model=list[ApprovalResponse]).
    # Test/backward-compat uchun `{"pending": [...]}` sxemasini ham qabul qilamiz.
    pending = body if isinstance(body, list) else body.get("pending", [])
    if not pending:
        out.print("[dim]Kutayotgan tasdiq yo'q.[/dim]")
        return

    table = Table(title="Kutayotgan tasdiqlar", border_style="yellow")
    table.add_column("ID", style="dim")
    table.add_column("Run", style="dim")
    table.add_column("Tool")
    table.add_column("Xarajat")
    table.add_column("Kim so'radi")
    for item in pending:
        table.add_row(
            str(item.get("id", "?"))[:8],
            str(item.get("run_id", "?"))[:8],
            str(item.get("tool_name", "?")),
            f"${item.get('estimated_cost_usd', 0):.4f}",
            str(item.get("requested_by", "?")),
        )
    out.print(table)


# ── z api ─────────────────────────────────────────────────────────
# public-apis katalogi — operator/admin buyruqlari (JB-18, Bo'lim 17).
# HTTP orqali (`_api_call`, `approve`/`reject` bilan bir xil sabab):
# `CatalogRepository`/`ProviderHealthTracker` jarayon-xotirasida
# (Redis/DB emas) — CLI ALBATTA ishga tushgan API serveriga chiqishi
# kerak, aks holda o'zining bo'sh, izolyatsiyalangan nusxasini ko'rardi.

api_app = typer.Typer(
    name="api",
    help="Tashqi API katalogi (public-apis integratsiyasi)",
    no_args_is_help=True,
)
app.add_typer(api_app, name="api")


@api_app.command("search")
def api_search(
    query: str = typer.Argument(..., help="Qidiruv so'zi/iborasi (masalan 'valyuta')"),
    limit: int = typer.Option(10, "--limit", "-l", help="Nechta nomzod (max 50)"),
) -> None:
    """Katalogni qidiradi — reytinglangan nomzodlar ro'yxati (kashfiyot, ijro emas)."""
    from urllib.parse import urlencode

    _setup()
    qs = urlencode({"q": query, "limit": limit})
    status_code, body = _api_call("GET", f"/api/v1/public-apis/search?{qs}")
    if status_code != 200:
        detail = body.get("detail") if isinstance(body, dict) else body
        out.print(f"[red]✗ HTTP {status_code}:[/red] {detail}")
        raise SystemExit(1)

    candidates = body.get("candidates", [])
    if not candidates:
        out.print(f"[dim]'{query}' bo'yicha hech narsa topilmadi.[/dim]")
        return

    table = Table(title=f"public-apis qidiruv: '{query}'", border_style="cyan")
    table.add_column("Nom")
    table.add_column("Provider", style="dim")
    table.add_column("Auth")
    table.add_column("Holat")
    table.add_column("Ball", justify="right")
    for c in candidates:
        status = str(c.get("status", "?"))
        status_style = "green" if status == "enabled" else "dim"
        table.add_row(
            str(c.get("name", "?")),
            str(c.get("provider", "?")),
            str(c.get("auth_type", "?")),
            f"[{status_style}]{status}[/{status_style}]",
            f"{c.get('composite_score', 0):.2f}",
        )
    out.print(table)


@api_app.command("refresh")
def api_refresh() -> None:
    """Katalogni `public-apis/public-apis`dan HAQIQIY qayta sinxronlaydi."""
    _setup()
    out.print("[dim]Sinxronlanmoqda...[/dim]")
    status_code, body = _api_call("POST", "/api/v1/public-apis/refresh")
    if status_code != 200:
        detail = body.get("detail") if isinstance(body, dict) else body
        out.print(f"[red]✗ HTTP {status_code}:[/red] {detail}")
        raise SystemExit(1)

    if not body.get("ok"):
        out.print(f"[red]✗ Sync muvaffaqiyatsiz:[/red] {body.get('error')}")
        raise SystemExit(1)

    out.print(
        f"[green]✓ Sinxronlandi[/green] — jami {body.get('total_entries')} yozuv "
        f"({body.get('categories')} kategoriya): "
        f"+{body.get('added')} yangi, {body.get('changed')} o'zgardi, "
        f"-{body.get('removed')} o'chdi"
    )


@api_app.command("health")
def api_health() -> None:
    """ENABLED adapterlarning HAQIQIY chaqiruv statistikasi."""
    _setup()
    status_code, body = _api_call("GET", "/api/v1/public-apis/health")
    if status_code != 200:
        detail = body.get("detail") if isinstance(body, dict) else body
        out.print(f"[red]✗ HTTP {status_code}:[/red] {detail}")
        raise SystemExit(1)

    if not body:
        out.print("[dim]Hali hech qanday adapter chaqirilmagan (sog'liq ma'lumoti yo'q).[/dim]")
        return

    table = Table(title="public-apis adapter sog'ligi", border_style="cyan")
    table.add_column("Provider")
    table.add_column("Chaqiruv", justify="right")
    table.add_column("Muvaffaqiyat", justify="right")
    table.add_column("Xato", justify="right")
    table.add_column("O'rtacha (ms)", justify="right")
    table.add_column("Muvaffaqiyat %", justify="right")
    for s in body:
        rate = s.get("success_rate")
        rate_text = f"{rate:.0%}" if rate is not None else "—"
        table.add_row(
            str(s.get("provider", "?")),
            str(s.get("total_calls", 0)),
            str(s.get("successes", 0)),
            str(s.get("failures", 0)),
            f"{s.get('avg_latency_ms', 0):.0f}",
            rate_text,
        )
    out.print(table)


@api_app.command("stats")
def api_stats() -> None:
    """Katalog holati — jami yozuv, kategoriya, oxirgi sync."""
    _setup()
    status_code, body = _api_call("GET", "/api/v1/public-apis/stats")
    if status_code != 200:
        detail = body.get("detail") if isinstance(body, dict) else body
        out.print(f"[red]✗ HTTP {status_code}:[/red] {detail}")
        raise SystemExit(1)

    last_sync_at = body.get("last_sync_at") or "hali sinxronlanmagan"
    out.print(
        f"Jami yozuv: [bold]{body.get('total_entries')}[/bold]  "
        f"Kategoriya: [bold]{body.get('categories')}[/bold]  "
        f"ENABLED: [bold]{body.get('enabled')}[/bold]\n"
        f"Oxirgi sync: [dim]{last_sync_at}[/dim]"
    )


# ── z daemon ──────────────────────────────────────────────────────


@app.command()
def daemon() -> None:
    """Kunlik jadval daemon'ini fon rejimida ishga tushirish (V-35).

    Doimiy jarayon — Ctrl+C bilan to'xtatiladi. ADR-0007 bo'yicha
    native service sifatida (launchd/systemd) shu komanda chaqiriladi.

    F9 (BLOCK-3 audit) TUZATILDI: ilgari bu yerda `DailyScheduleDaemon`
    `session_factory`/`llm_providers`/`settings`/`notifier`SIZ qurilardi
    — daemon "muvaffaqiyatli" deb log yozardi, lekin real LLM chaqirmasdi
    (`FakeProvider()` fallback) va Telegram'ga HECH NARSA yubormasdi
    (`notifier=None`). Endi FastAPI lifespan (`api/app.py`) bilan bir xil
    to'liq wiring ishlatiladi — `z daemon` va serverning o'zi bir xil
    natija beradi.
    """
    import asyncio

    _setup()
    settings = get_settings()

    from zet.api.deps import (
        get_agent_registry,
        get_core_state,
        get_daily_schedule_manager,
        get_killswitch,
        get_llm_providers,
        get_notifier,
        get_permission_policy,
        get_session_factory,
        get_tool_registry,
    )
    from zet.deploy.bootstrap import bootstrap_agents
    from zet.deploy.daemon import DailyScheduleDaemon

    bootstrap_agents()

    notifier = get_notifier()
    notifier_kind = type(notifier).__name__

    d = DailyScheduleDaemon(
        schedule=get_daily_schedule_manager(),
        agent_registry=get_agent_registry(),
        tool_registry=get_tool_registry(),
        permission_policy=get_permission_policy(),
        core_state=get_core_state(),
        killswitch=get_killswitch(),
        timezone=settings.timezone,
        session_factory=get_session_factory(),
        llm_providers=get_llm_providers(),
        settings=settings,
        notifier=notifier,
    )

    telegram_line = (
        "[green]Telegram: real TelegramNotifier ulangan[/green]"
        if notifier_kind == "TelegramNotifier"
        else "[yellow]Telegram: StubNotifier (ZET_TELEGRAM_BOT_TOKEN/"
        "ZET_TELEGRAM_OWNER_IDS sozlanmagan — xabar hech qayerga "
        "yuborilmaydi, faqat log)[/yellow]"
    )
    out.print(
        Panel(
            f"Vaqt mintaqasi: {settings.timezone}\n"
            f"Vazifalar: {get_daily_schedule_manager().stats['enabled']} yoqilgan\n"
            f"{telegram_line}",
            title="[bold]ZET Daemon[/bold]",
            border_style="cyan",
        )
    )
    out.print("  [dim]Ctrl+C bilan to'xtating[/dim]")

    try:
        asyncio.run(d.run_forever())
    except KeyboardInterrupt:
        out.print("\n  [yellow]Daemon to'xtatildi[/yellow]")


# ── z budget ──────────────────────────────────────────────────────


@app.command()
def budget() -> None:
    """Budjet holatini ko'rsatish."""
    _setup()
    settings = get_settings()

    table = Table(title="ZET Budjet", border_style="cyan")
    table.add_column("Chegara", style="bold")
    table.add_column("Qiymat", justify="right")

    table.add_row("Oylik", f"${settings.budget_monthly_usd:.2f}")
    table.add_row("Kunlik", f"${settings.budget_daily_usd:.2f}")
    table.add_row("Run", f"${settings.run_max_usd:.2f}")
    table.add_row("Avtonom ulush", f"{settings.autonomous_budget_share:.0%}")
    table.add_row("Avtonom kunlik", f"${settings.autonomous_daily_budget_usd:.2f}")
    table.add_row("T3 kunlik", f"{settings.tier3_daily_calls} ta chaqiruv")

    out.print(table)


# ── z version ─────────────────────────────────────────────────────


@app.command()
def version() -> None:
    """Versiya ma'lumoti."""
    out.print("[bold cyan]ZET[/bold cyan] v0.1.0 — Shaxsiy AI operatsion tizim")
    out.print(f"  Python: {sys.version.split()[0]}")


# ── Asosiy kirish nuqtasi ─────────────────────────────────────────


def main() -> None:
    """CLI kirish nuqtasi."""
    app()


if __name__ == "__main__":
    main()
