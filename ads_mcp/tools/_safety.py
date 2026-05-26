"""Safety helpers shared by every write/mutate tool.

All write tools MUST:
  1. Call check_read_only() first and short-circuit if it returns a dict.
  2. Wrap any field that accepts micro-amount budgets with check_max_budget().
  3. Wrap GoogleAdsException via handle_googleads_exception() for consistent
     error shape: {"success": False, "errors": [{"message", "code"}, ...]}.

Env vars consumed:
  GOOGLE_ADS_READ_ONLY        — when truthy, blocks every write tool.
  MAX_DAILY_BUDGET_MICROS     — integer cap; budgets above it are rejected.
"""

from __future__ import annotations

import os
from typing import Optional


_TRUTHY = {"1", "true", "yes", "y", "on"}


def _is_truthy(val: Optional[str]) -> bool:
    return (val or "").strip().lower() in _TRUTHY


def check_read_only() -> Optional[dict]:
    """Returns an error dict if GOOGLE_ADS_READ_ONLY is set truthy, else None."""
    if _is_truthy(os.environ.get("GOOGLE_ADS_READ_ONLY")):
        return {
            "success": False,
            "error": (
                "Write tools are disabled: GOOGLE_ADS_READ_ONLY env var is set."
            ),
        }
    return None


def check_max_budget(amount_micros: int) -> Optional[dict]:
    """Returns an error dict if amount exceeds MAX_DAILY_BUDGET_MICROS, else None.

    No enforcement when the env var is unset or non-integer.
    """
    raw = os.environ.get("MAX_DAILY_BUDGET_MICROS")
    if not raw:
        return None
    try:
        cap = int(raw)
    except ValueError:
        return None
    if amount_micros > cap:
        return {
            "success": False,
            "error": (
                f"Budget {amount_micros} micros exceeds "
                f"MAX_DAILY_BUDGET_MICROS={cap}."
            ),
        }
    return None


def handle_googleads_exception(ex) -> dict:
    """Flattens a GoogleAdsException into the standard write-tool error dict.

    Includes the Google-reported `field_path` (joined from
    `error.location.field_path_elements`) so callers can see *which* field
    triggered errors like REQUIRED or INVALID_VALUE without guessing. Also
    surfaces a `hint` for known account-level restrictions.
    """
    errors = []
    saw_mutate_not_allowed = False

    for error in ex.failure.errors:
        entry = {
            "message": error.message,
            "code": str(error.error_code),
        }
        try:
            fpes = error.location.field_path_elements
            if fpes:
                parts = []
                for fpe in fpes:
                    name = fpe.field_name
                    # `index` is only meaningful for repeated fields.
                    idx = getattr(fpe, "index", None)
                    if idx is not None and idx > 0:
                        parts.append(f"{name}[{idx}]")
                    else:
                        parts.append(name)
                entry["field_path"] = ".".join(parts)
        except Exception:
            pass

        # Surface known account-level restrictions explicitly. The Google Ads
        # API returns `MUTATE_NOT_ALLOWED` (often paired with `UNKNOWN`) when
        # the account isn't enabled for a given mutate — e.g. Video campaign
        # creation requires a linked YouTube channel + policy approval.
        if "MUTATE_NOT_ALLOWED" in entry["code"]:
            saw_mutate_not_allowed = True

        errors.append(entry)

    out = {"success": False, "errors": errors}
    if saw_mutate_not_allowed:
        out["hint"] = (
            "MUTATE_NOT_ALLOWED is typically an account-level restriction, "
            "not a tool bug. Common causes: account not enabled for this "
            "campaign type (e.g. Video requires a linked YouTube channel and "
            "policy approval); manager-account mutating a child without "
            "permission; closed/cancelled account; missing billing setup."
        )
    return out
