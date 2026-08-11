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
