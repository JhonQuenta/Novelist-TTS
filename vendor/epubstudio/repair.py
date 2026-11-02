from __future__ import annotations

import difflib
import re


STUTTER_COMMA_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<letter>[A-Za-z]),(?P<space>\s*)"
    r"(?=(?P<word>[A-Za-z][A-Za-z'’]*))"
)
MULTI_STUTTER_COMMA_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<prefix>[A-Za-z]{2,3}),(?P<space>\s*)"
    r"(?P<word>[A-Za-z][A-Za-z'’]*(?:-[A-Za-z][A-Za-z'’]*)*)"
)


def _apostrophe_belongs_to_word(value: str, start: int) -> bool:
    return bool(
        start >= 2
        and value[start - 1:start] in {"'", "’"}
        and value[start - 2:start - 1].isalnum()
    )


def _inside_double_quoted_dialogue(value: str, position: int) -> bool:
    prefix = value[:position]
    return prefix.count('"') % 2 == 1 or (
        prefix.rfind("“") > prefix.rfind("”")
    )


def repair_stutter_commas(value: str) -> tuple[str, int]:
    """Restore hyphens replaced by commas in obvious one-letter stutters."""
    changes = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changes
        letter = match.group("letter")
        word = match.group("word")
        has_space = bool(match.group("space"))
        if _apostrophe_belongs_to_word(value, match.start()):
            return match.group(0)
        if letter.casefold() != word[0].casefold():
            return match.group(0)
        if has_space and letter.casefold() == "i" and not re.fullmatch(
            r"(?:i|i['’](?:m|ll|d|ve)|it|it['’](?:s|ll|d))",
            word,
            re.I,
        ):
            return match.group(0)
        if has_space and letter.islower():
            prefix = value[:match.start()].rstrip()
            if (
                prefix
                and prefix[-1] not in "\"'“‘«([{.!?…:;♥"
                and not _inside_double_quoted_dialogue(value, match.start())
            ):
                return match.group(0)
        changes += 1
        return letter + "-"

    repaired = STUTTER_COMMA_CANDIDATE_RE.sub(replace, value)
    common_complete_words = {
        "all", "am", "an", "and", "any", "are", "as", "at", "be", "but",
        "by", "can", "did", "do", "for", "go", "had", "has", "he", "her",
        "him", "his", "how", "if", "in", "is", "it", "its", "man", "may",
        "me", "my", "new", "no", "not", "now", "of", "oh", "old", "on",
        "one", "or", "our", "out", "say", "see", "set", "she", "so", "the",
        "to", "too", "two", "uh", "uhm", "up", "us", "use", "was", "way",
        "we", "who", "why", "yes", "you",
    }

    def replace_multi(match: re.Match[str]) -> str:
        nonlocal changes
        prefix = match.group("prefix")
        word = match.group("word")
        prefix_key = prefix.casefold()
        word_key = word.casefold()
        if _apostrophe_belongs_to_word(repaired, match.start()):
            return match.group(0)
        if word_key == prefix_key:
            if match.group("space"):
                return match.group(0)
            changes += 1
            return prefix + "-" + word
        elif len(word) <= len(prefix) or not word_key.startswith(prefix_key):
            return match.group(0)
        # Avoid changing a plausible complete word followed by a missing
        # typographic space (for example "No,nothing").
        if prefix_key in common_complete_words:
            return match.group(0)
        changes += 1
        return prefix + "-" + word

    return MULTI_STUTTER_COMMA_RE.sub(replace_multi, repaired), changes


def repair_misplaced_dialogue_commas(value: str) -> tuple[str, int]:
    """Restore a straight opening quote that a source converted to a comma."""
    match = re.match(r"^(?P<space>\s*),(?P<body>.*)$", value, re.S)
    if match is None:
        return value, 0
    stripped = value.rstrip()
    # This corruption consistently has a closing quote but no opening quote.
    if not stripped.endswith('"') or stripped.count('"') != 1:
        return value, 0
    repaired = match.group("space") + '"' + match.group("body")
    # `?,"` and `!,"` are artifacts of the same conversion. A comma before
    # the closing quote can remain valid after a plain word, so only remove it
    # when terminal punctuation is already present.
    repaired = re.sub(r"([.!?…♥])\s*,\s*\"(?=\s*$)", r'\1"', repaired)
    return repaired, 1


def _redistribute_changed_text(values: list[str], repaired: str) -> list[str] | None:
    """Map a changed concatenated text run back onto its original XML slots."""
    original = "".join(values)
    boundaries = [0]
    for value in values:
        boundaries.append(boundaries[-1] + len(value))
    result = list(values)
    edits = [
        (old_start, old_end, repaired[new_start:new_end])
        for tag, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(
            None, original, repaired, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]

    def location(offset: int) -> tuple[int, int]:
        for index in range(len(values)):
            if offset < boundaries[index + 1] or (
                offset == boundaries[index + 1] and index == len(values) - 1
            ):
                return index, offset - boundaries[index]
        return len(values) - 1, len(values[-1])

    for old_start, old_end, replacement in reversed(edits):
        start_index, start_offset = location(old_start)
        if old_end == old_start:
            result[start_index] = (
                result[start_index][:start_offset]
                + replacement
                + result[start_index][start_offset:]
            )
            continue
        end_index, end_offset = location(old_end - 1)
        end_offset += 1
        if start_index == end_index:
            result[start_index] = (
                result[start_index][:start_offset]
                + replacement
                + result[start_index][end_offset:]
            )
            continue
        result[start_index] = result[start_index][:start_offset] + replacement
        for index in range(start_index + 1, end_index):
            result[index] = ""
        result[end_index] = result[end_index][end_offset:]
    return result if "".join(result) == repaired else None


def repair_stutter_comma_fragments(values: list[str]) -> tuple[list[str], int]:
    """Repair a stutter even when inline XHTML splits it into text fragments.

    The returned list has the same number of entries as ``values``.  Only the
    punctuation around the stutter is moved; the surrounding inline elements
    therefore keep their styling and position.
    """
    if not values:
        return values, 0
    original = "".join(values)
    repaired, changes = repair_stutter_commas(original)
    if not changes or repaired == original:
        return values, 0

    result = _redistribute_changed_text(values, repaired)
    if result is None:
        return values, 0
    return result, changes


def repair_misplaced_dialogue_comma_fragments(values: list[str]) -> tuple[list[str], int]:
    if not values:
        return values, 0
    repaired, changes = repair_misplaced_dialogue_commas("".join(values))
    if not changes:
        return values, 0
    result = _redistribute_changed_text(values, repaired)
    return (result, changes) if result is not None else (values, 0)
