# ADR-0004 — Tool System

- **Status:** Qabul qilindi (2026-08-11)
- **Qaror qabul qildi:** Loyiha egasi
- **Bog'liq:** ADR-0001, ADR-0002

## Kontekst

ZET LLM orqali toollar bilan ishlaydi. Tool — tashqi dunyo bilan o'zaro
ta'sir: fayl tizimi, shell, API, DB. Tool tizimi kengaytirilishi va
xavfsiz bo'lishi kerak.

## Qaror

### Tool ABC

```python
class Tool(ABC):
    name: str                    # noyob nom (namespace.action)
    description: str             # LLM uchun tavsif
    input_schema: dict           # JSON Schema
    permission_level: READ       # default
    idempotent: bool = True      # retry uchun
    timeout_seconds: float = 30

    async def execute(params, *, caller_permission, dry_run) -> ToolResult
    async def _execute(params) -> str  # subclass'lar shu ni implement qiladi
```

### ToolRegistry

- Allowlist prinsipi — faqat ro'yxatga olingan toollar
- JSON Schema validatsiya (jsonschema kutubxonasi)
- Permission tekshiruvi bajarish oldidan
- dry_run rejimi — haqiqiy ish bajarilmaydi

### Bo'lim 1 toollar

| Tool | Permission | Vazifa |
|---|---|---|
| `time.now` | READ | Joriy vaqt |
| `note.write` | WRITE | Nota yozish (path traversal himoyasi) |
| `shell.exec` | EXECUTE | Shell buyruq (default O'CHIRILGAN) |

### Xavfsizlik

- `note.write`: path traversal sanitizatsiyasi (`..'ni `_` bilan almashtirish)
- `shell.exec`: default O'CHIRILGAN, allowlist, xavfli belgilar rad etiladi
- JSON Schema validatsiya har bir chaqiruvda
- ToolPermissionDeniedError — ruxsat yetmasa
- ToolTimeoutError — timeout oshsa

## Oqibatlar

- Har bir yangi tool `Tool` ABC'dan meros oladi
- ToolRegistry'ga ro'yxatdan o'tkazilishi shart
- LLM `tool_use` orqali chaqiradi (function calling)
- Executor retry qiladi (faqat idempotent toollar)
