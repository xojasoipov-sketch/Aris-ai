"""Secret Manager — maxfiy kalitlar boshqaruvi (Bo'lim 11).

.. note:: ikki xil ishlatilish holati, ikkalasi ham HAQIQIY

    1. **Belgilangan, operator-oldindan-biladigan xizmatlar** (Anthropic,
       Telegram, GitHub va h.k.) — bular hamon `zet.config.Settings`
       orqali (`.env`dan, pydantic-settings) yuklanadi. `SecretManager`ni
       BU maqsad uchun ISHLATMANG — ikkita alohida sir manbasini
       saqlash sinxronsizlikka olib keladi.

    2. **Dinamik, ishga tushirilgandan keyin qo'shiladigan provayder
       kredensiallari** (masalan `integrations/public_apis/credentials/`
       — public-apis katalogidan topilgan tashqi API provayderlari,
       oldindan qancha bo'lishi noma'lum) — `Settings`ning FIKSATLANGAN
       pydantic maydonlari BU holatga mos EMAS (har yangi provayder kod
       o'zgarishi+qayta deploy talab qilardi). Aynan shu holat uchun
       `SecretManager` ILGARI QURILGAN EDI — `register()`/`get_value()`/
       `rotate()`/`revoke()`/`list_secrets()` allaqachon bor va sinovdan
       o'tgan (`tests/test_security_bolim11.py`). Bu modul hozir aynan
       shu (2) maqsad uchun ishlatiladi.

Xavfsizlik:
    - Kalitlar hech qachon logga yozilmaydi
    - Kalitlar hech qachon API javobida qaytarilmaydi
    - Faqat maskalangan versiya ko'rsatiladi (oxirgi 4 ta belgi)
    - Rotatsiya callback orqali amalga oshiriladi

Bog'liq qarorlar:
    Bo'lim 11 — xavfsizlik
    V-33 — secret rotation
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)


class SecretStatus(StrEnum):
    """Kalit holati."""

    ACTIVE = "active"
    """Faol — ishlatilmoqda."""

    EXPIRING = "expiring"
    """Muddati yaqinlashmoqda (7 kun ichida)."""

    EXPIRED = "expired"
    """Muddati tugagan."""

    REVOKED = "revoked"
    """Bekor qilingan."""


class SecretMetadata(BaseModel, frozen=True):
    """Kalit metadata — kalit qiymatisiz.

    XAVFSIZLIK: qiymatning o'zi hech qachon bu modelda saqlanmaydi.
    Faqat metadata (nomi, holati, muddati) saqlanadi.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unikal ID."""

    name: str = Field(min_length=1, max_length=100)
    """Kalit nomi (masalan: 'MISTRAL_API_KEY')."""

    status: SecretStatus = SecretStatus.ACTIVE
    """Holati."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Yaratilgan vaqt."""

    expires_at: datetime | None = None
    """Muddati tugash vaqti (None = cheksiz)."""

    rotated_at: datetime | None = None
    """Oxirgi rotatsiya vaqti."""

    rotation_count: int = 0
    """Necha marta rotatsiya qilingan."""

    last_used_at: datetime | None = None
    """Oxirgi marta `get_value()` orqali HAQIQATAN o'qilgan vaqt (`None`
    — hali hech qachon ishlatilmagan). `integrations/public_apis`
    sog'liq/audit ko'rinishida "bu kalit ishlatilyaptimi" savoliga
    javob berish uchun (Phase 8/17)."""

    masked_value: str = ""
    """Maskalangan qiymat (oxirgi 4 ta belgi). Masalan: '****abcd'."""

    @property
    def is_expired(self) -> bool:
        """Muddati tugaganmi."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) >= self.expires_at

    @property
    def days_until_expiry(self) -> int | None:
        """Muddati tugashigacha qolgan kunlar."""
        if self.expires_at is None:
            return None
        delta = self.expires_at - datetime.now(UTC)
        return max(0, delta.days)


def mask_value(value: str, *, visible: int = 4) -> str:
    """Kalit qiymatini maskalash.

    Args:
        value: Asl qiymat
        visible: Ko'rinadigan belgilar soni (oxirdan)

    Returns:
        Maskalangan qiymat (masalan: '****abcd')
    """
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]


class SecretManager:
    """Maxfiy kalitlar boshqaruvchisi (in-memory).

    XAVFSIZLIK: kalit qiymatlari faqat _values dict da saqlanadi.
    Tashqariga faqat metadata chiqariladi.
    """

    def __init__(self) -> None:
        self._metadata: dict[str, SecretMetadata] = {}
        self._values: dict[str, str] = {}
        self._name_to_id: dict[str, str] = {}

    def register(
        self,
        *,
        name: str,
        value: str,
        expires_in_days: int | None = None,
    ) -> SecretMetadata:
        """Yangi kalit ro'yxatga olish.

        Args:
            name: Kalit nomi
            value: Kalit qiymati
            expires_in_days: Muddati (kunlarda). None = cheksiz

        Returns:
            SecretMetadata (qiymatsiz)
        """
        expires_at = None
        if expires_in_days is not None:
            expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)

        meta = SecretMetadata(
            name=name,
            expires_at=expires_at,
            masked_value=mask_value(value),
        )
        self._metadata[meta.id] = meta
        self._values[meta.id] = value
        self._name_to_id[name] = meta.id

        log.info("secret.registered", name=name, id=meta.id)
        return meta

    def get_value(self, name: str) -> str | None:
        """Kalit qiymatini olish (faqat ichki foydalanish uchun).

        XAVFSIZLIK: bu metod faqat ichki komponentlar tomonidan
        chaqirilishi kerak. Natija hech qachon logga yozilmasligi
        yoki API orqali qaytarilmasligi kerak.

        Args:
            name: Kalit nomi

        Returns:
            Kalit qiymati yoki None
        """
        secret_id = self._name_to_id.get(name)
        if secret_id is None:
            return None
        meta = self._metadata.get(secret_id)
        if meta is None:
            return None
        if meta.status in (SecretStatus.REVOKED, SecretStatus.EXPIRED):
            return None
        value = self._values.get(secret_id)
        if value is not None:
            # Har HAQIQIY o'qish `last_used_at`ni yangilaydi — chaqiruvchi
            # buni alohida eslab qolishi shart emas (unutilishi mumkin
            # bo'lgan qadam emas, `get_value()`ning o'zi kafolatlaydi).
            self._metadata[secret_id] = meta.model_copy(
                update={"last_used_at": datetime.now(UTC)}
            )
        return value

    def get_metadata(self, name: str) -> SecretMetadata | None:
        """Kalit metadatasini olish (qiymatsiz).

        Args:
            name: Kalit nomi

        Returns:
            SecretMetadata yoki None
        """
        secret_id = self._name_to_id.get(name)
        if secret_id is None:
            return None
        return self._metadata.get(secret_id)

    def rotate(self, name: str, new_value: str) -> SecretMetadata | None:
        """Kalitni rotatsiya qilish — yangi qiymat bilan almashtirish.

        Args:
            name: Kalit nomi
            new_value: Yangi qiymat

        Returns:
            Yangilangan SecretMetadata yoki None
        """
        secret_id = self._name_to_id.get(name)
        if secret_id is None:
            return None
        old_meta = self._metadata.get(secret_id)
        if old_meta is None:
            return None

        new_meta = SecretMetadata(
            id=old_meta.id,
            name=old_meta.name,
            status=SecretStatus.ACTIVE,
            created_at=old_meta.created_at,
            expires_at=old_meta.expires_at,
            rotated_at=datetime.now(UTC),
            rotation_count=old_meta.rotation_count + 1,
            masked_value=mask_value(new_value),
        )
        self._metadata[secret_id] = new_meta
        self._values[secret_id] = new_value

        log.info(
            "secret.rotated",
            name=name,
            rotation_count=new_meta.rotation_count,
        )
        return new_meta

    def revoke(self, name: str) -> bool:
        """Kalitni bekor qilish.

        Args:
            name: Kalit nomi

        Returns:
            True agar topilsa va bekor qilinsa
        """
        secret_id = self._name_to_id.get(name)
        if secret_id is None:
            return False
        old_meta = self._metadata.get(secret_id)
        if old_meta is None:
            return False

        new_meta = SecretMetadata(
            id=old_meta.id,
            name=old_meta.name,
            status=SecretStatus.REVOKED,
            created_at=old_meta.created_at,
            expires_at=old_meta.expires_at,
            rotated_at=old_meta.rotated_at,
            rotation_count=old_meta.rotation_count,
            masked_value=old_meta.masked_value,
        )
        self._metadata[secret_id] = new_meta
        # Qiymatni o'chirish — xavfsizlik uchun
        self._values.pop(secret_id, None)

        log.warning("secret.revoked", name=name)
        return True

    def list_secrets(self) -> list[SecretMetadata]:
        """Barcha kalitlar metadatasi (qiymatsiz).

        Returns:
            SecretMetadata ro'yxati
        """
        return list(self._metadata.values())

    def expiring_soon(self, *, days: int = 7) -> list[SecretMetadata]:
        """Muddati yaqinlashgan kalitlar.

        Args:
            days: Necha kun ichida tugaydi

        Returns:
            Muddati yaqinlashgan kalitlar
        """
        threshold = datetime.now(UTC) + timedelta(days=days)
        return [
            m
            for m in self._metadata.values()
            if m.expires_at is not None
            and m.status == SecretStatus.ACTIVE
            and m.expires_at <= threshold
        ]

    @property
    def stats(self) -> dict[str, int]:
        """Statistika."""
        metas = list(self._metadata.values())
        return {
            "total": len(metas),
            "active": sum(1 for m in metas if m.status == SecretStatus.ACTIVE),
            "expiring": len(self.expiring_soon()),
            "expired": sum(1 for m in metas if m.status == SecretStatus.EXPIRED),
            "revoked": sum(1 for m in metas if m.status == SecretStatus.REVOKED),
        }
