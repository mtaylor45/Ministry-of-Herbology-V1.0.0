"""Invariants of the deployment stack file that are not obvious. The deployment.

Each of these is here because walking docs/deploy/README.md end to end on a
real swarm broke on it. They are cheap to check and expensive to rediscover.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STACK_FILE = REPO_ROOT / "infra" / "stack" / "docker-stack.yml"

#: ${NAME:?message}
REQUIRED_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):\?([^}]*)\}")


def test_required_variable_hints_contain_no_hyphen() -> None:
    """A hyphen in a ``:?`` message is silently destructive under swarm.

    ``docker stack deploy`` reads the hyphen as the ``-`` default-value
    operator and substitutes the text following it. Measured on Docker 29.3.1:

        image: ${MOH_REGISTRY:?... registry.example.net/ministry-of-herbology}

    with MOH_REGISTRY correctly set deploys ``of-herbology/moh-api``, and says
    nothing at all. Every node then reports "No such image", which points
    nowhere near the cause. ``docker compose config`` renders the same file
    correctly, so a preview does not catch it either.

    The readable guidance lives in ``make preflight``, which has no such
    parser. These messages stay terse.
    """
    offenders = [
        (name, message)
        for name, message in REQUIRED_VAR.findall(STACK_FILE.read_text())
        if "-" in message
    ]
    assert not offenders, (
        "A ${VAR:?message} hint contains a hyphen, which docker stack deploy "
        "silently treats as a default value: "
        + "; ".join(f"{name} -> {message!r}" for name, message in offenders)
    )


def test_every_required_variable_is_actually_required() -> None:
    """The four an operator must supply never acquire a default.

    everything an operator must supply is a parameter with no
    usable default. A ``:-`` on any of these would turn a missing value into a
    working-looking deployment pointed at the wrong place.
    """
    text = STACK_FILE.read_text()
    for name in (
        "MOH_REGISTRY",
        "MOH_IMAGE_TAG",
        "MOH_PUBLIC_BASE_URL",
        "MOH_NWS_USER_AGENT",
    ):
        assert f"${{{name}:?" in text, f"{name} should be required with :?"
        assert f"${{{name}:-" not in text, f"{name} must not have a default"
        assert f"${{{name}}}" not in text, f"{name} must not be used unguarded"


def test_no_credential_shaped_default_anywhere() -> None:
    """No variable in the stack file defaults to something usable as a secret.

    Cheap guard against the failure the design names: a working value shipped in
    the repository becomes a credential shared by every installation.
    """
    defaults = re.findall(
        r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\}", STACK_FILE.read_text()
    )
    for name, value in defaults:
        # A secret's swarm *name* (``MOH_DB_PASSWORD_SECRET`` defaulting to
        # ``moh_db_password``) is the name of an object the operator creates,
        # not a value; it is how a rotation survives a redeploy. Exempt that
        # shape exactly, and nothing else.
        stem = name.removeprefix("MOH_").removesuffix("_SECRET").lower()
        if re.fullmatch(r"MOH_[A-Z_]+_SECRET", name) and value == f"moh_{stem}":
            continue
        lowered = name.lower()
        assert not any(
            word in lowered for word in ("password", "token", "secret", "key")
        ), f"{name} has a default value ({value!r}); credentials are swarm secrets"


def test_secrets_are_external() -> None:
    """Nothing in the repository supplies a secret's content.

    An inline `file:` under `secrets:` would mean a credential lives in the
    tree. Every secret is created by the operator and referenced by name.
    """
    text = STACK_FILE.read_text()
    secrets_block = text.split("\nsecrets:\n", 1)[1]
    assert "file:" not in secrets_block, "a stack secret must never come from a file"
    assert secrets_block.count("external: true") == 6


def test_every_service_that_reads_the_api_names_it() -> None:
    """``MOH_API_URL`` is written in both stacks, on every service that reads it.

    The API's own process reads it too: the hub's routes it serves (the
    Lunette) fetch the round from it. The API service left it to a
    default in the hub's settings, so the one address the deployment uses
    for itself was half in the stack and half in code (the hub's change, escalation 6).
    F drops that default once this holds, and then an unset value is a failure
    rather than a guess.
    """
    import yaml

    dev = REPO_ROOT / "infra" / "compose" / "docker-compose.dev.yml"
    for path, services in (
        (STACK_FILE, ("api", "web", "worker-hub")),
        (dev, ("api", "web", "worker-hub")),
    ):
        stack = yaml.safe_load(path.read_text())
        for name in services:
            env = stack["services"][name]["environment"]
            assert (
                env.get("MOH_API_URL") == "http://api:8000"
            ), f"{path.name}: {name} does not set MOH_API_URL to the API service"


def test_every_secret_can_be_renamed_without_moving_its_path() -> None:
    """A rotation is a new swarm name behind the same key (guide §12).

    The key is what services list, so the path in every container stays
    ``/run/secrets/<key>``; ``name`` is the swarm object, from ``.env.deploy``.
    """
    import yaml

    secrets = yaml.safe_load(STACK_FILE.read_text())["secrets"]
    assert len(secrets) == 6
    for key, spec in secrets.items():
        variable = f"MOH_{key.removeprefix('moh_').upper()}_SECRET"
        assert spec == {"external": True, "name": f"${{{variable}:-{key}}}"}, key
