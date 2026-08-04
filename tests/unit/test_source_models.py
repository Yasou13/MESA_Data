from mesa_legal_data.models import DiscoveredItem, FetchedArtifact

def test_discovered_item():
    item = DiscoveredItem(
        document_id="doc1",
        family="family",
        document_type="type",
        jurisdiction="TR",
        stable_key="key",
        source_url="http://test"
    )
    assert item.document_id == "doc1"
    assert item.fetch_method == "GET"

def test_fetched_artifact():
    artifact = FetchedArtifact(
        artifact_id="art1",
        document_id="doc1",
        source_id="src1",
        source_url="http://test",
        retrieved_at="2026",
        fetch_method="GET",
        http_status=200,
        declared_content_type="html",
        detected_content_type="html",
        byte_size=10,
        sha256="hash",
        raw_path="path",
        transport_status="verified"
    )
    assert artifact.artifact_id == "art1"
