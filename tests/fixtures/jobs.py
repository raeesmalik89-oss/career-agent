"""Mock job data (fictional companies) and a fake HTTP client, so job-source tests never touch the network."""

from datetime import UTC, datetime, timedelta

from integrations.sources.base import SourceError

NOW = datetime.now(UTC)


def _date(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


# A neutral introduction (no skills, places or levels) so each mock reads as a full posting, not a summary.
INTRO = (
    "We are a small product company building tools that our customers rely on every day. You will join a friendly "
    "team that cares about calm, well-documented work, clear ownership and steady delivery. Day to day you will "
    "improve how our services are built, shipped and looked after, pair with colleagues on tricky problems, write "
    "short design notes, and help new teammates find their feet. We value curiosity, kindness and good judgement."
)
REQ = (
    INTRO + "\n\nRequirements:\n- {years} years of experience with {req}\n\nNice to have:\n- {nice}\n\n"
    "Benefits:\n- Laptop"
)

# (title, company, location restriction, required skills, nice-to-have, years, salary, days ago)
MOCK_SPECS = [
    (
        "DevOps Engineer",
        "Northwind Cloud",
        "Worldwide",
        "Docker, Kubernetes, Terraform",
        "Prometheus",
        2,
        "$60k - $80k",
        1,
    ),
    ("Junior DevOps Engineer", "Blue Harbor", "Pakistan, India", "Docker, GitHub Actions, Linux", "AWS", 1, "", 2),
    (
        "Site Reliability Engineer",
        "Quantum Loop",
        "USA",
        "Kubernetes, Prometheus, Grafana",
        "Go",
        4,
        "$150k - $180k",
        1,
    ),
    ("Senior SRE", "Aurora Grid", "Europe", "Kubernetes, Terraform, AWS", "Datadog", 6, "", 3),
    ("MLOps Engineer", "Helix AI", "Worldwide", "Python, MLflow, Docker, Kubernetes", "Kubeflow", 3, "", 2),
    ("AI Engineer", "Cortex Labs", "APAC", "Python, LangChain, RAG", "LangGraph", 2, "", 5),
    ("Cloud Engineer", "Stratus Works", "Canada", "AWS, Terraform, Python", "Ansible", 3, "", 4),
    ("Platform Engineer", "Keel Systems", "Worldwide", "Kubernetes, Helm, ArgoCD", "Istio", 3, "", 6),
    ("DevSecOps Engineer", "Shieldline", "EMEA", "Trivy, OPA, GitHub Actions", "Vault", 3, "", 2),
    ("AIOps Engineer", "Pulse Health", "Worldwide", "Python, Prometheus, anomaly detection", "Kafka", 2, "", 1),
    ("Kubernetes Administrator", "Orbit Ops", "UK", "Kubernetes, Linux, Bash", "Helm", 3, "", 7),
    ("Senior Cloud Security Engineer", "Vaultify", "USA", "AWS, IAM, Terraform", "Kyverno", 7, "", 3),
    ("DevOps Engineer (Azure)", "Cedar Health", "Worldwide", "Azure, AKS, Azure DevOps", "Terraform", 2, "", 2),
    ("Machine Learning Engineer", "Signal Forge", "Worldwide", "Python, scikit-learn, XGBoost", "MLflow", 3, "", 8),
    ("Site Reliability Engineer II", "Tidepool", "Asia", "Kubernetes, Prometheus, Python", "Jaeger", 3, "", 2),
    ("DevOps Intern", "Seedling", "Worldwide", "Linux, Docker", "Git", 1, "", 1),
    ("Staff Platform Engineer", "Monolith Inc", "USA", "Kubernetes, Go, Terraform", "Envoy", 10, "", 9),
    ("Cloud Infrastructure Engineer", "Nimbus", "Worldwide", "GCP, Terraform, Kubernetes", "Pulumi", 4, "", 3),
    ("LLM Engineer", "Wordsmith AI", "Europe", "Python, LLMs, RAG", "vector database", 3, "", 2),
    ("DevOps Engineer", "Harbor Freight Digital", "Worldwide", "Jenkins, Docker, Ansible", "AWS", 2, "", 10),
    ("SRE - Observability", "Lumen Metrics", "Worldwide", "OpenTelemetry, Prometheus, Grafana", "Loki", 3, "", 4),
    ("Associate Cloud Engineer", "Brightpath", "Pakistan", "Azure, Linux, PowerShell", "Terraform", 1, "", 2),
    ("MLOps Platform Engineer", "Tensorworks", "USA", "Kubeflow, Kubernetes, Python", "Ray", 5, "", 5),
    ("DevOps Engineer", "Kestrel Pay", "Worldwide", "AWS, Kubernetes, GitLab CI", "Vault", 3, "$70k - $90k", 3),
    ("Senior DevOps Engineer", "Granite Bank", "Germany", "Terraform, AWS, Kubernetes", "OPA", 6, "", 2),
    ("AI Platform Engineer", "Synapse Cloud", "Worldwide", "Kubernetes, Python, LLMs", "vLLM", 4, "", 6),
    ("Cloud Engineer", "Monsoon Tech", "Pakistan, UAE, Saudi Arabia", "AWS, Docker, Linux", "Terraform", 2, "", 1),
    ("DevOps Engineer", "Glacier Data", "Latin America", "Kubernetes, Helm, AWS", "Karpenter", 3, "", 4),
    (
        "Site Reliability Engineer",
        "Ember Games",
        "Worldwide",
        "Kubernetes, Prometheus, Terraform",
        "Chaos engineering",
        4,
        "",
        2,
    ),
    ("DevSecOps Engineer", "Citadel Soft", "Worldwide", "SAST, Trivy, Kubernetes security", "Falco", 3, "", 5),
    ("Cloud Operations Engineer", "Tundra Systems", "Worldwide", "AWS, Linux, Bash", "CloudWatch", 2, "", 3),
    ("SRE Team Lead", "Quasar Net", "EMEA", "Kubernetes, Terraform, Prometheus", "Go", 8, "", 4),
    ("Frontend Developer", "Pixel Corp", "Worldwide", "React, TypeScript", "Figma", 3, "", 1),
    ("Old DevOps Role", "Fossil Ltd", "Worldwide", "Docker", "Kubernetes", 2, "", 120),
]


def remotive_job(i: int, spec: tuple) -> dict:
    title, company, loc, req, nice, years, salary, days = spec
    return {
        "id": 10_000 + i,
        "url": f"https://remotive.com/remote-jobs/devops/job-{i}",
        "title": title,
        "company_name": company,
        "category": "DevOps",
        "tags": [],
        "job_type": "full_time",
        "publication_date": _date(days),
        "candidate_required_location": loc,
        "salary": salary,
        "description": "<p>" + REQ.format(years=years, req=req, nice=nice).replace("\n", "<br>") + "</p>",
    }


def remotive_payload(specs: list[tuple] | None = None) -> dict:
    return {"jobs": [remotive_job(i, s) for i, s in enumerate(specs or MOCK_SPECS)]}


def himalayas_payload(specs: list[tuple]) -> dict:
    jobs = []
    for i, (title, company, loc, req, nice, years, _salary, days) in enumerate(specs):
        jobs.append(
            {
                "title": title,
                "companyName": company,
                "guid": f"https://himalayas.app/jobs/{i}",
                "applicationLink": f"https://himalayas.app/jobs/{i}/apply",
                "locationRestrictions": [loc],
                "employmentType": "Full Time",
                "seniority": [],
                "pubDate": int((NOW - timedelta(days=days)).timestamp()),
                "description": REQ.format(years=years, req=req, nice=nice),
                "categories": [],
            }
        )
    return {"jobs": jobs}


class FakeHttp:
    """Stands in for HttpClient: URL-prefix -> payload (or exception)."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.requests = 0
        self.calls: list[str] = []

    def _lookup(self, url: str):
        self.requests += 1
        self.calls.append(url)
        for prefix, value in self.routes.items():
            if url.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return value
        raise SourceError(f"HTTP 404 from {url}")

    def get_json(self, url: str):
        return self._lookup(url)

    def get_text(self, url: str) -> str:
        return self._lookup(url)

    def post_json(self, url: str, payload: dict):
        return self._lookup(url)
