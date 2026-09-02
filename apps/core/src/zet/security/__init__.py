"""ZET xavfsizlik moduli — Bo'lim 1, 7, 11.

Komponentlar:
    - PermissionPolicy: ruxsat siyosati (V-31, V-32)
    - ApprovalService: tasdiq darvozasi (V-32)
    - KillSwitchState: favqulodda to'xtash (V-33)
    - InjectionScanner: injection himoyasi (A-05, Bo'lim 7)
    - RateLimiter: so'rov chastotasi cheklash (Bo'lim 11)
    - SecretManager: maxfiy kalitlar boshqaruvi (Bo'lim 11, deprekatsiyalangan)

NEGA in-memory `AuditLog` yo'q. Ilgari `zet.security.audit.AuditLog`
in-memory sifatida re-export qilinardi, lekin haqiqiy audit yozuvlari
`zet.security.audit_writer.write_audit()` orqali DB'ga (append-only
`AuditLog` jadvali) yoziladi. Ikkita alohida audit sxemasini saqlash
sinxronsizlikka olib kelardi — in-memory versiya olib tashlandi.

Bog'liq qarorlar:
    V-31 — ruxsat darajalari
    V-32 — majburiy tasdiq
    V-33 — xavfsizlik
    A-05 — trust level chegaralari
    Bo'lim 11 — xavfsizlik + testlash
"""

from zet.security.injection import InjectionType, ScanResult, is_safe, scan_text
from zet.security.killswitch import KillSwitchEngagedError, KillSwitchState
from zet.security.permissions import PermissionDecision, PermissionPolicy
from zet.security.ratelimit import RateLimiter, RateLimitResult, RateLimitTier
from zet.security.risk import TOOL_RISK_LEVELS, RiskLevel, risk_for
from zet.security.secrets import SecretManager, SecretMetadata, SecretStatus

__all__ = [
    "TOOL_RISK_LEVELS",
    "InjectionType",
    "KillSwitchEngagedError",
    "KillSwitchState",
    "PermissionDecision",
    "PermissionPolicy",
    "RateLimitResult",
    "RateLimitTier",
    "RateLimiter",
    "RiskLevel",
    "ScanResult",
    "SecretManager",
    "SecretMetadata",
    "SecretStatus",
    "is_safe",
    "risk_for",
    "scan_text",
]
