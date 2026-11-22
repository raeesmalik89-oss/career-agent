"""The focus-area CVs must reference real taxonomy skill categories, or they would emphasise nothing."""

from agents.application_agent.package import FOCUS_CATEGORIES
from agents.taxonomy import get_taxonomy


def test_focus_categories_exist_in_taxonomy():
    categories = {s.category for s in get_taxonomy().skills.values()}
    for focus, families in FOCUS_CATEGORIES.items():
        assert families, f"{focus} has no categories"
        for c in families:
            assert c in categories, f"focus {focus!r} references unknown taxonomy category {c!r}"
