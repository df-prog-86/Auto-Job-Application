"""
Edits a COPY of the master Word file in place so the layout stays exactly the
master's: fonts, spacing, headings, columns and sections are never touched.
Only these things can change: the order of bullets within a role's bullet list,
a bullet's wording, the wording of a Summary/Profile paragraph, and the order of the
items in a Skills line. Plus house cleanup on the tailored copy only:
dashes become hyphens and trailing blank paragraphs are removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from docx.oxml.ns import qn
from lxml import etree
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


@dataclass
class TextPart:
    """A Summary paragraph or a Skills line that can be reworded or reordered in place."""

    id: int
    kind: str  # "summary" | "skills"
    element: object
    text: str  # the editable text (for skills: everything after the "Label:" prefix)
    split: int  # character offset where the editable text starts inside the paragraph
    label: str = ""  # skills only: the "Languages:" prefix, never edited
    items: list = field(default_factory=list)  # skills only
    seps: list = field(default_factory=list)  # skills only: the separators between items


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


# ---------------------------------------------------------------------------
# Summary and Skills sections
# ---------------------------------------------------------------------------

_SUMMARY_HEAD = re.compile(
    r"^((professional|executive|career|personal) )?(summary|profile|objective|overview)( statement| of qualifications)?$"
    r"|^summary of qualifications$|^about( me)?$"
)
_SKILLS_HEAD = re.compile(
    r"^((core|key|technical|professional|relevant|additional) )?(skills|competencies|expertise|proficiencies)( (and|&) \w+)?$"
    r"|^areas of expertise$|^skills (and|&) \w+$"
)
_ANY_HEAD = re.compile(
    r"^(professional |work |relevant |related )?(experience|employment|employment history|work history|history)$"
    r"|^education( (and|&) \w+)?$|^certifications?( (and|&) \w+)?$|^licenses?( (and|&) \w+)?$|^projects?$|^awards?( (and|&) \w+)?$"
    r"|^publications?$|^volunteer( experience| work)?$|^training$|^languages$|^interests$|^references$|^affiliations$|^achievements$"
)
_LABEL = re.compile(r"^([^:]{1,40}):\s*")
_SEPARATOR = re.compile(r"\s*[,;|\u2022\u00b7]\s*")
MAX_SECTION_PARAGRAPHS = 8
MIN_SUMMARY_CHARS = 60


def _norm_heading(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[:.\u2013\u2014-]+\s*$", "", text.strip().lower())).strip()


def _is_heading(el, text: str) -> bool:
    t = text.strip()
    if not t or _is_bullet(el, t):
        return False
    if _ANY_HEAD.match(_norm_heading(t)) or _SUMMARY_HEAD.match(_norm_heading(t)) or _SKILLS_HEAD.match(_norm_heading(t)):
        return True
    ppr = el.find(qn("w:pPr"))
    if ppr is not None:
        style = ppr.find(qn("w:pStyle"))
        if style is not None and (style.get(qn("w:val")) or "").lower().startswith("heading"):
            return True
    return len(t) <= 40 and t.isupper() and t.count(" ") <= 4


def _run_formats(el, from_offset: int) -> set[str]:
    """The distinct run formats of the text at or after from_offset (a straddling run counts)."""
    formats: set[str] = set()
    pos = 0
    for r in el.iter(qn("w:r")):
        run_text = "".join(t.text or "" for t in r.iter(qn("w:t")))
        if not run_text:
            continue
        end = pos + len(run_text)
        if end > from_offset:
            rpr = r.find(qn("w:rPr"))
            formats.add(etree.tostring(rpr).decode() if rpr is not None else "")
        pos = end
    return formats


def _split_items(tail: str) -> tuple[list[str], list[str]] | None:
    """Splits "a, b (x, y), c" at top-level separators only. None when it cannot be done safely."""
    items: list[str] = []
    seps: list[str] = []
    depth = 0
    start = 0
    i = 0
    while i < len(tail):
        ch = tail[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return None
        elif depth == 0 and _SEPARATOR.match(tail, i) and ch in ",;|\u2022\u00b7":
            m = _SEPARATOR.match(tail, i)
            items.append(tail[start:i].strip())
            seps.append(m.group(0))
            i = m.end()
            start = i
            continue
        i += 1
    if depth != 0:
        return None
    items.append(tail[start:].strip())
    if len(items) < 2 or any(not it for it in items):
        return None
    return items, seps


def find_text_parts(doc, first_id: int = 100) -> list[TextPart]:
    """Summary paragraphs and Skills lines that sit under a recognised heading and can be edited safely.
    Ids start at 100 so they can never be mistaken for a bullet or block id."""
    paragraphs = list(doc.element.body.iter(qn("w:p")))
    parts: list[TextPart] = []
    next_id = first_id
    for i, head in enumerate(paragraphs):
        kind = None
        norm = _norm_heading(_text(head))
        if _SUMMARY_HEAD.match(norm):
            kind = "summary"
        elif _SKILLS_HEAD.match(norm):
            kind = "skills"
        if kind is None or _is_bullet(head, _text(head)):
            continue
        body = []
        j = i + 1
        while j < len(paragraphs) and paragraphs[j].getparent() is head.getparent():
            t = _text(paragraphs[j])
            if _is_heading(paragraphs[j], t):
                break
            if t.strip():
                body.append(paragraphs[j])
            j += 1
        if not body or len(body) > MAX_SECTION_PARAGRAPHS or any(_is_bullet(p, _text(p)) for p in body):
            continue  # bullet lists are already handled as blocks
        for p in body:
            full = _text(p)
            if kind == "summary":
                if len(full.strip()) < MIN_SUMMARY_CHARS or len(_run_formats(p, 0)) != 1:
                    continue
                parts.append(TextPart(next_id, "summary", p, full, 0))
            else:
                m = _LABEL.match(full)
                split = m.end() if m else 0
                tail = full[split:]
                pieces = _split_items(tail)
                if pieces is None or len(_run_formats(p, split)) != 1:
                    continue
                parts.append(
                    TextPart(next_id, "skills", p, tail, split, label=full[:split], items=pieces[0], seps=pieces[1])
                )
            next_id += 1
    return parts


def _rewrite_tail(el, split: int, new_tail: str) -> None:
    """Replaces the paragraph text from `split` on, keeping every run's formatting before it."""
    pos = 0
    done = False
    for t in el.iter(qn("w:t")):
        text = t.text or ""
        start, end = pos, pos + len(text)
        pos = end
        if done:
            t.text = ""
        elif end > split or split == 0:
            t.text = text[: max(split - start, 0)] + new_tail
            t.set(_XML_SPACE, "preserve")
            done = True
    if not done:
        ts = list(el.iter(qn("w:t")))
        if ts:
            ts[-1].text = (ts[-1].text or "") + new_tail
            ts[-1].set(_XML_SPACE, "preserve")


def apply_text_plan(parts: list[TextPart], summary: dict[int, str], skills: dict[int, list[str]]) -> int:
    """summary: part id -> new paragraph text. skills: part id -> items in the new order. Returns how many changed."""
    changed = 0
    for part in parts:
        if part.kind == "summary" and part.id in summary and summary[part.id] != part.text:
            _rewrite_tail(part.element, 0, summary[part.id])
            changed += 1
        elif part.kind == "skills" and part.id in skills and skills[part.id] != part.items:
            order = skills[part.id]
            out = order[0]
            for sep, item in zip(part.seps, order[1:]):
                out += sep + item
            _rewrite_tail(part.element, part.split, out)
            changed += 1
    return changed
