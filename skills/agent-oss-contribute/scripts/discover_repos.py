#!/usr/bin/env python3
"""Rank GitHub repos for contribution using hard filters + merge/release/usage scores."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

AGENT_HINT = ("agent", "llm", "mcp", "langchain", "langgraph", "autogen", "crewai", "multi-agent")
AGENT_KW = '(mcp OR langchain OR "ai agent" OR "ai-agent" OR langgraph OR autogen)'
REPO_NAME_RE = re.compile(
    r"(?:第\s*\d+\s*名：`|https://github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
)

# Ranking: keep maintainer-health signals, add how many people actually use the project.
WEIGHT_PR = 0.4
WEIGHT_RELEASE = 0.3
WEIGHT_USAGE = 0.3
# log10(1 + units) maps USAGE_LOG_CAP monthly-equivalent units → 100.
USAGE_LOG_CAP = 1_000_000
README_EXCERPT_CHARS = 1200
JS_LANGUAGES = {"TypeScript", "JavaScript", "Vue", "Svelte", "CSS"}
HTTP_UA = "agent-oss-contribute/1.0 (+https://github.com/MengMa-dev/skills)"
PYPI_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

SEARCH_GQL = """
query SearchRepos($query: String!, $first: Int!) {
  search(query: $query, type: REPOSITORY, first: $first) {
    nodes {
      ... on Repository { nameWithOwner }
    }
  }
}
"""

REPO_FIELDS = """
nameWithOwner
url
description
homepageUrl
isArchived
pushedAt
stargazerCount
forkCount
watchers { totalCount }
primaryLanguage { name }
repositoryTopics(first: 12) { nodes { topic { name } } }
openIssues: issues(states: OPEN) { totalCount }
closedIssues: issues(states: CLOSED) { totalCount }
packageJson: object(expression: "HEAD:package.json") { ... on Blob { text } }
pyproject: object(expression: "HEAD:pyproject.toml") { ... on Blob { text } }
cargoToml: object(expression: "HEAD:Cargo.toml") { ... on Blob { text } }
releases(first: 50, orderBy: {field: CREATED_AT, direction: DESC}) {
  nodes {
    publishedAt
    isDraft
    releaseAssets(first: 30) { nodes { downloadCount } }
  }
}
pullRequests(first: 25, states: MERGED, orderBy: {field: UPDATED_AT, direction: DESC}) {
  nodes { createdAt mergedAt }
}
"""


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables}).encode()
    gh = shutil.which("gh")
    if gh:
        proc = subprocess.run(
            [gh, "api", "graphql", "--input", "-"],
            input=payload,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"gh api graphql 失败: {err or proc.returncode}")
        data = json.loads(proc.stdout.decode())
    else:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise RuntimeError(
                "未找到 gh，且未设置 GH_TOKEN/GITHUB_TOKEN。请先 `gh auth login` 或导出 token。"
            )
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": HTTP_UA,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub GraphQL HTTP {exc.code}: {body}") from exc
    if data.get("errors"):
        raise RuntimeError(f"GitHub GraphQL errors: {json.dumps(data['errors'], ensure_ascii=False)}")
    return data["data"]


def _token() -> str:
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""


def curl_text(
    url: str,
    head: bool = False,
    extra_headers: list[str] | None = None,
    send_github_token: bool = True,
) -> tuple[int, str, str]:
    cmd = [
        "curl",
        "-sS",
        "-w",
        "\n%{http_code}",
        "-H",
        f"User-Agent: {HTTP_UA}",
        "-H",
        "Accept: application/vnd.github+json",
    ]
    for header in extra_headers or []:
        cmd += ["-H", header]
    token = _token()
    if send_github_token and token:
        cmd += ["-H", f"Authorization: Bearer {token}"]
    if head:
        cmd += ["-I"]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"curl 失败: {err or proc.returncode}")
    raw = proc.stdout.decode("utf-8", errors="replace")
    if "\n" not in raw:
        raise RuntimeError(f"curl 响应异常: {raw[:200]}")
    body, _, status_s = raw.rpartition("\n")
    try:
        status = int(status_s.strip())
    except ValueError as exc:
        raise RuntimeError(f"curl 状态码异常: {raw[-80:]}") from exc
    return status, body, proc.stderr.decode("utf-8", errors="replace")


def rest_json(url: str) -> Any:
    status, body, _ = curl_text(url, head=False)
    if status == 403:
        raise RuntimeError(f"GitHub API 限流或拒绝: {body[:300]}")
    if status >= 400:
        raise RuntimeError(f"GitHub REST {status}: {body[:300]}")
    return json.loads(body) if body.strip() else None


def rest_count(url: str) -> int:
    status, headers, _ = curl_text(url, head=True)
    if status >= 400:
        status, body, _ = curl_text(url, head=False)
        if status >= 400:
            raise RuntimeError(f"GitHub REST {status}: {body[:300]}")
        items = json.loads(body) if body.strip() else []
        return len(items) if isinstance(items, list) else 0
    last_page = None
    for line in headers.splitlines():
        if line.lower().startswith("link:"):
            for part in line.split(","):
                if 'rel="last"' in part:
                    start = part.find("<") + 1
                    end = part.find(">", start)
                    qs = parse_qs(urlparse(part[start:end]).query)
                    if qs.get("page"):
                        last_page = int(qs["page"][0])
    if last_page is not None:
        return last_page
    status, body, _ = curl_text(url, head=False)
    items = json.loads(body) if body.strip() else []
    return len(items) if isinstance(items, list) else 0


def http_json(url: str, extra_headers: dict[str, str] | None = None) -> Any | None:
    """Best-effort GET JSON from a public registry. 404/errors → None (never abort search)."""
    headers = {
        "User-Agent": HTTP_UA,
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 404):
            return None
        return None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    try:
        return json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        return None


def blob_text(node: Any) -> str:
    if isinstance(node, dict):
        return (node.get("text") or "").strip()
    return ""


def parse_npm_name(text: str) -> str | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("private"):
        return None
    name = data.get("name")
    if isinstance(name, str) and name.strip() and name.strip() != ".":
        return name.strip()
    return None


def parse_toml_section_name(text: str, section: str) -> str | None:
    pattern = rf"(?ms)^\s*\[{re.escape(section)}\]\s*$.*?(?=^\s*\[|\Z)"
    block = re.search(pattern, text)
    if not block:
        return None
    match = re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', block.group(0))
    return match.group(1).strip() if match else None


def parse_python_package_name(text: str) -> str | None:
    return parse_toml_section_name(text, "project") or parse_toml_section_name(text, "tool.poetry")


def parse_crate_name(text: str) -> str | None:
    return parse_toml_section_name(text, "package")


def topic_names(raw: dict[str, Any]) -> list[str]:
    nodes = ((raw.get("repositoryTopics") or {}).get("nodes")) or []
    names: list[str] = []
    for node in nodes:
        topic = ((node or {}).get("topic") or {}).get("name")
        if topic:
            names.append(str(topic))
    for topic in raw.get("topics") or []:
        if topic and topic not in names:
            names.append(str(topic))
    return names


def excerpt_readme(text: str, limit: int = README_EXCERPT_CHARS) -> str:
    """Drop badges/images; keep heading + prose for description rewriting."""
    kept: list[str] = []
    used = 0
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        lower = stripped.lower()
        if (
            stripped.startswith("<")
            or stripped.startswith("[![")
            or stripped.startswith("<img")
            or "shields.io" in lower
            or ("badge" in lower and stripped.startswith("!["))
            or (stripped.startswith("![") and ("](" in stripped or "][" in stripped))
        ):
            continue
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
            if not stripped:
                continue
        kept.append(stripped)
        used += len(stripped) + 1
        if used >= limit:
            break
    excerpt = " ".join(x for x in kept if x).strip()
    if len(excerpt) > limit:
        excerpt = excerpt[: limit - 1].rstrip() + "…"
    return excerpt


def fetch_readme_excerpt(full_name: str) -> str:
    owner, name = full_name.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{name}/readme"
    try:
        status, body, _ = curl_text(url, extra_headers=["Accept: application/vnd.github.raw"])
    except RuntimeError:
        return ""
    if status >= 400 or not body.strip():
        return ""
    return excerpt_readme(body)


_REGISTRY_CACHE: dict[tuple[str, str], tuple[int | None, str]] = {}
_PYPISTATS_AVAILABLE = True


def pypi_downloads_pypistats(package: str) -> int | None:
    """Return last-month downloads, or None on 404/error. Disables further calls after HTTP 429."""
    global _PYPISTATS_AVAILABLE
    if not _PYPISTATS_AVAILABLE:
        return None
    name = package.lower().strip()
    if not PYPI_NAME_RE.fullmatch(name):
        return None
    url = "https://pypistats.org/api/packages/" + quote(name, safe="") + "/recent"
    req = urllib.request.Request(url, headers={"User-Agent": HTTP_UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace") or "null")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _PYPISTATS_AVAILABLE = False
        return None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    inner = data.get("data") if isinstance(data, dict) else None
    if isinstance(inner, dict) and inner.get("last_month") is not None:
        return int(inner.get("last_month") or 0)
    return None


def pypi_downloads_clickhouse(package: str) -> int | None:
    """Fallback when pypistats.org is rate-limited. Counts include mirrors."""
    name = package.lower().strip()
    if not PYPI_NAME_RE.fullmatch(name):
        return None
    query = (
        "SELECT sum(count) AS downloads FROM pypi.pypi_downloads_per_day "
        f"WHERE project = '{name}' AND date >= today() - 30 FORMAT JSONEachRow"
    )
    req = urllib.request.Request(
        "https://sql-clickhouse.clickhouse.com/?user=demo",
        data=query.encode(),
        headers={"User-Agent": HTTP_UA, "Content-Type": "text/plain"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="replace").strip()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw.splitlines()[0])
    except json.JSONDecodeError:
        return None
    value = data.get("downloads")
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def registry_downloads(ecosystem: str, package: str) -> tuple[int | None, str]:
    """Return (count, window_label). count is None when the package is missing/unavailable."""
    eco = ecosystem.lower()
    pkg = package.strip()
    if not pkg:
        return None, ""
    cache_key = (eco, pkg)
    if cache_key in _REGISTRY_CACHE:
        return _REGISTRY_CACHE[cache_key]
    result: tuple[int | None, str] = (None, "")
    if eco == "npm":
        url = "https://api.npmjs.org/downloads/point/last-month/" + quote(pkg, safe="")
        data = http_json(url)
        if isinstance(data, dict) and "downloads" in data:
            result = (int(data.get("downloads") or 0), "近 30 天")
    elif eco == "pypi":
        stats = pypi_downloads_pypistats(pkg)
        if stats is not None:
            result = (stats, "近 30 天")
        else:
            ch = pypi_downloads_clickhouse(pkg)
            if ch:
                result = (ch, "近 30 天(含镜像)")
    elif eco == "crates":
        url = "https://crates.io/api/v1/crates/" + quote(pkg, safe="")
        data = http_json(url)
        crate = (data or {}).get("crate") if isinstance(data, dict) else None
        if isinstance(crate, dict) and crate.get("recent_downloads") is not None:
            # crates.io recent_downloads ≈ last 90 days; convert to a 30-day estimate.
            recent_90 = int(crate.get("recent_downloads") or 0)
            result = (int(round(recent_90 / 3.0)), "近 30 天(crates 90天/3)")
    _REGISTRY_CACHE[cache_key] = result
    return result


def manifest_package_candidates(raw: dict[str, Any], language: str) -> list[tuple[str, str]]:
    """Ordered (ecosystem, package_name) guesses from manifests, then repo name."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []

    def add(eco: str, name: str | None) -> None:
        if not name:
            return
        key = (eco, name)
        if key in seen:
            return
        seen.add(key)
        out.append(key)

    add("npm", parse_npm_name(blob_text(raw.get("packageJson"))))
    add("pypi", parse_python_package_name(blob_text(raw.get("pyproject"))))
    add("crates", parse_crate_name(blob_text(raw.get("cargoToml"))))

    full = str(raw.get("nameWithOwner") or "")
    repo = full.split("/", 1)[-1] if full else ""
    repo_l = repo.lower()
    lang = language or ""
    if lang in JS_LANGUAGES or lang == "":
        add("npm", repo_l)
        # langchainjs → langchain; foo-js → foo
        if repo_l.endswith("-js") and len(repo_l) > 3:
            add("npm", repo_l[:-3])
        elif repo_l.endswith("js") and len(repo_l) > 2:
            stem = repo_l[:-2].rstrip("-_")
            if stem:
                add("npm", stem)
        if "/" in full:
            add("npm", f"@{full.split('/', 1)[0].lower()}/{repo_l}")
    if lang in {"Python", ""}:
        add("pypi", repo_l)
        add("pypi", repo_l.replace("-", "_"))
    if lang in {"Rust", ""}:
        add("crates", repo_l)
    return out


def fetch_best_registry_downloads(
    raw: dict[str, Any], language: str
) -> tuple[int | None, str, str]:
    """Return (downloads, ecosystem, window_label) for the first registry hit."""
    for eco, name in manifest_package_candidates(raw, language):
        count, window = registry_downloads(eco, name)
        if count is not None:
            return count, f"{eco}:{name}", window
    return None, "", ""


def release_download_total(nodes: list[dict[str, Any]], now: datetime) -> int:
    cutoff = now - timedelta(days=365)
    total = 0
    for node in nodes:
        if node.get("isDraft"):
            continue
        published = parse_dt(node.get("publishedAt"))
        if not published or published < cutoff:
            continue
        assets = ((node.get("releaseAssets") or {}).get("nodes")) or []
        for asset in assets:
            total += int(asset.get("downloadCount") or asset.get("download_count") or 0)
    return total


def popularity_units(stars: int, forks: int) -> int:
    return max(0, int(stars) + 2 * int(forks))


def usage_units(
    downloads_30d: int | None,
    release_dl_12m: int,
    stars: int,
    forks: int,
) -> tuple[float, str]:
    """Pick the strongest usage signal so ranking can show how many people use the project."""
    pop = popularity_units(stars, forks)
    monthly_rel = max(0, int(release_dl_12m)) / 12.0
    candidates: list[tuple[float, str]] = [(float(pop), "stars+forks")]
    if downloads_30d is not None:
        candidates.append((float(max(0, downloads_30d)), "registry-30d"))
    if monthly_rel > 0:
        candidates.append((monthly_rel, "github-release-monthly"))
    units, source = max(candidates, key=lambda item: item[0])
    return units, source


def score_usage(units: float, cap: float = USAGE_LOG_CAP) -> float:
    units = max(0.0, float(units))
    if cap <= 0:
        return 0.0
    return min(100.0, 100.0 * math.log10(1.0 + units) / math.log10(1.0 + cap))


def format_count(value: int | float | None) -> str:
    if value is None:
        return "未取到"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.1f}"
    return f"{int(value):,}"


def looks_like_agent(text: str) -> bool:
    blob = text.lower()
    return any(h in blob for h in AGENT_HINT)


def round_robin_merge(buckets: list[list[str]]) -> list[str]:
    """Interleave per-query hits so one popular query cannot fill the whole candidate pool."""
    seen: set[str] = set()
    out: list[str] = []
    max_len = max((len(b) for b in buckets), default=0)
    for i in range(max_len):
        for bucket in buckets:
            if i >= len(bucket):
                continue
            name = bucket[i]
            if name in seen:
                continue
            seen.add(name)
            out.append(name)
    return out


def rest_search_names(queries: list[str], per_query: int, require_agent_hint: bool) -> list[str]:
    buckets: list[list[str]] = []
    for q in queries:
        url = "https://api.github.com/search/repositories?" + urlencode({"q": q, "per_page": per_query})
        data = rest_json(url)
        batch: list[str] = []
        for item in (data or {}).get("items") or []:
            name = item.get("full_name")
            if not name:
                continue
            hay = " ".join([name, item.get("description") or "", " ".join(item.get("topics") or [])])
            if require_agent_hint and not looks_like_agent(hay):
                continue
            batch.append(name)
        buckets.append(batch)
    return round_robin_merge(buckets)


def hydrate_rest(names: list[str]) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    for full in names:
        owner, name = full.split("/", 1)
        repo = rest_json(f"https://api.github.com/repos/{owner}/{name}")
        open_mix = rest_count(f"https://api.github.com/repos/{owner}/{name}/issues?state=open&per_page=1")
        closed_mix = rest_count(f"https://api.github.com/repos/{owner}/{name}/issues?state=closed&per_page=1")
        open_prs = rest_count(f"https://api.github.com/repos/{owner}/{name}/pulls?state=open&per_page=1")
        closed_prs = rest_count(f"https://api.github.com/repos/{owner}/{name}/pulls?state=closed&per_page=1")
        pulls = rest_json(
            f"https://api.github.com/repos/{owner}/{name}/pulls?state=closed&sort=updated&direction=desc&per_page=30"
        ) or []
        releases = rest_json(f"https://api.github.com/repos/{owner}/{name}/releases?per_page=50") or []
        lang = (repo or {}).get("language") or ""
        topics = (repo or {}).get("topics") or []
        release_nodes = []
        for r in releases:
            assets = [
                {"downloadCount": a.get("download_count") or 0}
                for a in (r.get("assets") or [])
            ]
            release_nodes.append(
                {
                    "publishedAt": r.get("published_at"),
                    "isDraft": bool(r.get("draft")),
                    "releaseAssets": {"nodes": assets},
                }
            )
        repos.append(
            {
                "nameWithOwner": full,
                "url": (repo or {}).get("html_url") or f"https://github.com/{full}",
                "description": (repo or {}).get("description") or "",
                "homepageUrl": (repo or {}).get("homepage") or "",
                "isArchived": bool((repo or {}).get("archived")),
                "pushedAt": (repo or {}).get("pushed_at"),
                "stargazerCount": (repo or {}).get("stargazers_count") or 0,
                "forkCount": (repo or {}).get("forks_count") or 0,
                "watchers": {"totalCount": (repo or {}).get("subscribers_count") or 0},
                "primaryLanguage": {"name": lang} if lang else None,
                "topics": topics,
                "openIssues": {"totalCount": max(0, open_mix - open_prs)},
                "closedIssues": {"totalCount": max(0, closed_mix - closed_prs)},
                "pullRequests": {
                    "nodes": [
                        {"createdAt": p.get("created_at"), "mergedAt": p.get("merged_at")}
                        for p in pulls
                        if p.get("merged_at")
                    ]
                },
                "releases": {"nodes": release_nodes},
            }
        )
    return repos


def build_queries(
    pushed_since: str,
    domain: str,
    extra: str,
    languages: list[str],
    topics: list[str],
    min_stars: int,
    max_stars: int | None,
    raw_query: str,
) -> list[str]:
    """Build GitHub search queries. User filters are additive unless --raw-query is set."""
    base_parts = [
        f"stars:>={min_stars}",
        f"pushed:>={pushed_since}",
        "fork:false",
        "archived:false",
    ]
    if max_stars is not None:
        base_parts.append(f"stars:<={max_stars}")
    for topic in topics:
        base_parts.append(f"topic:{topic}")
    extra = extra.strip()
    if extra:
        base_parts.append(extra)
    base = " ".join(base_parts)

    if raw_query.strip():
        return [f"{base} {raw_query.strip()}"]

    langs = languages or ["Python", "TypeScript"]

    if domain == "any":
        return [f"{base} language:{lang}" for lang in langs]

    queries = [f"{base} language:{lang} {AGENT_KW}" for lang in langs]
    # Topic-only probes diversify beyond language buckets; skip if user already pinned topics.
    if not topics:
        queries.extend(
            [
                f"{base} topic:ai-agents",
                f"{base} topic:mcp",
                f"{base} topic:langchain",
            ]
        )
    return queries


def issue_ratio(open_n: int, closed_n: int) -> float | None:
    if open_n == 0:
        return math.inf if closed_n > 0 else None
    return closed_n / open_n


def median_merge_days(nodes: list[dict[str, Any]]) -> float | None:
    days: list[float] = []
    for node in nodes:
        created = parse_dt(node.get("createdAt"))
        merged = parse_dt(node.get("mergedAt"))
        if not created or not merged or merged < created:
            continue
        days.append((merged - created).total_seconds() / 86400.0)
    if len(days) < 3:
        return None
    return statistics.median(days)


def releases_last_year(nodes: list[dict[str, Any]], now: datetime) -> int:
    cutoff = now - timedelta(days=365)
    count = 0
    for node in nodes:
        if node.get("isDraft"):
            continue
        published = parse_dt(node.get("publishedAt"))
        if published and published >= cutoff:
            count += 1
    return count


def score_repo(
    raw: dict[str, Any],
    now: datetime,
    min_stars: int,
    max_stars: int | None,
    since: datetime,
    min_ratio: float,
) -> dict[str, Any] | None:
    if not raw or raw.get("isArchived"):
        return None
    stars = int(raw.get("stargazerCount") or 0)
    if stars < min_stars:
        return None
    if max_stars is not None and stars > max_stars:
        return None
    pushed = parse_dt(raw.get("pushedAt"))
    if not pushed or pushed < since:
        return None
    open_n = int((raw.get("openIssues") or {}).get("totalCount") or 0)
    closed_n = int((raw.get("closedIssues") or {}).get("totalCount") or 0)
    ratio = issue_ratio(open_n, closed_n)
    if ratio is None or ratio <= min_ratio:
        return None
    merge_days = median_merge_days((raw.get("pullRequests") or {}).get("nodes") or [])
    if merge_days is None:
        return None
    rel_n = releases_last_year((raw.get("releases") or {}).get("nodes") or [], now)
    score_pr = 100.0 / (1.0 + merge_days)
    score_rel = min(100.0, (rel_n / 12.0) * 100.0)
    lang = ((raw.get("primaryLanguage") or {}) or {}).get("name") or ""
    forks = int(raw.get("forkCount") or 0)
    watchers = int((raw.get("watchers") or {}).get("totalCount") or 0)
    release_dl = release_download_total((raw.get("releases") or {}).get("nodes") or [], now)
    downloads_30d, download_source, download_window = fetch_best_registry_downloads(raw, lang)
    units, usage_source = usage_units(downloads_30d, release_dl, stars, forks)
    score_use = score_usage(units)
    total = WEIGHT_PR * score_pr + WEIGHT_RELEASE * score_rel + WEIGHT_USAGE * score_use
    topics = topic_names(raw)
    github_desc = (raw.get("description") or "").strip()
    return {
        "full_name": raw["nameWithOwner"],
        "url": raw["url"],
        "description": github_desc or "（无 GitHub 简介）",
        "github_description": github_desc,
        "homepage": (raw.get("homepageUrl") or "").strip(),
        "topics": topics,
        "readme_excerpt": "",
        "stars": stars,
        "forks": forks,
        "watchers": watchers,
        "language": lang or "",
        "pushed_at": pushed.date().isoformat(),
        "open_issues": open_n,
        "closed_issues": closed_n,
        "issue_ratio": ratio if math.isfinite(ratio) else None,
        "issue_ratio_label": "∞" if ratio is math.inf else f"{ratio:.2f}",
        "median_merge_days": round(merge_days, 2),
        "releases_12m": rel_n,
        "downloads_30d": downloads_30d,
        "download_source": download_source,
        "download_window": download_window,
        "release_downloads_12m": release_dl,
        "usage_units": round(units, 1),
        "usage_source": usage_source,
        "score_pr": round(score_pr, 2),
        "score_release": round(score_rel, 2),
        "score_usage": round(score_use, 2),
        "score": round(total, 2),
    }


def search_names(queries: list[str], per_query: int) -> list[str]:
    buckets: list[list[str]] = []
    for q in queries:
        data = graphql(SEARCH_GQL, {"query": q, "first": per_query})
        batch: list[str] = []
        for node in (data.get("search") or {}).get("nodes") or []:
            name = (node or {}).get("nameWithOwner")
            if name:
                batch.append(name)
        buckets.append(batch)
    return round_robin_merge(buckets)


def hydrate(names: list[str]) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    chunk_size = 4
    for offset in range(0, len(names), chunk_size):
        chunk = names[offset : offset + chunk_size]
        var_defs = ", ".join(f"$o{i}: String!, $n{i}: String!" for i in range(len(chunk)))
        fields = " ".join(f"r{i}: repository(owner: $o{i}, name: $n{i}) {{ {REPO_FIELDS} }}" for i in range(len(chunk)))
        variables: dict[str, Any] = {}
        for i, full in enumerate(chunk):
            owner, name = full.split("/", 1)
            variables[f"o{i}"] = owner
            variables[f"n{i}"] = name
        data = graphql(f"query Hydrate({var_defs}) {{ {fields} }}", variables)
        for i in range(len(chunk)):
            node = data.get(f"r{i}")
            if node:
                repos.append(node)
    return repos


def normalize_repo(name: str) -> str:
    text = name.strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
    return text.lower()


def load_previous_repos(artifact_root: Path) -> set[str]:
    search_dir = artifact_root / "search"
    if not search_dir.is_dir():
        return set()
    found: set[str] = set()
    for path in sorted(search_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for match in REPO_NAME_RE.finditer(text):
            found.add(normalize_repo(match.group(1)))
    return found


def collect_exclusions(
    exclude: list[str],
    exclude_org: list[str],
    artifact_root: str | None,
    exclude_previous: bool,
) -> tuple[set[str], set[str], set[str]]:
    """Returns (exact repos, orgs, previous-from-disk repos)."""
    repos = {normalize_repo(x) for x in exclude if x.strip()}
    orgs = {o.strip().lower() for o in exclude_org if o.strip()}
    previous: set[str] = set()
    if exclude_previous and artifact_root:
        previous = load_previous_repos(Path(artifact_root))
        repos |= previous
    return repos, orgs, previous


def is_excluded(full_name: str, repos: set[str], orgs: set[str]) -> bool:
    key = normalize_repo(full_name)
    if key in repos:
        return True
    owner = key.split("/", 1)[0]
    return owner in orgs


def render_markdown(
    rows: list[dict[str, Any]],
    top: int,
    *,
    filters_note: str,
    excluded_note: str,
) -> str:
    picked = rows[:top]
    lines = [
        f"## 可贡献项目 Top {len(picked)}",
        "",
        "硬性条件：stars 下限（默认 ≥ 1000），近 N 天有 commit/push，Issue closed/open > 1，至少 3 条已合并 PR。",
        (
            f"得分 = {WEIGHT_PR} × PR 合并速度分 + {WEIGHT_RELEASE} × Release 频率分"
            f" + {WEIGHT_USAGE} × 使用分。"
            "PR 分 = 100 / (1 + 中位合并天数)；"
            "Release 分 = min(100, 近12个月 Release 数 / 12 × 100)；"
            f"使用分 = min(100, 100 × log10(1 + 使用信号) / log10(1 + {USAGE_LOG_CAP:,}))，"
            "使用信号取 registry 近 30 天下载、GitHub Release 资源月均下载、Stars+2×Forks 三者中的最大值。"
        ),
        "",
        "项目描述须按**用户语言**改写（见 discover.md），覆盖：做什么 / 解决的核心问题 / 适用场景。"
        "下面「GitHub 简介 / Topics / README 摘要」只是素材，不要原样当作给用户的项目描述。",
        "",
    ]
    if filters_note:
        lines.extend([f"本次过滤：{filters_note}", ""])
    if excluded_note:
        lines.extend([excluded_note, ""])
    if not picked:
        lines.append(
            "没有同时满足硬性条件与本次过滤的仓库。"
            "可放宽关键词（`--domain any` / `--query`）、去掉排除项（`--no-exclude-previous`），或检查 `gh` 登录状态。"
        )
        return "\n".join(lines)
    for i, row in enumerate(picked, 1):
        download_bit = "未取到"
        if row.get("downloads_30d") is not None:
            src = row.get("download_source") or "registry"
            window = row.get("download_window") or "近 30 天"
            download_bit = f"{format_count(row['downloads_30d'])}（{src}，{window}）"
        topics = "、".join(row.get("topics") or []) or "—"
        readme = (row.get("readme_excerpt") or "").strip() or "（未取到 README 摘要）"
        homepage = (row.get("homepage") or "").strip()
        homepage_line = f"- Homepage：{homepage}" if homepage else ""
        usage_src = {
            "registry-30d": "registry 近 30 天下载",
            "github-release-monthly": "GitHub Release 月均下载",
            "stars+forks": "Stars+2×Forks 流行度代理",
        }.get(row.get("usage_source") or "", row.get("usage_source") or "—")
        block = [
            f"### 第 {i} 名：`{row['full_name']}`（得分 {row['score']}）",
            f"- 项目地址：{row['url']}",
            "- 项目描述：（用用户语言改写为：做什么 / 解决的问题 / 适用场景；勿粘贴下一行简介）",
            f"- GitHub 简介：{row['description']}",
            f"- Topics：{topics}",
            f"- README 摘要：{readme}",
            f"- Stars：{format_count(row['stars'])}；Forks：{format_count(row.get('forks'))}；"
            f"Watchers：{format_count(row.get('watchers'))}；语言：{row['language'] or '—'}；"
            f"最近 push：{row['pushed_at']}",
            (
                f"- 使用情况：registry 下载 {download_bit}；"
                f"Release 资源近 12 个月下载 {format_count(row.get('release_downloads_12m'))}；"
                f"使用信号 {format_count(row.get('usage_units'))}（{usage_src}）；"
                f"使用分 {row.get('score_usage')}"
            ),
            f"- Issue closed/open：{row['closed_issues']}/{row['open_issues']} = {row['issue_ratio_label']}",
            f"- PR 中位合并：{row['median_merge_days']} 天（速度分 {row['score_pr']}）",
            f"- 近 12 个月 Release：{row['releases_12m']}（频率分 {row['score_release']}）",
            "",
        ]
        if homepage_line:
            block.insert(2, homepage_line)
        lines.extend(block)
    return "\n".join(lines).rstrip() + "\n"


def format_filters_note(args: argparse.Namespace) -> str:
    parts: list[str] = [f"domain={args.domain}", f"stars>={args.stars}", f"days<={args.days}"]
    if args.max_stars is not None:
        parts.append(f"stars<={args.max_stars}")
    if args.language:
        parts.append("language=" + ",".join(args.language))
    if args.topic:
        parts.append("topic=" + ",".join(args.topic))
    if args.query.strip():
        parts.append(f'query="{args.query.strip()}"')
    if args.raw_query.strip():
        parts.append(f'raw_query="{args.raw_query.strip()}"')
    if args.min_ratio != 1.0:
        parts.append(f"min_ratio={args.min_ratio}")
    if getattr(args, "user_language", ""):
        parts.append(f"user_language={args.user_language}")
    return "；".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="发现并打分可贡献的 GitHub 仓库")
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--stars", type=int, default=1000, help="最低 stars（搜索与硬性条件）")
    parser.add_argument("--max-stars", type=int, default=None, help="最高 stars（可选上限）")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--min-ratio", type=float, default=1.0)
    parser.add_argument("--domain", choices=("agent", "any"), default="agent")
    parser.add_argument(
        "--query",
        default="",
        help="追加搜索关键词（并入每条 query，不覆盖默认领域词）",
    )
    parser.add_argument(
        "--raw-query",
        default="",
        help="自定义搜索片段：只用 base 约束 + 本参数，不再套默认 agent/any 模板",
    )
    parser.add_argument(
        "--language",
        action="append",
        default=[],
        help="限定语言，可重复；例：--language TypeScript",
    )
    parser.add_argument(
        "--topic",
        action="append",
        default=[],
        help="限定 GitHub topic，可重复；例：--topic mcp",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="排除仓库 owner/repo，可重复",
    )
    parser.add_argument(
        "--exclude-org",
        action="append",
        default=[],
        help="排除整组织/用户下的仓库，可重复",
    )
    parser.add_argument(
        "--artifact-root",
        default="",
        help="中间产物根（含 search/）。用于读取历史 Top 并默认排除",
    )
    parser.add_argument(
        "--exclude-previous",
        dest="exclude_previous",
        action="store_true",
        default=True,
        help="排除 artifact-root/search/ 历史结果中出现过的仓库（默认开启）",
    )
    parser.add_argument(
        "--no-exclude-previous",
        dest="exclude_previous",
        action="store_false",
        help="允许再次推荐历史 search 里出现过的仓库",
    )
    parser.add_argument("--per-query", type=int, default=20)
    parser.add_argument(
        "--user-language",
        default="",
        help="用户语言（如 zh / en / ja）。写入过滤说明，供改写项目描述时对齐",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=40,
        help="打分前最多 hydrate 的候选数（扩大池子，减轻结果固化）",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.days)
    pushed_since = since.date().isoformat()
    queries = build_queries(
        pushed_since,
        args.domain,
        args.query,
        args.language,
        args.topic,
        args.stars,
        args.max_stars,
        args.raw_query,
    )
    exclude_repos, exclude_orgs, previous_repos = collect_exclusions(
        args.exclude,
        args.exclude_org,
        args.artifact_root or None,
        args.exclude_previous,
    )

    try:
        try:
            names = search_names(queries, args.per_query)
            names = [n for n in names if not is_excluded(n, exclude_repos, exclude_orgs)]
            names = names[: args.max_candidates]
            nodes = hydrate(names)
        except RuntimeError:
            names = rest_search_names(
                queries,
                min(args.per_query, 10),
                require_agent_hint=(args.domain == "agent" and not args.raw_query.strip()),
            )
            names = [n for n in names if not is_excluded(n, exclude_repos, exclude_orgs)]
            names = names[: args.max_candidates]
            nodes = hydrate_rest(names)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    ranked: list[dict[str, Any]] = []
    skipped_excluded = 0
    for node in nodes:
        full = node.get("nameWithOwner") or ""
        if full and is_excluded(full, exclude_repos, exclude_orgs):
            skipped_excluded += 1
            continue
        row = score_repo(node, now, args.stars, args.max_stars, since, args.min_ratio)
        if row:
            ranked.append(row)
    ranked.sort(key=lambda r: (-r["score"], -r.get("usage_units", 0), -r["stars"]))

    for row in ranked[: args.top]:
        if not row.get("readme_excerpt"):
            row["readme_excerpt"] = fetch_readme_excerpt(row["full_name"])

    filters_note = format_filters_note(args)
    excluded_bits: list[str] = []
    if previous_repos:
        excluded_bits.append(f"历史 search 排除 {len(previous_repos)} 个")
    if args.exclude:
        excluded_bits.append("手动排除 " + ", ".join(args.exclude))
    if args.exclude_org:
        excluded_bits.append("排除组织 " + ", ".join(args.exclude_org))
    if skipped_excluded:
        excluded_bits.append(f"本轮跳过已排除候选 {skipped_excluded} 个")
    excluded_note = ("排除：" + "；".join(excluded_bits)) if excluded_bits else ""

    payload = {
        "queries": queries,
        "candidates": len(nodes),
        "ranked": ranked[: args.top],
        "filters": filters_note,
        "excluded_previous_count": len(previous_repos),
        "exclude": sorted(exclude_repos),
        "exclude_org": sorted(exclude_orgs),
    }

    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(
            render_markdown(
                ranked,
                args.top,
                filters_note=filters_note,
                excluded_note=excluded_note,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
