import subprocess
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from tavily import TavilyClient

from idea_council.models.session import MarketVerification
from idea_council.providers.adapter import ProviderAdapter
from idea_council.roles.prompts import (
    SYNTHESIZER_QUERY_GENERATION,
    SYNTHESIZER_MARKET_INTERPRETATION,
)


def _generate_search_queries(
    seed_idea: str, synthesizer: ProviderAdapter, max_tokens: int
) -> list[str]:
    """Ask the synthesizer to produce 4 semantically distinct search queries for the idea."""
    raw = synthesizer.call(
        system=SYNTHESIZER_QUERY_GENERATION,
        user=f"Product idea:\n\n{seed_idea}",
        max_tokens=max_tokens,
    )

    queries = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if line:
            queries.append(line)

    return queries[:4]


def _search_github(query: str, max_results: int) -> list[dict]:
    """
    Search GitHub repositories using the gh CLI.
    Returns a list of dicts with name, description, url, and stars.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "search",
                "repos",
                query,
                "--limit",
                str(max_results),
                "--json",
                "name,description,url,stargazersCount",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout)
    except Exception:
        return []


def _search_tavily(query: str, client: TavilyClient) -> list[dict]:
    """
    Search the web using Tavily.
    Returns a list of dicts with title and url.
    """
    try:
        response = client.search(query=query, max_results=5)
        results = []
        for item in response.get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                }
            )
        return results
    except Exception:
        return []


def _interpret_results(
    seed_idea: str,
    github_results: list[dict],
    web_results: list[dict],
    synthesizer: ProviderAdapter,
    max_tokens: int,
) -> tuple[int, str]:
    """
    Ask the synthesizer to score market saturation and identify the gap.
    Returns (market_openness, remaining_gap, raw interpretation text).
    """
    github_section = ""
    if github_results:
        lines = []
        for repo in github_results:
            stars = repo.get("stargazersCount", 0)
            desc = repo.get("description", "no description")
            url = repo.get("url", "")
            lines.append(f"- {repo['name']} ({stars} stars): {desc} — {url}")
        github_section = "GitHub repositories found:\n" + "\n".join(lines)
    else:
        github_section = "GitHub repositories found: none"

    web_section = ""
    if web_results:
        lines = []
        for item in web_results:
            lines.append(f"- {item['title']} — {item['url']}")
        web_section = "Web search results:\n" + "\n".join(lines)
    else:
        web_section = "Web search results: none"

    user = f"Product idea:\n\n{seed_idea}\n\n{github_section}\n\n{web_section}"

    raw = synthesizer.call(
        system=SYNTHESIZER_MARKET_INTERPRETATION,
        user=user,
        max_tokens=max_tokens,
    )

    # Parse market_openness from the response
    score = 5  # default if parsing fails
    for line in raw.splitlines():
        if line.strip().startswith("MARKET_OPENNESS:"):
            try:
                score = int(line.strip().replace("MARKET_OPENNESS:", "").strip())
                score = max(1, min(10, score))
            except ValueError:
                pass

    # Parse remaining gap
    remaining_gap = None
    in_gap_section = False
    gap_lines = []
    for line in raw.splitlines():
        if line.strip().startswith("REMAINING_GAP:"):
            in_gap_section = True
            inline = line.strip().replace("REMAINING_GAP:", "").strip()
            if inline:
                gap_lines.append(inline)
        elif in_gap_section:
            if line.strip():
                gap_lines.append(line.strip())
            else:
                break
    if gap_lines:
        remaining_gap = " ".join(gap_lines)

    return score, remaining_gap, raw


def run_market_verification(
    seed_idea: str,
    synthesizer: ProviderAdapter,
    github_enabled: bool,
    github_max_results: int,
    tavily_api_key: str,
    max_tokens: int,
) -> MarketVerification:
    """
    Runs the full market verification step:
    1. Generate 4 search queries
    2. Search GitHub in parallel across all queries
    3. Search Tavily in parallel across all queries (if key is set)
    4. Deduplicate results
    5. Ask synthesizer to score and interpret
    """
    if not github_enabled and not tavily_api_key:
        return MarketVerification(
            search_queries=[],
            github_hits=[],
            web_hits=[],
            competitor_hits=[],
            market_openness=None,
            remaining_gap=None,
            skipped=True,
        )

    queries = _generate_search_queries(seed_idea, synthesizer, max_tokens)

    if not queries:
        return MarketVerification(
            search_queries=[],
            github_hits=[],
            web_hits=[],
            competitor_hits=[],
            market_openness=None,
            remaining_gap=None,
            skipped=True,
        )

    all_github_results = []
    all_web_results = []

    tavily_client = None
    if tavily_api_key:
        tavily_client = TavilyClient(api_key=tavily_api_key)

    with ThreadPoolExecutor() as executor:
        futures = []

        if github_enabled:
            for query in queries:
                futures.append(
                    executor.submit(_search_github, query, github_max_results)
                )

        if tavily_client:
            for query in queries:
                futures.append(executor.submit(_search_tavily, query, tavily_client))

        for future in as_completed(futures):
            try:
                result = future.result()
                # GitHub results have a "name" key, web results have "title"
                if result and "name" in result[0] if result else False:
                    all_github_results.extend(result)
                elif result:
                    all_web_results.extend(result)
            except Exception:
                pass

    # Deduplicate by URL
    seen_urls = set()
    unique_github = []
    for repo in all_github_results:
        url = repo.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_github.append(repo)

    unique_web = []
    for item in all_web_results:
        url = item.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_web.append(item)

    github_hits = [r.get("url", "") for r in unique_github]
    web_hits = [r.get("url", "") for r in unique_web]
    competitor_hits = github_hits + web_hits

    market_openness = None
    remaining_gap = None
    if competitor_hits or unique_github or unique_web:
        market_openness, remaining_gap, _ = _interpret_results(
            seed_idea,
            unique_github,
            unique_web,
            synthesizer,
            max_tokens,
        )

    return MarketVerification(
        search_queries=queries,
        github_hits=github_hits,
        web_hits=web_hits,
        competitor_hits=competitor_hits,
        market_openness=market_openness,
        remaining_gap=remaining_gap,
        skipped=False,
    )
