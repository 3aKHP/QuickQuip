"""Explicit generic wire policy for tests of protocol behavior without client identity."""
from dataclasses import replace
from pathlib import Path

from quickquip.llm.client_fingerprints.catalog import FingerprintRuntime, parse_profile


_PROTOCOL_ONLY = parse_profile('''format_version = 1
id = "protocol-only"
label = "Protocol test fixture"
[headers]
accept-encoding = "gzip, deflate"
[protocols.openai]
[protocols.openai_responses]
[protocols.gemini]
''', "protocol-only")


def protocol_only_config(config):
    """Retain protocol/retry/media assertions under an explicit identity-free Profile."""
    if (config.protocol not in ("openai", "openai_responses", "gemini")
            or config.client_fingerprint != "default"):
        return config
    return replace(config, client_fingerprint="protocol-only",
                   fingerprint_runtime=FingerprintRuntime(_PROTOCOL_ONLY, "", Path(".")))
