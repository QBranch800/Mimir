"""What each category is about and where its stories come from, shared by the filter
and the scorer.

They are used twice:

- before scoring, `on_topic` decides whether a story is plainly about one of its source's
  categories. It is strict on purpose: every story it lets through costs part of a
  Gemini request, and a story that never uses its category's own words is almost never
  a good one for it.
- after scoring, `fits` checks the category Gemini assigned: the story's source must be
  the one chosen for that category, and for monetary policy, US fiscal policy and US
  macro data it must use that category's words, which is where the lighter model kept
  filing company stories that merely mentioned a policy. The two US categories must also
  be about the US, since a French budget or a Japanese PMI uses the same words.
"""

import re

# Where each category's stories come from: one source each. A story only counts for a
# category its source was chosen to cover.
SOURCE = {
    "monetary_policy": "rss",
    "us_fiscal_policy": "google",
    "us_macro_data": "google",
    "geopolitics": "gdelt",
    "tech_and_ai": "google",
}

# Core vocabulary: a story genuinely about the category almost always uses one of these.
CORE = {
    "monetary_policy": [
        r"central banks?", r"federal reserve", r"\bthe fed\b", r"\bfed(?:'s)?\b", r"\bfomc\b",
        r"interest rates?", r"rate (?:cut|hike|rise|decision|path|outlook)s?",
        r"monetary policy", r"\becb\b", r"european central bank", r"bank of england",
        r"\bboe\b", r"bank of japan", r"\bboj\b", r"swiss national bank", r"\bsnb\b",
        r"people'?s bank of china", r"\bpboc\b", r"reserve bank", r"bank of canada",
        r"\bpowell\b", r"\blagarde\b", r"quantitative (?:easing|tightening)",
        r"policy rate", r"benchmark rate", r"basis points?", r"inflation target",
    ],
    # Money words, not parliament words: "Senate" and "Congress" turn up in every Capitol
    # story, from college sports to an Iran war vote, so they cannot show a story is
    # about budgets, tax or spending.
    "us_fiscal_policy": [
        r"federal budget", r"budget (?:deal|bill|resolution|deficit|request|proposal|office|talks|fight)",
        r"\bdeficits?\b", r"debt (?:ceiling|limit)", r"national debt", r"government shutdown",
        r"\bshutdown\b", r"appropriations?", r"spending (?:bill|package|cuts?|plan|deal|levels?)",
        r"stopgap", r"continuing resolution", r"budget reconciliation",
        r"tax (?:bill|cut|cuts|plan|code|credits?|hike|increase|package|reform|revenue|rates?)",
        r"\btreasury (?:secretary|department)\b", r"\bbessent\b", r"\bcbo\b",
        r"congressional budget office", r"\birs\b", r"federal spending", r"government funding",
        r"funding (?:bill|deadline|lapse|package)", r"white house budget", r"\bomb\b",
        r"tariff revenue", r"\bstimulus\b",
        # "fiscal" alone also matches "fiscal year", which every defence contract mentions
        r"fiscal (?:policy|package|plan|stimulus|deficit|cliff|hawks?|outlook|position|rules?|responsibility)",
    ],
    "us_macro_data": [
        r"\bcpi\b", r"consumer prices?", r"\binflation\b", r"jobs report", r"payrolls?",
        r"unemployment", r"jobless claims", r"\bgdp\b", r"gross domestic product",
        r"\bpmi\b", r"purchasing managers", r"retail sales", r"consumer spending",
        r"consumer (?:confidence|sentiment)", r"\bpce\b", r"housing starts", r"home sales",
        r"durable goods", r"industrial production", r"\bism\b", r"business activity",
        r"economic (?:data|growth|activity|report)", r"\brecession\b", r"labor market",
        r"job (?:openings|growth|gains|losses)", r"wage growth", r"productivity",
    ],
    "geopolitics": [
        r"\bwar\b", r"conflict", r"fighting", r"military", r"troops", r"missiles?",
        r"drones?", r"\bstrikes?\b", r"invasion", r"sanctions?", r"tariffs?",
        r"trade (?:war|deal|talks|tensions|dispute|pact|agreement)", r"summit",
        r"ceasefire", r"peace (?:talks|deal|plan)", r"elections?", r"\bvote\b",
        r"diplomat", r"\bnato\b", r"united nations", r"\bun\b", r"nuclear", r"embargo",
        r"\bcoup\b", r"border", r"strait", r"blockade", r"\btalks\b", r"treaty",
        r"president", r"prime minister", r"foreign minister", r"government",
        r"\bchina\b", r"\brussia\b", r"\bukraine\b", r"\biran\b", r"\bisrael\b",
        r"\bgaza\b", r"\btaiwan\b", r"north korea", r"middle east", r"opec", r"oil",
    ],
    # AI, chips and their policy, and the companies that move them: the AI labs, the
    # chipmakers, and the hyperscalers and cloud giants. Consumer brands are left out:
    # "Apple" turns up in share-price pieces far more often than in AI news.
    "tech_and_ai": [
        r"\bai\b", r"artificial intelligence", r"\bchips?\b", r"chipmakers?",
        r"semiconductors?", r"data cent(?:er|re)s?", r"\bllms?\b", r"language models?",
        r"export controls?", r"antitrust", r"big tech", r"hyperscalers?",
        r"cyber ?attacks?", r"\bhack", r"quantum comput", r"\bcompute\b",
        r"\bfoundr(?:y|ies)\b", r"\bcloud\b",
        r"\bopenai\b", r"\banthropic\b", r"\bdeepmind\b", r"\bxai\b", r"\bchatgpt\b",
        r"\bmistral\b", r"\bdeepseek\b",
        r"\bnvidia\b", r"\btsmc\b", r"\bamd\b", r"\bintel\b", r"\bbroadcom\b", r"\basml\b",
        r"\bmicron\b", r"\bmicrosoft\b", r"\balphabet\b", r"\bgoogle\b",
        r"amazon web services", r"\baws\b", r"\boracle\b", r"\bcoreweave\b",
    ],
}

_CORE_RE = {cat: re.compile("|".join(terms), re.I) for cat, terms in CORE.items()}

# Only these categories are checked after scoring: their words are specific enough that a
# genuine story nearly always uses one. Geopolitics and tech vocabulary is too broad to
# prove anything, so those are left to the verification pass instead.
GUARDED = {"monetary_policy", "us_fiscal_policy", "us_macro_data"}

# The two US categories also need the story to be about the US: budget and PMI words read
# the same in France and Japan, and both got filed as US news before this check existed.
# "US" is matched case-sensitively, since in lower case it is just the word "us".
US_ONLY = {"us_fiscal_policy", "us_macro_data"}
_US_CASED = re.compile(r"\bU\.?S\.?A?\b")
_US_WORDS = re.compile(
    r"united states|\bamerica(?:n|ns)?\b|\bcongress|\bsenate\b|white house|\btreasury\b|"
    r"\bfederal\b|\bthe fed\b|\bwashington\b|\btrump\b|\birs\b|\bcbo\b|\bbessent\b|"
    r"wall street|\bdow\b|s&p 500|\bnasdaq\b|\bbls\b|bureau of labor|commerce department|"
    r"\bhouse (?:passes|passed|votes?|voted|republicans|democrats|speaker|majority)\b|"
    r"\brepublicans?\b|\bdemocrats?\b|\bgop\b",
    re.I)


def is_about_us(article):
    text = _text(article)
    return bool(_US_CASED.search(text) or _US_WORDS.search(text))


def _text(article):
    return f"{article.get('title') or ''} {article.get('summary') or ''}"


def categories_of(feed):
    """The categories a source was chosen to cover, in the briefing's order."""
    return [category for category, source in SOURCE.items() if source == feed]


def on_topic(article, category):
    """Before scoring: does the story use this category's core words, and for the two
    US categories, is it about the US?"""
    if category in US_ONLY and not is_about_us(article):
        return False
    return bool(_CORE_RE[category].search(_text(article)))


def fits(article, category):
    """After scoring: can the story stand in the category Gemini gave it?

    It must come from the source chosen for that category. Categories outside GUARDED
    are not checked for words, since theirs are too broad to settle it.
    """
    if SOURCE.get(category) != article.get("feed"):
        return False
    if category not in GUARDED:
        return True
    return on_topic(article, category)
