"""DeviceDBRepository — qurilma va tokenlarni DB'da saqlash (Bo'lim 8).

Ilgari `DeviceRegistry` (in-memory) protsess qayta ishga tushishi bilan
barcha qurilma va tokenlarni yo'qotardi (GAP_ANALYSIS #12: "qurilgan-u
ulanmagan"). `AgentRepository`, `PgCRM` va `CommerceRepository` bilan
bir xil naqsh — async, egaga bog'langan, `_get_*_row` yordamchilari.

Xavfsizlik qarori — XOM TOKEN FAQAT YARATISHDA:
    `register()` xom qiymat ham (foydalanuvchiga bir marta ko'rsatish
    uchun), xesh ham (bazaga saqlash uchun) hosil qiladi. Bazaga faqat
    xesh yoziladi (`hashlib.sha256`). Keyingi tekshiruvlar kelgan xom
    tokenni xeshlab jadval bilan solishtiradi — asl qiymat DB'da HECH
    QAYERDA yo'q. Egasi tokenni yo'qotsa yangisini yaratishi kerak.

`validate_token` **fail-open**: DB xatosida `False` qaytadi — chaqiruvchi
kod hech qachon istisno ko'rmaydi. Bu qat'iy shart: kamera snapshot yoki
push bildirishnomasi baza mavjud bo'lmagan lahzada ham "xato" (500) emas,
"ruxsat yo'q" (403) qaytarsin, aks holda ega qurilmalari jimgina yiqiladi.

Bog'liq qarorlar:
    Bo'lim 8 — qurilmalar (iPhone/Mac control)
    A-06 — capability token asosida ruxsat
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.models.device import CapabilityToken as CapabilityTokenRow
from zet.db.models.device import Device as DeviceRow
from zet.devices.registry import DeviceType

log = structlog.get_logger(__name__)


def _hash_token(raw_token: str) -> str:
    """Xom tokenning SHA-256 xeshi (hex-64 belgi).

    Nima uchun SHA-256, HMAC emas: token qiymatining O'ZI kriptografik
    tasodifiy (`secrets.token_urlsafe(32)` — 256 bit entropiya). Egasi
    yo'qotib qo'ymaguncha uni topib bo'lmaydi, shuning uchun kalitli
    xesh (HMAC) qo'shimcha himoya bermaydi — faqat sirlarni ko'paytiradi.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DeviceRecord:
    """`DeviceRow`ning tashqi ko'rinishi — API va boshqa qatlamlar shuni oladi.

    `DeviceRow`ni to'g'ridan-to'g'ri qaytarish ORM obyektining sessiyasi
    tugagach `DetachedInstanceError` beradi. Bu — oddiy qiymat.
    """

    id: str
    owner_id: str
    name: str
    device_type: DeviceType
    platform: str
    model: str
    ip_address: str
    online: bool
    last_seen: datetime | None
    meta: dict[str, object]
    created_at: datetime
    updated_at: datetime


def _row_to_record(row: DeviceRow) -> DeviceRecord:
    return DeviceRecord(
        id=str(row.id),
        owner_id=str(row.owner_id),
        name=row.name,
        device_type=row.device_type,
        platform=row.platform,
        model=row.model,
        ip_address=row.ip_address,
        online=row.online,
        last_seen=row.last_seen,
        meta=dict(row.meta or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class DeviceDBRepository:
    """DB-backed qurilma va token repozitoriysi — bitta egaga bog'langan."""

    def __init__(self, session: AsyncSession, *, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    # ── Qurilma CRUD ──────────────────────────────────────────────

    async def register(
        self,
        *,
        name: str,
        device_type: DeviceType,
        platform: str = "",
        model: str = "",
        capabilities: list[str] | None = None,
        expires_at: datetime | None = None,
        label: str = "",
    ) -> tuple[DeviceRecord, str]:
        """Yangi qurilma ro'yxatga oladi va unga token beradi.

        Returns:
            `(record, raw_token)` — **xom token FAQAT SHU YERDA** ko'rinadi.
            Chaqiruvchi uni bir marta foydalanuvchiga ko'rsatishi kerak;
            keyin uni qayta olib bo'lmaydi (DB'da faqat xesh).
        """
        device = DeviceRow(
            owner_id=self._owner_id,
            name=name,
            device_type=device_type,
            platform=platform,
            model=model,
        )
        self._session.add(device)
        await self._session.flush()

        raw_token = secrets.token_urlsafe(32)
        token_row = CapabilityTokenRow(
            device_id=device.id,
            token_hash=_hash_token(raw_token),
            capabilities=list(capabilities or []),
            expires_at=expires_at,
            label=label,
        )
        self._session.add(token_row)
        await self._session.flush()

        log.info(
            "device.registered",
            id=str(device.id),
            name=name,
            type=device_type.value,
            capabilities=list(capabilities or []),
        )
        return _row_to_record(device), raw_token

    async def get(self, device_id: str) -> DeviceRecord | None:
        row = await self._get_device_row(device_id)
        return _row_to_record(row) if row is not None else None

    async def list(self, device_type: DeviceType | None = None) -> list[DeviceRecord]:
        """Egasi qurilmalarining ro'yxati (ixtiyoriy tur filtri)."""
        stmt = select(DeviceRow).where(DeviceRow.owner_id == self._owner_id)
        if device_type is not None:
            stmt = stmt.where(DeviceRow.device_type == device_type)
        result = await self._session.execute(stmt.order_by(DeviceRow.created_at))
        return [_row_to_record(r) for r in result.scalars().all()]

    async def update_status(self, device_id: str, *, online: bool) -> DeviceRecord | None:
        """Qurilma onlaynligini yangilaydi. `online=True` bo'lsa `last_seen` ham yangilanadi."""
        row = await self._get_device_row(device_id)
        if row is None:
            return None
        row.online = online
        if online:
            row.last_seen = datetime.now(UTC)
        await self._session.flush()
        log.info("device.status_updated", id=device_id, online=online)
        return _row_to_record(row)

    async def delete(self, device_id: str) -> bool:
        """Qurilmani (va uning barcha tokenlarini) o'chiradi.

        Tokenlar `ondelete="CASCADE"` bilan bog'langan, shuning uchun
        alohida `DELETE` shart emas — lekin `revoked_at` audit uchun
        oldindan qo'yiladi (agar biror joyda tarix o'qilsa "o'chirilgan
        vaqtda faol edi" degan noto'g'ri xulosa chiqmasin).
        """
        row = await self._get_device_row(device_id)
        if row is None:
            return False
        await self._revoke_all_for_device(row.id)
        await self._session.delete(row)
        await self._session.flush()
        log.info("device.deleted", id=device_id)
        return True

    # ── Tokenlar ──────────────────────────────────────────────────

    async def validate_token(self, raw_token: str, capability: str) -> bool:
        """Xom tokenni tekshiradi — faol, muddati o'tmagan, imkoniyat mavjud.

        **FAIL-OPEN**: har qanday DB xatosida `False` qaytadi. Bu — atayin
        qaror: kamera snapshot yoki push chaqiruvi bazaviy nosozlik
        payida "500 xato" emas, "ruxsat yo'q" qaytarsin, aks holda ega
        qurilmalari jimgina yiqiladi (modul docstringidagi izohga qarang).
        """
        if not raw_token:
            return False
        try:
            token_hash = _hash_token(raw_token)
            result = await self._session.execute(
                select(CapabilityTokenRow).where(CapabilityTokenRow.token_hash == token_hash)
            )
            row = result.scalar_one_or_none()
        except SQLAlchemyError:
            log.warning("device.token_validate_db_error")
            return False

        if row is None:
            return False
        if row.revoked_at is not None:
            return False
        if row.expires_at is not None and datetime.now(UTC) >= row.expires_at:
            return False
        return capability in (row.capabilities or [])

    async def revoke_token(self, raw_token: str) -> bool:
        """Tokenni bekor qiladi (`revoked_at` = hozir). Yozuv o'chirilmaydi.

        Sabab: audit izi qolsin — kim, qachon bekor qilingan bo'lsa,
        `capability_token` jadvalidan hech qachon yo'qolmaydi.
        """
        if not raw_token:
            return False
        try:
            token_hash = _hash_token(raw_token)
            result = await self._session.execute(
                select(CapabilityTokenRow).where(CapabilityTokenRow.token_hash == token_hash)
            )
            row = result.scalar_one_or_none()
            if row is None or row.revoked_at is not None:
                return False
            row.revoked_at = datetime.now(UTC)
            await self._session.flush()
        except SQLAlchemyError:
            log.warning("device.token_revoke_db_error")
            return False
        log.info("device.token_revoked", token_prefix=raw_token[:8] + "...")
        return True

    async def revoke_all_tokens(self) -> int:
        """Egasining barcha faol tokenlarini bekor qiladi (SR-06 killswitch).

        Kill-switch yoqilganda mavjud iPhone/Mac/kamera tokenlari ham
        hech qanday ish qila olmasligi kerak — aks holda "emergency
        stop" faqat yangi run'larni to'xtatib, allaqachon ochilgan
        eshiklarni ochiq qoldirardi. Bulk UPDATE — bitta so'rov, ega
        chegarasida:

        ```sql
        UPDATE capability_token
           SET revoked_at = now()
         WHERE device_id IN (SELECT id FROM device WHERE owner_id=:owner)
           AND revoked_at IS NULL
        ```

        Returns:
            Bekor qilingan tokenlar soni. DB xatosida `0` — chaqiruvchi
            baribir killswitch yoqilganini foydalanuvchiga bildiradi
            (fail-open, `validate_token` bilan bir xil naqsh).
        """
        now = datetime.now(UTC)
        owner_devices_subquery = select(DeviceRow.id).where(DeviceRow.owner_id == self._owner_id)
        try:
            result = await self._session.execute(
                update(CapabilityTokenRow)
                .where(
                    CapabilityTokenRow.device_id.in_(owner_devices_subquery),
                    CapabilityTokenRow.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await self._session.flush()
        except SQLAlchemyError:
            log.warning("device.revoke_all_db_error")
            return 0
        count = int(result.rowcount or 0)
        if count:
            log.critical("device.tokens_bulk_revoked", count=count, owner_id=str(self._owner_id))
        return count

    # ── Yordamchi ─────────────────────────────────────────────────

    async def _get_device_row(self, device_id: str) -> DeviceRow | None:
        try:
            row_id = uuid.UUID(device_id)
        except ValueError:
            return None
        result = await self._session.execute(
            select(DeviceRow).where(DeviceRow.id == row_id, DeviceRow.owner_id == self._owner_id)
        )
        return result.scalar_one_or_none()

    async def _revoke_all_for_device(self, device_id: uuid.UUID) -> None:
        """Qurilma barcha faol tokenlarini o'chirishdan oldin bekor qiladi."""
        result = await self._session.execute(
            select(CapabilityTokenRow).where(
                CapabilityTokenRow.device_id == device_id,
                CapabilityTokenRow.revoked_at.is_(None),
            )
        )
        now = datetime.now(UTC)
        for row in result.scalars().all():
            row.revoked_at = now
        await self._session.flush()


__all__ = ["DeviceDBRepository", "DeviceRecord"]
