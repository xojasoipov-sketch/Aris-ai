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
    """Yangi run boshlash.

    Bo'lim 1 lean versiya — faqat intent aniqlash.
    To'liq pipeline keyingi bo'limlarda.
    """
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

        # Bo'lim 1: faqat qabul qilish
        out.print(f"  [green]✓[/green] Qabul qilindi — trace_id: [dim]{trace_id}[/dim]")
        out.print("  [yellow]⚠[/yellow] To'liq pipeline hali ulangan emas (Bo'lim 2)")
    finally:
        unbind_trace()


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
