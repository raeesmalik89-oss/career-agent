"""Read-only connectors for sources that publish jobs through a public API or feed.

Each connector keeps the raw payload for audit and never infers fields a source did not provide.
"""

import re
import urllib.parse
import xml.etree.ElementTree as ET  # noqa: N817, S405 - trusted-format RSS; no DTDs are resolved by ElementTree

from integrations.sources.base import (
    Connector,
    JobPosting,
    SourceError,
    as_float,
    html_to_text,
    matches_any,
    parse_datetime,
)


def _q(value: str) -> str:
    return urllib.parse.quote(value)


class RemoteOK(Connector):
    """Single feed of all jobs (no search); filtered locally. Terms: link back and credit Remote OK."""

    key = "remoteok"
    hosts = ("remoteok.com",)

    def fetch(self, queries: list[str], limit: int) -> list[JobPosting]:
        data = self.http.get_json("https://remoteok.com/api")
        out = []
        for j in data[1:] if isinstance(data, list) else []:
            text = " ".join([j.get("position", ""), " ".join(j.get("tags") or [])])
            if not matches_any(text, queries):
                continue
            out.append(
                JobPosting(
                    source=self.key,
                    external_id=str(j["id"]),
                    title=j.get("position", "").strip(),
                    company=j.get("company", "").strip(),
                    url=j.get("url", ""),
                    application_url=j.get("apply_url"),
                    description=html_to_text(j.get("description")),
                    location=j.get("location") or None,
                    remote_hint="remote",
                    salary_min=as_float(j.get("salary_min")),
                    salary_max=as_float(j.get("salary_max")),
                    salary_currency="USD" if as_float(j.get("salary_max")) else None,
                    salary_period="year" if as_float(j.get("salary_max")) else None,
                    posted_at=parse_datetime(j.get("date") or j.get("epoch")),
                    tags=list(j.get("tags") or []),
                    raw=j,
                )
            )
            if len(out) >= limit:
                break
        return out


class Remotive(Connector):
    """Remotive asks for ~4 requests/day, so we read a few category feeds and filter locally."""

    key = "remotive"
    hosts = ("remotive.com",)
    CATEGORIES = ("devops", "software-dev", "data")

    def fetch(self, queries: list[str], limit: int) -> list[JobPosting]:
        seen: dict[str, JobPosting] = {}
        for cat in self.config.get("categories", self.CATEGORIES)[:3]:
            data = self.http.get_json(f"https://remotive.com/api/remote-jobs?category={_q(cat)}")
            for j in data.get("jobs", []):
                if not matches_any(" ".join([j.get("title", ""), " ".join(j.get("tags") or [])]), queries):
                    continue
                loc = j.get("candidate_required_location") or ""
                seen.setdefault(
                    str(j["id"]),
                    JobPosting(
                        source=self.key,
                        external_id=str(j["id"]),
                        title=j.get("title", "").strip(),
                        company=j.get("company_name", "").strip(),
                        url=j.get("url", ""),
                        application_url=j.get("url"),
                        description=html_to_text(j.get("description")),
                        location=loc or None,
                        location_restrictions=[p.strip() for p in re.split(r",|/|;", loc) if p.strip()],
                        remote_hint="remote",
                        employment_type=j.get("job_type"),
                        salary_text=j.get("salary") or None,
                        posted_at=parse_datetime(j.get("publication_date")),
                        tags=list(j.get("tags") or []),
                        raw=j,
                    ),
                )
            if len(seen) >= limit:
                break
        return list(seen.values())[:limit]


class Himalayas(Connector):
    key = "himalayas"
    hosts = ("himalayas.app",)

    def fetch(self, queries: list[str], limit: int) -> list[JobPosting]:
        seen: dict[str, JobPosting] = {}
        for q in queries:
            data = self.http.get_json(f"https://himalayas.app/jobs/api/search?q={_q(q)}&limit={min(limit, 50)}")
            for j in data.get("jobs", []):
                guid = j.get("guid") or j.get("applicationLink")
                if not guid:
                    continue
                period = j.get("salaryPeriod")
                seen.setdefault(
                    guid,
                    JobPosting(
                        source=self.key,
                        external_id=guid,
                        title=(j.get("title") or "").strip(),
                        company=(j.get("companyName") or "").strip(),
                        url=guid,
                        application_url=j.get("applicationLink"),
                        description=html_to_text(j.get("description") or j.get("excerpt")),
                        location_restrictions=list(j.get("locationRestrictions") or []),
                        location=", ".join(j.get("locationRestrictions") or []) or "Worldwide",
                        remote_hint="remote",
                        employment_type=j.get("employmentType"),
                        seniority_hint=", ".join(j.get("seniority") or []) or None,
                        salary_min=as_float(j.get("minSalary")),
                        salary_max=as_float(j.get("maxSalary")),
                        salary_currency=j.get("currency"),
                        salary_period={"annual": "year", "yearly": "year"}.get(period, period),
                        posted_at=parse_datetime(j.get("pubDate")),
                        tags=list(j.get("categories") or []),
                        raw={k: v for k, v in j.items() if k != "description"}
                        | {"timezoneRestrictions": j.get("timezoneRestrictions")},
                    ),
                )
            if len(seen) >= limit:
                break
        return list(seen.values())[:limit]


class Arbeitnow(Connector):
    key = "arbeitnow"
    hosts = ("www.arbeitnow.com",)

    def fetch(self, queries: list[str], limit: int) -> list[JobPosting]:
        out = []
        for page in (1, 2, 3):
            data = self.http.get_json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
            for j in data.get("data", []):
                if not matches_any(" ".join([j.get("title", ""), " ".join(j.get("tags") or [])]), queries):
                    continue
                out.append(
                    JobPosting(
                        source=self.key,
                        external_id=j["slug"],
                        title=j.get("title", "").strip(),
                        company=j.get("company_name", "").strip(),
                        url=j.get("url", ""),
                        application_url=j.get("url"),
                        description=html_to_text(j.get("description")),
                        location=j.get("location") or None,
                        remote_hint="remote" if j.get("remote") else None,
                        employment_type=", ".join(j.get("job_types") or []) or None,
                        posted_at=parse_datetime(j.get("created_at")),
                        tags=list(j.get("tags") or []),
                        raw={k: v for k, v in j.items() if k != "description"},
                    )
                )
            if len(out) >= limit or not data.get("links", {}).get("next"):
                break
        return out[:limit]


class WeWorkRemotely(Connector):
    key = "weworkremotely"
    hosts = ("weworkremotely.com",)
    CATEGORIES = (
        "remote-devops-sysadmin-jobs",
        "remote-back-end-programming-jobs",
        "remote-full-stack-programming-jobs",
    )

    def fetch(self, queries: list[str], limit: int) -> list[JobPosting]:
        out = []
        for cat in self.config.get("categories", self.CATEGORIES):
            root = ET.fromstring(self.http.get_text(f"https://weworkremotely.com/categories/{cat}.rss"))  # noqa: S314
            for item in root.iter("item"):

                def tag(name: str, node=item) -> str:
                    el = node.find(name)
                    return (el.text or "").strip() if el is not None and el.text else ""

                full_title = tag("title")
                company, _, title = full_title.partition(": ")
                if not title:
                    company, title = "", full_title
                if not matches_any(f"{title} {tag('skills')} {tag('category')}", queries):
                    continue
                region = tag("region")
                out.append(
                    JobPosting(
                        source=self.key,
                        external_id=tag("guid") or tag("link"),
                        title=title.strip(),
                        company=company.strip(),
                        url=tag("link"),
                        application_url=tag("link"),
                        description=html_to_text(tag("description")),
                        location=region or None,
                        location_restrictions=[r.strip() for r in re.split(r",|/", region) if r.strip()],
                        remote_hint="remote",
                        employment_type=tag("type") or None,
                        posted_at=parse_datetime(_rfc822(tag("pubDate"))),
                        raw={"title": full_title, "region": region, "category": tag("category"), "type": tag("type")},
                    )
                )
        return out[:limit]


def _rfc822(value: str) -> str | None:
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(value).isoformat() if value else None
    except (TypeError, ValueError):
        return None


class Greenhouse(Connector):
    """Per-company public job boards (config.companies = board tokens, e.g. 'gitlab')."""

    key = "greenhouse"
    hosts = ("boards-api.greenhouse.io",)

    def fetch(self, queries: list[str], limit: int) -> list[JobPosting]:
        out = []
        for company in self.config.get("companies", []):
            try:
                data = self.http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{_q(company)}/jobs?content=true")
            except SourceError:
                continue  # one bad board token must not stop the others
            for j in data.get("jobs", []):
                if not matches_any(j.get("title", ""), queries):
                    continue
                out.append(
                    JobPosting(
                        source=self.key,
                        external_id=str(j["id"]),
                        title=j.get("title", "").strip(),
                        company=j.get("company_name") or company,
                        url=j.get("absolute_url", ""),
                        application_url=j.get("absolute_url"),
                        description=html_to_text(j.get("content")),
                        location=(j.get("location") or {}).get("name"),
                        posted_at=parse_datetime(j.get("first_published") or j.get("updated_at")),
                        raw={k: v for k, v in j.items() if k != "content"},
                    )
                )
        return out[:limit]


class Lever(Connector):
    key = "lever"
    hosts = ("api.lever.co",)

    def fetch(self, queries: list[str], limit: int) -> list[JobPosting]:
        out = []
        for company in self.config.get("companies", []):
            try:
                data = self.http.get_json(f"https://api.lever.co/v0/postings/{_q(company)}?mode=json")
            except SourceError:
                continue
            for j in data if isinstance(data, list) else []:
                if not matches_any(j.get("text", ""), queries):
                    continue
                cats = j.get("categories") or {}
                lists = "\n".join(f"{x.get('text', '')}\n{html_to_text(x.get('content'))}" for x in j.get("lists", []))
                sal = j.get("salaryRange") or {}
                out.append(
                    JobPosting(
                        source=self.key,
                        external_id=j["id"],
                        title=j.get("text", "").strip(),
                        company=company,
                        url=j.get("hostedUrl", ""),
                        application_url=j.get("applyUrl"),
                        description="\n\n".join(
                            filter(None, [j.get("descriptionPlain"), lists, j.get("additionalPlain")])
                        ),
                        location=cats.get("location"),
                        remote_hint={"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}.get(
                            j.get("workplaceType")
                        ),
                        employment_type=cats.get("commitment"),
                        salary_min=as_float(sal.get("min")),
                        salary_max=as_float(sal.get("max")),
                        salary_currency=sal.get("currency"),
                        salary_period={"per-year-salary": "year"}.get(sal.get("interval"), sal.get("interval")),
                        posted_at=parse_datetime(j.get("createdAt")),
                        location_restrictions=[x for x in (cats.get("allLocations") or [])],
                        raw={
                            k: v
                            for k, v in j.items()
                            if k not in ("description", "descriptionPlain", "lists", "additional", "additionalPlain")
                        },
                    )
                )
        return out[:limit]


class Ashby(Connector):
    key = "ashby"
    hosts = ("api.ashbyhq.com",)

    def fetch(self, queries: list[str], limit: int) -> list[JobPosting]:
        out = []
        for company in self.config.get("companies", []):
            try:
                data = self.http.get_json(
                    f"https://api.ashbyhq.com/posting-api/job-board/{_q(company)}?includeCompensation=true"
                )
            except SourceError:
                continue
            for j in data.get("jobs", []):
                if not j.get("isListed", True) or not matches_any(j.get("title", ""), queries):
                    continue
                locs = [j.get("location")] + [s.get("location") for s in j.get("secondaryLocations") or []]
                comp = (j.get("compensation") or {}).get("compensationTierSummary")
                out.append(
                    JobPosting(
                        source=self.key,
                        external_id=j["id"],
                        title=j.get("title", "").strip(),
                        company=company,
                        url=j.get("jobUrl", ""),
                        application_url=j.get("applyUrl"),
                        description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                        location="; ".join(filter(None, locs)) or None,
                        location_restrictions=[x for x in locs if x],
                        remote_hint={"Remote": "remote", "Hybrid": "hybrid", "OnSite": "onsite"}.get(
                            j.get("workplaceType")
                        )
                        or ("remote" if j.get("isRemote") else None),
                        employment_type=j.get("employmentType"),
                        salary_text=comp,
                        posted_at=parse_datetime(j.get("publishedAt")),
                        raw={k: v for k, v in j.items() if k not in ("descriptionHtml", "descriptionPlain")},
                    )
                )
        return out[:limit]


class Jooble(Connector):
    """Needs a free API key (secret 'jooble_api_key'). Covers Pakistan, including Islamabad on-site roles.

    Free keys have a small total quota (500 requests), so each scan makes a few broad searches
    (config.searches) instead of one request per query, and stops once config.quota is used up.
    """

    key = "jooble"
    hosts = ("jooble.org", "pk.jooble.org")
    metered = True  # every request counts against a small quota
    DEFAULT_SEARCHES = (
        ("devops", "Islamabad"),
        ("cloud engineer", "Islamabad"),
        ("devops", "Pakistan"),
        ("site reliability engineer", "Pakistan"),
    )

    def __init__(self, http, config=None):
        super().__init__(http, config)
        self.requests_made = 0

    def fetch(self, queries: list[str], limit: int) -> list[JobPosting]:
        api_key = self.config.get("api_key")
        if not api_key:
            raise SourceError("Jooble needs an API key (register free at jooble.org/api/about)")
        if not re.fullmatch(r"[A-Za-z0-9-]{8,80}", api_key):
            raise SourceError("Jooble API key has an unexpected format")
        remaining = int(self.config.get("quota", 500)) - int(self.config.get("requests_used", 0))
        if remaining <= 0:
            raise SourceError("Jooble request quota used up; ask Jooble for more or disable the source")
        searches = [tuple(x) for x in self.config.get("searches", self.DEFAULT_SEARCHES)]
        out: dict[str, JobPosting] = {}
        for keywords, location in searches[: min(len(searches), remaining)]:
            host = self.config.get("api_host", "jooble.org")  # keys are issued per country site
            if host not in self.hosts:
                raise SourceError(f"unsupported Jooble host {host!r}")
            data = self.http.post_json(f"https://{host}/api/{api_key}", {"keywords": keywords, "location": location})
            self.requests_made += 1
            for j in data.get("jobs", []):
                jid = str(j.get("id") or j.get("link"))
                out.setdefault(
                    jid,
                    JobPosting(
                        source=self.key,
                        external_id=jid,
                        title=html_to_text(j.get("title")),
                        company=(j.get("company") or "").strip(),
                        url=j.get("link", ""),
                        application_url=j.get("link"),
                        description=html_to_text(j.get("snippet")),
                        location=j.get("location") or None,
                        employment_type=j.get("type") or None,
                        salary_text=j.get("salary") or None,
                        posted_at=parse_datetime(j.get("updated")),
                        raw=j,
                    ),
                )
        return list(out.values())[:limit]


CONNECTORS: dict[str, type[Connector]] = {
    c.key: c for c in (RemoteOK, Remotive, Himalayas, Arbeitnow, WeWorkRemotely, Greenhouse, Lever, Ashby, Jooble)
}
