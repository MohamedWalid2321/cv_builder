"""Deterministic phrase counting for extracted job descriptions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from models.schemas import JobRequirement


@dataclass(frozen=True)
class RequirementCounts:
    literal_counts: dict[str, int]
    total_literal_phrase_matches: int


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    normalized_phrase = re.sub(r"\s+", " ", phrase.strip())
    return re.compile(rf"(?<!\w){re.escape(normalized_phrase)}(?!\w)", re.IGNORECASE)


def _normalized_source(text: str) -> str:
    """Normalize whitespace only; punctuation and wording remain unchanged."""

    return re.sub(r"\s+", " ", text.strip())


def count_phrase_occurrences(text: str, phrase: str) -> int:
    """Count case-insensitive whole-word/phrase matches without substring matches."""

    normalized_phrase = phrase.strip()
    if not normalized_phrase:
        return 0
    return len(_phrase_pattern(normalized_phrase).findall(_normalized_source(text)))


def count_requirement_mentions(text: str, requirement: JobRequirement) -> RequirementCounts:
    """Count aliases while preventing overlapping aliases from double-counting a span."""

    # Requirement names are labels, not necessarily literal source phrases.
    # Only phrases explicitly approved in literal_phrases are counted.
    phrases = list(dict.fromkeys(requirement.literal_phrases))
    literal_counts = {phrase: count_phrase_occurrences(text, phrase) for phrase in phrases}

    normalized_text = _normalized_source(text)
    matches: list[tuple[int, int]] = []
    for phrase in phrases:
        if phrase.strip():
            matches.extend((match.start(), match.end()) for match in _phrase_pattern(phrase).finditer(normalized_text))

    accepted: list[tuple[int, int]] = []
    for start, end in sorted(matches, key=lambda item: (item[0], -(item[1] - item[0]))):
        if not any(start < accepted_end and end > accepted_start for accepted_start, accepted_end in accepted):
            accepted.append((start, end))

    return RequirementCounts(
        literal_counts=literal_counts,
        total_literal_phrase_matches=len(accepted),
    )
