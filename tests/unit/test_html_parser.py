from mesa_legal_data.parsers.html import parse_html


def test_parse_html_clean():
    raw_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page</title>
        <style>body { color: red; }</style>
        <script>console.log('test');</script>
    </head>
    <body>
        <h1>MADDE 1</h1>
        <p>Hukukun uygulanması ve <b>kaynakları</b>.</p>
        <noscript>Javascript disabled</noscript>
    </body>
    </html>
    """
    cleaned = parse_html(raw_html)
    assert "MADDE 1" in cleaned
    assert "Hukukun uygulanması ve kaynakları." in cleaned
    assert "color: red" not in cleaned
    assert "console.log" not in cleaned
    assert "Javascript disabled" not in cleaned
