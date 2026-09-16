#!/usr/bin/env python3
"""
backend/sanitizer.py - Security & Log Sanitization Subsystem for CC2 API.

Ensures that:
1. Passwords, private keys, authentication tokens, and credentials are never
   exposed in API responses or logs.
2. Terminal ANSI escape sequences are stripped for clean presentation.
3. System paths containing private user credentials or keys are masked.
"""

import re
from typing import Optional, List, Dict, Any


ANSI_ESCAPE_PATTERN = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

SECRET_PATTERNS = [
    # SSH Private Keys
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----", re.MULTILINE),
     "[REDACTED PRIVATE KEY]"),

    # SSH OpenSSH Private Keys
    (re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----[\s\S]*?-----END OPENSSH PRIVATE KEY-----", re.MULTILINE),
     "[REDACTED OPENSSH PRIVATE KEY]"),

    # SSH RSA / DSA Keys in single lines or public strings
    (re.compile(r"ssh-rsa\s+AAAA[0-9A-Za-z+/]+[=]{0,3}(\s+\S+)?"),
     "[REDACTED SSH KEY]"),

    # Passwords in command strings (e.g., sshpass -p 'xyz' or password=xyz)
    (re.compile(r"sshpass\s+-p\s+['\"][^'\"]+['\"]", re.IGNORECASE),
     "sshpass -p '********'"),
    (re.compile(r"sshpass\s+-p\s+\S+", re.IGNORECASE),
     "sshpass -p ********"),

    # Password assignment patterns in JSON or config
    (re.compile(r"([\"']?(?:ssh_password|password|pass|secret|api_key|token)[\"']?\s*[:=]\s*[\"'])[^\"'\n]+([\"'])", re.IGNORECASE),
     r"\1********\2"),

    # Authorization headers
    (re.compile(r"Authorization:\s*(?:Bearer|Basic)\s+\S+", re.IGNORECASE),
     "Authorization: Bearer ********"),

    # Sensitive environment assignments
    (re.compile(r"((?:KVM|VBOX|LXC)_(?:SSH_)?PASSWORD=)[^\s\n]+", re.IGNORECASE),
     r"\1********")
]


def sanitize_text(text: Optional[str]) -> str:
    """
    Sanitizes a string by stripping ANSI codes and masking all secret patterns.
    """
    if not text:
        return ""

    # 1. Strip ANSI escape codes
    clean = ANSI_ESCAPE_PATTERN.sub("", text)

    # 2. Apply secret redaction patterns
    for pattern, replacement in SECRET_PATTERNS:
        clean = pattern.sub(replacement, clean)

    return clean


def sanitize_dict_records(data: Any) -> Any:
    """
    Recursively masks sensitive dictionary keys in data payloads.
    """
    sensitive_keys = {
        "password", "ssh_password", "secret", "token",
        "api_key", "private_key", "credentials", "auth_token"
    }

    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if str(k).lower() in sensitive_keys or any(s in str(k).lower() for s in ["password", "secret"]):
                sanitized[k] = "********" if v else "(not configured)"
            elif isinstance(v, (dict, list)):
                sanitized[k] = sanitize_dict_records(v)
            elif isinstance(v, str):
                sanitized[k] = sanitize_text(v)
            else:
                sanitized[k] = v
        return sanitized
    elif isinstance(data, list):
        return [sanitize_dict_records(item) for item in data]
    return data
