import re


class UnsafeReleaseIDError(ValueError):
    pass


RELEASE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def validate_release_id(release_id: str) -> str:
    if not release_id or not isinstance(release_id, str):
        raise UnsafeReleaseIDError("Release ID must be a non-empty string")

    if ".." in release_id or "/" in release_id or "\\" in release_id:
        raise UnsafeReleaseIDError(f"Path traversal detected in release ID: {release_id}")

    if release_id.startswith(".") or release_id.startswith("/") or release_id.startswith("\\"):
        raise UnsafeReleaseIDError(f"Unsafe release ID prefix: {release_id}")

    if not RELEASE_ID_PATTERN.match(release_id):
        raise UnsafeReleaseIDError(f"Invalid release ID format: '{release_id}'")

    return release_id
