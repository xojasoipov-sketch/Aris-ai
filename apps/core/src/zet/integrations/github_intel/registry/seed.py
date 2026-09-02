"""Spec'da so'ralgan 9 ta repo (jumladan public-apis, allaqachon
`integrations/public_apis/`da chuqur integratsiya qilingan) — QO'LDA
yozilgan seed.

MUHIM: bu ro'yxat public-apis'ning 1584-yozuvli avtomatik parse
qilingan katalogidan TUBDAN farq qiladi — bu yerda HAR BIR yozuv ushbu
audit sessiyasida (JB-19) HAQIQATAN ko'rib chiqilgan (WebFetch orqali
litsenziya/tavsif/yulduz soni tekshirilgan — `docs/audits/
GITHUB_TOP_REPOS_FINAL_AUDIT.md`ga qarang), taxmin qilinmagan.

`code_executable=True` FAQAT public-apis'da — chunki FAQAT o'sha
repo'dan HAQIQIY, ijro etiladigan kod (`integrations/public_apis/
adapters/`) qurilgan. Qolgan 8 tasi — BILIM manbalari, kod hech qachon
ishga tushirilmaydi (spec Bo'lim 4 qat'iy qoidasi).
"""

from __future__ import annotations

from zet.integrations.github_intel.registry.models import (
    IntegrationAction,
    KnowledgeSource,
    SourceCategory,
    SourceType,
    TrustLevel,
    source_id,
)


def _source(
    *,
    repository: str,
    name: str,
    description: str,
    category: SourceCategory,
    license: str,
    trust_level: TrustLevel,
    capabilities: tuple[str, ...],
    action: IntegrationAction,
    notes: str,
    code_executable: bool = False,
) -> KnowledgeSource:
    return KnowledgeSource(
        id=source_id(repository),
        repository=repository,
        name=name,
        description=description,
        category=category,
        license=license,
        source_type=SourceType.GITHUB_REPOSITORY,
        trust_level=trust_level,
        capabilities=capabilities,
        documentation_url=f"https://github.com/{repository}",
        integration_action=action,
        notes=notes,
        code_executable=code_executable,
    )


def builtin_sources() -> list[KnowledgeSource]:
    """JB-19 auditida ko'rib chiqilgan spec'ning 9 ta repo'si."""
    return [
        _source(
            repository="codecrafters-io/build-your-own-x",
            name="Build Your Own X",
            description=(
                "'Recreate your favorite technology from scratch' — "
                "ma'lumotlar bazasi/tarmoq/kompilyator/tarjimon/taqsimlangan "
                "tizim qo'llanmalari to'plami."
            ),
            category=SourceCategory.ENGINEERING_REFERENCE,
            license="CC0-1.0",
            trust_level=TrustLevel.EXTERNAL_SOURCE,
            capabilities=("networking", "databases", "compilers", "distributed_systems"),
            action=IntegrationAction.REFERENCE_ONLY,
            notes=(
                "Ta'lim loyihalari to'plami — ishlab chiqarish kodiga "
                "ko'chirilmaydi. Research/Developer agent web.search/web.read "
                "orqali kerak bo'lganda so'rov vaqtida o'qiydi."
            ),
        ),
        _source(
            repository="public-apis/public-apis",
            name="Public APIs",
            description="'A collective list of free APIs' — 1500+ tashqi API ro'yxati.",
            category=SourceCategory.API_CATALOG,
            license="MIT",
            trust_level=TrustLevel.TRUSTED_REFERENCE,
            capabilities=("api_discovery", "weather", "currency", "geocoding", "ip_lookup"),
            action=IntegrationAction.INTEGRATE,
            notes=(
                "JB-18'da TO'LIQ integratsiya qilingan — "
                "`integrations/public_apis/` (katalog+discovery+3 haqiqiy "
                "adapter). Bu yerdagi yozuv FAQAT registrda ko'rinish uchun; "
                "haqiqiy sync/qidiruv `CatalogRepository`da (BOSHQA, "
                "ixtisoslashgan struktura — bu SourceRegistry uni "
                "TAKRORLAMAYDI). To'liq audit: "
                "docs/audits/PUBLIC_APIS_INTEGRATION_FINAL.md."
            ),
            code_executable=True,
        ),
        _source(
            repository="freeCodeCamp/freeCodeCamp",
            name="freeCodeCamp",
            description=(
                "Dasturlash/veb-dasturlash/CS o'quv dasturi va interaktiv "
                "mashqlar — notijorat, bepul."
            ),
            category=SourceCategory.LEARNING_RESOURCES,
            license="BSD-3-Clause",
            trust_level=TrustLevel.EXTERNAL_SOURCE,
            capabilities=("web_development", "algorithms", "databases", "apis"),
            action=IntegrationAction.REFERENCE_ONLY,
            notes=(
                "To'liq o'quv dasturi RUNTIME'ga IMPORT QILINMAYDI. "
                "Research Agent texnik savolga javob berishda tegishli "
                "ochiq material'ga havola berishi mumkin (web.read orqali), "
                "litsenziya (BSD-3-Clause) atribut talab qiladi — to'liq "
                "matn ko'chirilmaydi, faqat havola/qisqa iqtibos."
            ),
        ),
        _source(
            repository="EbookFoundation/free-programming-books",
            name="Free Programming Books",
            description="Ochiq litsenziyali dasturlash kitoblari/kurslari/hujjatlar katalogi.",
            category=SourceCategory.KNOWLEDGE_BASE,
            license="CC-BY-4.0",
            trust_level=TrustLevel.EXTERNAL_SOURCE,
            capabilities=("book_discovery", "documentation_discovery", "learning_resources"),
            action=IntegrationAction.REFERENCE_ONLY,
            notes=(
                "Kitoblarning O'ZI YUKLAB OLINMAYDI/qayta tarqatilmaydi — "
                "faqat metadata/havola (litsenziya CC-BY-4.0 atribut talab "
                "qiladi, lekin bu ham repo METADATASI uchun, kitoblarning "
                "o'ziga EMAS — ko'p kitob boshqa, ko'proq cheklovchi "
                "litsenziyaga ega bo'lishi mumkin, tekshirilmagan)."
            ),
        ),
        _source(
            repository="openclaw/openclaw",
            name="OpenClaw",
            description=(
                "'Your own personal AI assistant. Any OS. Any Platform.' — "
                "TypeScript'da yozilgan, ko'p-kanalli (30+ chat platforma), "
                "plagin arxitekturali AI agent gateway."
            ),
            category=SourceCategory.AI_AGENT,
            license="MIT",
            trust_level=TrustLevel.VERIFIED_SOURCE,
            capabilities=("agent", "tools", "memory", "automation", "permissions", "channels"),
            action=IntegrationAction.ADAPT,
            notes=(
                "Chuqur audit (klonlangan repo, haqiqiy SQL sxema, haqiqiy "
                "hujjatlar — docs/audits/OPENCLAW_JARVIS_COMPARISON.md'da "
                "to'liq): 15 sohaning barchasi ko'rib chiqilgan. Xulosa: "
                "kod NUSXALANMAYDI (litsenziya mos bo'lsa ham — spec "
                "Bo'lim 4 qat'iy qoidasi), lekin bir nechta ANIQ arxitektura "
                "naqshi ZET'ning O'Z kodiga moslashtirilishi mumkin "
                "(masalan xotira provenance-first yozish siyosati, "
                "'stricter of two configs' xavfsizlik naqshi). ADAPT — "
                "REFERENCE_ONLY emas, chunki kamida bitta naqsh HAQIQATAN "
                "ZET kodiga moslashtirish uchun tavsiya etiladi (audit "
                "hujjatiga qarang)."
            ),
        ),
        _source(
            repository="nilbuild/developer-roadmap",
            name="Developer Roadmap (roadmap.sh)",
            description=(
                "roadmap.sh saytini quvvatlaydigan interaktiv o'rganish "
                "yo'l xaritalari (backend/frontend/DevOps/AI/xavfsizlik va h.k.)."
            ),
            category=SourceCategory.LEARNING_RESOURCES,
            license="CC-BY-NC-ND-3.0 (+ qo'shimcha cheklovlar)",
            trust_level=TrustLevel.EXTERNAL_SOURCE,
            capabilities=("learning_path", "technology_roadmap"),
            action=IntegrationAction.REFERENCE_ONLY,
            notes=(
                "MUHIM litsenziya topilmasi (WebFetch bilan tasdiqlangan, "
                "JB-19): NoDerivatives+NonCommercial — mazmunni ko'chirish/"
                "qayta ishlash TAQIQLANGAN, faqat repo/sayt'ga HAVOLA berish "
                "mumkin. Shuning uchun bu manba QAT'IY REFERENCE_ONLY — "
                "hech qanday matn ko'chirilmaydi, faqat 'bu mavzu bo'yicha "
                "roadmap.sh'da yo'l xaritasi bor' deb havola beriladi. "
                "Ilgari `kamranahmedse/developer-roadmap` nomi bilan mashhur "
                "bo'lgan, `nilbuild` tashkilotiga o'tgan (sana noma'lum, "
                "audit vaqtida shunday topildi)."
            ),
        ),
        _source(
            repository="donnemartin/system-design-primer",
            name="System Design Primer",
            description="Kengaytiriluvchan tizimlar arxitekturasi bo'yicha o'quv material to'plami.",
            category=SourceCategory.SYSTEM_DESIGN,
            license="CC-BY-4.0",
            trust_level=TrustLevel.VERIFIED_SOURCE,
            capabilities=("scalability", "caching", "queues", "distributed_systems"),
            action=IntegrationAction.IMPROVE,
            notes=(
                "Chuqur audit docs/audits/SYSTEM_DESIGN_JARVIS_REVIEW.md'da — "
                "JARVIS arxitekturasiga bevosita ta'sir qilishi mumkin bo'lgan "
                "yagona P0 'bilim' manbai (kod emas, lekin ARXITEKTURA "
                "qarorlariga ta'sir qiladi, shuning uchun VERIFIED_SOURCE, "
                "oddiy EXTERNAL_SOURCE emas)."
            ),
        ),
        _source(
            repository="jwasham/coding-interview-university",
            name="Coding Interview University",
            description="CS asoslari/algoritmlar/tizim dizayni bo'yicha ko'p oylik o'quv reja.",
            category=SourceCategory.ALGORITHMS_CS,
            license="CC-BY-SA-4.0",
            trust_level=TrustLevel.EXTERNAL_SOURCE,
            capabilities=("algorithms", "data_structures", "complexity", "system_design"),
            action=IntegrationAction.REFERENCE_ONLY,
            notes=(
                "Developer Agent'ning algoritm tushuntirish/murakkablik "
                "tahlili so'rovlarida FONDA bilim sifatida foydali — "
                "litsenziya (CC-BY-SA-4.0) 'share-alike' talab qiladi, "
                "to'g'ridan-to'g'ri ko'chirish emas, havola/qisqa xulosa."
            ),
        ),
        _source(
            repository="practical-tutorials/project-based-learning",
            name="Project Based Learning",
            description="Dasturlash tillari bo'yicha loyiha-asosidagi qo'llanmalar ro'yxati.",
            category=SourceCategory.LEARNING_RESOURCES,
            license="MIT",
            trust_level=TrustLevel.EXTERNAL_SOURCE,
            capabilities=("project_discovery", "reference_implementation"),
            action=IntegrationAction.REFERENCE_ONLY,
            notes=(
                "'Shunga o'xshash loyiha top' so'roviga javob — FAQAT "
                "havola/tavsif qaytariladi. Hech qanday loyiha AVTOMATIK "
                "klonlanmaydi yoki ijro etilmaydi (spec Bo'lim: 'treat all "
                "external repositories as untrusted code')."
            ),
        ),
    ]


__all__ = ["builtin_sources"]
