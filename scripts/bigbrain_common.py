"""Back-compat shim: the old shared-helpers module, now re-exported.

This file used to hold the whole implementation -- configuration loading, the
HTTP client, JSON extraction and the advisor schema. All of that now lives in
the ``bigbrain`` package, split by concern:

    bigbrain.config     configuration, constants, errors, secrets
    bigbrain.client     the Messages API client and response parsing
    bigbrain.schema     JSON extraction, validation, normalisation
    bigbrain.io         file helpers and context loading

Nothing new should import from here. It exists so that a script or a
third-party caller that did ``from bigbrain_common import load_config`` keeps
working after the restructure, and so the change is a refactor rather than a
break. Prefer importing from ``bigbrain`` directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bigbrain.client import (  # noqa: F401,E402
    HttpResponse,
    extract_text,
    post_messages,
)
from bigbrain.config import (  # noqa: F401,E402
    ADVISOR_STATUSES,
    ADVISOR_VERDICTS,
    ANTHROPIC_VERSION,
    CONFIG_ENV_FILE,
    DEFAULT_MAX_CONTEXT_CHARS,
    DEFAULT_MAX_ROUNDS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    EXIT_AUTH,
    EXIT_BAD_JSON,
    EXIT_BLOCKED,
    EXIT_CONFIG,
    EXIT_HTTP,
    EXIT_MAX_ROUNDS,
    EXIT_MODEL,
    EXIT_NETWORK,
    EXIT_OK,
    AdvisorParseError,
    BigbrainError,
    config_problems,
    default_system_prompt_path,
    load_config,
    load_system_prompt,
    mask_secret,
    parse_env_file,
    skill_root,
    validate_config,
)
from bigbrain.io import (  # noqa: F401,E402
    eprint,
    read_context_files,
    read_text_file,
    write_json,
)
from bigbrain.schema import (  # noqa: F401,E402
    extract_json_object,
    normalize_advisor,
    parse_advisor_reply,
)

# The pre-restructure name for the env-file location.
CONFIG_FILE = CONFIG_ENV_FILE

__all__ = [
    "ADVISOR_STATUSES",
    "ADVISOR_VERDICTS",
    "ANTHROPIC_VERSION",
    "AdvisorParseError",
    "CONFIG_ENV_FILE",
    "CONFIG_FILE",
    "DEFAULT_MAX_CONTEXT_CHARS",
    "DEFAULT_MAX_ROUNDS",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT",
    "BigbrainError",
    "EXIT_AUTH",
    "EXIT_BAD_JSON",
    "EXIT_BLOCKED",
    "EXIT_CONFIG",
    "EXIT_HTTP",
    "EXIT_MAX_ROUNDS",
    "EXIT_MODEL",
    "EXIT_NETWORK",
    "EXIT_OK",
    "HttpResponse",
    "config_problems",
    "default_system_prompt_path",
    "eprint",
    "extract_json_object",
    "extract_text",
    "load_config",
    "load_system_prompt",
    "mask_secret",
    "normalize_advisor",
    "parse_advisor_reply",
    "parse_env_file",
    "post_messages",
    "read_context_files",
    "read_text_file",
    "skill_root",
    "validate_config",
    "write_json",
]
