"""The HTML half of an email, built from the text half.

Every automated message this product sends is written as plain text first, and
that stays true: the text is what `Message.content` stores, what Fair Housing
screens, and what a client with no HTML rendering receives. This module turns
that same text into the second half, so the two can never say different things.

It exists because of a complaint from a real inbox on 2026-09-19. A reply from
the assistant ended like this:

    Don't want these emails? Unsubscribe here:
    https://www.denverhomestory.com/api/v1/public/unsubscribe/MTI3NQ.tS2yNp2og…

Plain text has no way to carry a link, so the compliant footer prints seventy
characters of token under a sentence, on a message that is otherwise trying to
sound like a person wrote it. The fix is not to shorten the footer — CAN-SPAM
wants it clear and conspicuous — but to send an HTML half where the link hides
behind its own words while the brokerage line and the postal address stay
visible text.

**Everything is escaped.** The body is model output on one lane and whatever a
realtor typed on another, and both are about to be rendered as a document. An
ampersand in a brokerage name is not an attack, it is Tuesday, and it must not
become markup either way.

**Links are recognised, not invented.** Only `http` and `https` become anchors.
A `javascript:` or `data:` URL is inert in plain text and clickable once
rendered, which is the whole reason this file is careful.
"""

from __future__ import annotations

import re
from html import escape

__all__ = ["document", "paragraphs"]

#: Bare URLs in the body — a virtual tour, the options page, a guide. Matched
#: after escaping, so an `&` inside a query string is already `&amp;`, which is
#: what belongs inside an `href` anyway. The trailing-punctuation class keeps a
#: sentence's full stop out of the link.
_URL = re.compile(r"(https?://[^\s<>\"']+?)(?=[.,;:!?)\]]*(?:\s|$))")


def _linkify(escaped: str) -> str:
    return _URL.sub(
        lambda m: f'<a href="{m.group(1)}" style="color:#7a1f3d;">{m.group(1)}</a>',
        escaped,
    )


def paragraphs(text: str) -> str:
    """Plain text as HTML paragraphs. Blank line splits, single newline breaks.

    The shape of a written message is information: a two-line question under a
    one-line greeting reads as a question, and the same words in one block read
    as a wall. Collapsing the newlines would throw that away.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    out: list[str] = []
    for block in blocks:
        body = _linkify(escape(block)).replace("\n", "<br>")
        out.append(f'<p style="margin:0 0 14px 0;">{body}</p>')
    return "".join(out)


def document(inner: str) -> str:
    """The whole HTML mail. Inline styles only, nothing external.

    Gmail strips `<style>` blocks and `@font-face`, so chasing the brand font
    would produce a brand font in the one client nobody reads mail in. A system
    serif is what actually arrives looking deliberate.
    """
    return (
        "<!doctype html><html><body "
        'style="margin:0;padding:24px;background:#ffffff;color:#1a1a1a;'
        "font-family:Georgia,'Times New Roman',serif;font-size:15px;"
        'line-height:1.55;">'
        f'<div style="max-width:560px;">{inner}</div>'
        "</body></html>"
    )
