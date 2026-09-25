#!/usr/bin/env python3
"""Rank GitHub repos for contribution using hard filters + merge/release scores."""

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
from urllib.parse import parse_qs, urlencode, urlparse

AGENT_HINT = ("agent", "llm", "mcp", "langchain", "langgraph", "autogen", "crewai", "multi-agent")
AGENT_KW = '(mcp OR langchain OR "ai agent" OR "ai-agent" OR langgraph OR autogen)'
REPO_NAME_RE = re.compile(
    r"(?:第\s*\d+\s*名：`|https://github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
)

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
isArchived
pushedAt
stargazerCount
primaryLanguage { name }
openIssues: issues(states: OPEN) { totalCount }
closedIssues: issues(states: CLOSED) { totalCount }
releases(first: 50, orderBy: {field: CREATED_AT, direction: DESC}) {
  nodes { publishedAt isDraft }
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
                "User-Agent": "oss-contribution",
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


def curl_text(url: str, head: bool = False) -> tuple[int, str, str]:
    cmd = [
        "curl",
        "-sS",
        "-w",
        "\n%{http_code}",
        "-H",
        "User-Agent: oss-contribution",
        "-H",
        "Accept: application/vnd.github+json",
    ]
    token = _token()
    if token:
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
        repos.append(
            {
                "nameWithOwner": full,
                "url": (repo or {}).get("html_url") or f"https://github.com/{full}",
                "description": (repo or {}).get("description") or "",
                "isArchived": bool((repo or {}).get("archived")),
                "pushedAt": (repo or {}).get("pushed_at"),
                "stargazerCount": (repo or {}).get("stargazers_count") or 0,
                "primaryLanguage": {"name": lang} if lang else None,
                "openIssues": {"totalCount": max(0, open_mix - open_prs)},
                "closedIssues": {"totalCount": max(0, closed_mix - closed_prs)},
                "pullRequests": {
                    "nodes": [
                        {"createdAt": p.get("created_at"), "mergedAt": p.get("merged_at")}
                        for p in pulls
                        if p.get("merged_at")
                    ]
                },
                "releases": {
                    "nodes": [
                        {"publishedAt": r.get("published_at"), "isDraft": bool(r.get("draft"))}
                        for r in releases
                    ]
                },
            }
        )
    return repos


DEFAULT_LANGS = {
    "agent": ["Python", "TypeScript"],
    "any": ["Python", "TypeScript", "Go", "Rust"],
}


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

    langs = languages or DEFAULT_LANGS[domain]

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
    total = 0.5 * score_pr + 0.5 * score_rel
    lang = ((raw.get("primaryLanguage") or {}) or {}).get("name")
    return {
        "full_name": raw["nameWithOwner"],
        "url": raw["url"],
        "description": (raw.get("description") or "").strip() or "（无描述）",
        "stars": stars,
        "language": lang or "",
        "pushed_at": pushed.date().isoformat(),
        "open_issues": open_n,
        "closed_issues": closed_n,
        "issue_ratio": ratio if math.isfinite(ratio) else None,
        "issue_ratio_label": "∞" if ratio is math.inf else f"{ratio:.2f}",
        "median_merge_days": round(merge_days, 2),
        "releases_12m": rel_n,
        "score_pr": round(score_pr, 2),
        "score_release": round(score_rel, 2),
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
        "得分 = 0.5 × PR 合并速度分 + 0.5 × Release 频率分。PR 分 = 100 / (1 + 中位合并天数)；Release 分 = min(100, 近12个月 Release 数 / 12 × 100)。",
        "",
    ]
    if filters_note:
        lines.extend([f"本次过滤：{filters_note}", ""])
    if excluded_note:
        lines.extend([excluded_note, ""])
    if not picked:
        lines.append(
            "没有同时满足硬性条件与本次过滤的仓库。"
            "可放宽语言或关键词（`--query` / `--raw-query`）、去掉排除项（`--no-exclude-previous`），或检查 `gh` 登录状态。"
        )
        return "\n".join(lines)
    for i, row in enumerate(picked, 1):
        lines.extend(
            [
                f"### 第 {i} 名：`{row['full_name']}`（得分 {row['score']}）",
                f"- 项目地址：{row['url']}",
                f"- 项目描述：{row['description']}",
                f"- Stars：{row['stars']}；语言：{row['language'] or '—'}；最近 push：{row['pushed_at']}",
                f"- Issue closed/open：{row['closed_issues']}/{row['open_issues']} = {row['issue_ratio_label']}",
                f"- PR 中位合并：{row['median_merge_days']} 天（速度分 {row['score_pr']}）",
                f"- 近 12 个月 Release：{row['releases_12m']}（频率分 {row['score_release']}）",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def format_filters_note(args: argparse.Namespace) -> str:
    parts: list[str] = [f"domain={args.domain}", f"stars>={args.stars}", f"days<={args.days}"]
    if args.max_stars is not None:
        parts.append(f"stars<={args.max_stars}")
    if args.language:
        parts.append("language=" + ",".join(args.language))
    else:
        parts.append("language=" + ",".join(DEFAULT_LANGS[args.domain]) + "（默认）")
    if args.topic:
        parts.append("topic=" + ",".join(args.topic))
    if args.query.strip():
        parts.append(f'query="{args.query.strip()}"')
    if args.raw_query.strip():
        parts.append(f'raw_query="{args.raw_query.strip()}"')
    if args.min_ratio != 1.0:
        parts.append(f"min_ratio={args.min_ratio}")
    return "；".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="发现并打分可贡献的 GitHub 仓库")
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--stars", type=int, default=1000, help="最低 stars（搜索与硬性条件）")
    parser.add_argument("--max-stars", type=int, default=None, help="最高 stars（可选上限）")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--min-ratio", type=float, default=1.0)
    parser.add_argument("--domain", choices=("agent", "any"), default="any")
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
    ranked.sort(key=lambda r: (-r["score"], -r["stars"]))

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
