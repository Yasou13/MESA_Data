import pytest

from mesa_legal_data.storage_paths import secure_slug, build_raw_path, PathSecurityError

def test_secure_slug():
    assert secure_slug("Normal Name") == "normal-name"
    assert secure_slug("Türkçe Başlık ŞÇÖĞÜI") == "turkce-baslik-scogui"
    assert secure_slug("file@name!") == "filename"
    
def test_secure_slug_length():
    long_name = "a" * 150
    slug = secure_slug(long_name)
    assert len(slug) == 100

def test_secure_slug_security():
    with pytest.raises(PathSecurityError, match="Null byte"):
        secure_slug("file\0name")
        
    with pytest.raises(PathSecurityError, match="Path separators"):
        secure_slug("dir/file")
        
    with pytest.raises(PathSecurityError, match="Path separators"):
        secure_slug("dir\\file")
        
    with pytest.raises(PathSecurityError, match="Invalid filename"):
        secure_slug("..")
        
    with pytest.raises(PathSecurityError, match="empty slug"):
        secure_slug("!!!")

def test_build_raw_path():
    hash64 = "a" * 64
    path = build_raw_path("legislation", "mevzuat", 2026, "tr-law-4721", hash64, ".pdf")
    expected = f"raw/legislation/mevzuat/2026/tr-law-4721/{hash64}/payload.pdf"
    assert str(path) == expected

def test_build_raw_path_invalid_hash():
    with pytest.raises(PathSecurityError, match="exactly 64"):
        build_raw_path("leg", "src", 2026, "key", "short-hash", ".pdf")
