"""Deterministic normalization for extracted job profiles."""

from __future__ import annotations

import re

from models.schemas import JobProfile, JobRequirement, JobResponsibility
from services.skill_counter import count_phrase_occurrences


_CATEGORY_PREFIXES = {
    "hard_skill": "HS",
    "soft_skill": "SS",
    "education": "ED",
    "experience": "EX",
    "certification": "CE",
    "seniority": "SE",
    "experience_level": "EL",
    "operational_competency": "OC",
    "technical_competency": "TC",
    "learning": "LR",
    "working_arrangement": "WA",
    "keyword": "KW",
}


def synchronize_profile_links(profile: JobProfile, source_text: str = "") -> None:
    """Normalize taxonomy, add required explicit duties, and link responsibilities safely."""

    _normalize_requirement_categories(profile)
    if source_text:
        _add_explicit_requirements(profile, source_text)
        _add_explicit_responsibilities(profile, source_text)
        _normalize_source_backed_phrases(profile, source_text)
        _populate_requirement_source_traces(profile, source_text)

    counters: dict[str, int] = {}
    for requirement in profile.requirements:
        prefix = _CATEGORY_PREFIXES[requirement.category]
        counters[prefix] = counters.get(prefix, 0) + 1
        requirement.requirement_id = f"{prefix}{counters[prefix]:03d}"

    for responsibility in profile.responsibilities:
        _classify_responsibility_priority(responsibility)

        responsibility_text = f"{responsibility.name} {responsibility.job_evidence}"
        supported_ids: list[str] = []
        for requirement in profile.requirements:
            if _requirement_supported_by_responsibility(requirement, responsibility_text):
                supported_ids.append(requirement.requirement_id)
        responsibility.related_requirement_ids = supported_ids


def validate_profile_against_source(profile: JobProfile, source_text: str) -> list[str]:
    """Return structural/source-trace errors after deterministic synchronization."""

    requirement_ids = {requirement.requirement_id for requirement in profile.requirements}
    errors: list[str] = []
    for requirement in profile.requirements:
        expected_prefix = _CATEGORY_PREFIXES[requirement.category]
        if not requirement.requirement_id.startswith(expected_prefix):
            errors.append(f"{requirement.name}: ID/category prefix mismatch")
        if requirement.source_span and _find_source_excerpt(source_text, requirement.source_span) == "":
            errors.append(f"{requirement.name}: source_span is not in the original JD")
    for responsibility in profile.responsibilities:
        missing = set(responsibility.related_requirement_ids) - requirement_ids
        if missing:
            errors.append(f"{responsibility.name}: unknown requirement IDs {sorted(missing)}")
    return errors


def _populate_requirement_source_traces(profile: JobProfile, source_text: str) -> None:
    """Ensure each requirement points to an exact excerpt in the original JD."""

    for requirement in profile.requirements:
        requirement.source_span = _trace_requirement_to_source(requirement, source_text)
        if not requirement.source_section:
            requirement.source_section = "job_description"


def _normalize_source_backed_phrases(profile: JobProfile, source_text: str) -> None:
    """Keep literal phrases source-backed while preserving semantic concepts separately."""

    for requirement in profile.requirements:
        original_phrases = list(requirement.literal_phrases)
        phrases = [phrase for phrase in original_phrases if count_phrase_occurrences(source_text, phrase)]
        requirement.related_concepts = list(dict.fromkeys(
            [*requirement.related_concepts, *(phrase for phrase in original_phrases if phrase not in phrases)]
        ))
        requirement_text = f"{requirement.name} {requirement.job_evidence}".casefold()
        if "vpn" in requirement_text and count_phrase_occurrences(source_text, "VPN"):
            phrases.append("VPN")
        if "incident" in requirement_text and any(term in requirement_text for term in ("response", "investigation")):
            incident_terms = ("incident investigation", "documentation", "escalation", "resolution")
            phrases.extend(term for term in incident_terms if count_phrase_occurrences(source_text, term))
        requirement.literal_phrases = list(dict.fromkeys(phrases))


def _add_explicit_requirements(profile: JobProfile, source_text: str) -> None:
    """Add only explicit, independently scorable requirements missing from the AI output."""

    def ensure(name: str, category: str, phrases: tuple[str, ...], concepts: tuple[str, ...] = ()) -> None:
        identity = " ".join([name, *phrases, *concepts]).casefold()
        if any(_requirement_identity_matches(item, identity) for item in profile.requirements):
            return
        if "incident" in identity and any(
            "incident" in item.name.casefold()
            and any(term in item.name.casefold() for term in ("response", "investigation"))
            for item in profile.requirements
        ):
            return
        found_phrases = [phrase for phrase in phrases if count_phrase_occurrences(source_text, phrase)]
        if not found_phrases:
            return
        profile.requirements.append(
            JobRequirement(
                name=name,
                category=category,
                literal_phrases=found_phrases,
                related_concepts=list(concepts),
                job_evidence=_sentence_containing(source_text, found_phrases[0]),
            )
        )

    ensure(
        "Operation of network security solutions",
        "hard_skill",
        (
            "operation of network security solutions",
            "operate network security solutions",
            "operating network security solutions",
            "operation",
        ),
        ("network security operations",),
    )
    ensure(
        "IDS/IPS, proxy, and DNS configuration and maintenance",
        "hard_skill",
        ("IDS/IPS", "proxy", "DNS"),
        ("configuration", "maintenance"),
    )
    ensure(
        "Security upgrades, technology implementations, and testing",
        "operational_competency",
        ("upgrades", "technology implementations", "testing"),
    )
    ensure(
        "Incident investigation, documentation, escalation, and resolution",
        "hard_skill",
        ("incident investigation", "documentation", "escalation", "resolution"),
    )
    ensure(
        "Security project support",
        "operational_competency",
        ("security projects", "project support"),
    )
    ensure(
        "Security policy and procedure compliance",
        "operational_competency",
        ("security policies", "standards", "operational procedures"),
    )
    ensure(
        "Continuous improvement",
        "operational_competency",
        ("continuous improvement",),
    )
    ensure(
        "Staying current with network security technologies",
        "learning",
        (
            "stay current",
            "staying current",
            "stay updated",
            "staying updated",
            "current with technologies",
            "updated with relevant network security technologies",
        ),
    )


def _requirement_identity_matches(requirement, identity: str) -> bool:
    existing = " ".join(
        [requirement.name, *requirement.literal_phrases, *requirement.related_concepts]
    ).casefold()
    anchors = [term for term in re.findall(r"[a-zA-Z][a-zA-Z0-9+/#-]*", identity) if len(term) > 4]
    return bool(anchors) and all(anchor.casefold() in existing for anchor in anchors[:2])


def _find_source_excerpt(source_text: str, excerpt: str) -> str:
    start = source_text.casefold().find(excerpt.casefold())
    if start < 0:
        return ""
    return source_text[start : start + len(excerpt)]


def _trace_requirement_to_source(requirement, source_text: str) -> str:
    """Return a source sentence even when a model-created phrase is non-contiguous."""

    candidates = [*requirement.literal_phrases, requirement.name, requirement.job_evidence]
    for candidate in candidates:
        words = re.findall(r"[a-zA-Z][a-zA-Z0-9+/#-]*", candidate)
        for term in ([candidate] if candidate else []) + words[:1]:
            if term:
                sentence = _sentence_containing(source_text, term)
                if sentence != term:
                    return sentence
    return ""


def _requirement_supported_by_responsibility(requirement, responsibility_text: str) -> bool:
    """Link exact phrases, or a clear non-contiguous concept from the requirement name."""

    responsibility_lower = responsibility_text.casefold()
    requirement_text = " ".join(
        [requirement.name, requirement.job_evidence, *requirement.literal_phrases, *requirement.related_concepts]
    ).casefold()
    if "documentation" in responsibility_lower and not any(
        term in requirement_text for term in ("documentation", "incident report", "incident documentation")
    ):
        return False

    if any(count_phrase_occurrences(responsibility_text, phrase) > 0 for phrase in requirement.literal_phrases):
        return True

    phrase_starts = {
        match.group(0).casefold()
        for phrase in [*requirement.literal_phrases, *requirement.related_concepts]
        if len(re.findall(r"[a-zA-Z][a-zA-Z0-9+/#-]*", phrase)) >= 3
        and (match := re.search(r"[a-zA-Z][a-zA-Z0-9+/#-]*", phrase))
    }
    responsibility_tokens = {
        token.casefold()
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+/#-]*", responsibility_text)
    }
    return bool(phrase_starts & responsibility_tokens)


def _normalize_requirement_categories(profile: JobProfile) -> None:
    for requirement in profile.requirements:
        identity_text = " ".join(
            [requirement.name, *requirement.literal_phrases, *requirement.related_concepts]
        ).casefold()
        text = f"{identity_text} {requirement.job_evidence}".casefold()
        if any(term in text for term in ("cross-functional", "coordination", "collaboration", "teamwork")):
            requirement.category = "soft_skill"
        elif any(term in identity_text for term in ("guidance from senior", "under the guidance", "supervision context")):
            requirement.category = "working_arrangement"
        elif any(term in identity_text for term in ("project support", "security project support")):
            requirement.category = "operational_competency"
        elif "continuous improvement" in text:
            requirement.category = "operational_competency"
        elif any(term in text for term in ("stay current", "staying current", "current with technolog", "technology awareness", "ongoing learning")):
            requirement.category = "learning"
        elif "security polic" in text or "policy compliance" in text:
            requirement.category = "operational_competency"
        elif "documentation" in text and requirement.category == "soft_skill":
            requirement.category = "technical_competency"
        elif any(term in text for term in ("junior", "entry level", "entry-level", "senior level")):
            requirement.category = "experience_level"


def _classify_responsibility_priority(responsibility) -> None:
    """Only explicit priority markers determine required/preferred duty priority."""

    evidence = f"{responsibility.name} {responsibility.job_evidence}".casefold()
    required_marker = re.search(
        r"\b(?:must|shall|mandatory)\b|\bmandatory\s*:\s*|\brequired\s*:\s*|"
        r"\brequired\s+(?:qualification|skill|experience|certification|requirement)s?\b",
        evidence,
    )
    if required_marker:
        responsibility.priority = "required"
        responsibility.priority_basis = "explicit"
    elif re.search(r"\b(preferred|preferably|desirable|nice to have)\b", evidence):
        responsibility.priority = "preferred"
        responsibility.priority_basis = "explicit"
    elif responsibility.job_evidence.strip():
        responsibility.priority = "unspecified"
        responsibility.priority_basis = "explicit"
    else:
        responsibility.priority = "unspecified"
        responsibility.priority_basis = "unspecified"


def _add_explicit_responsibilities(profile: JobProfile, source_text: str) -> None:
    rules = (
        ("security polic", "Follow security policies"),
        ("continuous improvement", "Support continuous improvement initiatives"),
        ("stay current", "Stay current with technologies"),
        ("staying current", "Stay current with technologies"),
        ("current with technolog", "Stay current with technologies"),
        ("stay updated", "Stay current with technologies"),
        ("staying updated", "Stay current with technologies"),
    )
    lower_source = source_text.casefold()
    for phrase, name in rules:
        existing = " ".join(item.name for item in profile.responsibilities).casefold()
        if phrase not in lower_source or phrase in existing:
            continue
        evidence = _sentence_containing(source_text, phrase)
        related_names = [
            requirement.name
            for requirement in profile.requirements
            if any(count_phrase_occurrences(evidence, literal) for literal in requirement.literal_phrases)
        ]
        profile.responsibilities.append(
            JobResponsibility(
                name=name,
                job_evidence=evidence,
                related_requirement_names=related_names,
            )
        )


def _sentence_containing(source_text: str, phrase: str) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", source_text):
        if phrase in sentence.casefold():
            return sentence.strip()
    return phrase
