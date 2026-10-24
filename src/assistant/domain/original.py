"""Offering the raw output of content-heavy tools after a summary.

Pages, files and logs are summarised first. The reply ends with a fixed question; a short
affirmative answer then shows the stored output verbatim, without involving the model.
"""

from __future__ import annotations

import re

OFFER_TEXT = "Would you like to see the original output?"

_YES = r"(?:yes|yeah|yep|yup|sure|ok|okay|y|please|go ahead|do it)"
_SHOW = r"(?:show|give|display|let me see|see)(?: me)?(?: it| that| the)?"
_WHAT = r"(?:the )?(?:original|raw|full)(?: output| content| text)?"
_AFFIRMATIVE = re.compile(
    rf"^(?:{_YES}(?:[ ,]+(?:{_YES}|{_SHOW}|{_WHAT}))*|{_SHOW}(?: {_WHAT})?|{_WHAT})[ .!]*$",
    re.IGNORECASE,
)


def is_affirmative(text: str) -> bool:
    """True for a short "yes, show it" style reply (anything else is a new request)."""
    return bool(_AFFIRMATIVE.match(text.strip()))


def original_reply(tool: str, text: str) -> str:
    """The separate message that carries the verbatim output."""
    return f"Original output of {tool}:\n\n{text}"
