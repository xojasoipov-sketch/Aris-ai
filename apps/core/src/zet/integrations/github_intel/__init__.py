"""GitHub Intelligence Layer (JB-19) — bitta, birlashtirilgan qatlam,
"top GitHub repositories" auditidan (docs/audits/
GITHUB_REPOSITORY_INTEGRATION_MATRIX.md) foydalanish uchun. To'qqizta
repo uchun to'qqizta ALOHIDA integratsiya QURILMADI (spec'ning o'zi
buni ochiq taqiqlaydi — "CRITICAL ARCHITECTURE RULE").

Qatlamlar:

    registry/   — `KnowledgeSource` modeli, ishonch klassifikatsiyasi
                  (TRUSTED_REFERENCE/VERIFIED_SOURCE/EXTERNAL_SOURCE/
                  UNTRUSTED_CODE) va 9 ta ko'rib chiqilgan repo'ning
                  qo'lda tuzilgan (LLM emas) seed ro'yxati.
    analyzer/   — `analyze_repository()` — HAQIQIY GitHub REST API
                  chaqiruvi orqali OLINADIGAN faktlar (til, litsenziya,
                  yulduz, README) qaytaradi. Arxitektura/naqsh XULOSASINI
                  chiqarmaydi — bu LLM (Brain/Research agent)ning ishi,
                  tool esa faqat TEKSHIRILADIGAN faktlarni beradi (Bo'lim
                  11 falsafasi: "no fabrication", `public_apis` bilan bir
                  xil).

MUHIM QOIDA (spec Bo'lim 4 — "Code vs Knowledge Separation"): default
holatda HAR QANDAY tashqi repo kodi ISHGA TUSHIRILMAYDI
(`KnowledgeSource.code_executable=False`). Faqat ushbu repo ICHIDA
qo'lda yozilgan, ko'rib chiqilgan kod (masalan `integrations/
public_apis/adapters/`) haqiqatan ijro etiladi.

To'liq audit: `docs/audits/GITHUB_TOP_REPOS_FINAL_AUDIT.md`.
"""

from __future__ import annotations
