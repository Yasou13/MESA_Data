from mesa_legal_data.config import load_settings


def test_storage_quota_config():
    settings = load_settings()
    assert settings.storage.active_data_limit_gb == 50.0
    assert settings.storage.raw_limit_gb == 25.0
    assert settings.storage.minimum_free_space_gb == 20.0
    assert settings.mesa_staging_db.endswith("mesa_staging.sqlite")
