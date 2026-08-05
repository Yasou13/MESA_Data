from pathlib import Path

from fastapi import HTTPException

from mesa_legal_data.hashing import hash_stream


def resolve_verified_download(
    *,
    relative_path: str | Path,
    expected_sha256: str | None = None,
    data_root: Path,
) -> Path:
    """
    Central verified download helper.
    Enforces path resolution, data_root boundary, symlink rejection, file existence, regular file check,
    and optional SHA-256 integrity verification.
    """
    target_path = Path(relative_path)
    if not target_path.is_absolute():
        target_path = data_root / target_path

    # Check symlink on target before resolve
    if target_path.is_symlink():
        raise HTTPException(
            status_code=403,
            detail={"code": "SYMLINK_REJECTED", "message": "Symlink file access is forbidden"},
        )

    try:
        resolved_path = target_path.resolve()
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": "PATH_INVALID", "message": str(e)})

    # Data root boundary check
    resolved_root = data_root.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail={"code": "PATH_TRAVERSAL_DENIED", "message": "Access outside data root is forbidden"},
        )

    # Check symlinks on target and resolved path
    if target_path.is_symlink() or resolved_path.is_symlink():
        raise HTTPException(
            status_code=403,
            detail={"code": "SYMLINK_REJECTED", "message": "Symlink file access is forbidden"},
        )

    # Check parent components for symlinks
    curr = target_path
    while curr != data_root and curr != curr.parent:
        if curr.is_symlink():
            raise HTTPException(
                status_code=403,
                detail={"code": "SYMLINK_REJECTED", "message": "Symlink path component is forbidden"},
            )
        curr = curr.parent

    # File existence and regular file check
    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"code": "FILE_NOT_FOUND", "message": f"Requested file missing on disk: {target_path.name}"},
        )

    # SHA-256 verification
    if expected_sha256:
        with open(resolved_path, "rb") as f:
            actual_sha = hash_stream(f)
        if actual_sha.lower() != expected_sha256.lower():
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "HASH_MISMATCH",
                    "message": f"SHA-256 mismatch for file: expected {expected_sha256}, got {actual_sha}",
                },
            )

    return resolved_path
