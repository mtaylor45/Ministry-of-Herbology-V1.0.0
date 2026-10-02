"""The original-theme rule, in one place: a themed title never ships without its plain twin.

``task.title`` and ``task.plain_title`` are both ``NOT NULL`` in
``contracts/schema/001_init.sql``. That is not a style note — the plain title is
what a screen reader announces, what a calendar event carries into Google, and
what somebody reads at seven in the morning without wanting to decode it. Every
task in this package is built through :func:`titles_for`, so there is no path
that can produce one without the other.

The earlier mock got the pairing and the article rule right and both are covered by
``tests/contract/test_mock_stack.py``; they are kept here verbatim.
"""

from __future__ import annotations

from typing import Any

#: Themed title, then the plain equivalent. Keys are the ``task_type`` values
#: the frozen schema's CHECK constraint allows.
TITLES: dict[str, tuple[str, str]] = {
    "water": ("Tend {name}", "Water {name}"),
    "fertilize": ("Feed {name}", "Fertilize {name}"),
    "mist": ("Mist {name}", "Mist {name}"),
    "inspect": ("Inspect {name}", "Check {name} for pests"),
    "bring_indoors": ("Shelter {name} from the frost", "Bring {name} indoors"),
    "return_outdoors": (
        "Return {name} to the grounds",
        "Put {name} back outside",
    ),
    "cover": ("Shroud {name}", "Cover {name} before frost"),
    "prune": ("Prune {name}", "Prune {name}"),
    "repot": ("Rehouse {name}", "Repot {name}"),
    "rotate": ("Turn {name}", "Rotate {name}"),
}

#: The plain *action*, for the one line a calendar client shows at a glance.
#: The plan's own example is "Tend the Monstera — water 500 ml": the themed
#: phrase names the plant, the plain half says what to do, and repeating the
#: plant's name twice in a calendar row helps nobody.
ACTIONS: dict[str, str] = {
    "water": "water",
    "fertilize": "feed",
    "mist": "mist",
    "inspect": "check for pests",
    "bring_indoors": "bring indoors",
    "return_outdoors": "put back outside",
    "cover": "cover before frost",
    "prune": "prune",
    "repot": "repot",
    "rotate": "rotate",
}

#: Every task type the schema allows. Generating one outside this set would
#: fail the CHECK constraint at write time in live mode and pass silently in
#: mock mode, which is the worst of both.
TASK_TYPES: tuple[str, ...] = tuple(TITLES)


def subject(display_name: str, *, has_nickname: bool) -> str:
    """A nickname is already a name and takes no article; a species name does.

    "Tend Sour Bertram" and "Tend the snake plant", never "Tend the Sour
    Bertram". Asserted on the wire by
    ``tests/contract/test_mock_stack.py::test_a_nickname_is_not_given_an_article``.
    """
    return display_name if has_nickname else f"the {display_name.lower()}"


def titles_for(
    task_type: str,
    display_name: str,
    *,
    has_nickname: bool,
    amount_ml: int | None = None,
) -> tuple[str, str]:
    """The themed title and the plain one, always as a pair.

    An unknown task type falls back to the generic pairing rather than raising:
    a care rule carrying a type this table has not learned yet should still
    produce a legible task, and ``TASK_TYPES`` is what stops one being written.
    """
    themed_template, plain_template = TITLES.get(
        task_type, ("Tend {name}", "Tend {name}")
    )
    name = subject(display_name, has_nickname=has_nickname)
    themed = themed_template.format(name=name)
    plain = plain_template.format(name=name)
    if amount_ml:
        # The contract's own example: "Water the Monstera — 500 ml". The amount
        # goes on the plain title only; the themed one stays a phrase.
        plain = f"{plain} — {amount_ml} ml"
    return themed, plain


def plain_action(task_type: str, amount_ml: int | None = None) -> str:
    """ "water 500 ml" — the plain half of a calendar summary."""
    action = ACTIONS.get(task_type, "tend")
    return f"{action} {amount_ml} ml" if amount_ml else action


def display_subject(specimen: dict[str, Any], display_name: str) -> str:
    """``subject`` for a raw specimen row, which is what the stores hold."""
    return subject(display_name, has_nickname=bool(specimen.get("nickname")))
