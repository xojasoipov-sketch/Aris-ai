"""Approval Gate — tasdiq so'rash va kutish (Z1.12).

Fail-closed: TTL tugasa → EXPIRED → run CANCELLED.
Tasdiqni chetlab o'tish mumkin emas (kod + test bilan isbot).

Bog'liq qarorlar:
    V-32 — majburiy tasdiq
    A-01 — AWAITING_APPROVAL holati
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from zet.domain.enums import ApprovalStatus, PermissionLevel, RiskLevel

log = structlog.get_logger(__name__)


class ApprovalError(Exception):
    """Tasdiq jarayonida xato."""


class ApprovalExpiredError(ApprovalError):
    """Tasdiq muddati tugadi (TTL)."""


class ApprovalRejectedError(ApprovalError):
    """Ega tasdiqni rad etdi."""


class ApprovalRequest:
    """Tasdiq so'rovi — yaratilganidan boshlab TTL bilan chegaralangan.

    Attributes:
        id: unikal identifikator
        run_id: bog'liq run
        step_position: qadam pozitsiyasi
        reason: nima uchun tasdiq kerak
        requested_permission: talab qilingan ruxsat
        tool_name: tool nomi
        preview: bajarilishi kutilayotgan amalning qisqa tavsifi
        status: hozirgi holat
        created_at: yaratilgan vaqt
        expires_at: muddati tugash vaqti
        decided_at: qaror qilingan vaqt
        decision_note: qaror izohi
    """

    def __init__(
        self,
        *,
        run_id: uuid.UUID,
        step_position: int | None = None,
        reason: str,
        requested_permission: PermissionLevel,
        tool_name: str | None = None,
        preview: dict[str, Any] | None = None,
        ttl_minutes: int = 30,
        now: datetime | None = None,
        mission_id: uuid.UUID | None = None,
        risk_level: RiskLevel | None = None,
    ) -> None:
        _now = now or datetime.now(tz=UTC)
        self.id: uuid.UUID = uuid.uuid4()
        self.run_id = run_id
        # Mission-level approval (Bo'lim 2, §2.2). Ega "sayt qur" desa
        # butun mission ega tomonidan tasdiqlanishi kerak — bitta step
        # emas. Bu maydon step-darajali approval'ga TA'SIR QILMAYDI:
        # step approval'lar `step_position` bilan keladi, mission
        # approval'lar esa `mission_id` bilan; ikkalasi ham bir vaqtda
        # bo'lishi mumkin.
        self.mission_id = mission_id
        self.step_position = step_position
        self.reason = reason
        self.requested_permission = requested_permission
        self.tool_name = tool_name
        self.preview: dict[str, Any] = preview or {}
        self.status: ApprovalStatus = ApprovalStatus.PENDING
        self.created_at: datetime = _now
        self.expires_at: datetime = _now + timedelta(minutes=ttl_minutes)
        self.decided_at: datetime | None = None
        self.decision_note: str | None = None
        # NEGA risk_level ochiq maydon: CLI (`z approvals`) va Telegram
        # bildirishnomasi "nima uchun tasdiq kerak?" degan savolga
        # darhol javob bera olsin va HIGH ni ustuvor ko'rsatsin. None
        # bo'lsa — eski chaqiruvchi (risk axis'ni bilmagan) yozgan.
        self.risk_level: RiskLevel | None = risk_level

    def is_expired(self, now: datetime | None = None) -> bool:
        """Muddati tugaganmi."""
        return (now or datetime.now(tz=UTC)) >= self.expires_at

    def approve(
        self,
        *,
        note: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Tasdiqni qabul qilish.

        Raises:
            ApprovalError: holat PENDING emas
            ApprovalExpiredError: muddati tugagan
        """
        _now = now or datetime.now(tz=UTC)
        if self.is_expired(_now):
            self.status = ApprovalStatus.EXPIRED
            raise ApprovalExpiredError("Tasdiq muddati tugadi")
        if self.status != ApprovalStatus.PENDING:
            raise ApprovalError(f"Tasdiq {self.status.value} holatda — o'zgartirib bo'lmaydi")
        self.status = ApprovalStatus.APPROVED
        self.decided_at = _now
        self.decision_note = note
        log.info("approval.approved", approval_id=str(self.id), run_id=str(self.run_id))

    def reject(
        self,
        *,
        note: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Tasdiqni rad etish.

        Raises:
            ApprovalError: holat PENDING emas
            ApprovalExpiredError: muddati tugagan
        """
        _now = now or datetime.now(tz=UTC)
        if self.is_expired(_now):
            self.status = ApprovalStatus.EXPIRED
            raise ApprovalExpiredError("Tasdiq muddati tugadi")
        if self.status != ApprovalStatus.PENDING:
            raise ApprovalError(f"Tasdiq {self.status.value} holatda — o'zgartirib bo'lmaydi")
        self.status = ApprovalStatus.REJECTED
        self.decided_at = _now
        self.decision_note = note
        log.info("approval.rejected", approval_id=str(self.id), run_id=str(self.run_id))

    def check_expired(self, now: datetime | None = None) -> bool:
        """Muddatni tekshiradi va agar tugagan bo'lsa statusni yangilaydi.

        Returns:
            True agar tugagan bo'lsa
        """
        if self.status == ApprovalStatus.PENDING and self.is_expired(now):
            self.status = ApprovalStatus.EXPIRED
            log.warning(
                "approval.expired",
                approval_id=str(self.id),
                run_id=str(self.run_id),
            )
            return True
        return False


class ApprovalService:
    """Tasdiq so'rovlarini boshqarish.

    In-memory store — Bo'lim 1 uchun yetarli.
    Z1.11 (Executor) shu orqali tasdiq so'raydi.
    """

    def __init__(self, *, ttl_minutes: int = 30) -> None:
        self._ttl_minutes = ttl_minutes
        self._requests: dict[uuid.UUID, ApprovalRequest] = {}
        self._by_run: dict[uuid.UUID, list[uuid.UUID]] = {}
        self._by_mission: dict[uuid.UUID, list[uuid.UUID]] = {}

    def request_approval(
        self,
        *,
        run_id: uuid.UUID,
        step_position: int | None = None,
        reason: str,
        requested_permission: PermissionLevel,
        tool_name: str | None = None,
        preview: dict[str, Any] | None = None,
        now: datetime | None = None,
        mission_id: uuid.UUID | None = None,
        risk_level: RiskLevel | None = None,
    ) -> ApprovalRequest:
        """Yangi tasdiq so'rovi yaratadi.

        Returns:
            ApprovalRequest
        """
        req = ApprovalRequest(
            run_id=run_id,
            step_position=step_position,
            reason=reason,
            requested_permission=requested_permission,
            tool_name=tool_name,
            preview=preview,
            ttl_minutes=self._ttl_minutes,
            now=now,
            mission_id=mission_id,
            risk_level=risk_level,
        )
        self._requests[req.id] = req
        self._by_run.setdefault(run_id, []).append(req.id)
        if mission_id is not None:
            self._by_mission.setdefault(mission_id, []).append(req.id)

        log.info(
            "approval.requested",
            approval_id=str(req.id),
            run_id=str(run_id),
            permission=requested_permission.value,
            tool=tool_name,
        )
        return req

    def get(self, approval_id: uuid.UUID) -> ApprovalRequest:
        """Tasdiq so'rovini topadi.

        Raises:
            KeyError: topilmadi
        """
        return self._requests[approval_id]

    def pending_for_run(self, run_id: uuid.UUID) -> list[ApprovalRequest]:
        """Run uchun kutilayotgan tasdiqlar."""
        ids = self._by_run.get(run_id, [])
        return [
            self._requests[aid]
            for aid in ids
            if self._requests[aid].status == ApprovalStatus.PENDING
        ]

    def pending_for_mission(self, mission_id: uuid.UUID) -> list[ApprovalRequest]:
        """Mission uchun kutilayotgan tasdiqlar (Bo'lim 2, §2.2)."""
        ids = self._by_mission.get(mission_id, [])
        return [
            self._requests[aid]
            for aid in ids
            if self._requests[aid].status == ApprovalStatus.PENDING
        ]

    def all_pending(self) -> list[ApprovalRequest]:
        """Barcha kutilayotgan tasdiqlar (run bo'yicha filtrsiz).

        `z approvals` CLI orqali "hozir nimalar tasdiq kutmoqda?" savoliga
        javob berish uchun kerak — GAP_ANALYSIS BROKEN #1 yopishning bir
        qismi. Cross-process approve/reject ish beradi, lekin ID'ni
        boshqa joydan (Telegram bildirishnomasi, log) topish kerak edi;
        endi CLI o'zi ro'yxatlab beradi.
        """
        return [r for r in self._requests.values() if r.status == ApprovalStatus.PENDING]

    def approve(
        self,
        approval_id: uuid.UUID,
        *,
        note: str | None = None,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Tasdiqni qabul qilish.

        Raises:
            KeyError: topilmadi
            ApprovalExpiredError: muddati tugagan
            ApprovalError: holat PENDING emas
        """
        req = self._requests[approval_id]
        req.approve(note=note, now=now)
        return req

    def reject(
        self,
        approval_id: uuid.UUID,
        *,
        note: str | None = None,
        now: datetime | None = None,
    ) -> ApprovalRequest:
        """Tasdiqni rad etish.

        Raises:
            KeyError: topilmadi
            ApprovalExpiredError: muddati tugagan
            ApprovalError: holat PENDING emas
        """
        req = self._requests[approval_id]
        req.reject(note=note, now=now)
        return req

    def expire_all_pending(self, now: datetime | None = None) -> list[ApprovalRequest]:
        """Muddati tugagan barcha so'rovlarni EXPIRED ga o'tkazadi.

        Returns:
            Muddati tugagan so'rovlar ro'yxati
        """
        expired: list[ApprovalRequest] = []
        for req in self._requests.values():
            if req.check_expired(now):
                expired.append(req)
        return expired
