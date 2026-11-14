"""Translate bounded provenance diagnostics only at the UI boundary.

The verifier stays standalone standard library for build/appcast tools. Its
string-compatible detail carries no URL, response body or certificate text.
"""


def user_detail(detail, t):
    code = getattr(detail, "code", "")
    if not code:
        return str(detail)
    reasons = {
        "rate_limited": t("mac_update_verify_rate_limited"),
        "access_denied": t("mac_update_verify_access_denied"),
        "not_found": t("mac_update_verify_not_found"),
        "server": t("mac_update_verify_server"),
        "tls": t("mac_update_verify_tls"),
        "dns": t("mac_update_verify_dns"),
        "timeout": t("mac_update_verify_timeout"),
        "connection": t("mac_update_verify_connection"),
        "unexpected": t("mac_update_verify_unexpected"),
        "http_error": t("mac_update_verify_http_error"),
    }
    reason = reasons.get(code, reasons["unexpected"])
    if code in {"rate_limited", "server"} and getattr(detail, "retry_after", 0) > 0:
        reason += " " + t("mac_update_verify_wait").format(seconds=detail.retry_after)
    if getattr(detail, "stage", "") == "verification_file":
        return t("mac_update_verify_file").format(reason=reason)
    return t("mac_update_verify_tag").format(reason=reason)
