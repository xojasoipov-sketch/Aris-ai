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
    """Yangi run boshlash — to'liq pipeline: intent → reja → bajarish → tekshirish."""
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
            record = asyncio.run(_run_pipeline(message, dry_run=dry_run))
        except Exception as exc:
            out.print(f"  [red]✗ Pipeline xatosi:[/red] {exc}")
            return

        if record.status.value == "awaiting_approval":
            out.print(
                f"  [yellow]⏸ Tasdiq kerak[/yellow] — approval_id: "
                f"[dim]{record.pending_approval_id}[/dim]"
            )
            out.print(
                f"  Tasdiqlash uchun: POST /api/v1/approvals/{record.pending_approval_id}/approve"
            )
        elif record.status.value == "done":
            out.print(f"  [green]✓[/green] {record.result_summary}")
            out.print(f"  [dim]xarajat: ${record.spent_usd:.4f}[/dim]")
        else:
            out.print(f"  [red]✗[/red] {record.status.value}: {record.error}")
    finally:
        unbind_trace()


async def _run_pipeline(message: str, *, dry_run: bool):
    """`z run` uchun Orchestrator'ni qurib, buyruqni bajaradi."""
    from zet.api.deps import (
        get_approval_service,
        get_killswitch,
        get_llm_providers,
        get_permission_policy,
        get_run_store,
        get_session_factory,
        get_tool_registry,
    )
    from zet.core.orchestrator import Orchestrator
    from zet.db.session import session_scope
    from zet.domain.command import Command
    from zet.llm.router import ModelRouter

    settings = get_settings()
    async with session_scope(get_session_factory()) as session:
        router = ModelRouter(get_llm_providers(), session, settings)
        orchestrator = Orchestrator(
            router=router,
            tool_registry=get_tool_registry(),
            permission_policy=get_permission_policy(),
            approval_service=get_approval_service(),
            killswitch=get_killswitch(),
            run_store=get_run_store(),
            budget_usd=settings.run_max_usd,
            max_steps=settings.run_max_steps,
        )
        return await orchestrator.start(Command(text=message, channel="cli"), dry_run=dry_run)


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


@memory_app.command("add")
def mem_add(
    content: str = typer.Argument(..., help="Yozuv matni"),
    layer: str = typer.Option("knowledge", "--layer", "-l", help="Qatlam nomi"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Teglar"),
) -> None:
    """Yangi xotira yozuvi qo'shish."""
    _setup()
    from zet.api.deps import get_memory_store
    from zet.domain.memory import MemoryLayer

    store = get_memory_store()
    try:
        mem_layer = MemoryLayer(layer)
    except ValueError:
        out.print(f"[red]Noto'g'ri qatlam: {layer}[/red]")
        out.print(f"Mumkin: {', '.join(m.value for m in MemoryLayer)}")
        raise SystemExit(1) from None

    entry = store.add(layer=mem_layer, content=content, tags=tags)
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
    from zet.api.deps import get_memory_store
    from zet.domain.memory import MemoryLayer, MemoryQuery

    store = get_memory_store()
    layers = None
    if layer:
        try:
            layers = [MemoryLayer(layer)]
        except ValueError:
            out.print(f"[red]Noto'g'ri qatlam: {layer}[/red]")
            raise SystemExit(1) from None

    query = MemoryQuery(text=text, layers=layers, limit=limit, min_similarity=0.0)
    results = store.search(query)

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
    from zet.api.deps import get_memory_store
    from zet.domain.memory import MemoryLayer

    store = get_memory_store()
    try:
        mem_layer = MemoryLayer(layer)
    except ValueError:
        out.print(f"[red]Noto'g'ri qatlam: {layer}[/red]")
        out.print(f"Mumkin: {', '.join(m.value for m in MemoryLayer)}")
        raise SystemExit(1) from None

    entries = store.list_by_layer(mem_layer, limit=limit)
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
    from zet.api.deps import get_memory_store

    store = get_memory_store()
    out.print(f"[bold cyan]Xotira[/bold cyan]: {store.count} faol yozuv")


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
