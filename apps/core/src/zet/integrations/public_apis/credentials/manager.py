"""Dinamik public-API provayder kredensiallari — mavjud `SecretManager`
ustidagi YUPQA qatlam (Bo'lim 8).

NEGA yangi klass emas: `zet.security.secrets.SecretManager` allaqachon
register/get_value/rotate/revoke/list_secrets/expiring_soon'ga ega va
sinovdan o'tgan (`security/secrets.py`dagi izohga qarang). Bu klass
FAQAT nom maydonini (`public_apis:{provider}`) izolyatsiya qiladi —
public-apis provayder kalitlari boshqa (kelajakdagi) `SecretManager`
foydalanuvchilari bilan bir xil nom fazosini bo'lishmasin.

XAVFSIZLIK: `get_value()` xom qiymatni qaytaradi — bu FAQAT adapter
konstruktor darajasida chaqirilishi kerak (bir marta, tool yaratilganda),
LLM/Planner/Brain HECH QACHON bu klassni to'g'ridan-to'g'ri ko'rmaydi
yoki chaqirmaydi.
"""

from __future__ import annotations

from zet.security.secrets import SecretManager, SecretMetadata

_KEY_PREFIX = "public_apis:"


class PublicAPICredentialManager:
    """`SecretManager`ni public-apis provayder nomlari bilan o'raydi."""

    def __init__(self, secret_manager: SecretManager | None = None) -> None:
        self._secrets = secret_manager if secret_manager is not None else SecretManager()

    @staticmethod
    def _key(provider: str) -> str:
        return f"{_KEY_PREFIX}{provider.strip().lower()}"

    def register(
        self, *, provider: str, value: str, expires_in_days: int | None = None
    ) -> SecretMetadata:
        return self._secrets.register(
            name=self._key(provider), value=value, expires_in_days=expires_in_days
        )

    def get_value(self, provider: str) -> str | None:
        """Xom kredensial qiymati — FAQAT adapter konstruktorida ishlatiladi."""
        return self._secrets.get_value(self._key(provider))

    def has_credential(self, provider: str) -> bool:
        return self.get_value(provider) is not None

    def status(self, provider: str) -> SecretMetadata | None:
        return self._secrets.get_metadata(self._key(provider))

    def rotate(self, provider: str, new_value: str) -> SecretMetadata | None:
        return self._secrets.rotate(self._key(provider), new_value)

    def revoke(self, provider: str) -> bool:
        return self._secrets.revoke(self._key(provider))

    def list_providers(self) -> list[SecretMetadata]:
        return [
            meta for meta in self._secrets.list_secrets() if meta.name.startswith(_KEY_PREFIX)
        ]


__all__ = ["PublicAPICredentialManager"]
