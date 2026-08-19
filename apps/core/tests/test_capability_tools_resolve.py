"""JB-13 Gap #3 — Capability registry reconciliation validatsiyasi.

AUDIT TOPILMASI: `builtin_capabilities()`dagi 20 ta seed capability'dan
~14 tasi `default_tools`da `ToolRegistry`da UMUMAN mavjud bo'lmagan
nomlarga ishora qilardi (masalan `instagram.publish` — haqiqiy nomi
`instagram.publish_photo`, `telegram.send` — bunday tool umuman yo'q).
Bu jimgina xavfli edi: `MissionEngine.execute()` (JB-4) mission.tools`ni
`ToolRegistry.subset()`ga uzatadi — noma'lum nom xatoga uchraydi, bu
FAIL-OPEN yutiladi va Executor cheklanmagan TO'LIQ global registryga
qaytadi (least-privilege scoping o'sha capability uchun jimgina
ishlamay qolardi — audit disclosure `core/capability.py` docstring'ida).

Bu test — HAR bir builtin capability'ning BUTUN `default_tools`
ro'yxati haqiqiy (production bilan bir xil) `ToolRegistry`da
topilishini tasdiqlaydi. Kelajakda YANGI capability qo'shilganda yoki
mavjud biri o'zgartirilganda, agar xato nom kiritilsa — bu test
DARHOL yiqiladi (regressiya himoyasi).
"""

from __future__ import annotations

from pathlib import Path

from zet.core.capability import builtin_capabilities
from zet.tools.builtin import build_default_registry


class TestBuiltinCapabilityToolsResolve:
    def test_all_default_tools_exist_in_real_registry(self, tmp_path: Path) -> None:
        registry = build_default_registry(notes_dir=tmp_path)
        real_names = set(registry.tool_names())

        unresolved: list[tuple[str, str]] = [
            (cap.name, tool)
            for cap in builtin_capabilities()
            for tool in cap.default_tools
            if tool not in real_names
        ]

        assert not unresolved, (
            f"Quyidagi capability→tool juftliklari haqiqiy ToolRegistry'da "
            f"topilmadi (least-privilege scoping jimgina ishlamay qoladi): "
            f"{unresolved}"
        )

    def test_no_capability_has_empty_default_tools_silently(self) -> None:
        """Har bir capability KAMIDA bitta haqiqiy tool bilan ishlashi kerak
        — aks holda "capability bor, lekin hech narsa qila olmaydi" degan
        jim/soxta holat paydo bo'ladi (audit fikri: "mark explicitly
        unavailable rather than silently pretending it exists" — bo'sh
        ro'yxat esa umuman ko'rinmas bo'lib qolardi)."""
        empty = [cap.name for cap in builtin_capabilities() if not cap.default_tools]
        assert not empty, f"Bo'sh default_tools'li capability'lar: {empty}"

    def test_builtin_capability_count_unchanged(self) -> None:
        """Regressiya qulfi — JB-13 reconciliation capability SONI emas,
        faqat `default_tools` MAZMUNIni o'zgartirishi kerak edi.

        20 → 21 (JB-18, public-apis integratsiyasi): bu safar SON
        ATAYLAB o'zgardi — `location` capability'si YANGI, haqiqiy
        capability sifatida qo'shildi (reconciling emas, kengaytirish)."""
        assert len(builtin_capabilities()) == 21
