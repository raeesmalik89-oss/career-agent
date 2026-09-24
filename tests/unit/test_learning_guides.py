import copy

import pytest

from agents.skill_agent.learning import (
    MAX_NODES,
    GuideError,
    concept_map_markdown,
    concept_map_mermaid,
    concept_map_tree,
    get_guides,
    validate_concept_map,
    validate_guide,
)

GUIDES = get_guides()


def test_every_guide_is_valid_and_produces_evidence():
    assert {"sre", "gcp", "llm", "agentic_ai", "gitops", "vector_database"} <= set(GUIDES)
    for g in GUIDES.values():
        assert g["mini_project"]["evidence"] and all(r["url"].startswith("https://") for r in g["resources"])


def test_invented_commands_and_bad_links_are_rejected():
    g = copy.deepcopy(GUIDES["gitops"])
    g["commands"].append({"cmd": "argocdd app sync web", "what": "typo"})
    with pytest.raises(GuideError, match="known tool"):
        validate_guide(g)
    g = copy.deepcopy(GUIDES["gitops"])
    g["resources"].append({"title": "x", "url": "http://insecure.example.com"})
    with pytest.raises(GuideError, match="https"):
        validate_guide(g)
    g = copy.deepcopy(GUIDES["gitops"])
    g["mini_project"]["evidence"] = ""
    with pytest.raises(GuideError, match="evidence"):
        validate_guide(g)


def test_concept_map_limits():
    deep = {"concept": "x", "components": [{"label": "a", "children": [{"label": "b", "children": [
        {"label": "c", "children": [{"label": "d", "children": ["e"]}]}]}]}]}  # fmt: skip
    with pytest.raises(GuideError, match="deeper"):
        validate_concept_map("x", deep)
    wide = {"concept": "x", "components": [f"n{i}" for i in range(MAX_NODES)]}
    with pytest.raises(GuideError, match="nodes"):
        validate_concept_map("x", wide)


def test_renderers():
    cmap = GUIDES["gitops"]["concept_map"]
    mermaid = concept_map_mermaid(cmap)
    assert mermaid.startswith("mindmap\n  root((GitOps))") and "      Drift detection" in mermaid
    assert "(" not in mermaid.split("\n", 2)[2]  # node text cannot change Mermaid node shapes
    md = concept_map_markdown(cmap)
    assert md.startswith("# GitOps") and "## Interview traps" in md
    tree = concept_map_tree(cmap)
    assert tree["label"] == "GitOps" and tree["children"][0]["label"] == "Components"
