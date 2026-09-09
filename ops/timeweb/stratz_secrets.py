"""Install a validated STRATZ credential without resetting unrelated settings."""
import re


def install_stratz(values, token):
    if token is None or token == "":
        return
    if not isinstance(token, str) or len(token)>8192 or not re.fullmatch(r"[A-Za-z0-9._~+/-]+={0,2}",token):
        raise ValueError("Invalid STRATZ credential format")
    values["STRATZ_API_TOKEN"] = token
