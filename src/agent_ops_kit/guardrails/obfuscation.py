"""Normalização anti-ofuscação: homoglyphs, zero-width, token-splitting e Base64/Hex."""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata

from .verdict import strip_invisible

# Mapeamento de confusables cirílicos e gregos comuns para ASCII equivalente.
_HOMOGLYPHS: dict[str, str] = {
    # Cirílico -> ASCII
    "\u0430": "a",  # а
    "\u0410": "A",  # А
    "\u0412": "B",  # В
    "\u0441": "c",  # с
    "\u0421": "C",  # С
    "\u0501": "d",  # ԁ
    "\u0435": "e",  # е
    "\u0415": "E",  # Е
    "\u0451": "e",  # ё
    "\u0401": "E",  # Ё
    "\u04bb": "h",  # һ
    "\u041d": "H",  # Н
    "\u0456": "i",  # і
    "\u0406": "I",  # І
    "\u0457": "i",  # ї
    "\u0407": "I",  # Ї
    "\u0458": "j",  # ј
    "\u0408": "J",  # Ј
    "\u043a": "k",  # к
    "\u041a": "K",  # К
    "\u04cf": "l",  # ӏ
    "\u04c0": "I",  # Ӏ
    "\u041c": "M",  # М
    "\u043e": "o",  # о
    "\u041e": "O",  # О
    "\u0440": "p",  # р
    "\u0420": "P",  # Р
    "\u0455": "s",  # ѕ
    "\u0405": "S",  # Ѕ
    "\u0422": "T",  # Т
    "\u0443": "y",  # у
    "\u0423": "Y",  # У
    "\u0445": "x",  # х
    "\u0425": "X",  # Х
    # Grego -> ASCII
    "\u03b1": "a",  # α
    "\u0391": "A",  # Α
    "\u03b2": "b",  # β
    "\u0392": "B",  # Β
    "\u03b5": "e",  # ε
    "\u0395": "E",  # Ε
    "\u0396": "Z",  # Ζ
    "\u0397": "H",  # Η
    "\u03b9": "i",  # ι
    "\u0399": "I",  # Ι
    "\u03ba": "k",  # κ
    "\u039a": "K",  # Κ
    "\u039c": "M",  # Μ
    "\u03bd": "v",  # ν
    "\u039d": "N",  # Ν
    "\u03bf": "o",  # ο
    "\u039f": "O",  # Ο
    "\u03c1": "p",  # ρ
    "\u03a1": "P",  # Ρ
    "\u03c2": "c",  # ς
    "\u03f2": "c",  # ϲ
    "\u03f9": "C",  # Ϲ
    "\u03c4": "t",  # τ
    "\u03a4": "T",  # Τ
    "\u03c5": "u",  # υ
    "\u03a5": "Y",  # Υ
    "\u03c7": "x",  # χ
    "\u03a7": "X",  # Χ
}
_HOMOGLYPH_TRANS = str.maketrans(_HOMOGLYPHS)

_PUNCT_SPLIT_RE = re.compile(
    r"(?<![A-Za-zÀ-ÿ0-9])([A-Za-zÀ-ÿ]{1,2}(?:[.\-_][A-Za-zÀ-ÿ]{1,2}){2,})(?![A-Za-zÀ-ÿ0-9])"
)
_SPACE_SPLIT_RE = re.compile(
    r"(?<![A-Za-zÀ-ÿ0-9])([A-Za-zÀ-ÿ](?:[ \t][A-Za-zÀ-ÿ]){2,})(?![A-Za-zÀ-ÿ0-9])"
)
_CONTINUOUS_ATTACK_WORDS = re.compile(
    r"(?i)(ignore|disregard|forget|override|bypass|reveal|show|print|repeat|display|dump"
    r"|mostre|revel[ea]?|exib[ae]?|imprim[ae]?|esquec[ae]|esque[çc]a|desconsidere|anule"
    r"|previous|anteriores|all|todas|suas|your|instructions|instru[cç][oõ]es|regras|rules"
    r"|system|sistema|prompt|secrets?|segredos?|canary|developer|mode|modo|desenvolvedor|jailbreak)"
)

_B64_CANDIDATE_RE = re.compile(
    r"(?<![A-Za-z0-9+/=_-])([A-Za-z0-9+/_-]{14,}={0,2})(?![A-Za-z0-9+/=_-])"
)
_HEX_COMPACT_RE = re.compile(r"(?<![A-Za-z0-9])(?:0[xX])?([0-9a-fA-F]{20,})(?![A-Za-z0-9])")
_HEX_SPACED_RE = re.compile(
    r"(?<![A-Za-z0-9])((?:0[xX])?[0-9a-fA-F]{2}(?:[ \t]+(?:0[xX])?[0-9a-fA-F]{2}){9,})(?![A-Za-z0-9])"
)


def deobfuscate_homoglyphs(text: str) -> str:
    """Remove NFKC/zero-width (via `strip_invisible`), outros Cf e confusables para ASCII."""
    cleaned = "".join(c for c in strip_invisible(text) if unicodedata.category(c) != "Cf")
    return cleaned.translate(_HOMOGLYPH_TRANS)


def _collapse_punct_match(match: re.Match[str]) -> str:
    token = match.group(1)
    parts = re.split(r"[.\-_]", token)
    if all(len(p) == 1 for p in parts) or sum(len(p) for p in parts) >= 5:
        return "".join(parts)
    return token


def _collapse_space_match(match: re.Match[str]) -> str:
    collapsed = re.sub(r"[ \t]+", "", match.group(1))
    if len(collapsed) >= 12:
        spaced = _CONTINUOUS_ATTACK_WORDS.sub(r" \1 ", collapsed)
        return re.sub(r"\s+", " ", spaced).strip()
    return collapsed


def collapse_token_splitting(text: str) -> str:
    """Colapsa sequências de letras/tokens curtos separados por pontuação ou espaço único."""
    collapsed = _PUNCT_SPLIT_RE.sub(_collapse_punct_match, text)
    return _SPACE_SPLIT_RE.sub(_collapse_space_match, collapsed)


def _is_readable_utf8(raw: bytes) -> str | None:
    if not raw:
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    stripped = decoded.strip()
    if len(stripped) < 4:
        return None
    if any(ord(c) < 32 and c not in "\n\r\t" for c in decoded):
        return None
    printable = sum(1 for c in decoded if c.isprintable() or c in "\n\r\t")
    if printable / len(decoded) < 0.90:
        return None
    return decoded


def _try_decode_base64(token: str) -> str | None:
    if len(token) < 16:
        return None
    rem = len(token) % 4
    if rem == 1:
        return None
    padded = token if "=" in token or rem == 0 else token + ("=" * (4 - rem))
    try:
        if "-" in padded or "_" in padded:
            raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        else:
            raw = base64.b64decode(padded.encode("ascii"), validate=True)
    except (binascii.Error, ValueError):
        return None
    return _is_readable_utf8(raw)


def _try_decode_hex(hex_digits: str) -> str | None:
    if len(hex_digits) < 20 or len(hex_digits) % 2 != 0:
        return None
    try:
        raw = bytes.fromhex(hex_digits)
    except ValueError:
        return None
    return _is_readable_utf8(raw)


def decode_encoded_payloads(text: str) -> list[tuple[str, str]]:
    """Extrai payloads Base64 (>=16 chars) e Hex (>=20 dígitos) decodificados em UTF-8 legível."""
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(method: str, decoded: str | None) -> None:
        if decoded is None:
            return
        item = (method, decoded)
        if item not in seen:
            seen.add(item)
            found.append(item)

    for m in _B64_CANDIDATE_RE.finditer(text):
        _add("base64", _try_decode_base64(m.group(1)))

    for m in _HEX_COMPACT_RE.finditer(text):
        _add("hex", _try_decode_hex(m.group(1)))

    for m in _HEX_SPACED_RE.finditer(text):
        digits = re.sub(r"(?i)0x|\s+", "", m.group(1))
        _add("hex", _try_decode_hex(digits))

    return found


def expand_obfuscated_variants(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Gera variantes desofuscadas e payloads decodificados `[(metodo, texto)]`."""
    base = strip_invisible(text)
    homo = deobfuscate_homoglyphs(text)
    split_base = collapse_token_splitting(base)
    split_homo = collapse_token_splitting(homo)

    variants: list[str] = []
    for candidate in (base, homo, split_base, split_homo):
        if candidate and candidate not in variants:
            variants.append(candidate)

    decoded = decode_encoded_payloads(base)
    if homo != base:
        for item in decode_encoded_payloads(homo):
            if item not in decoded:
                decoded.append(item)
    return variants, decoded
