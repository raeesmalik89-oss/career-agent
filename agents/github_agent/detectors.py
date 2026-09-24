"""File-level skill detectors.

Each detector looks at a real file (path + content) and emits evidence. Strength rules:
  high   - configuration/code/CI that actually uses the technology (a Dockerfile, a workflow, a .tf resource,
           Python that imports and calls a library)
  medium - declared but not clearly exercised (a dependency in requirements.txt, a one-line stub file)
  low    - only mentioned in prose (README/docs). Never enough to claim a skill on its own.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

import yaml


@dataclass(frozen=True)
class Evidence:
    skill: str
    evidence_type: str  # file | config | code | ci | test | docs
    path: str
    detail: str
    strength: str  # high | medium | low


Detector = Callable[[str, str], list[Evidence]]

# Python import name -> skill keys
PY_IMPORTS: dict[str, tuple[str, ...]] = {
    "fastapi": ("fastapi",),
    "flask": ("flask",),
    "django": ("django",),
    "streamlit": ("streamlit",),
    "sklearn": ("scikit_learn",),
    "tensorflow": ("tensorflow",),
    "keras": ("tensorflow",),
    "torch": ("pytorch",),
    "pandas": ("pandas",),
    "numpy": ("numpy",),
    "xgboost": ("xgboost",),
    "mlflow": ("mlflow",),
    "kafka": ("kafka",),
    "confluent_kafka": ("kafka",),
    "psycopg": ("postgresql",),
    "psycopg2": ("postgresql",),
    "asyncpg": ("postgresql",),
    "sqlalchemy": ("sql",),
    "redis": ("redis",),
    "pymongo": ("mongodb",),
    "prometheus_client": ("prometheus",),
    "opentelemetry": ("opentelemetry",),
    "boto3": ("aws",),
    "azure": ("azure",),
    "google.cloud": ("gcp",),
    "langchain": ("langchain",),
    "langgraph": ("langgraph",),
    "openai": ("llm",),
    "anthropic": ("llm",),
    "transformers": ("hugging_face",),
    "selenium": ("selenium",),
    "pytest": ("pytest",),
    "kubernetes": ("kubernetes",),
    "docker": ("docker",),
    "jwt": ("oauth2",),
    "keycloak": ("keycloak",),
    "pyspark": ("spark",),
    "airflow": ("airflow",),
    "shap": ("machine_learning",),
    "lightgbm": ("ensembles",),
    "requests": ("rest_api",),
    "hvac": ("hashicorp_vault",),
    # vector stores and agent frameworks
    "chromadb": ("vector_database",),
    "faiss": ("vector_database",),
    "pinecone": ("vector_database",),
    "qdrant_client": ("vector_database",),
    "weaviate": ("vector_database",),
    "pgvector": ("pgvector",),
    "llama_index": ("llm",),
    "crewai": ("agentic_ai",),
    "autogen": ("agentic_ai",),
    "mcp": ("mcp",),
    "ddtrace": ("datadog",),
    "datadog": ("datadog",),
}
# requirements.txt / pyproject package name -> skill keys
PY_PACKAGES = {
    **{k.replace(".", "-"): v for k, v in PY_IMPORTS.items()},
    "scikit-learn": ("scikit_learn",),
    "kafka-python": ("kafka",),
    "confluent-kafka": ("kafka",),
    "psycopg2-binary": ("postgresql",),
    "prometheus-client": ("prometheus",),
    "python-jose": ("oauth2",),
    "pyjwt": ("oauth2",),
    "gunicorn": ("python",),
    "uvicorn": ("fastapi",),
}
JS_PACKAGES = {
    "react": ("react",),
    "express": ("nodejs",),
    "next": ("react",),
    "typescript": ("typescript",),
    "jest": ("javascript",),
    "pg": ("postgresql",),
    "mongoose": ("mongodb",),
    "redis": ("redis",),
    "prom-client": ("prometheus",),
    "kafkajs": ("kafka",),
}
# docker image name fragment -> skill keys
IMAGES = {
    "prom/prometheus": ("prometheus",),
    "datadog/agent": ("datadog",),
    "prometheus": ("prometheus",),
    "grafana": ("grafana",),
    "alertmanager": ("alertmanager",),
    "jaegertracing": ("jaeger",),
    "otel/": ("opentelemetry",),
    "elasticsearch": ("elk",),
    "kibana": ("elk",),
    "logstash": ("elk",),
    "loki": ("loki",),
    "kafka": ("kafka",),
    "zookeeper": ("zookeeper",),
    "postgres": ("postgresql",),
    "mysql": ("mysql",),
    "mongo": ("mongodb",),
    "redis": ("redis",),
    "rabbitmq": ("rabbitmq",),
    "keycloak": ("keycloak",),
    "nginx": ("nginx",),
    "mlflow": ("mlflow",),
    "vault": ("hashicorp_vault",),
    "jenkins": ("jenkins",),
    "sonarqube": ("sonarqube",),
    "openpolicyagent": ("opa",),
    "airflow": ("airflow",),
}
TF_RESOURCES = {
    "aws_instance": "aws_ec2",
    "aws_s3_bucket": "aws_s3",
    "aws_eks_cluster": "eks",
    "aws_lambda_function": "aws_lambda",
    "aws_db_instance": "aws_rds",
    "aws_vpc": "aws_vpc",
    "aws_iam_": "iam",
    "aws_ecs_": "aws_ecs",
    "aws_sns_topic": "aws_sns",
    "aws_cloudwatch_": "cloudwatch",
    "aws_autoscaling_group": "auto_scaling",
    "aws_lb": "load_balancing",
    "aws_alb": "load_balancing",
    "azurerm_kubernetes_cluster": "aks",
    "azurerm_": "azure",
    "google_container_cluster": "gke",
    "google_": "gcp",
    "kubernetes_": "kubernetes",
    "helm_release": "helm",
}
TF_PROVIDERS = {"aws": "aws", "azurerm": "azure", "google": "gcp", "kubernetes": "kubernetes", "helm": "helm"}
CI_ACTIONS = {
    "aquasecurity/trivy-action": "trivy",
    "docker/build-push-action": "docker",
    "docker/login-action": "docker",
    "hashicorp/setup-terraform": "terraform",
    "azure/k8s-deploy": "kubernetes",
    "azure/setup-kubectl": "kubernetes",
    "azure/setup-helm": "helm",
    "aws-actions/configure-aws-credentials": "aws",
    "azure/login": "azure",
    "github/codeql-action": "sast",
    "sonarsource/": "sonarqube",
    "gitleaks/gitleaks-action": "supply_chain_security",
    "anchore/sbom-action": "supply_chain_security",
    "snyk/actions": "snyk",
}
CI_COMMANDS = {
    r"\bpytest\b": "pytest",
    r"\bkubectl\b": "kubernetes",
    r"\bhelm\s": "helm",
    r"\bterraform\s": "terraform",
    r"\bdocker\s+(build|push|compose)": "docker",
    r"\btrivy\b": "trivy",
    r"\bansible-playbook\b": "ansible",
    r"\bflake8|ruff|pylint|bandit\b": "sast",
    r"\baz\s": "azure",
    r"\baws\s": "aws",
    r"\bgitleaks\b": "supply_chain_security",
}
K8S_KINDS = {
    "HorizontalPodAutoscaler": "auto_scaling",
    "NetworkPolicy": "k8s_security",
    "PodSecurityPolicy": "pod_security_policy",
    "Ingress": "load_balancing",
}

_IMPORT_RX = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)


def _lines(text: str) -> int:
    return sum(1 for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#"))


def _yaml_docs(text: str) -> list[dict]:
    try:
        return [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]
    except yaml.YAMLError:
        return []


def _images(text: str) -> set[str]:
    found = set()
    for m in re.finditer(r"image:\s*['\"]?([\w./:@-]+)", text):
        img = m.group(1).lower()
        for frag, skills in IMAGES.items():
            if frag in img:
                found.update(skills)
    return found


def detect_dockerfile(path: str, text: str) -> list[Evidence]:
    name = path.rsplit("/", 1)[-1].lower()
    is_dockerfile = name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile")
    if not is_dockerfile or name.endswith((".md", ".txt", ".rst", ".html")):
        return []
    froms = re.findall(r"^\s*FROM\s+(\S+)", text, re.M | re.I)
    if not froms:
        return []
    out = [Evidence("docker", "config", path, f"Dockerfile FROM {', '.join(froms[:3])}", "high")]
    if re.search(r"^\s*USER\s+(?!root\b)\S+", text, re.M | re.I):
        out.append(Evidence("container_security", "config", path, "runs as a non-root USER", "medium"))
    if len(froms) > 1:
        out.append(Evidence("docker", "config", path, "multi-stage build", "high"))
    return out


def detect_compose(path: str, text: str) -> list[Evidence]:
    name = path.rsplit("/", 1)[-1].lower()
    if not re.fullmatch(r"(docker-)?compose[\w.-]*\.ya?ml", name):
        return []
    docs = _yaml_docs(text)
    services = (docs[0].get("services") or {}) if docs else {}
    if not isinstance(services, dict) or not services:
        return []
    out = [
        Evidence("docker_compose", "config", path, f"{len(services)} services: {', '.join(list(services)[:8])}", "high")
    ]
    out += [Evidence(s, "config", path, "service image in compose file", "medium") for s in sorted(_images(text))]
    return out


def detect_k8s(path: str, text: str) -> list[Evidence]:
    if not path.lower().endswith((".yaml", ".yml")) or "apiVersion" not in text or "kind" not in text:
        return []
    kinds = []
    out: list[Evidence] = []
    for d in _yaml_docs(text):
        kind, api = d.get("kind"), str(d.get("apiVersion", ""))
        if not isinstance(kind, str) or not api:
            continue
        if "kyverno.io" in api:
            out.append(Evidence("kyverno", "config", path, f"Kyverno {kind}", "high"))
            continue
        if api.startswith("argoproj.io"):
            out.append(Evidence("argocd", "config", path, f"Argo {kind}", "high"))
            continue
        kinds.append(kind)
        if kind in K8S_KINDS:
            out.append(Evidence(K8S_KINDS[kind], "config", path, f"Kubernetes {kind}", "high"))
    if kinds:
        out.append(Evidence("kubernetes", "config", path, f"manifests: {', '.join(sorted(set(kinds)))}", "high"))
        if re.search(r"securityContext|runAsNonRoot|readOnlyRootFilesystem|seccompProfile", text):
            out.append(Evidence("k8s_security", "config", path, "pod/container securityContext", "high"))
        if re.search(r"livenessProbe|readinessProbe", text):
            out.append(Evidence("kubernetes", "config", path, "liveness/readiness probes", "high"))
        out += [Evidence(s, "config", path, "container image in manifest", "medium") for s in sorted(_images(text))]
    return out


def detect_helm_kustomize(path: str, text: str) -> list[Evidence]:
    name = path.rsplit("/", 1)[-1]
    if name == "Chart.yaml":
        return [Evidence("helm", "config", path, "Helm chart", "high")]
    if name in ("kustomization.yaml", "kustomization.yml"):
        return [Evidence("kustomize", "config", path, "Kustomize overlay", "high")]
    return []


def detect_terraform(path: str, text: str) -> list[Evidence]:
    if not path.endswith(".tf"):
        return []
    resources = re.findall(r'^\s*(?:resource|data)\s+"([\w-]+)"', text, re.M)
    providers = re.findall(r'^\s*provider\s+"([\w-]+)"', text, re.M)
    providers += re.findall(r'source\s*=\s*"hashicorp/([\w-]+)"', text)
    modules = re.findall(r'^\s*module\s+"([\w-]+)"', text, re.M)
    if not (resources or providers or modules):
        return []
    strength = "high" if resources or modules else "medium"
    out = [Evidence("terraform", "config", path, f"{len(resources)} resources, {len(modules)} modules", strength)]
    seen: set[str] = set()
    for r in resources:
        for prefix, skill in TF_RESOURCES.items():
            if r.startswith(prefix) and skill not in seen:
                seen.add(skill)
                out.append(Evidence(skill, "config", path, f"Terraform resource {r}", "high"))
                break
    for p in providers:
        if p in TF_PROVIDERS and TF_PROVIDERS[p] not in seen:
            seen.add(TF_PROVIDERS[p])
            out.append(Evidence(TF_PROVIDERS[p], "config", path, f"Terraform provider {p}", "medium"))
    return out


def detect_ansible(path: str, text: str) -> list[Evidence]:
    low = path.lower()
    if low.endswith("ansible.cfg"):
        return [Evidence("ansible", "config", path, "ansible.cfg", "medium")]
    if not low.endswith((".yml", ".yaml")):
        return []
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if (
        isinstance(doc, list)
        and doc
        and isinstance(doc[0], dict)
        and "hosts" in doc[0]
        and ("tasks" in doc[0] or "roles" in doc[0])
    ):
        return [Evidence("ansible", "config", path, f"playbook targeting hosts={doc[0]['hosts']}", "high")]
    if "/roles/" in f"/{low}" and "/tasks/" in low:
        return [Evidence("ansible", "config", path, "Ansible role tasks", "high")]
    return []


def detect_ci(path: str, text: str) -> list[Evidence]:
    low = path.lower()
    out: list[Evidence] = []
    if low.startswith(".github/workflows/") and low.endswith((".yml", ".yaml")):
        out.append(Evidence("github_actions", "ci", path, "GitHub Actions workflow", "high"))
        for action, skill in CI_ACTIONS.items():
            if f"uses: {action}" in text.lower() or f"uses: '{action}" in text.lower():
                out.append(Evidence(skill, "ci", path, f"workflow step uses {action}", "high"))
    elif low.endswith(".gitlab-ci.yml"):
        out.append(Evidence("gitlab_ci", "ci", path, "GitLab CI pipeline", "high"))
    elif low.rsplit("/", 1)[-1] == "jenkinsfile":
        out.append(Evidence("jenkins", "ci", path, "Jenkinsfile pipeline", "high"))
    elif low.endswith("azure-pipelines.yml"):
        out.append(Evidence("azure_pipelines", "ci", path, "Azure Pipelines definition", "high"))
    if out:
        for rx, skill in CI_COMMANDS.items():
            if re.search(rx, text):
                out.append(Evidence(skill, "ci", path, f"pipeline step uses {skill}", "high"))
    return out


def detect_python(path: str, text: str) -> list[Evidence]:
    if path.endswith(".ipynb"):
        return _detect_notebook(path, text)
    if not path.endswith(".py"):
        return []
    n = _lines(text)
    out = [Evidence("python", "code", path, f"{n} lines", "high" if n >= 20 else "medium")]
    imports = {(m.group(1) or m.group(2)) for m in _IMPORT_RX.finditer(text)}
    for imp in sorted(imports):
        for mod, skills in PY_IMPORTS.items():
            if imp == mod or imp.startswith(mod + "."):
                out += [Evidence(s, "code", path, f"imports {imp}", "high" if n >= 10 else "medium") for s in skills]
    if re.search(r"\bIsolationForest\b", text):
        out.append(Evidence("isolation_forest", "code", path, "uses IsolationForest", "high"))
    if re.search(r"@(?:app|router|bp|api|blueprint)\.(?:route|get|post|put|patch|delete)\(", text):
        out.append(Evidence("rest_api", "code", path, "defines HTTP API routes", "high"))
    if re.search(r"\b(RandomForest|GradientBoosting|XGB|Bagging|AdaBoost)\w*\(", text):
        out.append(Evidence("ensembles", "code", path, "trains an ensemble model", "high"))
    vector = {s for e in out for s in [e.skill] if s in ("vector_database", "pgvector")}
    if vector and re.search(r"\b(embed(ding)?s?|similarity_search|as_retriever|retriev\w*)\b", text):
        out.append(Evidence("rag", "code", path, "retrieves from a vector store for generation", "high"))
    if re.search(r"\b(StateGraph|create_react_agent|AgentExecutor|@tool\b|tools\s*=\s*\[)", text):
        out.append(Evidence("agentic_ai", "code", path, "defines an agent with tools", "high"))
    name = path.rsplit("/", 1)[-1]
    if name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{path}":
        out.append(Evidence("pytest", "test", path, "automated test file", "high"))
    return out


def _detect_notebook(path: str, text: str) -> list[Evidence]:
    import json

    try:
        cells = json.loads(text).get("cells", [])
    except (ValueError, AttributeError):
        return []
    code = "\n".join("".join(c.get("source", [])) for c in cells if c.get("cell_type") == "code")
    out = [Evidence("jupyter", "code", path, f"{len(cells)} cells", "high")]
    for ev in detect_python(path[:-6] + ".py", code):
        if ev.skill != "pytest":
            out.append(Evidence(ev.skill, ev.evidence_type, path, ev.detail, ev.strength))
    return out


def detect_dependencies(path: str, text: str) -> list[Evidence]:
    name = path.rsplit("/", 1)[-1].lower()
    out: list[Evidence] = []
    if name.startswith("requirements") and name.endswith(".txt") or name == "pyproject.toml":
        for m in re.finditer(r"^\s*['\"]?([A-Za-z0-9_.-]+)", text, re.M):
            pkg = m.group(1).lower()
            for skill in PY_PACKAGES.get(pkg, ()):
                out.append(Evidence(skill, "config", path, f"dependency {pkg}", "medium"))
    elif name == "package.json":
        import json

        try:
            data = json.loads(text)
        except ValueError:
            return []
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        out.append(Evidence("javascript", "config", path, f"{len(deps)} npm dependencies", "medium"))
        for pkg in deps:
            for skill in JS_PACKAGES.get(pkg.lower(), ()):
                out.append(Evidence(skill, "config", path, f"dependency {pkg}", "medium"))
    return out


def detect_scripts_and_misc(path: str, text: str) -> list[Evidence]:
    low = path.lower()
    name = low.rsplit("/", 1)[-1]
    if low.endswith(".sh"):
        n = _lines(text)
        return [Evidence("bash", "code", path, f"{n} lines", "high" if n >= 10 else "medium")]
    for exts, lang in (((".js", ".jsx", ".mjs"), "javascript"), ((".ts", ".tsx"), "typescript")):
        if low.endswith(exts):
            n = _lines(text)
            return [Evidence(lang, "code", path, f"{n} lines", "high" if n >= 20 else "medium")]
    if low.endswith(".sql"):
        return [Evidence("sql", "code", path, f"{_lines(text)} lines", "medium")]
    if low.endswith((".ps1", ".psm1")):
        n = _lines(text)
        return [Evidence("powershell", "code", path, f"{n} lines", "high" if n >= 10 else "medium")]
    if low.endswith(".java"):
        n = _lines(text)
        return [Evidence("java", "code", path, f"{n} lines", "high" if n >= 20 else "medium")]
    if name in ("pom.xml", "build.gradle", "build.gradle.kts"):
        return [Evidence("java", "config", path, f"{name} build", "high")]
    if name in ("datadog.yaml", "datadog.yml") or re.search(r"^\s*datadog:\s*$", text, re.M) and "apiKey" in text:
        return [Evidence("datadog", "config", path, "Datadog agent configuration", "high")]
    if re.search(r"^\s*(apiVersion:\s*(sloth\.slok\.dev|openslo)|slos:\s*$)", text, re.M | re.I):
        return [Evidence("slo", "config", path, "SLO definition (Sloth / OpenSLO)", "high")]
    if re.search(r"^\s*-?\s*record:\s*\S*(slo|sli|error_budget)\S*", text, re.M | re.I):
        return [Evidence("slo", "config", path, "Prometheus SLO / error-budget recording rules", "high")]
    if low.endswith(".rego"):
        return [Evidence("opa", "config", path, "Rego policy", "high")]
    if name in ("prometheus.yml", "prometheus.yaml") or re.search(r"^\s*scrape_configs:", text, re.M):
        return [Evidence("prometheus", "config", path, "Prometheus scrape config", "high")]
    if name in ("alertmanager.yml", "alertmanager.yaml"):
        return [Evidence("alertmanager", "config", path, "Alertmanager config", "high")]
    if re.search(r"^\s*groups:\s*$", text, re.M) and re.search(r"^\s*-?\s*alert:", text, re.M):
        return [Evidence("prometheus", "config", path, "Prometheus alerting rules", "high")]
    if "grafana" in low and low.endswith((".json", ".yml", ".yaml")):
        return [Evidence("grafana", "config", path, "Grafana dashboard/provisioning", "high")]
    if name in (".pre-commit-config.yaml", ".gitleaks.toml") or name == "trivy.yaml":
        return [Evidence("supply_chain_security", "config", path, name, "medium")]
    if "keycloak" in low and low.endswith(".json") and '"realm"' in text:
        return [Evidence("keycloak", "config", path, "Keycloak realm export", "high")]
    if name == "mlproject":
        return [Evidence("mlflow", "config", path, "MLflow project", "high")]
    return []


DETECTORS: list[Detector] = [
    detect_dockerfile,
    detect_compose,
    detect_k8s,
    detect_helm_kustomize,
    detect_terraform,
    detect_ansible,
    detect_ci,
    detect_python,
    detect_dependencies,
    detect_scripts_and_misc,
]


def detect_file(path: str, text: str) -> list[Evidence]:
    out: list[Evidence] = []
    for det in DETECTORS:
        try:
            out.extend(det(path, text))
        except Exception:  # noqa: BLE001, S112 - one malformed file must not abort a repository scan
            continue
    return out


# Skills a file detector can actually observe. Anything else (e.g. "AIOps", "microservices") is a concept that
# a repository cannot prove or disprove, so project verification reports it as "not checkable".
DETECTABLE: frozenset[str] = frozenset(
    {
        s
        for skills in (*PY_IMPORTS.values(), *PY_PACKAGES.values(), *JS_PACKAGES.values(), *IMAGES.values())
        for s in skills
    }
    | set(TF_RESOURCES.values())
    | set(TF_PROVIDERS.values())
    | set(CI_ACTIONS.values())
    | set(CI_COMMANDS.values())
    | set(K8S_KINDS.values())
    | {
        "docker",
        "docker_compose",
        "container_security",
        "kubernetes",
        "k8s_security",
        "kyverno",
        "argocd",
        "helm",
        "kustomize",
        "terraform",
        "ansible",
        "github_actions",
        "gitlab_ci",
        "jenkins",
        "azure_pipelines",
        "python",
        "pytest",
        "isolation_forest",
        "ensembles",
        "jupyter",
        "bash",
        "javascript",
        "typescript",
        "sql",
        "opa",
        "prometheus",
        "alertmanager",
        "grafana",
        "supply_chain_security",
        "keycloak",
        "mlflow",
    }
)
