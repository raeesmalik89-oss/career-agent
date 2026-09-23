import pytest

from agents.job_agent import extract as X
from agents.job_agent.ingest import fingerprint, norm_company, norm_title
from agents.taxonomy import get_taxonomy
from integrations.sources.base import HttpClient, JobPosting, SourceError, html_to_text, matches_any

TAX = get_taxonomy()


def posting(**kw) -> JobPosting:
    base = dict(
        source="test",
        external_id="1",
        title="DevOps Engineer",
        company="Acme",
        url="https://x/1",
        description="We build things.",
    )
    return JobPosting(**{**base, **kw})


@pytest.mark.parametrize(
    "title, family",
    [
        ("DevOps Engineer", "devops"),
        ("Senior Site Reliability Engineer", "sre"),
        ("Site Reliability Engineer, AI Infrastructure", "sre_ai"),
        ("MLOps Engineer", "mlops"),
        ("Senior Cloud Security Engineer", "devsecops"),
        ("Platform Engineer", "platform"),
        ("AI Engineer", "ai_engineer"),
        ("AIOps Engineer", "aiops"),
        ("Cloud Engineer", "cloud"),
        ("Kubernetes Administrator", "kubernetes"),
        ("Frontend Developer", None),
        ("Sales Engineer", None),
    ],
)
def test_role_family(title, family):
    assert X.classify_role(title) == family


@pytest.mark.parametrize(
    "title, hint, years, level",
    [
        ("Senior DevOps Engineer", None, None, "senior"),
        ("DevOps Intern", None, None, "intern"),
        ("Associate Cloud Engineer", None, None, "junior"),
        ("Staff SRE", None, None, "staff"),
        ("Engineering Manager, DevOps", None, None, "manager"),
        ("DevOps Engineer", "Mid-level", None, "mid"),
        ("DevOps Engineer", None, 1, "entry"),
        ("DevOps Engineer", None, 6, "senior"),
        ("DevOps Engineer", None, None, None),
    ],
)
def test_seniority(title, hint, years, level):
    assert X.classify_seniority(title, hint, years)[0] == level


@pytest.mark.parametrize(
    "text, years",
    [
        ("3+ years of experience with Kubernetes", 3),
        ("5-7 years experience", 5),
        ("At least 2 years of hands-on DevOps experience; 4+ years experience preferred", 2),
        ("We were founded 10 years ago", None),
    ],
)
def test_years(text, years):
    assert X.extract_years(text)[0] == years


def test_salary_only_from_source():
    assert X.extract_salary(posting(salary_text="$90k - $105k"))[:3] == (90000, 105000, "USD")
    assert X.extract_salary(posting(description="Pay: PKR 300,000 - 400,000 per month"))[:3] == (300000, 400000, "PKR")
    assert X.extract_salary(posting(salary_min=50000, salary_max=60000, salary_currency="EUR"))[:3] == (
        50000,
        60000,
        "EUR",
    )
    assert X.extract_salary(posting(description="Competitive salary"))[:3] == (None, None, None)


@pytest.mark.parametrize(
    "kw, expected",
    [
        ({"remote_hint": "hybrid"}, "hybrid"),
        ({"description": "This is a fully remote position."}, "remote"),
        ({"description": "Experience with remote debugging tools.", "location": "Berlin"}, "onsite"),
        ({"location": "Islamabad"}, "onsite"),
        ({}, "unknown"),
    ],
)
def test_remote_type(kw, expected):
    assert X.remote_type(posting(**kw))[0] == expected


@pytest.mark.parametrize(
    "kw, expected, evidence_part",
    [
        ({"remote_hint": "remote", "location_restrictions": ["USA", "Canada"]}, "ineligible", "USA"),
        ({"remote_hint": "remote", "location_restrictions": ["Worldwide"]}, "eligible", "Worldwide"),
        ({"remote_hint": "remote", "location_restrictions": ["Pakistan", "India"]}, "eligible", "Pakistan"),
        ({"remote_hint": "remote", "location": "Remote, Canada; Remote, United States"}, "ineligible", "Canada"),
        ({"remote_hint": "onsite", "location": "Islamabad, Pakistan"}, "eligible", "Islamabad"),
        ({"remote_hint": "hybrid", "location": "Berlin"}, "ineligible", "Berlin"),
        (
            {"remote_hint": "remote", "description": "You must be located in the United States."},
            "ineligible",
            "must be located in",
        ),
        ({"remote_hint": "remote", "description": "Security clearance required."}, "ineligible", "clearance"),
        ({"remote_hint": "remote", "description": "Hours overlap with UTC+3 to UTC+7."}, "eligible", "UTC+5"),
        ({"remote_hint": "remote", "raw": {"timezoneRestrictions": [4, 5, 6]}}, "eligible", "UTC+5"),
        ({"remote_hint": "remote", "raw": {"timezoneRestrictions": [-5, -4]}}, "ineligible", "excludes"),
        ({"remote_hint": "remote", "description": "Work from anywhere in the world."}, "eligible", "anywhere"),
        ({"remote_hint": "remote"}, "unknown", "Evidence not found."),
    ],
)
def test_pk_eligibility_always_has_evidence(kw, expected, evidence_part):
    p = posting(**kw)
    status, evidence = X.pk_eligibility(p, X.remote_type(p)[0])
    assert status == expected and evidence_part in evidence


def test_skills_required_vs_preferred():
    p = posting(
        title="DevOps Engineer",
        description=(
            "Our team runs Datadog.\n\nAbout us\nWe love Splunk.\n\nRequirements:\n- Kubernetes and Terraform\n\n"
            "Nice to have:\n- Helm\n\n"
            "Benefits:\n- Python training budget"
        ),
        tags=["aws"],
    )
    got = {s["skill"]: s["requirement"] for s in X.extract_skills(p, TAX)}
    assert got["kubernetes"] == "required" and got["terraform"] == "required"
    assert got["helm"] == "preferred" and got["datadog"] == "preferred" and got["aws"] == "preferred"
    assert "python" not in got and "splunk" not in got  # benefits / about-us sections are ignored


def test_visa_and_clearance():
    a = X.analyze(posting(description="We offer visa sponsorship is available for this role."), TAX)
    assert a.visa == "sponsorship available"
    a = X.analyze(posting(description="Unfortunately we cannot sponsor visas. Security clearance required."), TAX)
    assert a.visa == "no sponsorship" and a.clearance_required


def test_normalisation_and_fingerprint():
    assert norm_company("Acme Cloud (Pvt) Ltd.") == "acme cloud"
    assert norm_title("DevOps Engineer (m/w/d)") == norm_title("DevOps Engineer - Remote") == "devops engineer"
    assert fingerprint("Acme Inc", "DevOps Engineer (Remote)") == fingerprint("ACME", "DevOps Engineer")
    assert fingerprint("Acme", "Senior DevOps Engineer") != fingerprint("Acme", "DevOps Engineer")


def test_text_helpers():
    assert html_to_text("&lt;p&gt;Hello&lt;/p&gt;&lt;ul&gt;&lt;li&gt;A&lt;/li&gt;&lt;/ul&gt;") == "Hello\n\n- A"
    assert matches_any("Senior DevOps Engineer", ["devops engineer"])
    assert not matches_any("Frontend Engineer", ["devops engineer"])


def test_http_client_blocks_other_hosts():
    http = HttpClient({"remotive.com"})
    for url in (
        "https://evil.example.com/x",
        "http://remotive.com/api",
        "https://169.254.169.254/latest",
        "file:///etc/passwd",
    ):
        with pytest.raises(SourceError, match="blocked"):
            http.get_json(url)
