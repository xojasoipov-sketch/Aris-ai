"""Bo'lim 11 testlari — Xavfsizlik (Rate Limiter, Secret Manager).

NEGA `AuditLog` testlari yo'q. Ilgari in-memory `AuditLog` re-export
qilinardi va shu yerda qamrab olinardi. Endi haqiqiy audit
`zet.security.audit_writer.write_audit()` orqali DB'ga yoziladi —
`tests/test_audit_writer.py` uni sinaydi.

Test guruhlari:
    1. RateLimitTier — enum qiymatlari
    2. RateLimitResult — model maydonlari
    3. RateLimiter — check, limits, tiers, custom, reset, stats
    4. SecretStatus — enum qiymatlari
    5. SecretMetadata — yaratish, is_expired, days_until_expiry, frozen
    6. mask_value — turli uzunliklar
    7. SecretManager — register, get_value, rotate, revoke, list, expiring_soon
    8. Security __init__ exports (Bo'lim 11 qo'shimchalari)
    9. Xavfsizlik invariantlari
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from zet.security import (
    RateLimiter,
    RateLimitResult,
    RateLimitTier,
    SecretManager,
    SecretMetadata,
    SecretStatus,
)
from zet.security.secrets import mask_value

# ─── 1. RateLimitTier ───────────────────────────────────────────


class TestRateLimitTier:
    """RateLimitTier enum testlari."""

    def test_owner(self) -> None:
        assert RateLimitTier.OWNER == "owner"

    def test_system(self) -> None:
        assert RateLimitTier.SYSTEM == "system"

    def test_untrusted(self) -> None:
        assert RateLimitTier.UNTRUSTED == "untrusted"

    def test_three_tiers(self) -> None:
        assert len(RateLimitTier) == 3


# ─── 2. RateLimitResult ─────────────────────────────────────────


class TestRateLimitResult:
    """RateLimitResult model testlari."""

    def test_allowed(self) -> None:
        r = RateLimitResult(allowed=True, remaining=59, limit=60, reset_at=0.0)
        assert r.allowed is True
        assert r.remaining == 59
        assert r.retry_after == 0.0

    def test_denied(self) -> None:
        r = RateLimitResult(allowed=False, remaining=0, limit=60, reset_at=0.0, retry_after=30.0)
        assert r.allowed is False
        assert r.retry_after == 30.0


# ─── 3. RateLimiter ─────────────────────────────────────────────


class TestRateLimiter:
    """RateLimiter testlari."""

    def test_first_request_allowed(self) -> None:
        rl = RateLimiter()
        result = rl.check("user1")
        assert result.allowed is True
        assert result.remaining == 59  # 60 - 1

    def test_owner_default_limit(self) -> None:
        rl = RateLimiter()
        for _ in range(60):
            result = rl.check("user1", RateLimitTier.OWNER)
        assert result.allowed is True
        assert result.remaining == 0
        # 61-chi so'rov — rad
        result = rl.check("user1", RateLimitTier.OWNER)
        assert result.allowed is False

    def test_system_default_limit(self) -> None:
        rl = RateLimiter()
        for _ in range(30):
            result = rl.check("agent1", RateLimitTier.SYSTEM)
        assert result.allowed is True
        result = rl.check("agent1", RateLimitTier.SYSTEM)
        assert result.allowed is False

    def test_untrusted_default_limit(self) -> None:
        rl = RateLimiter()
        for _ in range(10):
            result = rl.check("ext1", RateLimitTier.UNTRUSTED)
        assert result.allowed is True
        result = rl.check("ext1", RateLimitTier.UNTRUSTED)
        assert result.allowed is False

    def test_different_keys_independent(self) -> None:
        rl = RateLimiter()
        for _ in range(10):
            rl.check("a", RateLimitTier.UNTRUSTED)
        # "a" tugadi
        assert rl.check("a", RateLimitTier.UNTRUSTED).allowed is False
        # "b" hali bor
        assert rl.check("b", RateLimitTier.UNTRUSTED).allowed is True

    def test_custom_limit(self) -> None:
        rl = RateLimiter()
        rl.set_custom_limit("vip", 5)
        for _ in range(5):
            result = rl.check("vip")
        assert result.allowed is True
        result = rl.check("vip")
        assert result.allowed is False

    def test_remove_custom_limit(self) -> None:
        rl = RateLimiter()
        rl.set_custom_limit("x", 5)
        assert rl.remove_custom_limit("x") is True
        assert rl.remove_custom_limit("x") is False

    def test_reset_key(self) -> None:
        rl = RateLimiter()
        for _ in range(10):
            rl.check("user1", RateLimitTier.UNTRUSTED)
        assert rl.check("user1", RateLimitTier.UNTRUSTED).allowed is False
        # Reset
        assert rl.reset("user1") is True
        assert rl.check("user1", RateLimitTier.UNTRUSTED).allowed is True

    def test_reset_missing(self) -> None:
        rl = RateLimiter()
        assert rl.reset("nope") is False

    def test_reset_all(self) -> None:
        rl = RateLimiter()
        rl.check("a")
        rl.check("b")
        count = rl.reset_all()
        assert count == 2

    def test_cost(self) -> None:
        rl = RateLimiter()
        rl.set_custom_limit("heavy", 10)
        result = rl.check("heavy", cost=5)
        assert result.allowed is True
        assert result.remaining == 5
        result = rl.check("heavy", cost=6)
        assert result.allowed is False

    def test_window_reset(self) -> None:
        """Vaqt oynasi tugagach — hisoblagich qaytadan."""
        rl = RateLimiter(window_s=1)  # 1 sekundlik oyna
        rl.set_custom_limit("fast", 2)
        rl.check("fast")
        rl.check("fast")
        assert rl.check("fast").allowed is False
        # Vaqt oynasi tugashini kutish
        time.sleep(1.1)
        assert rl.check("fast").allowed is True

    def test_retry_after(self) -> None:
        rl = RateLimiter(window_s=60)
        rl.set_custom_limit("x", 1)
        rl.check("x")
        result = rl.check("x")
        assert result.allowed is False
        assert result.retry_after > 0

    def test_stats(self) -> None:
        rl = RateLimiter()
        rl.check("a")
        rl.set_custom_limit("b", 1)
        rl.check("b")
        rl.check("b")  # denied
        s = rl.stats
        assert s["active_windows"] == 2
        assert s["custom_limits"] == 1
        assert s["total_allowed"] == 2
        assert s["total_denied"] == 1


# ─── 4. SecretStatus ────────────────────────────────────────────


class TestSecretStatus:
    """SecretStatus enum testlari."""

    def test_values(self) -> None:
        assert SecretStatus.ACTIVE == "active"
        assert SecretStatus.EXPIRING == "expiring"
        assert SecretStatus.EXPIRED == "expired"
        assert SecretStatus.REVOKED == "revoked"

    def test_four_statuses(self) -> None:
        assert len(SecretStatus) == 4


# ─── 5. SecretMetadata ──────────────────────────────────────────


class TestSecretMetadata:
    """SecretMetadata model testlari."""

    def test_create(self) -> None:
        m = SecretMetadata(name="API_KEY")
        assert m.name == "API_KEY"
        assert m.status == SecretStatus.ACTIVE
        assert m.expires_at is None
        assert m.rotation_count == 0

    def test_is_expired_no_expiry(self) -> None:
        m = SecretMetadata(name="KEY")
        assert m.is_expired is False

    def test_is_expired_future(self) -> None:
        m = SecretMetadata(
            name="KEY",
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        assert m.is_expired is False

    def test_is_expired_past(self) -> None:
        m = SecretMetadata(
            name="KEY",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        assert m.is_expired is True

    def test_days_until_expiry_none(self) -> None:
        m = SecretMetadata(name="KEY")
        assert m.days_until_expiry is None

    def test_days_until_expiry(self) -> None:
        m = SecretMetadata(
            name="KEY",
            expires_at=datetime.now(UTC) + timedelta(days=10),
        )
        days = m.days_until_expiry
        assert days is not None
        assert 9 <= days <= 10

    def test_frozen(self) -> None:
        m = SecretMetadata(name="KEY")
        with pytest.raises(ValidationError):
            m.name = "changed"  # type: ignore[misc]

    def test_name_validation(self) -> None:
        with pytest.raises(ValidationError):
            SecretMetadata(name="")


# ─── 6. mask_value ──────────────────────────────────────────────


class TestMaskValue:
    """mask_value funksiyasi testlari."""

    def test_normal(self) -> None:
        assert mask_value("sk-abc123xyz") == "********3xyz"

    def test_short_value(self) -> None:
        assert mask_value("abc") == "***"

    def test_exact_visible(self) -> None:
        assert mask_value("abcd") == "****"

    def test_custom_visible(self) -> None:
        assert mask_value("abcdef", visible=2) == "****ef"

    def test_empty(self) -> None:
        assert mask_value("") == ""

    def test_single_char(self) -> None:
        assert mask_value("x") == "*"


# ─── 7. SecretManager ──────────────────────────────────────────


class TestSecretManager:
    """SecretManager testlari."""

    def test_register(self) -> None:
        sm = SecretManager()
        meta = sm.register(name="API_KEY", value="sk-test123")
        assert meta.name == "API_KEY"
        assert meta.masked_value == "******t123"

    def test_get_value(self) -> None:
        sm = SecretManager()
        sm.register(name="KEY", value="secret_value")
        assert sm.get_value("KEY") == "secret_value"

    def test_get_value_missing(self) -> None:
        sm = SecretManager()
        assert sm.get_value("NOPE") is None

    def test_get_metadata(self) -> None:
        sm = SecretManager()
        sm.register(name="KEY", value="val")
        meta = sm.get_metadata("KEY")
        assert meta is not None
        assert meta.name == "KEY"

    def test_get_metadata_missing(self) -> None:
        sm = SecretManager()
        assert sm.get_metadata("NOPE") is None

    def test_rotate(self) -> None:
        sm = SecretManager()
        sm.register(name="KEY", value="old_value")
        meta = sm.rotate("KEY", "new_value")
        assert meta is not None
        assert meta.rotation_count == 1
        assert meta.rotated_at is not None
        assert sm.get_value("KEY") == "new_value"

    def test_rotate_multiple(self) -> None:
        sm = SecretManager()
        sm.register(name="KEY", value="v1")
        sm.rotate("KEY", "v2")
        meta = sm.rotate("KEY", "v3")
        assert meta is not None
        assert meta.rotation_count == 2
        assert sm.get_value("KEY") == "v3"

    def test_rotate_missing(self) -> None:
        sm = SecretManager()
        assert sm.rotate("NOPE", "val") is None

    def test_revoke(self) -> None:
        sm = SecretManager()
        sm.register(name="KEY", value="secret")
        assert sm.revoke("KEY") is True
        # Qiymat olib tashlangan
        assert sm.get_value("KEY") is None
        # Metadata hali bor
        meta = sm.get_metadata("KEY")
        assert meta is not None
        assert meta.status == SecretStatus.REVOKED

    def test_revoke_missing(self) -> None:
        sm = SecretManager()
        assert sm.revoke("NOPE") is False

    def test_list_secrets(self) -> None:
        sm = SecretManager()
        sm.register(name="A", value="a")
        sm.register(name="B", value="b")
        assert len(sm.list_secrets()) == 2

    def test_expiring_soon(self) -> None:
        sm = SecretManager()
        sm.register(name="SOON", value="v", expires_in_days=3)
        sm.register(name="LATER", value="v", expires_in_days=30)
        sm.register(name="FOREVER", value="v")
        expiring = sm.expiring_soon(days=7)
        names = [m.name for m in expiring]
        assert "SOON" in names
        assert "LATER" not in names
        assert "FOREVER" not in names

    def test_expiring_soon_revoked_excluded(self) -> None:
        sm = SecretManager()
        sm.register(name="REV", value="v", expires_in_days=3)
        sm.revoke("REV")
        assert sm.expiring_soon() == []

    def test_get_value_revoked(self) -> None:
        """Bekor qilingan kalitning qiymati qaytarilmaydi."""
        sm = SecretManager()
        sm.register(name="KEY", value="secret")
        sm.revoke("KEY")
        assert sm.get_value("KEY") is None

    def test_stats(self) -> None:
        sm = SecretManager()
        sm.register(name="A", value="a")
        sm.register(name="B", value="b", expires_in_days=3)
        sm.register(name="C", value="c")
        sm.revoke("C")
        s = sm.stats
        assert s["total"] == 3
        assert s["active"] == 2
        assert s["revoked"] == 1


# ─── 8. Security __init__ exports ──────────────────────────────


class TestSecurityExportsBolim11:
    """Bo'lim 11 qo'shimcha exportlar testlari."""

    def test_ratelimiter_importable(self) -> None:
        from zet.security import RateLimiter

        rl = RateLimiter()
        assert rl.stats["total_allowed"] == 0

    def test_secretmanager_importable(self) -> None:
        from zet.security import SecretManager

        sm = SecretManager()
        assert sm.stats["total"] == 0

    def test_all_bolim11_in_exports(self) -> None:
        import zet.security as mod

        bolim11_names = {
            "RateLimiter",
            "RateLimitResult",
            "RateLimitTier",
            "SecretManager",
            "SecretMetadata",
            "SecretStatus",
        }
        assert bolim11_names.issubset(set(mod.__all__))

    def test_audit_log_not_reexported(self) -> None:
        """NEGA. In-memory `AuditLog` olib tashlandi — haqiqiy audit
        `zet.security.audit_writer.write_audit()` orqali DB'ga yoziladi."""
        import zet.security as mod

        assert "AuditLog" not in mod.__all__
        assert "AuditCategory" not in mod.__all__
        assert "AuditEntry" not in mod.__all__


# ─── 9. Xavfsizlik invariantlari ───────────────────────────────


class TestSecurityBolim11Invariants:
    """Xavfsizlik invariantlari — Bo'lim 11."""

    def test_secret_metadata_frozen(self) -> None:
        """SecretMetadata o'zgartirib bo'lmaydi."""
        m = SecretMetadata(name="KEY")
        with pytest.raises(ValidationError):
            m.status = SecretStatus.REVOKED  # type: ignore[misc]

    def test_secret_value_not_in_metadata(self) -> None:
        """Kalit qiymati MetaData da emas, faqat maskalangan versiya."""
        sm = SecretManager()
        sm.register(name="KEY", value="super_secret_key_12345")
        meta = sm.get_metadata("KEY")
        assert meta is not None
        # Asl qiymat metadata da yo'q
        assert "super_secret_key_12345" not in str(meta.model_dump())
        # Maskalangan versiya bor
        assert "2345" in meta.masked_value
        assert "super" not in meta.masked_value

    def test_revoked_secret_value_deleted(self) -> None:
        """Bekor qilingan kalitning qiymati xotirada ham yo'q."""
        sm = SecretManager()
        meta = sm.register(name="KEY", value="secret")
        sm.revoke("KEY")
        # Ichki _values da yo'q
        assert meta.id not in sm._values

    def test_ratelimit_untrusted_stricter(self) -> None:
        """UNTRUSTED limit OWNER limitidan kichik."""
        rl = RateLimiter()
        # UNTRUSTED: 10, OWNER: 60
        for _ in range(10):
            rl.check("untrusted", RateLimitTier.UNTRUSTED)
        assert rl.check("untrusted", RateLimitTier.UNTRUSTED).allowed is False
        # OWNER hali bor
        for _ in range(10):
            rl.check("owner", RateLimitTier.OWNER)
        assert rl.check("owner", RateLimitTier.OWNER).allowed is True

    def test_ratelimit_cost_prevents_burst(self) -> None:
        """Og'ir so'rov limitni tezroq to'ldiradi."""
        rl = RateLimiter()
        rl.set_custom_limit("x", 10)
        result = rl.check("x", cost=11)
        assert result.allowed is False

    def test_mask_value_hides_secret(self) -> None:
        """mask_value kalitning ko'p qismini yashiradi."""
        masked = mask_value("sk-prod-1234567890abcdef")
        assert "sk-prod" not in masked
        assert "cdef" in masked  # Oxirgi 4 ta
