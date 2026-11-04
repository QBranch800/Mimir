from urllib.parse import urlparse

OUTLETS = {
    "CNN": ["cnn.com"],
    "BBC": ["bbc.com", "bbc.co.uk"],
    "The Wall Street Journal": ["wsj.com"],
    "Reuters": ["reuters.com"],
    "Axios": ["axios.com"],
    "The New York Times": ["nytimes.com"],
    "Bloomberg": ["bloomberg.com"],
    "Al Jazeera": ["aljazeera.com"],
    "The Guardian": ["theguardian.com"],
    "The Washington Post": ["washingtonpost.com"],
    "Fox News": ["foxnews.com"],
    "Associated Press": ["apnews.com"],
    "CNBC": ["cnbc.com"],
    "The National": ["thenationalnews.com"],
    "Yahoo Finance": ["finance.yahoo.com"],
    "Financial Times": ["ft.com"],
    "The Economist": ["economist.com"],
    "Forbes": ["forbes.com"],
    "CBS News": ["cbsnews.com"],
    "Politico": ["politico.com", "politico.eu"],
    "NBC News": ["nbcnews.com"],
}
SITES = [site for sites in OUTLETS.values() for site in sites]

PRESS_RELEASE_SITES = ["markets.ft.com", "markets-origin.ft.com"]


def _within(host, site):
    return host == site or host.endswith("." + site)


def site_of(url):
    host = urlparse(url or "").hostname or ""
    if any(_within(host, site) for site in PRESS_RELEASE_SITES):
        return None
    return next((site for site in SITES if _within(host, site)), None)
