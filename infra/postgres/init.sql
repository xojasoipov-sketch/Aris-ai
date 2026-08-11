-- ZET — Postgres boshlang'ich sozlamasi.
-- Faqat birinchi marta (bo'sh volume'da) ishga tushadi.

-- Bo'lim 2 (xotira) uchun semantik qidiruv
CREATE EXTENSION IF NOT EXISTS vector;

-- UUID generatsiyasi (gen_random_uuid pg13+ da o'rnatilgan, lekin aniqlik uchun)
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Matnli qidiruv uchun trigram (hybrid search: BM25 + vektor)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
