from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsingCoverage:
    canonical_chars: int
    covered_chars: int
    uncovered_chars: int
    coverage_ratio: float
    covered_intervals: list[tuple[int, int]]
    uncovered_ranges: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_chars": self.canonical_chars,
            "covered_chars": self.covered_chars,
            "uncovered_chars": self.uncovered_chars,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "uncovered_ranges": self.uncovered_ranges,
        }


def compute_parsing_coverage(
    canonical_text: str,
    spans: list[tuple[int, int]],
) -> ParsingCoverage:
    """
    Computes strict interval-merged parsing coverage on canonical text.
    Tracks canonical_chars, covered_chars, uncovered_chars, coverage_ratio,
    and classifies uncovered_ranges (preamble, gap, annex_trailing).
    """
    total_len = len(canonical_text)
    if total_len == 0:
        return ParsingCoverage(
            canonical_chars=0,
            covered_chars=0,
            uncovered_chars=0,
            coverage_ratio=1.0,
            covered_intervals=[],
            uncovered_ranges=[],
        )

    valid_spans: list[tuple[int, int]] = []
    for s_start, s_end in spans:
        if s_start is None or s_end is None:
            continue
        c_start = max(0, min(s_start, total_len))
        c_end = max(0, min(s_end, total_len))
        if c_start < c_end:
            valid_spans.append((c_start, c_end))

    valid_spans.sort(key=lambda x: (x[0], x[1]))

    merged: list[tuple[int, int]] = []
    for start, end in valid_spans:
        if not merged:
            merged.append((start, end))
        else:
            prev_start, prev_end = merged[-1]
            if start <= prev_end:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))

    covered_chars = sum(end - start for start, end in merged)
    uncovered_chars = max(0, total_len - covered_chars)
    coverage_ratio = covered_chars / total_len if total_len > 0 else 1.0

    uncovered_ranges: list[dict[str, Any]] = []
    curr = 0
    for idx, (m_start, m_end) in enumerate(merged):
        if curr < m_start:
            gap_len = m_start - curr
            cand = "preamble" if curr == 0 else "gap"
            preview = canonical_text[curr : min(curr + 100, m_start)].strip().replace("\n", " ")
            uncovered_ranges.append(
                {
                    "start": curr,
                    "end": m_start,
                    "length": gap_len,
                    "candidate_type": cand,
                    "preview": preview[:80],
                }
            )
        curr = max(curr, m_end)

    if curr < total_len:
        gap_len = total_len - curr
        preview = canonical_text[curr : min(curr + 100, total_len)].strip().replace("\n", " ")
        uncovered_ranges.append(
            {
                "start": curr,
                "end": total_len,
                "length": gap_len,
                "candidate_type": "annex_trailing",
                "preview": preview[:80],
            }
        )

    return ParsingCoverage(
        canonical_chars=total_len,
        covered_chars=covered_chars,
        uncovered_chars=uncovered_chars,
        coverage_ratio=coverage_ratio,
        covered_intervals=merged,
        uncovered_ranges=uncovered_ranges,
    )
