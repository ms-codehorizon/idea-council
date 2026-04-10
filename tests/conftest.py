from idea_council.providers.adapter import ProviderAdapter


class MockAdapter(ProviderAdapter):
    """
    A test double for any provider adapter. Returns a fixed response
    for every call. Tracks how many times it was called.
    """

    def __init__(self, provider: str, model: str, response: str):
        super().__init__(provider, model)
        self.response = response
        self.call_count = 0
        self.last_system = None
        self.last_user = None

    def call(self, system: str, user: str, max_tokens: int = 2048) -> str:
        self.call_count += 1
        self.last_system = system
        self.last_user = user
        return self.response


SAMPLE_DEBATER_RESPONSE = """POSITION: This idea has strong market potential in an underserved segment.
ARGUMENTS:
1. Gig economy workers represent 36% of the US workforce with no credit scoring solution built for them.
2. Traditional credit bureaus do not capture income volatility patterns that predict gig worker reliability.
3. Embedded finance APIs have proven demand after Stripe and Plaid demonstrated the market.
CONFIDENCE: 7"""

SAMPLE_CRITIC_RESPONSE = """POSITION: The core assumption about data access is likely wrong.
ARGUMENTS:
1. Gig platforms will not share transaction data with a third party without significant revenue sharing.
2. Regulatory classification of this as a credit bureau triggers FCRA compliance which requires $2M+ legal overhead.
3. Banks already have this data internally and will build this themselves before licensing it.
CONFIDENCE: 8"""

SAMPLE_EXIT_DONE = "done"
SAMPLE_EXIT_CONTINUE = "continue"

SAMPLE_FINAL_SYNTHESIS = """VERDICT: pivot
OPPORTUNITY_SCORE: 6
STRONGEST_ARGUMENT: Gig economy workers represent a genuinely underserved credit segment with no incumbents serving them directly.
FATAL_FLAW: Gig platforms control the data and have no incentive to share it with a third party.
KILL_CONDITIONS:
- Gig platforms refuse data sharing agreements
- Regulatory classification triggers FCRA compliance burden
WHAT_MUST_BE_TRUE:
- At least one major gig platform agrees to a data partnership
- Regulatory counsel confirms non-FCRA path exists"""

SAMPLE_MARKET_INTERPRETATION = """PRIOR_ART_SCORE: 6
COMPETITORS:
- github.com/example/gig-credit
- founderflow.tech
REMAINING_GAP: No existing solution covers income volatility modeling specifically for multi-platform gig workers."""
