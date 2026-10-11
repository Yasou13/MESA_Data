from typing import Any

from mesa_legal_data.publisher.hashing import calculate_content_hash
from mesa_legal_data.publisher.models import MESA_V4_EVIDENCE_SPAN_MAX_CHARS, SourceChunk


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
    document_metadata: dict[str, Any] | None = None,
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

    # MESA's current V4 insert contract accepts at most 4,096 characters in
    # ``evidence_span``.  Every source chunk becomes the complete evidence
    # payload for its deterministic fallback assertion, so the semantic limit
    # is stricter than the 32,768-character transport-content limit.
    chunk_limit_chars = min(content_limit_chars, MESA_V4_EVIDENCE_SPAN_MAX_CHARS)
    document_identity = dict(document_metadata or {})

    # Work on shallow copies so coordinate recovery never mutates canonical
    # records owned by the caller.
    normalized_records = [dict(record) for record in records]

    # Auto-resolve char_start and char_end if content is provided.
    search_cursor = 0
    for r in normalized_records:
        if r.get("char_start") is None and r.get("content"):
            pos = canonical_text.find(r["content"], search_cursor)
            if pos != -1:
                r["char_start"] = pos
                r["char_end"] = pos + len(r["content"])
                search_cursor = r["char_end"]

    # Filter and sort article records by char_start.
    article_records = [
        r
        for r in normalized_records
        if r.get("record_type") == "article" and r.get("char_start") is not None and r.get("char_end") is not None
    ]
    article_records.sort(key=lambda r: (r.get("char_start", 0), r.get("ordinal", 0)))

    previous_end = 0
    for article in article_records:
        start = article.get("char_start")
        end = article.get("char_end")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end > len(canonical_text)
            or start >= end
        ):
            raise ValueError(f"Invalid article source span: [{start}, {end}]")
        if start < previous_end:
            raise ValueError(f"Article source spans overlap at offset {start}")
        previous_end = end

    chunks: list[SourceChunk] = []
    ordinal_counter = 1

    if not article_records:
        # Generic text without article records (e.g. unsegmented or single decision)
        splits = _split_oversized_text(canonical_text, 0, chunk_limit_chars)
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
                    metadata={**document_identity, "piece_index": piece_idx, "total_pieces": len(splits)},
                )
            )
            ordinal_counter += 1
        return chunks

    # 1. Preamble Chunk (if meaningful content exists before first article)
    first_art_start = article_records[0].get("char_start", 0)
    if first_art_start > 0:
        preamble_text = canonical_text[:first_art_start]
        if preamble_text.strip():
            splits = _split_oversized_text(preamble_text, 0, chunk_limit_chars)
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
                        metadata={**document_identity, "piece_index": piece_idx, "total_pieces": len(splits)},
                    )
                )
                ordinal_counter += 1

    # 2. Article Chunks and meaningful structural gaps. Parser boundaries may
    # deliberately exclude headings such as BÖLÜM/KISIM between articles; those
    # bytes remain canonical evidence and must not disappear from publication.
    previous_end = first_art_start
    for art in article_records:
        a_start = int(art["char_start"])
        a_end = int(art["char_end"])
        if a_start > previous_end:
            gap_text = canonical_text[previous_end:a_start]
            if gap_text.strip():
                gap_splits = _split_oversized_text(gap_text, previous_end, chunk_limit_chars)
                for piece_idx, (c_start, c_end, piece_text) in enumerate(gap_splits, start=1):
                    chunk_id = (
                        f"{version_id}:chunk:{ordinal_counter:04d}"
                        if len(gap_splits) == 1
                        else f"{version_id}:chunk:{ordinal_counter:04d}:p{piece_idx}"
                    )
                    chunks.append(
                        SourceChunk(
                            chunk_id=chunk_id,
                            document_id=document_id,
                            version_id=version_id,
                            chunk_type="general",
                            title="Yapısal Başlık",
                            char_start=c_start,
                            char_end=c_end,
                            ordinal=ordinal_counter,
                            content=piece_text,
                            content_hash=calculate_content_hash(piece_text),
                            metadata={
                                **document_identity,
                                "piece_index": piece_idx,
                                "total_pieces": len(gap_splits),
                            },
                        )
                    )
                    ordinal_counter += 1
        art_text = canonical_text[a_start:a_end]
        art_id = art.get("record_id", "")
        art_num = art.get("article_number", "")
        art_title = art.get("title") or (f"Madde {art_num}" if art_num else "Madde")

        splits = _split_oversized_text(art_text, a_start, chunk_limit_chars)
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
                        **document_identity,
                        "article_id": art_id,
                        "article_number": art_num,
                        **{
                            key: art[key]
                            for key in (
                                "article_kind",
                                "law_number",
                                "law_title",
                                "effective_from",
                                "effective_to",
                            )
                            if key in art
                        },
                        "piece_index": piece_idx,
                        "total_pieces": len(splits),
                    },
                )
            )
            ordinal_counter += 1
        previous_end = a_end

    # 3. Annex / Trailing Chunk (if meaningful content exists after last article)
    last_art_end = article_records[-1].get("char_end", len(canonical_text))
    if last_art_end < len(canonical_text):
        annex_text = canonical_text[last_art_end:]
        if annex_text.strip():
            splits = _split_oversized_text(annex_text, last_art_end, chunk_limit_chars)
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
                        metadata={**document_identity, "piece_index": piece_idx, "total_pieces": len(splits)},
                    )
                )
                ordinal_counter += 1

    return chunks
