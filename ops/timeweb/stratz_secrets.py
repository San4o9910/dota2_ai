"""Install a validated STRATZ credential without resetting unrelated settings."""
import re


def install_stratz(values, token):
    if token is None or token == "":
        return
    if not isinstance(token, str) or len(token)>8192 or not re.fullmatch(r"[A-Za-z0-9._~+/-]+={0,2}",token):
        raise ValueError("Invalid STRATZ credential format")
    values["STRATZ_API_TOKEN"] = token


def build_stats_source(value=None):
    """A configured credential alone never opts a release into provider access."""
    source = "authored" if value is None else value
    if source not in ("authored", "stratz"):
        raise ValueError("Invalid build statistics source")
    return source


def build_stats_payload(environment):
    """Only an explicitly enabled provider credential crosses SSH stdin."""
    source = build_stats_source(environment.get("NARMA_BUILD_STATS_SOURCE"))
    payload = {"build_stats_source": source}
    if source == "stratz":
        token = environment.get("STRATZ_API_TOKEN")
        if not token:
            raise ValueError("Enabled STRATZ source requires a credential")
        validated = {}
        install_stratz(validated, token)
        payload["stratz_token"] = validated["STRATZ_API_TOKEN"]
    return payload


def install_build_statistics(values, incoming):
    """Select the release mode while retaining unrelated and dormant secrets."""
    source = build_stats_source(incoming.get("build_stats_source"))
    changes = {"NARMA_BUILD_STATS_SOURCE": source,
               "NARMA_STRATZ_REFRESH_ENABLED": "1" if source == "stratz" else "0"}
    if source == "stratz":
        token = incoming.get("stratz_token")
        if not token:
            raise ValueError("Enabled STRATZ source requires a credential")
        install_stratz(changes, token)
    values.update(changes)
