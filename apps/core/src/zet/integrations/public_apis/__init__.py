"""public-apis katalog integratsiyasi (JB-18).

`public-apis/public-apis` GitHub repozitoriysini QIDIRUV/KATALOG
manbai sifatida ishlatadi — hech qanday yozuv AVTOMATIK ravishda
ishlaydigan `Tool`ga aylanmaydi (Bo'lim 22). Qatlamlar:

    catalog/     — ingestion: manba → xom → normallashgan model
    discovery/   — qidiruv/reyting/capability xaritalash
    credentials/ — dinamik provayder kalitlari (mavjud
                   `zet.security.secrets.SecretManager` ustida)
    health/      — sog'liq kuzatuvi (muvaffaqiyat/kechikish)
    adapters/    — HAQIQIY, qo'lda yozilgan `Tool` subklasslar — FAQAT
                   shu qatlamdagi kod haqiqatan ijro etiladi

To'liq audit: `docs/audits/PUBLIC_APIS_INTEGRATION_AUDIT.md`.
"""

from __future__ import annotations
