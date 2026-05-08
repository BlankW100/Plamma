import re
from datetime import datetime
from bs4 import BeautifulSoup
from tor_proxy import get_session

DDG_HTML = "https://html.duckduckgo.com/html/"
FINVIZ_URL = "https://finviz.com/quote.ashx?t="

# Common English uppercase tokens that are not stock tickers
# ── Timezone resolution (answers "what time is it in X" locally, no web search) ──

_TZ_ALIASES: dict[str, str] = {
    # Country codes & names
    "jp": "Asia/Tokyo", "japan": "Asia/Tokyo", "tokyo": "Asia/Tokyo",
    "kr": "Asia/Seoul", "korea": "Asia/Seoul", "seoul": "Asia/Seoul",
    "cn": "Asia/Shanghai", "china": "Asia/Shanghai", "beijing": "Asia/Shanghai",
    "hk": "Asia/Hong_Kong", "hong kong": "Asia/Hong_Kong",
    "tw": "Asia/Taipei", "taiwan": "Asia/Taipei", "taipei": "Asia/Taipei",
    "sg": "Asia/Singapore", "singapore": "Asia/Singapore",
    "th": "Asia/Bangkok", "thailand": "Asia/Bangkok", "bangkok": "Asia/Bangkok",
    "vn": "Asia/Ho_Chi_Minh", "vietnam": "Asia/Ho_Chi_Minh",
    "ph": "Asia/Manila", "philippines": "Asia/Manila", "manila": "Asia/Manila",
    "my": "Asia/Kuala_Lumpur", "malaysia": "Asia/Kuala_Lumpur",
    "id": "Asia/Jakarta", "indonesia": "Asia/Jakarta", "jakarta": "Asia/Jakarta",
    "in": "Asia/Kolkata", "india": "Asia/Kolkata", "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata",
    "pk": "Asia/Karachi", "pakistan": "Asia/Karachi",
    "bd": "Asia/Dhaka", "bangladesh": "Asia/Dhaka",
    "ae": "Asia/Dubai", "uae": "Asia/Dubai", "dubai": "Asia/Dubai",
    "il": "Asia/Jerusalem", "israel": "Asia/Jerusalem",
    "ru": "Europe/Moscow", "russia": "Europe/Moscow", "moscow": "Europe/Moscow",
    "tr": "Europe/Istanbul", "turkey": "Europe/Istanbul", "istanbul": "Europe/Istanbul",
    "uk": "Europe/London", "gb": "Europe/London", "england": "Europe/London", "london": "Europe/London",
    "ie": "Europe/Dublin", "ireland": "Europe/Dublin",
    "pt": "Europe/Lisbon", "portugal": "Europe/Lisbon", "lisbon": "Europe/Lisbon",
    "es": "Europe/Madrid", "spain": "Europe/Madrid", "madrid": "Europe/Madrid",
    "fr": "Europe/Paris", "france": "Europe/Paris", "paris": "Europe/Paris",
    "de": "Europe/Berlin", "germany": "Europe/Berlin", "berlin": "Europe/Berlin",
    "it": "Europe/Rome", "italy": "Europe/Rome", "rome": "Europe/Rome",
    "nl": "Europe/Amsterdam", "netherlands": "Europe/Amsterdam", "amsterdam": "Europe/Amsterdam",
    "be": "Europe/Brussels", "belgium": "Europe/Brussels",
    "ch": "Europe/Zurich", "switzerland": "Europe/Zurich", "zurich": "Europe/Zurich",
    "at": "Europe/Vienna", "austria": "Europe/Vienna",
    "pl": "Europe/Warsaw", "poland": "Europe/Warsaw",
    "se": "Europe/Stockholm", "sweden": "Europe/Stockholm",
    "no": "Europe/Oslo", "norway": "Europe/Oslo",
    "fi": "Europe/Helsinki", "finland": "Europe/Helsinki",
    "dk": "Europe/Copenhagen", "denmark": "Europe/Copenhagen",
    "eg": "Africa/Cairo", "egypt": "Africa/Cairo", "cairo": "Africa/Cairo",
    "za": "Africa/Johannesburg", "south africa": "Africa/Johannesburg",
    "ng": "Africa/Lagos", "nigeria": "Africa/Lagos",
    "ke": "Africa/Nairobi", "kenya": "Africa/Nairobi",
    "au": "Australia/Sydney", "australia": "Australia/Sydney", "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne", "brisbane": "Australia/Brisbane", "perth": "Australia/Perth",
    "nz": "Pacific/Auckland", "new zealand": "Pacific/Auckland", "auckland": "Pacific/Auckland",
    "ca": "America/Toronto", "canada": "America/Toronto", "toronto": "America/Toronto",
    "vancouver": "America/Vancouver", "montreal": "America/Toronto",
    "mx": "America/Mexico_City", "mexico": "America/Mexico_City",
    "br": "America/Sao_Paulo", "brazil": "America/Sao_Paulo",
    "ar": "America/Argentina/Buenos_Aires", "argentina": "America/Argentina/Buenos_Aires",
    "co": "America/Bogota", "colombia": "America/Bogota",
    "pe": "America/Lima", "peru": "America/Lima",
    "cl": "America/Santiago", "chile": "America/Santiago",
    # US cities
    "new york": "America/New_York", "nyc": "America/New_York",
    "los angeles": "America/Los_Angeles", "la": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "houston": "America/Chicago",
    "dallas": "America/Chicago",
    "denver": "America/Denver",
    "phoenix": "America/Phoenix",
    "san francisco": "America/Los_Angeles", "sf": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "miami": "America/New_York",
    "boston": "America/New_York",
    "atlanta": "America/New_York",
    "washington": "America/New_York",
    "hawaii": "Pacific/Honolulu", "honolulu": "Pacific/Honolulu",
    "alaska": "America/Anchorage", "anchorage": "America/Anchorage",
    # Common timezone abbreviations
    "jst": "Asia/Tokyo",
    "kst": "Asia/Seoul",
    "cst": "Asia/Shanghai",
    "ist": "Asia/Kolkata",
    "gst": "Asia/Dubai",
    "msk": "Europe/Moscow",
    "gmt": "UTC",
    "utc": "UTC",
    "bst": "Europe/London",
    "cet": "Europe/Paris",
    "eet": "Europe/Helsinki",
    "est": "America/New_York",
    "edt": "America/New_York",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "mst": "America/Denver",
    "aest": "Australia/Sydney",
    "nzst": "Pacific/Auckland",
}

_TIME_PATTERNS = [
    r"\bwhat(?:'s| is) the (?:current |local )?time\b",
    r"\bwhat time is it\b",
    r"\bcurrent time\b",
    r"\btime (?:now|right now|at the moment)\b",
    r"\btime in\b",
    r"\btime (?:for|at)\b",
    r"\bnow in\b",
    r"\btime zone\b",
    r"\btimezone\b",
]


def resolve_time_query(message: str) -> str | None:
    """
    If the message asks for current time in a location, return a formatted
    fact string with the actual current time computed locally. Returns None
    if this is not a recognisable time query.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        return None

    low = message.lower()

    if not any(re.search(p, low) for p in _TIME_PATTERNS):
        return None

    # Find the most specific alias match (longest first)
    tz_id: str | None = None
    for alias in sorted(_TZ_ALIASES, key=len, reverse=True):
        if re.search(r'\b' + re.escape(alias) + r'\b', low):
            tz_id = _TZ_ALIASES[alias]
            break

    if tz_id is None:
        # No location — return local time
        now = datetime.now()
        return (
            f"Current local time: {now.strftime('%H:%M:%S')} "
            f"on {now.strftime('%A, %B %d, %Y')}"
        )

    try:
        tz = ZoneInfo(tz_id)
    except Exception:
        return None

    now = datetime.now(tz)
    offset = now.strftime('%z')         # e.g. "+0900"
    h, m = int(offset[1:3]), int(offset[3:5])
    utc_str = f"UTC{offset[0]}{h}" if m == 0 else f"UTC{offset[0]}{h}:{m:02d}"
    friendly = tz_id.split('/')[-1].replace('_', ' ')

    return (
        f"Current time in {friendly} ({tz_id}, {utc_str}): "
        f"{now.strftime('%H:%M:%S')} — {now.strftime('%A, %B %d, %Y')}"
    )


_NOT_TICKERS = {
    "I","A","AN","THE","AND","OR","IS","IN","TO","OF","FOR","ON","AT","BY",
    "AS","BE","DO","GO","US","UP","SO","IF","MY","NO","IT","HE","WE","ME",
    "OK","TV","ALL","ANY","CAN","MAY","TOO","WHO","HOW","NOW","NEW","OLD",
    "BIG","TOP","OUT","OFF","NOT","BUT","YET","ARE","HAS","WAS","HAD","DID",
    "GET","GOT","LET","SAY","SET","PUT","RUN","SEE","TRY","USE","ADD","ASK",
    "AI","API","URL","PDF","CSV","SQL","HTML","CSS","USD","EUR","GBP","JPY",
}

LIVE_KEYWORDS = {
    # time-sensitive
    "today","tonight","yesterday","current","currently","latest","recent",
    "recently","now","right now","live","real-time","realtime",
    "this week","this month","this year","at the moment","just happened",
    "lately","these days","still","2024","2025","2026",
    # finance
    "price","prices","stock","stocks","share","shares","ticker","market",
    "trading","crypto","bitcoin","ethereum","btc","eth","nft",
    "rate","rates","interest rate","exchange rate","earnings","ipo",
    # news / events
    "news","breaking","headline","headlines","announcement","update",
    "weather","temperature","forecast","score","result","standings","election",
    # inference helpers
    "who won","did they","have they","is he","is she","are they",
    # explicit online intent
    "internet","online","website","web search",
}

# Phrases that explicitly ask for a search, regardless of other keywords
_SEARCH_PHRASES = {
    "search for","search up","search about",
    "find me","find information","find out","find online",
    "look up","look it up","look for",
    "browse for","browse the web",
    "search online","search the web","search the internet",
    "check online","check the web","check the internet","check for",
    "google it","google for",
    "can you find","can you search","can you look up","can you check",
    "what does the internet say","what does google say",
    "get me information","get information on","get info on",
    "research","i need to know about","tell me the latest",
}

# .onion search engines — reachable only through Tor
AHMIA_ONION = "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/search/"
HAYSTAK_ONION = "http://haystak5njsmn2hqkewecpaxetahtwhsbsa64jom2k22z5afxhnpxfid.onion/"


def search_surface(query: str, max_results: int = 6) -> list[dict]:
    s = get_session()
    try:
        r = s.post(
            DDG_HTML,
            data={"q": query, "b": "", "kl": "us-en"},
            timeout=20,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for item in soup.select(".result")[:max_results]:
            title_el = item.select_one(".result__title a")
            snippet_el = item.select_one(".result__snippet")
            url_el = item.select_one(".result__url")
            if not title_el:
                continue
            url = url_el.get_text(strip=True) if url_el else title_el.get("href", "")
            results.append({
                "index": len(results) + 1,
                "title": title_el.get_text(strip=True),
                "url": url,
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                "source": "surface",
            })
        return results if results else [{"error": "No results found on DuckDuckGo.", "source": "surface"}]
    except Exception as e:
        return [{"error": f"Surface search failed: {e}", "source": "surface"}]


def search_dark(query: str, max_results: int = 6) -> list[dict]:
    s = get_session()
    results = []
    offset = len(results) + 1

    # Try Ahmia .onion
    try:
        r = s.get(AHMIA_ONION, params={"q": query}, timeout=45)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select("li.result")[:max_results]:
            title_el = item.select_one("h4")
            link_el = item.select_one("a")
            desc_el = item.select_one("p")
            if not (title_el and link_el):
                continue
            href = link_el.get("href", "")
            # Ahmia wraps onion URLs in a redirect — unwrap it
            if "redirect_url=" in href:
                from urllib.parse import parse_qs, urlparse
                qs = parse_qs(urlparse(href).query)
                href = qs.get("redirect_url", [href])[0]
            results.append({
                "index": offset + len(results),
                "title": title_el.get_text(strip=True),
                "url": href,
                "snippet": desc_el.get_text(strip=True)[:250] if desc_el else "",
                "source": "dark",
            })
    except Exception as e:
        results.append({"error": f"Ahmia .onion failed: {e}", "source": "dark"})

    # Try Haystak .onion if Ahmia gave nothing useful
    if sum(1 for r in results if "error" not in r) < 2:
        try:
            r = s.get(HAYSTAK_ONION, params={"q": query}, timeout=45)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for link in soup.select("a[href*='.onion']")[:max_results]:
                href = link.get("href", "")
                text = link.get_text(strip=True)
                if not text or len(text) < 4:
                    continue
                parent_text = link.parent.get_text(strip=True)[:250] if link.parent else ""
                results.append({
                    "index": offset + len(results),
                    "title": text,
                    "url": href,
                    "snippet": parent_text,
                    "source": "dark",
                })
        except Exception as e:
            results.append({"error": f"Haystak .onion failed: {e}", "source": "dark"})

    return results[:max_results] if results else [{"error": "No dark web results found.", "source": "dark"}]


def format_for_llm(results: list[dict]) -> str:
    lines = ["Search results:\n"]
    for r in results:
        if "error" in r:
            lines.append(f"  [Error] {r['error']}")
            continue
        tag = "[DARK WEB]" if r.get("source") == "dark" else "[WEB]"
        lines.append(f"[{r['index']}] {tag} {r.get('title', '(no title)')}")
        lines.append(f"    URL: {r.get('url', '')}")
        if r.get("snippet"):
            lines.append(f"    Snippet: {r['snippet']}")
    return "\n".join(lines)


def format_citations(results: list[dict]) -> str:
    lines = ["\n\nSources:"]
    for r in results:
        if "error" not in r:
            tag = "[dark]" if r.get("source") == "dark" else "[web]"
            lines.append(f"  [{r['index']}] {tag} {r.get('url', '')}")
    return "\n".join(lines)


_COMPANY_MAP: dict[str, str] = {
    # US / global — common names + misspellings → canonical ticker
    "nvidia": "NVDA", "nvdia": "NVDA", "nvda": "NVDA",
    "apple": "AAPL", "aapl": "AAPL",
    "google": "GOOGL", "alphabet": "GOOGL", "googl": "GOOGL", "goog": "GOOG",
    "microsoft": "MSFT", "msft": "MSFT",
    "amazon": "AMZN", "amzn": "AMZN",
    "tesla": "TSLA", "tsla": "TSLA",
    "meta": "META", "facebook": "META",
    "netflix": "NFLX", "nflx": "NFLX",
    "amd": "AMD", "intel": "INTC",
    "qualcomm": "QCOM", "broadcom": "AVGO",
    "tsmc": "TSM", "asml": "ASML", "arm": "ARM",
    "berkshire": "BRK-B",
    "jpmorgan": "JPM", "jp morgan": "JPM",
    "visa": "V", "mastercard": "MA",
    "walmart": "WMT", "disney": "DIS",
    "salesforce": "CRM", "adobe": "ADBE",
    "paypal": "PYPL", "uber": "UBER",
    "airbnb": "ABNB", "palantir": "PLTR",
    "snowflake": "SNOW", "shopify": "SHOP",
    "spotify": "SPOT", "coinbase": "COIN",
    "bitcoin": "BTC-USD", "ethereum": "ETH-USD",
    # Malaysia (Bursa) — Yahoo Finance uses .KL suffix
    "ecoshop": "5228.KL", "eco shop": "5228.KL",
    "mrdiy": "5296.KL", "mr diy": "5296.KL", "mr.diy": "5296.KL",
    "maybank": "1155.KL", "cimb": "1023.KL", "tenaga": "5347.KL",
    "petronas": "5183.KL", "axiata": "6888.KL", "ioicorp": "1961.KL",
    "rhb": "1066.KL", "public bank": "1295.KL", "hong leong": "5819.KL",
    # Singapore (SGX)
    "dbs": "D05.SI", "ocbc": "O39.SI", "uob": "U11.SI",
    "singtel": "Z74.SI", "capitaland": "9CI.SI",
    # Hong Kong (HKEX)
    "tencent": "0700.HK", "alibaba": "9988.HK", "baba": "BABA",
    "meituan": "3690.HK", "xiaomi": "1810.HK",
    # UK (LSE)
    "bp": "BP.L", "shell": "SHEL.L", "hsbc": "HSBA.L",
    "unilever": "ULVR.L", "astrazeneca": "AZN.L",
}


def detect_tickers(message: str) -> list[str]:
    """Return stock tickers found in message — matches uppercase symbols and company names."""
    seen: set[str] = set()
    result: list[str] = []
    low = message.lower()

    # Match company names / common spellings first
    for name, ticker in _COMPANY_MAP.items():
        if re.search(r'\b' + re.escape(name) + r'\b', low):
            if ticker not in seen:
                seen.add(ticker)
                result.append(ticker)

    # Also match explicit uppercase tickers like NVDA, TSLA
    for token in re.findall(r'\b([A-Z]{2,5})\b', message):
        if token not in _NOT_TICKERS and token not in seen:
            seen.add(token)
            result.append(token)

    return result


def needs_live_data(message: str) -> tuple[bool, list[str]]:
    """Return (should_auto_search, detected_tickers) for a plain user message."""
    low = message.lower()
    has_keyword = any(kw in low for kw in LIVE_KEYWORDS)
    has_phrase  = any(ph in low for ph in _SEARCH_PHRASES)
    tickers = detect_tickers(message)
    return (has_keyword or has_phrase or bool(tickers)), tickers


_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _fetch_yahoo_price(ticker: str) -> dict | None:
    """Fetch price data from Yahoo Finance JSON API. Works for any global exchange."""
    s = get_session()
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        "?interval=1d&range=1d"
    )
    try:
        r = s.get(url, timeout=15, headers=_YAHOO_HEADERS)
        if r.status_code != 200:
            return None
        result = r.json().get("chart", {}).get("result")
        if not result:
            return None
        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        if not price:
            return None
        currency = meta.get("currency", "")
        return {
            "price":    str(round(price, 4)),
            "currency": currency,
            "change":   str(round(meta.get("regularMarketChangePercent", 0), 2)) + "%",
            "volume":   str(meta.get("regularMarketVolume", "?")),
            "52w_high": str(round(meta.get("fiftyTwoWeekHigh", 0), 2)),
            "52w_low":  str(round(meta.get("fiftyTwoWeekLow", 0), 2)),
            "exchange": meta.get("exchangeName", ""),
        }
    except Exception:
        return None


def _search_yahoo_ticker(name: str) -> str | None:
    """Resolve a company name to a Yahoo Finance ticker symbol via their search API."""
    s = get_session()
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={name}&quotesCount=3&newsCount=0"
    try:
        r = s.get(url, timeout=10, headers=_YAHOO_HEADERS)
        if r.status_code != 200:
            return None
        for quote in r.json().get("quotes", []):
            symbol = quote.get("symbol", "")
            # Prefer equity-type results
            if quote.get("quoteType") in ("EQUITY", "ETF") and symbol:
                return symbol
    except Exception:
        pass
    return None


def fetch_finviz(tickers: list[str]) -> str:
    """
    Fetch live stock data for each ticker.
    Tries Finviz first (US stocks, rich data). Falls back to Yahoo Finance,
    which supports global exchanges (KLSE, SGX, HKEX, LSE, etc.).
    If a ticker yields no result on either source, attempts a Yahoo name-search.
    """
    s = get_session()
    _FIELDS = {"Price", "Change", "Volume", "Market Cap", "P/E", "52W High", "52W Low"}
    rows = []

    for ticker in tickers[:6]:
        data_line = None

        # ── 1. Finviz (US-listed stocks) ──────────────────────────────────────
        try:
            r = None
            for _ in range(2):
                try:
                    r = s.get(FINVIZ_URL + ticker, timeout=12)
                    if r.status_code == 200:
                        break
                    s = get_session()
                except Exception:
                    s = get_session()
            if r and r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                all_tds = soup.find_all("td")
                fz: dict[str, str] = {}
                for i, td in enumerate(all_tds):
                    txt = td.get_text(strip=True)
                    if txt in _FIELDS and i + 1 < len(all_tds):
                        fz[txt] = all_tds[i + 1].get_text(strip=True)
                if fz.get("Price"):
                    data_line = (
                        f"  {ticker} [Finviz]: Price=${fz['Price']}  "
                        f"Change={fz.get('Change','?')}  "
                        f"MarketCap={fz.get('Market Cap','?')}  "
                        f"P/E={fz.get('P/E','?')}  "
                        f"Volume={fz.get('Volume','?')}  "
                        f"52W-High={fz.get('52W High','?')}"
                    )
        except Exception:
            pass

        # ── 2. Yahoo Finance (global fallback) ────────────────────────────────
        if not data_line:
            ydata = _fetch_yahoo_price(ticker)
            if ydata:
                cur  = ydata["currency"]
                exch = f" [{ydata['exchange']}]" if ydata["exchange"] else ""
                data_line = (
                    f"  {ticker}{exch} [Yahoo]: Price={cur}{ydata['price']}  "
                    f"Change={ydata['change']}  "
                    f"Volume={ydata['volume']}  "
                    f"52W {ydata['52w_low']}–{ydata['52w_high']}"
                )

        # ── 3. Yahoo name-search (unknown / non-standard ticker strings) ──────
        if not data_line:
            resolved = _search_yahoo_ticker(ticker)
            if resolved and resolved != ticker:
                ydata = _fetch_yahoo_price(resolved)
                if ydata:
                    cur  = ydata["currency"]
                    exch = f" [{ydata['exchange']}]" if ydata["exchange"] else ""
                    data_line = (
                        f"  {ticker}→{resolved}{exch} [Yahoo]: Price={cur}{ydata['price']}  "
                        f"Change={ydata['change']}  "
                        f"Volume={ydata['volume']}  "
                        f"52W {ydata['52w_low']}–{ydata['52w_high']}"
                    )

        rows.append(data_line or f"  {ticker}: not found on Finviz or Yahoo Finance")

    if not rows:
        return ""
    return "Live stock data:\n" + "\n".join(rows)
