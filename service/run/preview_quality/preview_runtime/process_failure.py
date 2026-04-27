from __future__ import annotations

import re


def summarize_process_failure(*, stderr: str, stdout: str) -> tuple[str, str]:
    combined = (stderr or stdout or "").strip()
    if not combined:
        return "preview compile failed", ""
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    lines = [
        line
        for line in lines
        if "[UNDICI-EHPA] Warning: EnvHttpProxyAgent is experimental" not in line
        and "Use `node --trace-warnings" not in line
    ]
    if not lines:
        return "preview compile failed", ""
    filtered = [
        line for line in lines if not re.fullmatch(r"Node\.js v\d+(?:\.\d+){1,3}", line)
    ]
    focus = filtered or lines
    reason = focus[0][:240] if focus else "preview compile failed"
    details = " | ".join(focus[:5])[:1200]
    return reason, details
