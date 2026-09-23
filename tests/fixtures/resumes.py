"""Synthetic resumes for a fictional person. Never put real personal data in fixtures."""

import io

PRIMARY_TXT = """AYESHA KHAN
DevOps Engineer | Cloud & Kubernetes
Lahore, Pakistan | ayesha.khan@example.com | +92-300-000-0000
linkedin.com/in/ayesha-khan-example | github.com/ayesha-example
Available immediately • Remote or on-site in Lahore

PROFESSIONAL SUMMARY
DevOps engineer with two years of hands-on experience running Kubernetes and Terraform on AWS, building CI/CD
with GitHub Actions and observability with Prometheus and Grafana.

TECHNICAL SKILLS
Cloud: AWS (EC2, S3, EKS), Azure
DevOps: Docker, Kubernetes, Helm, Terraform, Docker Swarm, Go
Observability: Prometheus, Grafana, Datadog
Scripting: Python, Bash, Python

EXPERIENCE
DevOps Engineer | Acme Cloud Ltd | Jan 2023 – Present
• Migrated 40 services to Kubernetes on AWS EKS with Helm, cutting deploy time from 30 min to 5 min.
• Built Terraform modules for VPC and EKS; wrote GitHub Actions pipelines with automated tests and
image scanning using Trivy.
Junior DevOps Intern | Beta Systems | Jun 2022 – Dec 2022
• Wrote Python automation for Linux servers.

PROJECTS
Kubernetes Observability Stack
Prometheus • Grafana • Helm • Kubernetes
• Deployed kube-prometheus-stack with alerting rules for 12 microservices.

EDUCATION
BS Computer Science, University of the Punjab, Lahore | 2022 | CGPA: 3.4/4.0

LANGUAGES
English - Professional, Urdu - Native
"""

# Same person, different wording: title differs (Engineer vs Senior Engineer) and the org is spelled differently.
SECONDARY_TXT = """AYESHA KHAN
ayesha.khan@example.com

EXPERIENCE
Senior DevOps Engineer
Acme Cloud (Pvt) Ltd | Jan 2023 – Present
• Ran production Kubernetes clusters.

EDUCATION
Bachelor of Science in Computer Science — University of the Punjab | 2022

CERTIFICATIONS
• AWS Certified Cloud Practitioner (2023)
"""

CERTIFICATE_TXT = """Course
Certificate Issued: 16 September 2025 Certificate ID : 9999-1
This Certificate is Awarded to
Ayesha Khan
Who has successfully completed following program in
Certificate in DevOps and Cloud
This certificate is the property of Example Academy, and any
modifications in it is a criminal offence.
"""


def docx_bytes(text: str) -> bytes:
    import docx

    d = docx.Document()
    for line in text.splitlines():
        if line.startswith("• "):
            d.add_paragraph(line[2:], style="List Bullet")
        else:
            d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _pdf():
    from fpdf import FPDF

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_font("helvetica", size=10)  # core font: fixtures are ASCII only
    return pdf


def pdf_bytes(text: str) -> bytes:
    pdf = _pdf()
    y = 10
    for line in text.replace("•", "-").replace("–", "-").replace("—", "-").splitlines():
        pdf.set_xy(10, y)
        pdf.cell(0, 5, line)
        y += 5
    return bytes(pdf.output())


def two_column_pdf_bytes() -> bytes:
    """Sidebar (contact/skills) on the left, main content on the right."""
    left = [
        "CONTACT",
        "Lahore, Pakistan",
        "ayesha.khan@example.com",
        "SKILLS",
        "Docker",
        "Kubernetes",
        "Terraform",
        "Prometheus",
        "LANGUAGES",
        "English - Professional",
    ] + [f"Tool {i}" for i in range(8)]
    right = ["PROFESSIONAL SUMMARY", "DevOps engineer running Kubernetes on AWS for two years.",
             "EXPERIENCE", "DevOps Engineer", "Acme Cloud Ltd | Jan 2023 - Present",
             "- Migrated 40 services to Kubernetes with Helm and Terraform.",
             "- Built GitHub Actions pipelines with automated tests.",
             "EDUCATION", "BS Computer Science", "University of the Punjab | 2022"] + [
             f"- Additional achievement line number {i} with Grafana dashboards." for i in range(8)]  # fmt: skip
    pdf = _pdf()
    pdf.set_xy(10, 8)
    pdf.cell(0, 6, "AYESHA KHAN")
    for i, line in enumerate(left):
        pdf.set_xy(10, 20 + i * 6)
        pdf.cell(50, 5, line)
    for i, line in enumerate(right):
        pdf.set_xy(75, 20 + i * 6)
        pdf.cell(125, 5, line)
    return bytes(pdf.output())
