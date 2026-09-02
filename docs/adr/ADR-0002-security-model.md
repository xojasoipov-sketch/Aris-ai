# ADR-0002 — Security Model

- **Status:** Qabul qilindi (2026-08-11)
- **Qaror qabul qildi:** Loyiha egasi
- **Bog'liq:** `docs/04-CONSTRAINTS.md`, ADR-0001

## Kontekst

ZET avtonom harakatlar bajaradi — fayl o'qish/yozish, shell buyruqlar,
API chaqiruvlar. Xavfsizlik modeli xatoni erta aniqlashi va zarar kamaytirilishi kerak.
Fail-closed prinsipi: shubha bo'lsa — rad etiladi.

## Qaror

### Permission darajalari (V-31)

| Daraja | Avtomatik? | Misollar |
|---|---|---|
| READ | Ha | Fayl o'qish, API GET |
| WRITE | Sozlanadigan (default: ha) | Fayl yozish, nota qo'shish |
| EXECUTE | **Har doim tasdiq** | Shell, DB execute |
| ADMIN | **Har doim tasdiq** | Config o'zgartirish, sistem buyruqlar |

### Trust darajalari (A-05)

| Daraja | Ta'rifi |
|---|---|
| OWNER | Eganing to'g'ridan-to'g'ri buyrug'i |
| SYSTEM | Jadval bo'yicha ishlaydigan vazifalar |
| UNTRUSTED | Tashqi manba (email, webhook) |

UNTRUSTED kontekstdan WRITE va undan yuqori — **har doim tasdiq**.

### KillSwitch (V-33)

Global emergency stop — yoqilganda barcha run'lar bir zumda CANCELLED.
Faqat eganing aniq buyrug'i bilan qaytariladi (`z killswitch disengage`).

### Yuqori xavfli toollar (V-32)

`shell.exec`, `file.delete`, `db.execute`, `system.shutdown`, `config.modify`,
`network.request` — har doim tasdiq, hatto WRITE bo'lsa ham.

## Oqibatlar

- Har bir tool o'z permission_level'ini e'lon qiladi
- Executor har bir qadamda permission tekshiradi
- ApprovalService TTL bilan tasdiqlarni boshqaradi (30 daqiqa)
- Audit trail — har bir amal qayd qilinadi
