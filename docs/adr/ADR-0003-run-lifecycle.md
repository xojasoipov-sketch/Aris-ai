# ADR-0003 — Run Lifecycle

- **Status:** Qabul qilindi (2026-08-11)
- **Qaror qabul qildi:** Loyiha egasi
- **Bog'liq:** ADR-0001, ADR-0002

## Kontekst

Foydalanuvchi buyrug'idan natijagacha — bu "run". Har bir run aniq
holatlar bo'ylab o'tadi. Holat mashinasi dastur va foydalanuvchi uchun
birdek tushunarli bo'lishi kerak.

## Qaror

### Run holat mashinasi (A-01)

```
PENDING → PLANNING → AWAITING_APPROVAL → EXECUTING → VERIFYING → DONE
                                                                → FAILED
                                                                → CANCELLED
```

### Pipeline

```
USER → COMMAND → INTENT → PLAN → APPROVAL → EXECUTE → VERIFY → RESULT
```

| Bosqich | Modul | Kirish | Chiqish |
|---|---|---|---|
| Intent | `IntentRecognizer` | Command matn | Intent (tool_use) |
| Plan | `Planner` | Intent | Plan (qadamlar DAG) |
| Approval | `ApprovalService` | Plan | Tasdiqlangan qadamlar |
| Execute | `Executor` | Plan + approved | StepResult'lar |
| Verify | `Verifier` | StepResult | Verification |

### Chegaralar (A-07)

| Chegara | Qiymat |
|---|---|
| Run maks qadam | 20 |
| Run maks chuqurlik | 3 |
| Run timeout | 600s |
| Run budjet | $0.10 |

## Oqibatlar

- Har bir run noyob trace_id oladi
- Run holati DB'da saqlanadi
- Tasdiq kerak bo'lsa — run AWAITING_APPROVAL'da to'xtaydi
- KillSwitch yoqilsa — CANCELLED
- Budjet tugasa — FAILED
