from concurrent.futures import ThreadPoolExecutor, as_completed

from idea_council.providers.adapter import ProviderAdapter
from idea_council.roles.prompts import SEED_GENERATOR


def _generate_one_seed(
    adapter: ProviderAdapter, domain: str, exclusions: list[str], max_tokens: int
) -> str:
    """Ask one provider to generate a seed idea for the given domain."""
    user_prompt = f"Domain: {domain}"

    if exclusions:
        exclusion_list = "\n".join(f"- {e}" for e in exclusions)
        user_prompt += f"\n\nThe following already exist in this space. Do not generate ideas similar to them:\n{exclusion_list}"

    return adapter.call(system=SEED_GENERATOR, user=user_prompt, max_tokens=max_tokens)


def _pick_best_seed(
    seeds: list[str], domain: str, synthesizer: ProviderAdapter, max_tokens: int
) -> str:
    """Ask the synthesizer to pick the most distinctive seed from the list."""
    numbered = "\n\n".join(f"Idea {i + 1}:\n{seed}" for i, seed in enumerate(seeds))

    system = (
        "You are selecting the most promising idea from a list of candidates. "
        "Pick the one that is most specific, most distinct, and most worth debating. "
        "Return only the full text of the chosen idea. No explanation, no preamble."
    )
    user = f"Domain: {domain}\n\nCandidates:\n\n{numbered}"

    return synthesizer.call(system=system, user=user, max_tokens=max_tokens)


def generate_seeds(
    debaters: list[ProviderAdapter],
    synthesizer: ProviderAdapter,
    domain: str,
    exclusions: list[str],
    max_tokens: int,
) -> tuple[str, list[str]]:
    """
    Runs seed generation in parallel across all debaters.
    Returns the chosen seed and the list of rejected seeds.
    """
    seeds = []

    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(
                _generate_one_seed, adapter, domain, exclusions, max_tokens
            ): adapter
            for adapter in debaters
        }
        for future in as_completed(futures):
            adapter = futures[future]
            try:
                seed = future.result()
                seeds.append(seed.strip())
            except Exception as e:
                print(
                    f"[warning] Seed generation failed for {adapter.provider}/{adapter.model}: {e}"
                )

    if not seeds:
        raise RuntimeError(
            "All providers failed to generate a seed idea. Cannot continue."
        )

    if len(seeds) == 1:
        return seeds[0], []

    chosen = _pick_best_seed(seeds, domain, synthesizer, max_tokens)
    rejected = [s for s in seeds if s != chosen]

    return chosen, rejected
