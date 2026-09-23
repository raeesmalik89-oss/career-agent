import pytest

from agents.resume_agent.extract import Extracted
from agents.resume_agent.merge import compatible, fact_key, merge_data, same_entity
from agents.taxonomy import SkillDef, Taxonomy, get_taxonomy

TAX = get_taxonomy()


def keys(text: str, skills_list: bool = False) -> list[str]:
    return [h.key for h in TAX.find(text, in_skills_list=skills_list)]


def test_word_boundaries():
    assert keys("Git and GitHub Actions") == ["git", "github_actions"]
    assert "git" not in keys("GitHub Actions only")
    assert keys("CI/CD with Docker/Kubernetes") == ["ci_cd", "docker", "kubernetes"]


def test_longest_surface_wins():
    assert keys("Docker Compose files") == ["docker_compose"]
    assert "docker" in TAX.implied("docker_compose")


def test_ambiguous_skills_only_in_skills_list():
    assert "go" not in keys("Go to the cloud")
    assert "go" in keys("Languages: Python, Go", skills_list=True)
    assert "go" not in keys("Languages: Python, go", skills_list=True)  # case-sensitive


def test_implied_is_transitive():
    assert {"azure", "kubernetes"} <= TAX.implied("aks")
    assert {"llm", "agentic_ai"} <= TAX.implied("langgraph")


def test_taxonomy_rejects_unknown_references():
    with pytest.raises(ValueError, match="unknown skill"):
        Taxonomy({"a": SkillDef("a", "A", "other", implies=("missing",))})


@pytest.mark.parametrize(
    "field, a, b, ok",
    [
        ("start", "2021", "2021-07", True),
        ("start", "2021", "2022", False),
        ("title", "DevOps Engineer", "DevOps Engineer ", True),
        (
            "title",
            "AIOps / DevOps Trainee (12-month Job Training Program)",
            "AIOps / DevOps Intern - Job Training",
            False,
        ),
        ("title", "DevOps Engineer", "Senior DevOps Engineer", False),
        ("qualification", "PG Diploma, English Language", "Post Graduate Diploma - English Language", True),
    ],
)
def test_compatible(field, a, b, ok):
    assert compatible(field, a, b) is ok


def test_merge_records_grouped_conflicts_and_unions_lists():
    old = {"title": "DevOps Engineer", "start": "2023", "responsibilities": ["a"], "technologies": ["docker"]}
    new = {"title": "Senior DevOps Engineer", "start": "2023-01", "responsibilities": ["b"], "technologies": ["docker"]}
    merged, conflicts = merge_data("experience", old, new, "cv1", "cv2")
    assert [c["field"] for c in conflicts] == ["title"]
    assert merged["title"] == "DevOps Engineer"  # first value kept; the user decides
    assert merged["responsibilities"] == ["a", "b"] and merged["technologies"] == ["docker"]
    third = {"title": "Senior DevOps Engineer"}
    merged, _ = merge_data("experience", merged, third, "cv1", "cv3")
    values = merged["conflicts"][0]["values"]
    assert len(merged["conflicts"]) == 1 and len(values) == 2
    assert values[1]["documents"] == ["cv2", "cv3"]


def test_merge_languages_union():
    merged, conflicts = merge_data(
        "personal",
        {"field": "languages", "value": [{"language": "English", "level": "Professional"}]},
        {"field": "languages", "value": [{"language": "english", "level": None}, {"language": "Urdu", "level": "N"}]},
        "a", "b",
    )  # fmt: skip
    assert [v["language"] for v in merged["value"]] == ["English", "Urdu"] and not conflicts


def test_fact_keys_and_fuzzy_identity():
    e1 = Extracted("experience", {"title": "X", "organization": "Acme Cloud Ltd", "start": "2023-01"}, [])
    e2 = Extracted("experience", {"title": "X", "organization": "Acme Cloud (Pvt) Ltd", "start": "2023"}, [])
    assert fact_key(e1) == fact_key(e2) == "acme cloud|2023"
    undated = {"title": None, "organization": "Acme Cloud Ltd", "start": None}
    assert same_entity("experience", e1.data, undated)
    assert not same_entity("experience", e1.data, {**e2.data, "start": "2019"})
    edu_a = {"qualification": "BS Computer Science", "date": "2022"}
    edu_b = {"qualification": "Bachelor of Science in Computer Science", "date": None}
    assert same_entity("education", edu_a, edu_b)
    assert not same_entity("education", edu_a, {"qualification": "MS Computer Science", "date": "2022"})
