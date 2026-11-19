# SPDX-License-Identifier: Apache-2.0
"""Split a reference document into passages that can be cited by exact position.

Rules, all deterministic: a blank line starts a new paragraph; paragraphs stay whole when they fit in
``MAX_CHUNK_BYTES``; longer ones are cut at the last sentence end that fits, else at a word boundary, else (for
one enormous word) at a character boundary; a short paragraph (under ``MIN_CHUNK_BYTES``) is joined to the
chunk before it when the pair still fits, so headings do not become passages of their own. Every chunk is
exactly ``text[start:end]`` with no surrounding whitespace, chunks never overlap, and every non-space
character of the document lies in exactly one chunk.
"""
from __future__ import annotations

import re

MAX_CHUNK_BYTES = 800
MIN_CHUNK_BYTES = 120
_PARAGRAPH = re.compile(r"\S(?:.|\n)*?(?=\n[ \t]*\n|\Z)")
_ATOM = re.compile(r"\S+\s*")


def _size(text: str, start: int, end: int) -> int:
    return len(text[start:end].encode("utf-8"))


def _split_atom(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Cut one over-long run of characters on character boundaries so each piece fits the byte limit."""
    pieces, cursor = [], start
    while cursor < end:
        stop = cursor + 1
        while stop < end and _size(text, cursor, stop + 1) <= MAX_CHUNK_BYTES:
            stop += 1
        pieces.append((cursor, stop))
        cursor = stop
    return pieces


def _split_paragraph(text: str, start: int, end: int) -> list[tuple[int, int]]:
    if _size(text, start, end) <= MAX_CHUNK_BYTES:
        return [(start, end)]
    pieces, window_start, sentence_end, window_end = [], start, None, start
    for match in _ATOM.finditer(text, start, end):
        atom_start, atom_end = match.span()
        word_end = atom_start + len(match.group().rstrip())
        if _size(text, atom_start, word_end) > MAX_CHUNK_BYTES:  # a single enormous word
            if window_end > window_start:
                pieces.append((window_start, window_end))
            pieces.extend(_split_atom(text, atom_start, word_end))
            window_start = window_end = atom_end
            sentence_end = None
            continue
        while _size(text, window_start, word_end) > MAX_CHUNK_BYTES:
            cut = sentence_end if sentence_end is not None else window_end
            pieces.append((window_start, cut))
            window_start = atom_start if cut == window_end else _skip_space(text, cut)
            sentence_end = None
        window_end = word_end
        if text[atom_start:word_end][-1] in ".!?":
            sentence_end = word_end
    if window_end > window_start:
        pieces.append((window_start, window_end))
    return pieces


def _skip_space(text: str, position: int) -> int:
    while text[position].isspace():
        position += 1
    return position


def chunk(text: str) -> list[dict]:
    """Passages of ``text`` as ``{"index", "start", "end", "text"}`` in document order."""
    pieces: list[tuple[int, int]] = []
    for paragraph in _PARAGRAPH.finditer(text):
        start, end = paragraph.start(), len(paragraph.group().rstrip()) + paragraph.start()
        for piece in _split_paragraph(text, start, end):
            if (pieces and _size(text, *pieces[-1]) < MIN_CHUNK_BYTES and _size(text, pieces[-1][0], piece[1]) <= MAX_CHUNK_BYTES):
                pieces[-1] = (pieces[-1][0], piece[1])
            else:
                pieces.append(piece)
    return [{"index": i, "start": s, "end": e, "text": text[s:e]} for i, (s, e) in enumerate(pieces)]
