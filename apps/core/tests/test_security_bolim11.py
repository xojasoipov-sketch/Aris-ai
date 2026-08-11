"""Bo'lim 11 testlari — Xavfsizlik (Rate Limiter, Audit Log, Secret Manager).

Test guruhlari:
    1. RateLimitTier — enum qiymatlari
    2. RateLimitResult — model maydonlari
    3. RateLimiter — check, limits, tiers, custom, reset, stats
    4. AuditCategory — enum qiymatlari
    5. AuditEntry — yaratish, compute_hash, frozen
    6. AuditLog — append, entries filter, hash chain, verify_integrity, stats
    7. SecretStatus — enum qiymatlari
    8. SecretMetadata — yaratish, is_expired, days_until_expiry, frozen
    9. mask_value — turli uzunliklar
    10. SecretManager — register, get_value, rotate, revoke, list, expiring_soon
    11. Security __init__ exports (Bo'lim 11 qo'shimchalari)
    12. Xavfsizlik invariantlari
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from zet.security import (
    AuditCategory,
    AuditEntry,
    AuditLog,
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


# ─── 4. AuditCategory ──────────────────────────────────────────


class TestAuditCategory:
    """AuditCategory enum testlari."""

    def test_values(self) -> None:
        assert AuditCategory.AUTH == "auth"
        assert AuditCategory.PERMISSION == "permission"
        assert AuditCategory.DATA == "data"
        assert AuditCategory.CONFIG == "config"
        assert AuditCategory.SECURITY == "security"
        assert AuditCategory.SYSTEM == "system"

    def test_six_categories(self) -> None:
        assert len(AuditCategory) == 6


# ─── 5. AuditEntry ──────────────────────────────────────────────


class TestAuditEntry:
    """AuditEntry model testlari."""

    def test_create(self) -> None:
        e = AuditEntry(category=AuditCategory.AUTH, action="login")
        assert e.category == AuditCategory.AUTH
        assert e.action == "login"
        assert e.actor == "system"
        assert e.success is True
        assert len(e.id) == 16
        assert isinstance(e.timestamp, datetime)

    def test_create_with_details(self) -> None:
        e = AuditEntry(
            category=AuditCategory.SECURITY,
            action="injection.detected",
            actor="scanner",
            target="run_123",
            detail="Prompt injection topildi",
            success=False,
        )
        assert e.actor == "scanner"
        assert e.target == "run_123"
        assert e.success is False

    def test_compute_hash(self) -> None:
        e = AuditEntry(category=AuditCategory.AUTH, action="login")
        h = e.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 32  # SHA-256 truncated

    def test_hash_deterministic(self) -> None:
        e = AuditEntry(category=AuditCategory.AUTH, action="login")
        assert e.compute_hash() == e.compute_hash()

    def test_different_entries_different_hash(self) -> None:
        e1 = AuditEntry(category=AuditCategory.AUTH, action="login")
        e2 = AuditEntry(category=AuditCategory.AUTH, action="logout")
        assert e1.compute_hash() != e2.compute_hash()

    def test_frozen(self) -> None:
        e = AuditEntry(category=AuditCategory.AUTH, action="login")
        with pytest.raises(ValidationError):
            e.action = "changed"  # type: ignore[misc]


# ─── 6. AuditLog ────────────────────────────────────────────────


class TestAuditLog:
    """AuditLog testlari."""

    def test_append(self) -> None:
        al = AuditLog()
        entry = al.append(category=AuditCategory.AUTH, action="login")
        assert entry.category == AuditCategory.AUTH
        assert al.count == 1

    def test_append_multiple(self) -> None:
        al = AuditLog()
        al.append(category=AuditCategory.AUTH, action="login")
        al.append(category=AuditCategory.DATA, action="write")
        al.append(category=AuditCategory.SYSTEM, action="start")
        assert al.count == 3

    def test_last_entry(self) -> None:
        al = AuditLog()
        al.append(category=AuditCategory.AUTH, action="login")
        al.append(category=AuditCategory.DATA, action="write")
        assert al.last_entry is not None
        assert al.last_entry.action == "write"

    def test_last_entry_empty(self) -> None:
        al = AuditLog()
        assert al.last_entry is None

    def test_entries_reverse_order(self) -> None:
        al = AuditLog()
        al.append(category=AuditCategory.AUTH, action="first")
        al.append(category=AuditCategory.AUTH, action="second")
        al.append(category=AuditCategory.AUTH, action="third")
        entries = al.entries()
        assert entries[0].action == "third"
        assert entries[2].action == "first"

    def test_entries_filter_category(self) -> None:
        al = AuditLog()
        al.append(category=AuditCategory.AUTH, action="login")
        al.append(category=AuditCategory.DATA, action="write")
        al.append(category=AuditCategory.AUTH, action="logout")
        auth = al.entries(category=AuditCategory.AUTH)
        assert len(auth) == 2

    def test_entries_filter_actor(self) -> None:
        al = AuditLog()
        al.append(category=AuditCategory.AUTH, action="a", actor="owner")
        al.append(category=AuditCategory.AUTH, action="b", actor="system")
        owner = al.entries(actor="owner")
        assert len(owner) == 1
        assert owner[0].actor == "owner"

    def test_entries_limit(self) -> None:
        al = AuditLog()
        for i in range(20):
            al.append(category=AuditCategory.AUTH, action=f"act_{i}")
        limited = al.entries(limit=5)
        assert len(limited) == 5

    def test_hash_chain(self) -> None:
        """Har bir yozuvning prev_hash oldingi yozuvning hashiga teng."""
        al = AuditLog()
        e1 = al.append(category=AuditCategory.AUTH, action="first")
        e2 = al.append(category=AuditCategory.AUTH, action="second")
        assert e1.prev_hash == ""  # Birinchi yozuv — bo'sh
        assert e2.prev_hash == e1.compute_hash()

    def test_verify_integrity_ok(self) -> None:
        al = AuditLog()
        al.append(category=AuditCategory.AUTH, action="a")
        al.append(category=AuditCategory.DATA, action="b")
        al.append(category=AuditCategory.SYSTEM, action="c")
        assert al.verify_integrity() is True

    def test_verify_integrity_empty(self) -> None:
        al = AuditLog()
        assert al.verify_integrity() is True

    def test_verify_integrity_tampered(self) -> None:
        """Yozuv o'zgartirilsa — zanjir buziladi."""
        al = AuditLog()
        al.append(category=AuditCategory.AUTH, action="a")
        al.append(category=AuditCategory.AUTH, action="b")
        # Zanjirni buzish: birinchi yozuvni almashtirish
        fake = AuditEntry(
            category=AuditCategory.AUTH,
            action="tampered",
            prev_hash="",  # to'g'ri prev_hash, lekin hash o'zgaradi
        )
        al._entries[0] = fake
        assert al.verify_integrity() is False

    def test_stats(self) -> None:
        al = AuditLog()
        al.append(category=AuditCategory.AUTH, action="login", success=True)
        al.append(category=AuditCategory.SECURITY, action="blocked", success=False)
        s = al.stats
        assert s["total"] == 2
        assert s["failed"] == 1
        assert s["integrity_ok"] is True
        assert s["by_category"]["auth"] == 1
        assert s["by_category"]["security"] == 1


# ─── 7. SecretStatus ────────────────────────────────────────────


class TestSecretStatus:
    """SecretStatus enum testlari."""

    def test_values(self) -> None:
        assert SecretStatus.ACTIVE == "active"
        assert SecretStatus.EXPIRING == "expiring"
        assert SecretStatus.EXPIRED == "expired"
        assert SecretStatus.REVOKED == "revoked"

    def test_four_statuses(self) -> None:
        assert len(SecretStatus) == 4


# ─── 8. SecretMetadata ──────────────────────────────────────────


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


# ─── 9. mask_value ──────────────────────────────────────────────


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


# ─── 10. SecretManager ──────────────────────────────────────────


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


# ─── 11. Security __init__ exports ──────────────────────────────


class TestSecurityExportsBolim11:
    """Bo'lim 11 qo'shimcha exportlar testlari."""

    def test_ratelimiter_importable(self) -> None:
        from zet.security import RateLimiter

        rl = RateLimiter()
        assert rl.stats["total_allowed"] == 0

    def test_auditlog_importable(self) -> None:
        from zet.security import AuditLog

        al = AuditLog()
        assert al.count == 0

    def test_secretmanager_importable(self) -> None:
        from zet.security import SecretManager

        sm = SecretManager()
        assert sm.stats["total"] == 0

    def test_all_bolim11_in_exports(self) -> None:
        import zet.security as mod

        bolim11_names = {
            "AuditCategory",
            "AuditEntry",
            "AuditLog",
            "RateLimiter",
            "RateLimitResult",
            "RateLimitTier",
            "SecretManager",
            "SecretMetadata",
            "SecretStatus",
        }
        assert bolim11_names.issubset(set(mod.__all__))


# ─── 12. Xavfsizlik invariantlari ───────────────────────────────


class TestSecurityBolim11Invariants:
    """Xavfsizlik invariantlari — Bo'lim 11."""

    def test_audit_entry_frozen(self) -> None:
        """AuditEntry o'zgartirib bo'lmaydi."""
        e = AuditEntry(category=AuditCategory.AUTH, action="login")
        with pytest.raises(ValidationError):
            e.action = "changed"  # type: ignore[misc]

    def test_secret_metadata_frozen(self) -> None:
        """SecretMetadata o'zgartirib bo'lmaydi."""
        m = SecretMetadata(name="KEY")
        with pytest.raises(ValidationError):
            m.status = SecretStatus.REVOKED  # type: ignore[misc]

    def test_audit_hash_chain_immutable(self) -> None:
        """Hash chain buzilsa — verify_integrity False qaytaradi."""
        al = AuditLog()
        al.append(category=AuditCategory.AUTH, action="a")
        al.append(category=AuditCategory.AUTH, action="b")
        assert al.verify_integrity() is True
        # Buzish
        al._entries[0] = AuditEntry(category=AuditCategory.SECURITY, action="fake", prev_hash="")
        assert al.verify_integrity() is False

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

    def test_audit_append_only_semantics(self) -> None:
        """AuditLog faqat append qiladi — o'chirish metodi yo'q."""
        al = AuditLog()
        # O'chirish yoki yangilash metodi yo'qligini tekshirish
        assert not hasattr(al, "delete")
        assert not hasattr(al, "remove")
        assert not hasattr(al, "update")
        assert not hasattr(al, "clear")

    def test_mask_value_hides_secret(self) -> None:
        """mask_value kalitning ko'p qismini yashiradi."""
        masked = mask_value("sk-prod-1234567890abcdef")
        assert "sk-prod" not in masked
        assert "cdef" in masked  # Oxirgi 4 ta
