from bs4 import BeautifulSoup

from mesa_legal_data.parsers.text_normalizer import normalize_text


class HTMLParseError(Exception):
    pass


BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "article", "section", "blockquote"}


def parse_html(html_content: str | bytes) -> str:
    """
    Parses HTML content, strips script/style/noscript elements,
    preserves block boundaries with line breaks, and returns clean, normalized visible text.
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

    # Insert newlines for block-level elements to preserve paragraph and heading boundaries
    for tag in soup.find_all(BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")

    # Extract text with space separator for inline tags
    raw_text = soup.get_text(separator=" ")
    return normalize_text(raw_text)
