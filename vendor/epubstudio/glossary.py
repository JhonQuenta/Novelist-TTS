from __future__ import annotations

import re


# Treatments that commonly survive the English fan translation of Korean,
# Japanese and Chinese web novels. They are editorial choices rather than
# ordinary English vocabulary, so surfacing them is useful even when they are
# written in lowercase in the EPUB.
STANDALONE_HONORIFICS = {
    "ahjumma": "Ahjumma",
    "ajumma": "Ajumma",
    "ahjussi": "Ahjussi",
    "ajusshi": "Ajusshi",
    "aniki": "Aniki",
    "dage": "Dage",
    "dajie": "Dajie",
    "daren": "Daren",
    "eonni": "Eonni",
    "gege": "Gege",
    "gongzi": "Gongzi",
    "hoobae": "Hoobae",
    "hubae": "Hubae",
    "hyeong": "Hyeong",
    "hyung": "Hyung",
    "jangmo": "Jangmo",
    "jiejie": "Jiejie",
    "laoshi": "Laoshi",
    "noona": "Noona",
    "nuna": "Nuna",
    "onee-san": "Onee-san",
    "onee-sama": "Onee-sama",
    "onii-san": "Onii-san",
    "onii-sama": "Onii-sama",
    "oppa": "Oppa",
    "seobang": "Seobang",
    "senpai": "Senpai",
    "sensei": "Sensei",
    "shidi": "Shidi",
    "shifu": "Shifu",
    "shijie": "Shijie",
    "shimei": "Shimei",
    "shixiong": "Shixiong",
    "shizun": "Shizun",
    "sunbae": "Sunbae",
    "unni": "Unni",
    "unnie": "Unnie",
    "xiansheng": "Xiansheng",
}

SUFFIX_HONORIFICS = ("chan", "dono", "kun", "nim", "sama", "san", "ssi")

FALSE_CANDIDATE_LEADERS = {
    "a", "after", "although", "am", "an", "and", "another", "as", "at",
    "before", "because", "but", "can", "did", "do", "does", "even", "for",
    "from", "had", "has", "have", "hearing", "her", "here", "his", "how",
    "if", "in", "is", "my", "now", "once", "our", "seeing", "shall",
    "should", "since", "that", "the", "then", "this", "though", "to",
    "unlike", "until", "upon", "was", "watching", "were", "what", "when",
    "where", "while", "why", "will", "with", "without", "would", "yes",
    "your",
}

_standalone_alternatives = "|".join(
    re.escape(value) for value in sorted(STANDALONE_HONORIFICS, key=len, reverse=True)
)
STANDALONE_HONORIFIC_RE = re.compile(
    rf"(?<![A-Za-z])(?:{_standalone_alternatives})(?![A-Za-z])", re.I
)
SUFFIX_HONORIFIC_RE = re.compile(
    rf"(?<![A-Za-z])(?:[A-Z][A-Za-z'’]*(?:\s+[A-Z][A-Za-z'’]*){{0,1}})-(?i:{'|'.join(SUFFIX_HONORIFICS)})(?![A-Za-z])",
)

# English words that may be sound captions in one paragraph and normal verbs
# in another. A global glossary entry would freeze legitimate translations.
CONTEXTUAL_EFFECT_WORDS = {
    "bang", "bump", "buzz", "clap", "click", "crack", "gurgle", "gulp",
    "knock", "nod", "pat", "pop", "ring", "shake", "slap", "smack",
    "snap", "squeak", "tap", "throb", "thump", "wiggle", "wince",
}

ROMANIZED_EFFECT_ROOTS = {
    "beuryut", "brut", "bulkkeun", "buryut", "cheombeong", "eummooooooot",
    "gulreong", "heundeul", "jjak", "jjigeok", "jjilgeok", "jjubeok",
    "jjuueup", "kkulreong", "tsubeok", "tsubuk", "ttjigeok", "umjil",
    "umjjeul",
}

GENERIC_TRANSLATABLE_PHRASES = {
    "beach villa", "her husband", "the chairman", "the madam",
    "dear son-in-law", "first time", "milk cow", "my girlfriend",
    "movie theater", "public beach", "sales team", "sex toy", "son-in-law lee",
    "sow no", "united states", "young ladies", "young miss", "your majesty",
    "youtube",
}

ENGLISH_HONORIFIC_BASE_TRANSLATIONS = {
    "assistant manager": "Subgerente",
    "ball": "Testículo",
    "chairman": "Presidente",
    "cock": "Verga",
    "dick": "Pene",
    "dildo": "Consolador",
    "doctor": "Doctor",
    "female": "Hembra",
    "guest": "Invitado",
    "husband": "Esposo",
    "interviewer": "Entrevistador",
    "leader": "Líder",
    "male": "Macho",
    "manager": "Gerente",
    "master": "Amo",
    "mistress": "Ama",
    "owner": "Dueño",
    "queen": "Reina",
    "team leader": "Líder de equipo",
    "teacher": "Profesor",
}

# These English roles cannot always be translated correctly from the isolated
# word.  For example, Teacher-nim may be Profesor-nim in a school scene but
# Entrenador-nim in a gym, while Guest-nim can change gender.  Gemini must use
# the supplied excerpts instead of the fallback dictionary for these entries.
CONTEXT_SENSITIVE_HONORIFIC_BASES = {
    "ball", "female", "guest", "interviewer", "male", "mistress", "owner",
    "teacher",
}

CONTEXTUAL_NAME_STOPWORDS = FALSE_CANDIDATE_LEADERS | {
    "approaching", "by", "considering", "fucking", "greeting", "hot", "i",
    "kiss", "like", "only", "poor", "real", "serving", "telling",
    "welcoming", "yes", "yesh",
}

CONTEXTUAL_REORDER_ROLE_BASES = {
    "assistant manager", "chairman", "guest", "interviewer", "master",
    "queen", "team leader", "teacher",
}

_name_token = r"[A-Z][A-Za-z'’]*(?:-[A-Za-z'’]+)*"

PREFIXED_ROLE_TRANSLATIONS = {
    "assistant manager": "Subgerente",
    "team leader": "Líder de equipo",
    "manager": "Gerente",
}

_prefixed_role_alternatives = "|".join(
    re.escape(value) for value in sorted(PREFIXED_ROLE_TRANSLATIONS, key=len, reverse=True)
)
PREFIXED_ROLE_NAME_HONORIFIC_RE = re.compile(
    rf"(?<![A-Za-z])(?P<role>(?i:{_prefixed_role_alternatives}))\s+"
    rf"(?P<name>{_name_token}(?:\s+{_name_token}){{0,1}})-"
    rf"(?P<suffix>(?i:{'|'.join(SUFFIX_HONORIFICS)}))(?![A-Za-z])"
)


def parse_prefixed_role_honorific(term: str) -> tuple[str, str, str] | None:
    """Parse complete forms such as ``Assistant Manager Han-nim``."""
    match = PREFIXED_ROLE_NAME_HONORIFIC_RE.fullmatch(term.strip())
    if match is None:
        return None
    return match.group("role"), match.group("name"), match.group("suffix")


def translate_prefixed_role_honorific(term: str) -> str | None:
    parsed = parse_prefixed_role_honorific(term)
    if parsed is None:
        return None
    role, name, suffix = parsed
    translated = PREFIXED_ROLE_TRANSLATIONS.get(role.casefold())
    return f"{translated} {name}-{suffix}" if translated else None

_translated_role_alternatives = "|".join(
    re.escape(value)
    for value in sorted(ENGLISH_HONORIFIC_BASE_TRANSLATIONS, key=len, reverse=True)
)
CONTEXTUAL_ROLE_HONORIFIC_RE = re.compile(
    rf"(?<![A-Za-z])(?P<name>{_name_token}(?:\s+{_name_token}){{0,1}})\s+"
    rf"(?P<role>(?i:{_translated_role_alternatives}))-(?P<suffix>(?i:{'|'.join(SUFFIX_HONORIFICS)}))(?![A-Za-z])"
)


def parse_contextual_role_honorific(term: str) -> tuple[str, str, str] | None:
    """Parse ``Name Role-nim`` expressions whose Spanish order must change."""
    match = CONTEXTUAL_ROLE_HONORIFIC_RE.fullmatch(term.strip())
    if match is None:
        return None
    if match.group("role").casefold() not in CONTEXTUAL_REORDER_ROLE_BASES:
        return None
    name = match.group("name")
    if re.search(r"['’]s(?:\s|$)", name, re.I):
        return None
    name_words = name.split()
    for word in name_words:
        leader = re.match(r"[A-Za-z]+", word)
        leader_key = leader.group(0).casefold() if leader else ""
        if leader_key in CONTEXTUAL_NAME_STOPWORDS:
            return None
        if word.casefold() in STANDALONE_HONORIFICS:
            return None
        pieces = word.casefold().split("-", 1)
        if len(pieces) == 2 and pieces[0] and pieces[1].startswith(pieces[0]):
            # Dialogue stutters such as Ye-yes and Te-Team are not names.
            return None
        if re.search(rf"-(?:{'|'.join(SUFFIX_HONORIFICS)})$", word, re.I):
            return None
    return name, match.group("role"), match.group("suffix")


def is_contextual_role_honorific(term: str) -> bool:
    return parse_contextual_role_honorific(term) is not None


def translate_contextual_role_honorific(
    term: str, translated_role: str | None = None
) -> str | None:
    """Translate and reorder ``Juhyeon Master-nim`` safely.

    The suffix belongs to the complete form of address in the source.  In the
    user's preferred Spanish style it is retained after the person's name.
    """
    parsed = parse_contextual_role_honorific(term)
    if parsed is None:
        return None
    name, role, suffix = parsed
    translated = translated_role or ENGLISH_HONORIFIC_BASE_TRANSLATIONS.get(role.casefold())
    return f"{translated} {name}-{suffix}" if translated else None


def english_honorific_base(term: str) -> str | None:
    match = re.fullmatch(
        rf"(?P<base>[A-Za-z]+(?:\s+[A-Za-z]+)*)-(?P<suffix>{'|'.join(SUFFIX_HONORIFICS)})",
        term.strip(),
        re.I,
    )
    if match is None:
        return None
    base = match.group("base").casefold()
    return base if base in ENGLISH_HONORIFIC_BASE_TRANSLATIONS else None


def is_context_sensitive_honorific(term: str) -> bool:
    return english_honorific_base(term) in CONTEXT_SENSITIVE_HONORIFIC_BASES


def extract_honorific_terms(text: str) -> list[str]:
    """Return safe glossary-sized honorific expressions from running prose."""
    found: list[str] = []
    occupied: list[tuple[int, int]] = []
    for match in PREFIXED_ROLE_NAME_HONORIFIC_RE.finditer(text):
        found.append(match.group(0))
        occupied.append(match.span())
    # Preserve the full expression only when translating it requires a word
    # order change.  A later minimal-honorific pass must not collapse it.
    for match in CONTEXTUAL_ROLE_HONORIFIC_RE.finditer(text):
        found.append(match.group(0))
        occupied.append(match.span())
    for match in STANDALONE_HONORIFIC_RE.finditer(text):
        found.append(STANDALONE_HONORIFICS[match.group(0).casefold()])
        occupied.append(match.span())
    for match in SUFFIX_HONORIFIC_RE.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in occupied):
            continue
        surface = match.group(0)
        parts = surface.split()
        leader = re.match(r"[A-Za-z]+", parts[0]) if parts else None
        leader_key = leader.group(0).casefold() if leader else ""
        if len(parts) == 2 and leader_key in FALSE_CANDIDATE_LEADERS:
            surface = parts[-1]
        found.append(surface)
    return found


def is_honorific_term(term: str) -> bool:
    normalized = term.strip().casefold()
    if normalized in STANDALONE_HONORIFICS:
        return True
    if parse_prefixed_role_honorific(term):
        return True
    if is_contextual_role_honorific(term):
        return True
    if STANDALONE_HONORIFIC_RE.search(term):
        return False
    return bool(SUFFIX_HONORIFIC_RE.fullmatch(term.strip()))


def contains_honorific(term: str) -> bool:
    return bool(
        PREFIXED_ROLE_NAME_HONORIFIC_RE.search(term)
        or
        CONTEXTUAL_ROLE_HONORIFIC_RE.search(term)
        or STANDALONE_HONORIFIC_RE.search(term)
        or SUFFIX_HONORIFIC_RE.search(term)
    )


def minimal_honorific_term(term: str) -> str | None:
    """Reduce a phrase to the smallest honorific expression safe to protect."""
    if is_contextual_role_honorific(term) or parse_prefixed_role_honorific(term):
        return term.strip()
    candidates = extract_honorific_terms(term)
    if not candidates:
        return None
    standalone = next((
        candidate for candidate in candidates
        if candidate.casefold() in STANDALONE_HONORIFICS
    ), None)
    return standalone or candidates[-1]


def translate_english_honorific_base(term: str) -> str | None:
    """Translate an English role while retaining its Asian suffix."""
    match = re.fullmatch(
        rf"(?P<base>[A-Za-z]+(?:\s+[A-Za-z]+)*)-(?P<suffix>{'|'.join(SUFFIX_HONORIFICS)})",
        term.strip(),
        re.I,
    )
    if match is None:
        return None
    translated = ENGLISH_HONORIFIC_BASE_TRANSLATIONS.get(match.group("base").casefold())
    return f"{translated}-{match.group('suffix')}" if translated else None


def is_incomplete_hyphen_prefix(term: str, examples: list[str]) -> bool:
    """Detect scanner fragments such as 'Kim Mi' from 'Kim Mi-young'."""
    if not term or not examples:
        return False
    pattern = re.compile(rf"(?<![A-Za-z]){re.escape(term)}-[A-Za-z]", re.I)
    return all(pattern.search(example) is not None for example in examples)


def is_stutter_honorific_fragment(term: str, examples: list[str]) -> bool:
    """Reject ``Leader-nim`` when it only occurs inside ``Lea-Leader-nim``."""
    if not term or not examples or "-" not in term:
        return False
    base = term.split("-", 1)[0]
    pattern = re.compile(
        rf"(?<![A-Za-z])(?P<prefix>[A-Za-z]{{1,{min(5, max(1, len(base)))}}})-{re.escape(term)}(?![A-Za-z])",
        re.I,
    )

    def is_fragment(example: str) -> bool:
        matches = list(pattern.finditer(example))
        return bool(matches) and all(
            base.casefold().startswith(match.group("prefix").casefold())
            for match in matches
        )

    return all(is_fragment(example) for example in examples)
