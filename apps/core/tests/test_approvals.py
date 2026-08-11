"""Z1.12 — ApprovalService testlari.

Tekshiriladi:
    - Tasdiq so'rovi yaratiladi
    - Tasdiq qabul qilinadi (APPROVED)
    - Tasdiq rad etiladi (REJECTED)
    - TTL tugadi → EXPIRED
    - EXPIRED tasdiqni qabul/rad etib bo'lmaydi
    - APPROVED/REJECTED tasdiqni qayta o'zgartrib bo'lmaydi
    - pending_for_run faqat PENDING larni qaytaradi
    - expire_all_pending muddati tugaganlarni topadi
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from zet.domain.enums import ApprovalStatus, PermissionLevel
from zet.security.approvals import (
    ApprovalError,
    ApprovalExpiredError,
    ApprovalService,
)

_NOW = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
_RUN_ID = uuid.uuid4()


class TestApprovalRequest:
    """ApprovalRequest testlari."""

    def test_create(self) -> None:
        """Tasdiq so'rovi yaratiladi."""
        svc = ApprovalService(ttl_minutes=30)
        req = svc.request_approval(
            run_id=_RUN_ID,
            reason="EXECUTE daraja",
            requested_permission=PermissionLevel.EXECUTE,
            tool_name="shell.exec",
            now=_NOW,
        )

        assert req.status == ApprovalStatus.PENDING
        assert req.run_id == _RUN_ID
        assert req.requested_permission == PermissionLevel.EXECUTE
        assert req.tool_name == "shell.exec"
        assert req.expires_at == _NOW + timedelta(minutes=30)

    def test_approve(self) -> None:
        """Tasdiq qabul qilinadi."""
        svc = ApprovalService(ttl_minutes=30)
        req = svc.request_approval(
            run_id=_RUN_ID,
            reason="Test",
            requested_permission=PermissionLevel.EXECUTE,
            now=_NOW,
        )

        svc.approve(req.id, note="OK", now=_NOW + timedelta(minutes=5))

        assert req.status == ApprovalStatus.APPROVED
        assert req.decision_note == "OK"
        assert req.decided_at == _NOW + timedelta(minutes=5)

    def test_reject(self) -> None:
        """Tasdiq rad etiladi."""
        svc = ApprovalService(ttl_minutes=30)
        req = svc.request_approval(
            run_id=_RUN_ID,
            reason="Test",
            requested_permission=PermissionLevel.EXECUTE,
            now=_NOW,
        )

        svc.reject(req.id, note="Xavfli", now=_NOW + timedelta(minutes=1))

        assert req.status == ApprovalStatus.REJECTED
        assert req.decision_note == "Xavfli"

    def test_expired_cannot_approve(self) -> None:
        """Muddati tugagan tasdiqni qabul qilib bo'lmaydi."""
        svc = ApprovalService(ttl_minutes=5)
        req = svc.request_approval(
            run_id=_RUN_ID,
            reason="Test",
            requested_permission=PermissionLevel.EXECUTE,
            now=_NOW,
        )

        with pytest.raises(ApprovalExpiredError, match="tugadi"):
            svc.approve(req.id, now=_NOW + timedelta(minutes=10))

        assert req.status == ApprovalStatus.EXPIRED

    def test_expired_cannot_reject(self) -> None:
        """Muddati tugagan tasdiqni rad etib bo'lmaydi."""
        svc = ApprovalService(ttl_minutes=5)
        req = svc.request_approval(
            run_id=_RUN_ID,
            reason="Test",
            requested_permission=PermissionLevel.EXECUTE,
            now=_NOW,
        )

        with pytest.raises(ApprovalExpiredError):
            svc.reject(req.id, now=_NOW + timedelta(minutes=10))

    def test_approved_cannot_change(self) -> None:
        """APPROVED tasdiqni qayta o'zgartirib bo'lmaydi."""
        svc = ApprovalService(ttl_minutes=30)
        req = svc.request_approval(
            run_id=_RUN_ID,
            reason="Test",
            requested_permission=PermissionLevel.EXECUTE,
            now=_NOW,
        )

        svc.approve(req.id, now=_NOW + timedelta(minutes=1))

        with pytest.raises(ApprovalError, match="approved"):
            svc.reject(req.id, now=_NOW + timedelta(minutes=2))

    def test_rejected_cannot_change(self) -> None:
        """REJECTED tasdiqni qayta o'zgartirib bo'lmaydi."""
        svc = ApprovalService(ttl_minutes=30)
        req = svc.request_approval(
            run_id=_RUN_ID,
            reason="Test",
            requested_permission=PermissionLevel.EXECUTE,
            now=_NOW,
        )

        svc.reject(req.id, now=_NOW + timedelta(minutes=1))

        with pytest.raises(ApprovalError, match="rejected"):
            svc.approve(req.id, now=_NOW + timedelta(minutes=2))


class TestApprovalService:
    """ApprovalService testlari."""

    def test_pending_for_run(self) -> None:
        """pending_for_run faqat PENDING larni qaytaradi."""
        svc = ApprovalService(ttl_minutes=30)
        run_id = uuid.uuid4()

        req1 = svc.request_approval(
            run_id=run_id,
            reason="Birinchi",
            requested_permission=PermissionLevel.EXECUTE,
            now=_NOW,
        )
        req2 = svc.request_approval(
            run_id=run_id,
            reason="Ikkinchi",
            requested_permission=PermissionLevel.WRITE,
            now=_NOW,
        )

        # Birinchisini tasdiqlash
        svc.approve(req1.id, now=_NOW + timedelta(minutes=1))

        pending = svc.pending_for_run(run_id)
        assert len(pending) == 1
        assert pending[0].id == req2.id

    def test_pending_for_run_empty(self) -> None:
        """Mavjud bo'lmagan run — bo'sh ro'yxat."""
        svc = ApprovalService()
        assert svc.pending_for_run(uuid.uuid4()) == []

    def test_expire_all_pending(self) -> None:
        """expire_all_pending muddati tugaganlarni topadi."""
        svc = ApprovalService(ttl_minutes=5)
        run_id = uuid.uuid4()

        svc.request_approval(
            run_id=run_id,
            reason="Eski",
            requested_permission=PermissionLevel.EXECUTE,
            now=_NOW,
        )
        svc.request_approval(
            run_id=run_id,
            reason="Yangi",
            requested_permission=PermissionLevel.WRITE,
            now=_NOW + timedelta(minutes=4),
        )

        # 6 daqiqadan keyin — birinchisi tugagan, ikkinchisi hali yo'q
        expired = svc.expire_all_pending(now=_NOW + timedelta(minutes=6))
        assert len(expired) == 1
        assert expired[0].status == ApprovalStatus.EXPIRED

    def test_get(self) -> None:
        """Tasdiq so'rovini topish."""
        svc = ApprovalService()
        req = svc.request_approval(
            run_id=_RUN_ID,
            reason="Test",
            requested_permission=PermissionLevel.EXECUTE,
            now=_NOW,
        )

        found = svc.get(req.id)
        assert found.id == req.id

    def test_get_not_found(self) -> None:
        """Topilmagan tasdiq → KeyError."""
        svc = ApprovalService()

        with pytest.raises(KeyError):
            svc.get(uuid.uuid4())

    def test_preview_stored(self) -> None:
        """Preview ma'lumoti saqlanadi."""
        svc = ApprovalService()
        req = svc.request_approval(
            run_id=_RUN_ID,
            reason="Fayl o'chirish",
            requested_permission=PermissionLevel.EXECUTE,
            tool_name="file.delete",
            preview={"file": "notes/test.txt"},
            now=_NOW,
        )

        assert req.preview == {"file": "notes/test.txt"}

    def test_is_expired(self) -> None:
        """is_expired to'g'ri ishlaydi."""
        svc = ApprovalService(ttl_minutes=10)
        req = svc.request_approval(
            run_id=_RUN_ID,
            reason="Test",
            requested_permission=PermissionLevel.EXECUTE,
            now=_NOW,
        )

        assert req.is_expired(_NOW + timedelta(minutes=5)) is False
        assert req.is_expired(_NOW + timedelta(minutes=10)) is True
        assert req.is_expired(_NOW + timedelta(minutes=15)) is True
