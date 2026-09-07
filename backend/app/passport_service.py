"""Deterministic, art-free passport stamp styling. A trip's stamp accent
color is derived from its destination string alone -- same city always
stamps the same way, no per-city art asset or lookup table to maintain,
keeping this inside the $0 budget (CLAUDE.md constraint)."""
import hashlib

# A small fixed palette of existing Dusk City-adjacent hues (see
# docs/design-references.md's palette research) -- not arbitrary hex
# values, so a stamp always reads as "this app's colors," not a clashing
# one-off. Deliberately short; more variety isn't worth a maintained list.
STAMP_PALETTE = [
    "indigo", "copper", "teal", "amber", "rose", "violet", "emerald", "sky",
]


def accent_for_destination(destination: str) -> str:
    """One of STAMP_PALETTE's names, chosen deterministically from
    `destination` -- the same destination string always maps to the same
    color, with no state stored anywhere."""
    if not destination:
        return STAMP_PALETTE[0]
    digest = hashlib.md5(destination.encode("utf-8")).hexdigest()
    return STAMP_PALETTE[int(digest, 16) % len(STAMP_PALETTE)]
