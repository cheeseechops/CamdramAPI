"""
Role normalization and categorization rules for Camdram data.
"""

from __future__ import annotations

import html
import re

_WHITESPACE_RE = re.compile(r"\s+")
_SPACED_SLASH_RE = re.compile(r"\s*/\s*")
_DATE_SUFFIX_RE = re.compile(r"^(.*?)(?:\s+\d{1,2}[/-]\d{1,2})$")

_ROMAN_TO_INT = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}

_OBVIOUS_NON_ROLE_SINGLE_TOKENS = {
    "john",
    "mary",
    "sam",
    "romeo",
    "macbeth",
    "ko-ko",
    "koko",
}


def _normalize_spaces(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _strip_date_suffix(text: str) -> str:
    m = _DATE_SUFFIX_RE.match(text)
    return m.group(1).strip() if m else text


def _normalize_numbering(text: str) -> str:
    # Violin I == Violin 1, Keys II == Keys 2, etc.
    parts = text.split(" ")
    out: list[str] = []
    for part in parts:
        key = part.casefold().strip()
        out.append(_ROMAN_TO_INT.get(key, part))
    return " ".join(out)


def _normalize_key(text: str) -> str:
    x = html.unescape(text or "")
    x = _normalize_spaces(x)
    x = _strip_date_suffix(x)
    x = _normalize_numbering(x)
    x = x.replace("&", "/")
    x = re.sub(r"\band\b", "/", x, flags=re.IGNORECASE)
    x = _SPACED_SLASH_RE.sub("/", x)
    x = _normalize_spaces(x)
    return x.casefold()


def _singularize_simple(text: str) -> str:
    # Conservative singularization for common plural role labels.
    x = text.strip()
    if not x or "/" in x:
        return x
    if x.endswith("ies") and len(x) > 4:
        return x[:-3] + "y"
    if x.endswith("s") and not x.endswith("ss") and len(x) > 3:
        return x[:-1]
    return x


_ALIASES: dict[str, str] = {}


def _add_aliases(canonical: str, aliases: list[str]) -> None:
    _ALIASES[_normalize_key(canonical)] = canonical
    for alias in aliases:
        _ALIASES[_normalize_key(alias)] = canonical


_add_aliases("Assistant Stage Manager", ["ASM", "Assistant Stage Managers"])
_add_aliases("Deputy Stage Manager", ["DSM"])
_add_aliases("Stage Manager", ["SM"])
_add_aliases("Technical Director", ["TD", "Technical Directors"])
_add_aliases("Technical Director", ["Co-Technical Director"])
_add_aliases("Assistant Technical Director", [])

_add_aliases("Producer", ["Producers"])
_add_aliases("Producer", ["Co-producer", "Co-Producer"])
_add_aliases("Assistant Producer", ["Assistant producer"])
_add_aliases("Executive Producer", [])
_add_aliases("Associate Producer", [])

_add_aliases("Director", ["Directors"])
_add_aliases("Director", ["Co-director", "Co-Director"])
_add_aliases("Assistant Director", ["Assistant director"])
_add_aliases("Associate Director", [])

_add_aliases("Writer/Director", ["Director/Writer", "Director, Writer"])
_add_aliases("Director/Producer", ["Producer/Director"])
_add_aliases("Writer", ["Writers"])
_add_aliases(
    "Writer/Performer",
    ["Writer / Performer", "Writer/ Performer", "Writer/performer", "Writer /Performer"],
)
_add_aliases("Performer", ["Performer/Writer", "Performer, Writer", "Performer (Freshers)", "Performers"])
_add_aliases("Script Editor", ["Script editor"])

_add_aliases("Lighting (General)", ["LX", "Lighting"])
_add_aliases("Chief Electrician", ["CLX", "Chief LX"])
_add_aliases("Production Electrician", ["PLX", "Production LX"])
_add_aliases("Lighting Operator", ["Lighting Op", "LX Operator"])
_add_aliases("Followspot Operator", ["Followspot", "Followspot Op"])
_add_aliases("Lighting Designer", ["Lighting designer"])
_add_aliases("Lighting Design", [])
_add_aliases("Lighting Designer", ["Co-Lighting Designer"])
_add_aliases("Assistant Lighting Designer", [])
_add_aliases("Lighting Crew", ["Lighting Team"])
_add_aliases("Lighting & Sound Designer", ["Lighting and Sound", "Lighting and Sound Designer", "Lighting/Sound Designer"])

_add_aliases("Sound Operator", ["Sound", "Sound Op"])
_add_aliases("Sound Technician", ["Sound Tech"])
_add_aliases("Sound Assistant", [])
_add_aliases("Sound Designer", [])
_add_aliases("Assistant Sound Designer", [])
_add_aliases("Associate Sound Designer", [])
_add_aliases("Sound Design", [])
_add_aliases("Sound Engineer", [])
_add_aliases("Mic Runner", [])
_add_aliases("Sound Editor", [])
_add_aliases("Audio Editor", [])
_add_aliases("Sound Recordist", [])
_add_aliases("Sound Helper", [])

_add_aliases("Set Designer", ["Set Design"])
_add_aliases("Assistant Set Designer", [])
_add_aliases("Set Construction", ["Set Building"])
_add_aliases("Set Builder", [])
_add_aliases("Scenic Artist", ["Set Painter"])
_add_aliases("Props", [])
_add_aliases("Props Manager", [])
_add_aliases("Props Assistant", [])
_add_aliases("Head of Props", [])

_add_aliases("Costume (General)", ["Costume", "Costumes", "Costume Design"])
_add_aliases("Costume Designer", [])
_add_aliases("Costume Designer", ["Co-Costume Designer"])
_add_aliases("Assistant Costume Designer", [])
_add_aliases("Costume Assistant", [])
_add_aliases("Costume Team", [])
_add_aliases("Wardrobe Assistant", [])
_add_aliases("Wardrobe Supervisor", [])
_add_aliases("Wardrobe Mistress", [])
_add_aliases("Makeup (General)", ["Make-up", "Makeup"])
_add_aliases("Makeup Artist", ["Make-up Artist", "Make-Up Artist"])
_add_aliases("Makeup Designer", ["Make-Up Designer"])
_add_aliases("Hair & Makeup Designer", ["Hair & Makeup", "Hair and Makeup Designer", "Hair &amp; Makeup"])
_add_aliases("Hair Stylist", [])

_add_aliases("Publicity (General)", ["Publicity", "Publicist"])
_add_aliases("Publicity Designer", ["Publicity designer"])
_add_aliases("Publicity Design", [])
_add_aliases("Publicity Manager", [])
_add_aliases("Publicity Officer", [])
_add_aliases("Graphic Designer", [])
_add_aliases("Poster Designer", ["Poster Design"])
_add_aliases("Programme Designer", ["Programme Design"])
_add_aliases("Web Designer", ["Website Designer"])

_add_aliases("Photographer", ["Photography", "Headshot Photographer", "Production Photographer", "Rehearsal Photographer", "Dress Rehearsal Photographer", "Publicity Photographer"])
_add_aliases("Videographer", [])
_add_aliases("Camera Operator", [])
_add_aliases("Cinematographer", [])
_add_aliases("Video Director", [])
_add_aliases("Video Editor", [])
_add_aliases("Trailer Director", [])
_add_aliases("Trailer Cinematographer", [])
_add_aliases("Director of Photography", [])

_add_aliases("Musical Director", ["Music Director"])
_add_aliases("Assistant Musical Director", [])
_add_aliases("Associate Musical Director", [])
_add_aliases("Musical Director", ["Co-Musical Director"])
_add_aliases("Conductor", [])
_add_aliases("Chorus Master", [])
_add_aliases("Répétiteur", ["Répétiteur", "Repetiteur", "R&eacute;p&eacute;titeur"])
_add_aliases("Orchestrator", [])
_add_aliases("Arranger", [])
_add_aliases("Composer", [])
_add_aliases("Lyricist", [])
_add_aliases("Librettist", [])

_add_aliases("Cast", ["cast"])
_add_aliases("Performer", [])
_add_aliases("Actor", [])
_add_aliases("Ensemble", [])
_add_aliases("Chorus", ["Choir", "Male Chorus", "Female Chorus", "Ladies' Chorus", "Dance Chorus"])
_add_aliases("Singer", [])
_add_aliases("Soloist", [])
_add_aliases("Narrator", [])
_add_aliases("Compere", ["Compère", "MC"])

_add_aliases("Crew", ["Stage Crew", "Get-in Crew"])
_add_aliases("Get-In Helper", ["Get In Helper", "Get-in helper", "Get-In Helper"])
_add_aliases("Get-Out Helper", [])
_add_aliases("Stage Hand", [])
_add_aliases("Technician", ["Tech"])
_add_aliases("Carpenter", [])
_add_aliases("Head Carpenter", [])
_add_aliases("Master Carpenter", [])
_add_aliases("Production Assistant", [])
_add_aliases("Production Manager", [])
_add_aliases("Company Manager", [])
_add_aliases("Front of House", [])
_add_aliases("Welfare", ["Welfare Officer", "Welfare Rep"])
_add_aliases("Education", ["Education Officer", "Education Team"])
_add_aliases("Selection Committee", ["Film Selection Committee", "Film Selection"])
_add_aliases("Unknown", [])


def canonicalize_role(role_name: str) -> str | None:
    raw = html.unescape((role_name or "").strip())
    if not raw:
        return "Unknown"
    cleaned = _normalize_spaces(_strip_date_suffix(_normalize_numbering(raw)))
    lowered = cleaned.casefold()
    if lowered in _OBVIOUS_NON_ROLE_SINGLE_TOKENS and " " not in lowered and "/" not in lowered:
        return None

    key = _normalize_key(cleaned)
    if key in _ALIASES:
        return _ALIASES[key]

    singular_key = _singularize_simple(key)
    if singular_key in _ALIASES:
        return _ALIASES[singular_key]

    # Generic co-role merge: Co-X -> X when X is known.
    for prefix in ("co-", "co "):
        if key.startswith(prefix):
            base_key = key[len(prefix):]
            if base_key in _ALIASES:
                return _ALIASES[base_key]
            base_singular = _singularize_simple(base_key)
            if base_singular in _ALIASES:
                return _ALIASES[base_singular]

    # Fallback: keep normalized title while merging simple plurals.
    fallback = _singularize_simple(cleaned)
    return fallback or "Unknown"


def main_group_for_category(category: str) -> str:
    if category == "Music (Orchestra & Music Dept)":
        return "Band"
    if category == "Performance":
        return "Cast"
    if category in {
        "Sound",
        "Lighting",
        "Stage Management",
        "Technical (General / Crew / Build)",
        "Design (Set/Costume/Props/Projection)",
        "Media (Photo/Video)",
    }:
        return "Tech"
    return "Prod"


_EXPLICIT_CATEGORY: dict[str, str] = {
    "Actor": "Performance",
    "Cast": "Performance",
    "Chorus": "Performance",
    "Compere": "Performance",
    "Ensemble": "Performance",
    "Narrator": "Performance",
    "Performer": "Performance",
    "Singer": "Performance",
    "Soloist": "Performance",
    "Writer": "Writing",
    "Script Editor": "Writing",
    "Writer/Director": "Directing & Creative Leadership",
    "Writer/Performer": "Writing",
    "Director": "Directing & Creative Leadership",
    "Assistant Director": "Directing & Creative Leadership",
    "Associate Director": "Directing & Creative Leadership",
    "Director/Producer": "Directing & Creative Leadership",
    "Producer": "Producing & Production Management",
    "Assistant Producer": "Producing & Production Management",
    "Associate Producer": "Producing & Production Management",
    "Executive Producer": "Producing & Production Management",
    "Production Assistant": "Producing & Production Management",
    "Production Manager": "Producing & Production Management",
    "Company Manager": "Producing & Production Management",
    "Assistant Stage Manager": "Stage Management",
    "Deputy Stage Manager": "Stage Management",
    "Stage Manager": "Stage Management",
    "Sound Operator": "Sound",
    "Sound Technician": "Sound",
    "Sound Assistant": "Sound",
    "Sound Designer": "Sound",
    "Assistant Sound Designer": "Sound",
    "Associate Sound Designer": "Sound",
    "Sound Design": "Sound",
    "Sound Engineer": "Sound",
    "Mic Runner": "Sound",
    "Lighting (General)": "Lighting",
    "Chief Electrician": "Lighting",
    "Production Electrician": "Lighting",
    "Lighting Operator": "Lighting",
    "Followspot Operator": "Lighting",
    "Lighting Designer": "Lighting",
    "Lighting Design": "Lighting",
    "Lighting Crew": "Lighting",
    "Lighting & Sound Designer": "Lighting",
    "Set Designer": "Design (Set/Costume/Props/Projection)",
    "Set Construction": "Technical (General / Crew / Build)",
    "Set Builder": "Technical (General / Crew / Build)",
    "Scenic Artist": "Design (Set/Costume/Props/Projection)",
    "Props": "Design (Set/Costume/Props/Projection)",
    "Props Manager": "Design (Set/Costume/Props/Projection)",
    "Props Assistant": "Design (Set/Costume/Props/Projection)",
    "Costume (General)": "Design (Set/Costume/Props/Projection)",
    "Costume Designer": "Design (Set/Costume/Props/Projection)",
    "Makeup (General)": "Design (Set/Costume/Props/Projection)",
    "Makeup Artist": "Design (Set/Costume/Props/Projection)",
    "Hair & Makeup Designer": "Design (Set/Costume/Props/Projection)",
    "Musical Director": "Music (Orchestra & Music Dept)",
    "Assistant Musical Director": "Music (Orchestra & Music Dept)",
    "Associate Musical Director": "Music (Orchestra & Music Dept)",
    "Conductor": "Music (Orchestra & Music Dept)",
    "Répétiteur": "Music (Orchestra & Music Dept)",
    "Orchestrator": "Music (Orchestra & Music Dept)",
    "Arranger": "Music (Orchestra & Music Dept)",
    "Composer": "Music (Orchestra & Music Dept)",
    "Lyricist": "Music (Orchestra & Music Dept)",
    "Librettist": "Music (Orchestra & Music Dept)",
    "Photographer": "Media (Photo/Video)",
    "Videographer": "Media (Photo/Video)",
    "Camera Operator": "Media (Photo/Video)",
    "Cinematographer": "Media (Photo/Video)",
    "Video Director": "Media (Photo/Video)",
    "Video Editor": "Media (Photo/Video)",
    "Graphic Designer": "Marketing (Publicity/Graphics)",
    "Poster Designer": "Marketing (Publicity/Graphics)",
    "Programme Designer": "Marketing (Publicity/Graphics)",
    "Web Designer": "Marketing (Publicity/Graphics)",
    "Publicity (General)": "Marketing (Publicity/Graphics)",
    "Publicity Designer": "Marketing (Publicity/Graphics)",
    "Publicity Design": "Marketing (Publicity/Graphics)",
    "Publicity Manager": "Marketing (Publicity/Graphics)",
    "Publicity Officer": "Marketing (Publicity/Graphics)",
    "Welfare": "Welfare & Student Support",
    "Education": "Welfare & Student Support",
    "Front of House": "Front of House",
    "Selection Committee": "Admin / Committees",
    "Unknown": "Unknown / Unclassified",
}


def categorize_role(canonical_role: str) -> str:
    role = canonical_role or "Unknown"
    if role in _EXPLICIT_CATEGORY:
        return _EXPLICIT_CATEGORY[role]

    lower = role.casefold()
    if "designer" in lower:
        if "sound" in lower:
            return "Sound"
        if "light" in lower or "lx" in lower or "followspot" in lower:
            return "Lighting"
        if any(k in lower for k in ["publicity", "graphic", "poster", "programme", "web"]):
            return "Marketing (Publicity/Graphics)"
        return "Design (Set/Costume/Props/Projection)"
    if any(k in lower for k in ["operator", "technician", "assistant"]):
        if "sound" in lower:
            return "Sound"
        if any(k in lower for k in ["light", "lx", "followspot"]):
            return "Lighting"
        if "stage manager" in lower:
            return "Stage Management"
        return "Technical (General / Crew / Build)"
    if any(k in lower for k in ["violin", "trumpet", "keys", "keyboard", "piano", "orchestra", "band", "choir"]):
        return "Music (Orchestra & Music Dept)"
    if any(k in lower for k in ["photo", "video", "camera", "cinematograph"]):
        return "Media (Photo/Video)"
    return "Unknown / Unclassified"
