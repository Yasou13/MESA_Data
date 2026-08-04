import io

from mesa_legal_data.hashing import hash_stream

def test_hash_stream():
    content = b"Hello, world!"
    stream = io.BytesIO(content)
    # sha256 of "Hello, world!"
    expected_hash = "315f5bdb76d078c43b8ac0064e4a0164612b1fce77c869345bfc94c75894edd3"
    assert hash_stream(stream) == expected_hash

def test_hash_stream_chunking():
    content = b"A" * 10000
    stream = io.BytesIO(content)
    h1 = hash_stream(stream, chunk_size=8192)
    stream.seek(0)
    h2 = hash_stream(stream, chunk_size=1024)
    assert h1 == h2
