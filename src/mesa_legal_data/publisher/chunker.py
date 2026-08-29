from typing import Any

from mesa_legal_data.publisher.hashing import calculate_content_hash
from mesa_legal_data.publisher.models import SourceChunk


def _split_oversized_text(
    text: str,
    base_char_start: int,
    max_chars: int,
) -> list[tuple[int, int, str]]:
    """
    Deterministically splits oversized text into chunks <= max_chars.
    Strategy:
      1. Tries paragraph boundaries (\\n\\n).
      2. Tries single newline boundaries (\\n).
      3. Falls back to hard boundary slices.
    Returns list of (char_start, char_end, slice_text).
    """
    if len(text) <= max_chars:
        return [(base_char_start, base_char_start + len(text), text)]

    results: list[tuple[int, int, str]] = []
    current_pos = 0
    total_len = len(text)

    while current_pos < total_len:
        remaining_len = total_len - current_pos
        if remaining_len <= max_chars:
            slice_str = text[current_pos:]
            results.append((base_char_start + current_pos, base_char_start + total_len, slice_str))
            break

        # Find best break point within [current_pos + 1, current_pos + max_chars]
        target_limit = current_pos + max_chars
        window = text[current_pos:target_limit]

        # 1. Look for double newline
        split_idx = window.rfind("\n\n")
        if split_idx != -1 and split_idx > (max_chars // 4):
            end_pos = current_pos + split_idx + 2
        else:
            # 2. Look for single newline
            split_idx = window.rfind("\n")
            if split_idx != -1 and split_idx > (max_chars // 4):
                end_pos = current_pos + split_idx + 1
            else:
                # 3. Look for space
                split_idx = window.rfind(" ")
                if split_idx != -1 and split_idx > (max_chars // 4):
                    end_pos = current_pos + split_idx + 1
                else:
                    # 4. Safe hard cut
                    end_pos = target_limit

        slice_str = text[current_pos:end_pos]
        results.append((base_char_start + current_pos, base_char_start + end_pos, slice_str))
        current_pos = end_pos

    return results


def plan_source_chunks(
    *,
    document_id: str,
    version_id: str,
    canonical_text: str,
    records: list[dict[str, Any]],
    content_limit_chars: int = 32768,
) -> list[SourceChunk]:
    """
    Deterministically transforms canonical text and version records into ordered SourceChunks.
    Preserves:
      - Preamble ranges (meaningful header / introductory text)
      - Articles (structured legal units)
      - Annex / trailing ranges (schedules, transitional provisions)
    Guarantees:
      - Deterministic ordering by appearance (char_start)
      - Stable chunk IDs
      - Exact content hash for each chunk
    """
    if not canonical_text or not canonical_text.strip():
        return []

    # Auto-resolve char_start and char_end if content is provided
    search_cursor = 0
    for r in records:
        if r.get("char_start") is None and r.get("content"):
            pos = canonical_text.find(r["content"], search_cursor)
            if pos != -1:
                r["char_start"] = pos
                r["char_end"] = pos + len(r["content"])
                search_cursor = r["char_end"]

    # Filter and sort article records by char_start
    article_records = [
        r
        for r in records
        if r.get("record_type") == "article" and r.get("char_start") is not None and r.get("char_end") is not None
    ]
    article_records.sort(key=lambda r: (r.get("char_start", 0), r.get("ordinal", 0)))

    chunks: list[SourceChunk] = []
    ordinal_counter = 1

    if not article_records:
        # Generic text without article records (e.g. unsegmented or single decision)
        splits = _split_oversized_text(canonical_text, 0, content_limit_chars)
        for piece_idx, (c_start, c_end, piece_text) in enumerate(splits, start=1):
            chunk_id = (
                f"{version_id}:chunk:{ordinal_counter:04d}"
                if len(splits) == 1
                else f"{version_id}:chunk:{ordinal_counter:04d}:p{piece_idx}"
            )
            c_hash = calculate_content_hash(piece_text)
            chunks.append(
                SourceChunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    version_id=version_id,
                    chunk_type="general",
                    title="Genel Metin",
                    char_start=c_start,
                    char_end=c_end,
                    ordinal=ordinal_counter,
                    content=piece_text,
                    content_hash=c_hash,
                    metadata={"piece_index": piece_idx, "total_pieces": len(splits)},
                )
            )
            ordinal_counter += 1
        return chunks

    # 1. Preamble Chunk (if meaningful content exists before first article)
    first_art_start = article_records[0].get("char_start", 0)
    if first_art_start > 0:
        preamble_text = canonical_text[:first_art_start]
        if preamble_text.strip():
            splits = _split_oversized_text(preamble_text, 0, content_limit_chars)
            for piece_idx, (c_start, c_end, piece_text) in enumerate(splits, start=1):
                chunk_id = (
                    f"{version_id}:chunk:{ordinal_counter:04d}"
                    if len(splits) == 1
                    else f"{version_id}:chunk:{ordinal_counter:04d}:p{piece_idx}"
                )
                c_hash = calculate_content_hash(piece_text)
                chunks.append(
                    SourceChunk(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        version_id=version_id,
                        chunk_type="preamble",
                        title="Başlangıç / Başlık",
                        char_start=c_start,
                        char_end=c_end,
                        ordinal=ordinal_counter,
                        content=piece_text,
                        content_hash=c_hash,
                        metadata={"piece_index": piece_idx, "total_pieces": len(splits)},
                    )
                )
                ordinal_counter += 1

    # 2. Article Chunks
    for art in article_records:
        a_start = int(art["char_start"])
        a_end = int(art["char_end"])
        art_text = canonical_text[a_start:a_end]
        art_id = art.get("record_id", "")
        art_num = art.get("article_number", "")
        art_title = art.get("title") or (f"Madde {art_num}" if art_num else "Madde")

        splits = _split_oversized_text(art_text, a_start, content_limit_chars)
        for piece_idx, (c_start, c_end, piece_text) in enumerate(splits, start=1):
            chunk_id = (
                f"{version_id}:chunk:{ordinal_counter:04d}"
                if len(splits) == 1
                else f"{version_id}:chunk:{ordinal_counter:04d}:p{piece_idx}"
            )
            c_hash = calculate_content_hash(piece_text)
            chunks.append(
                SourceChunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    version_id=version_id,
                    chunk_type="article",
                    title=art_title,
                    char_start=c_start,
                    char_end=c_end,
                    ordinal=ordinal_counter,
                    content=piece_text,
                    content_hash=c_hash,
                    metadata={
                        "article_id": art_id,
                        "article_number": art_num,
                        "piece_index": piece_idx,
                        "total_pieces": len(splits),
                    },
                )
            )
            ordinal_counter += 1

    # 3. Annex / Trailing Chunk (if meaningful content exists after last article)
    last_art_end = article_records[-1].get("char_end", len(canonical_text))
    if last_art_end < len(canonical_text):
        annex_text = canonical_text[last_art_end:]
        if annex_text.strip():
            splits = _split_oversized_text(annex_text, last_art_end, content_limit_chars)
            for piece_idx, (c_start, c_end, piece_text) in enumerate(splits, start=1):
                chunk_id = (
                    f"{version_id}:chunk:{ordinal_counter:04d}"
                    if len(splits) == 1
                    else f"{version_id}:chunk:{ordinal_counter:04d}:p{piece_idx}"
                )
                c_hash = calculate_content_hash(piece_text)
                chunks.append(
                    SourceChunk(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        version_id=version_id,
                        chunk_type="annex",
                        title="Ek / Geçici Maddeler",
                        char_start=c_start,
                        char_end=c_end,
                        ordinal=ordinal_counter,
                        content=piece_text,
                        content_hash=c_hash,
                        metadata={"piece_index": piece_idx, "total_pieces": len(splits)},
                    )
                )
                ordinal_counter += 1

    return chunks
