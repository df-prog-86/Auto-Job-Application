"""
Edits a COPY of the master Word file in place so the layout stays exactly the
master's: fonts, spacing, headings, columns and sections are never touched.
Only two things can change: the order of bullets within a role's bullet list,
and (rarely) a bullet's wording. Plus house cleanup on the tailored copy only:
dashes become hyphens and trailing blank paragraphs are removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

_MARKER = re.compile(r"^\s*[•▪●◦*\-]\s+")
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@dataclass
class Bullet:
    id: int
    element: object
    text: str  # without any typed bullet marker
    prefix: str  # typed bullet marker, kept as-is when text is replaced


@dataclass
class Block:
    id: int
    context: str
    bullets: list[Bullet] = field(default_factory=list)


def _text(el) -> str:
    return Paragraph(el, None).text


def _is_bullet(el, text: str) -> bool:
    if not text.strip():
        return False
    ppr = el.find(qn("w:pPr"))
    if ppr is not None:
        if ppr.find(qn("w:numPr")) is not None:
            return True
        style = ppr.find(qn("w:pStyle"))
        if style is not None:
            name = (style.get(qn("w:val")) or "").lower()
            if "list" in name or "bullet" in name:
                return True
    return bool(_MARKER.match(text))


def find_blocks(doc) -> list[Block]:
    """Each run of consecutive bullet paragraphs (one role's bullets) is a block."""
    paragraphs = list(doc.element.body.iter(qn("w:p")))
    blocks: list[Block] = []
    next_bullet_id = 0
    i = 0
    while i < len(paragraphs):
        el = paragraphs[i]
        if not _is_bullet(el, _text(el)):
            i += 1
            continue
        parent = el.getparent()
        run: list = []
        j = i
        while j < len(paragraphs) and paragraphs[j].getparent() is parent and _is_bullet(
            paragraphs[j], _text(paragraphs[j])
        ):
            run.append(paragraphs[j])
            j += 1

        context_lines: list[str] = []
        k = i - 1
        while k >= 0 and len(context_lines) < 2:
            t = _text(paragraphs[k]).strip()
            if t and not _is_bullet(paragraphs[k], t):
                context_lines.append(t)
            k -= 1

        block = Block(id=len(blocks), context=" | ".join(reversed(context_lines)))
        for p in run:
            raw = _text(p)
            m = _MARKER.match(raw)
            block.bullets.append(
                Bullet(id=next_bullet_id, element=p, text=raw[m.end():] if m else raw, prefix=m.group(0) if m else "")
            )
            next_bullet_id += 1
        blocks.append(block)
        i = j
    return blocks


def full_text(doc) -> str:
    return "\n".join(_text(p) for p in doc.element.body.iter(qn("w:p")))


def _replace_text(el, text: str) -> None:
    ts = list(el.iter(qn("w:t")))
    if not ts:
        return
    ts[0].text = text
    ts[0].set(_XML_SPACE, "preserve")
    for t in ts[1:]:
        t.text = ""


def apply_plan(blocks: list[Block], plan: dict[int, list[tuple[int, str]]]) -> int:
    """
    plan: block_id -> [(bullet_id, text), ...] in the new order. Must already be
    validated (each block's bullets appear exactly once). Returns how many
    bullets had their wording changed.
    """
    changed = 0
    for block in blocks:
        ordered = plan.get(block.id)
        if not ordered:
            continue
        by_id = {b.id: b for b in block.bullets}
        elements = [b.element for b in block.bullets]
        parent = elements[0].getparent()
        index = parent.index(elements[0])
        for el in elements:
            parent.remove(el)
        for offset, (bullet_id, new_text) in enumerate(ordered):
            bullet = by_id[bullet_id]
            parent.insert(index + offset, bullet.element)
            if new_text != bullet.text:
                _replace_text(bullet.element, bullet.prefix + new_text)
                changed += 1
    return changed


def clean_dashes(doc) -> None:
    """House rule: no em or en dashes in the body. Run-level, so formatting is untouched."""
    for t in doc.element.body.iter(qn("w:t")):
        if t.text and ("–" in t.text or "—" in t.text):
            t.text = t.text.replace("–", "-").replace("—", "-")


def strip_trailing_blank_paragraphs(doc) -> None:
    body = doc.element.body
    while True:
        children = [c for c in body if c.tag != qn("w:sectPr")]
        if not children:
            return
        last = children[-1]
        if (
            last.tag == qn("w:p")
            and not _text(last).strip()
            and last.find(".//" + qn("w:drawing")) is None
            and last.find(qn("w:pPr") + "/" + qn("w:sectPr")) is None
        ):
            body.remove(last)
        else:
            return
