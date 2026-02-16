from lib.storage.io import gunzip_bytes, gzip_bytes


def test_gzip_roundtrip():
    payload = b"hello world\n"
    assert gunzip_bytes(gzip_bytes(payload)) == payload
