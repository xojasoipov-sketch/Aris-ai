"""DAG utilitasi — rejani parallel bajarish uchun bosqichlarga bo'ladi.

NEGA: `Executor` ilgari rejani `sorted(steps, key=position)` bilan
faqat pozitsiya bo'yicha tartiblab, qadamlarni birma-bir ketma-ket
ishga tushirar edi. Bu — mustaqil qadamlar (masalan, ikkita alohida
`web.search`) ham navbatda kutib turishini anglatardi. `plan_to_dag`
esa Kahn algoritmi bilan qadamlarni "bosqich"larga guruhlaydi:
bir bosqichdagi barcha qadamlarning DAG dependency'lari oldingi
bosqichlarda tugagan, shuning uchun ular `asyncio.gather` bilan
xavfsiz parallel ishga tushirilishi mumkin.

Ilgari: `_topological_sort` `sorted(by position)` qaytarardi —
bu DAG tartibini "hurmat qilar", lekin parallelism bermas edi.

Nega alohida modul: `plan.py` (domen qatlami) toza qoladi —
u faqat validatsiyani biladi, bajarilish rejasini emas.
`executor.py`ga yaqin joyda turadi va uni qamrab olmasdan
alohida test qilinadi (funksiya `Plan` obyektini emas, xom
`Sequence[PlanStep]`ni qabul qiladi — shu bois `Plan._validate_dag`ni
chetlab o'tib, sikl testlari yozish mumkin).

Bog'liq qarorlar:
    A-01 — plan bajarilish tartibi
    A-07 — avtomatlashtirish tormozlari (parallelism budgetni tezroq yeydi)
"""

from __future__ import annotations

from collections.abc import Sequence

from zet.domain.plan import PlanStep, PlanValidationError


def plan_to_dag(steps: Sequence[PlanStep]) -> list[list[PlanStep]]:
    """Qadamlarni parallel-bajariladigan bosqichlarga guruhlaydi (Kahn).

    Har bir qaytarilgan bosqich (`batch`) — dependency'lari OLDINGI
    bosqichlarda tugallangan qadamlar to'plami. Bosqich ichidagi
    qadamlar bir-biridan mustaqil, shu sabab `asyncio.gather` bilan
    parallel ishga tushirish xavfsiz. Determinizm uchun bosqich ichida
    qadamlar `position` bo'yicha tartiblanadi (log/audit reprodutsiya
    qilinadigan bo'lishi uchun).

    Bo'sh kirish → `[]`. Chiziqli reja (0→1→2→3) → to'rt bitta qadamli
    bosqich (ya'ni bugungi ketma-ket xatti-harakat aynan takrorlanadi).

    Sikl aniqlansa `PlanValidationError` ko'tariladi. Bu himoya —
    `Plan._validate_dag` allaqachon `dep < position` shartini talab
    qilib sikllarni bloklaydi, ammo `plan_to_dag` `Plan`ni emas, xom
    ro'yxatni qabul qilgani uchun o'z-o'zini himoya qiladi.

    Args:
        steps: reja qadamlari (ketma-ketligi ahamiyatsiz)

    Returns:
        bosqichlar ro'yxati; har biri parallel bajariladigan qadamlar

    Raises:
        PlanValidationError: DAG'da sikl aniqlandi (Kahn qoldig'i bor)
    """
    if not steps:
        return []

    by_pos: dict[int, PlanStep] = {s.position: s for s in steps}
    in_degree: dict[int, int] = {s.position: len(s.depends_on) for s in steps}

    # Reverse adjacency: dep → uni kutayotgan qadamlar ro'yxati.
    dependents: dict[int, list[int]] = {s.position: [] for s in steps}
    for step in steps:
        for dep in step.depends_on:
            # Noto'g'ri havola (`dep` yo'q) — `Plan._validate_dag`
            # allaqachon ushlaydi; xom ro'yxat kelsa esa in_degree'da
            # kamayish yo'q bo'lgani uchun sikl-kabi qoldiq beradi.
            if dep in dependents:
                dependents[dep].append(step.position)

    ready = sorted(pos for pos, deg in in_degree.items() if deg == 0)
    batches: list[list[PlanStep]] = []
    processed = 0

    while ready:
        batch = [by_pos[p] for p in ready]
        batches.append(batch)
        processed += len(batch)

        next_ready: list[int] = []
        for p in ready:
            for child in dependents[p]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_ready.append(child)
        ready = sorted(next_ready)

    if processed != len(steps):
        residue = [pos for pos, deg in in_degree.items() if deg > 0]
        raise PlanValidationError(f"DAG'da sikl aniqlandi — Kahn qoldig'i: {sorted(residue)}")

    return batches
