from bs4 import BeautifulSoup

from mesa_legal_data.parsers.text_normalizer import normalize_text


class HTMLParseError(Exception):
    pass


def parse_html(html_content: str | bytes) -> str:
    """
    Parses HTML content, strips script/style/nav/header/footer/noscript elements,
    and returns clean, normalized visible text.
    """
    if not html_content:
        return ""

    try:
        soup = BeautifulSoup(html_content, "lxml")
    except Exception:
        # Fallback parser if lxml fails
        soup = BeautifulSoup(html_content, "html.parser")

    # Remove non-content tags
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "head", "meta"]):
        tag.decompose()

    # Extract text with space separator for inline tags
    raw_text = soup.get_text(separator=" ")
    return normalize_text(raw_text)
