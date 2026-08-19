"""public-apis kredensial boshqaruvi testlari (JB-18, Bo'lim 8) —
`PublicAPICredentialManager` (mavjud `SecretManager` ustidagi nom
fazosi qatlami) + xavfsizlik: qiymat hech qachon metadata/status
javobida chiqmasligi.
"""

from __future__ import annotations

from zet.integrations.public_apis.credentials.manager import PublicAPICredentialManager
from zet.security.secrets import SecretManager


class TestRegisterAndGetValue:
    def test_register_then_get_value_roundtrip(self) -> None:
        mgr = PublicAPICredentialManager()
        mgr.register(provider="somenewapi", value="secret-key-abc123")
        assert mgr.get_value("somenewapi") == "secret-key-abc123"

    def test_unregistered_provider_returns_none(self) -> None:
        assert PublicAPICredentialManager().get_value("nope") is None

    def test_has_credential(self) -> None:
        mgr = PublicAPICredentialManager()
        assert mgr.has_credential("x") is False
        mgr.register(provider="x", value="v")
        assert mgr.has_credential("x") is True


class TestKeyNamespaceIsolation:
    def test_provider_names_are_prefixed_to_avoid_collision(self) -> None:
        """`SecretManager`ning nom fazosi umumiy — boshqa (kelajakdagi)
        foydalanuvchi bilan bir xil `provider` nomi TO'QNASHMASLIGI kerak."""
        underlying = SecretManager()
        mgr = PublicAPICredentialManager(underlying)
        mgr.register(provider="anthropic", value="pub-apis-value")
        underlying.register(name="anthropic", value="unrelated-other-value")

        assert mgr.get_value("anthropic") == "pub-apis-value"
        assert underlying.get_value("anthropic") == "unrelated-other-value"

    def test_case_and_whitespace_normalized_in_key(self) -> None:
        mgr = PublicAPICredentialManager()
        mgr.register(provider="  SomeAPI  ", value="v1")
        assert mgr.get_value("someapi") == "v1"
        assert mgr.get_value("SOMEAPI") == "v1"


class TestListProvidersOnlyReturnsOwnNamespace:
    def test_list_providers_excludes_unrelated_secrets(self) -> None:
        underlying = SecretManager()
        mgr = PublicAPICredentialManager(underlying)
        mgr.register(provider="providerA", value="a")
        mgr.register(provider="providerB", value="b")
        underlying.register(name="ANTHROPIC_API_KEY", value="unrelated")

        names = {m.name for m in mgr.list_providers()}
        assert names == {"public_apis:providera", "public_apis:providerb"}


class TestRotateAndRevoke:
    def test_rotate_updates_value(self) -> None:
        mgr = PublicAPICredentialManager()
        mgr.register(provider="x", value="old")
        mgr.rotate("x", "new")
        assert mgr.get_value("x") == "new"

    def test_revoke_makes_value_unavailable(self) -> None:
        mgr = PublicAPICredentialManager()
        mgr.register(provider="x", value="v")
        assert mgr.revoke("x") is True
        assert mgr.get_value("x") is None

    def test_revoke_unknown_provider_returns_false(self) -> None:
        assert PublicAPICredentialManager().revoke("nope") is False


# ── Xavfsizlik: qiymat metadata/status javobida HECH QACHON chiqmasin ──


class TestCredentialValueNeverLeaksThroughMetadata:
    def test_status_exposes_masked_value_only(self) -> None:
        mgr = PublicAPICredentialManager()
        mgr.register(provider="leaktest", value="super-secret-raw-value-12345")
        status = mgr.status("leaktest")
        assert status is not None
        assert "super-secret-raw-value-12345" not in status.masked_value
        assert status.masked_value.endswith("2345")  # oxirgi 4 belgi ko'rinadi
        assert status.masked_value.startswith("*")

    def test_status_model_has_no_raw_value_field(self) -> None:
        """`SecretMetadata`ning O'ZI xom qiymat maydoniga EGA EMAS — bu
        arxitektura darajasidagi kafolat (masalan `model_dump()`
        natijasi hech qachon xom qiymatni o'z ichiga OLA OLMAYDI)."""
        mgr = PublicAPICredentialManager()
        mgr.register(provider="leaktest2", value="another-raw-secret")
        status = mgr.status("leaktest2")
        assert status is not None
        dumped = status.model_dump()
        assert "another-raw-secret" not in str(dumped)

    def test_list_providers_never_exposes_raw_values(self) -> None:
        mgr = PublicAPICredentialManager()
        mgr.register(provider="a", value="raw-value-a")
        mgr.register(provider="b", value="raw-value-b")
        dumped = [m.model_dump() for m in mgr.list_providers()]
        blob = str(dumped)
        assert "raw-value-a" not in blob
        assert "raw-value-b" not in blob

    def test_get_value_updates_last_used_at(self) -> None:
        """Bo'lim 8/17: har HAQIQIY o'qish `last_used_at`ni yangilaydi —
        audit/sog'liq ko'rinishida "ishlatilyaptimi" savoliga javob."""
        mgr = PublicAPICredentialManager()
        mgr.register(provider="x", value="v")
        before = mgr.status("x")
        assert before is not None
        assert before.last_used_at is None  # hali o'qilmagan
        mgr.get_value("x")
        after = mgr.status("x")
        assert after is not None
        assert after.last_used_at is not None
