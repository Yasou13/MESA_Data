from datetime import date

from mesa_legal_data.harvest.config import HarvestSourceConfig
from mesa_legal_data.harvest.models import DiscoveredDocument, SelectionDecision


def evaluate_selection(doc: DiscoveredDocument, source_cfg: HarvestSourceConfig) -> SelectionDecision:
    if not source_cfg.enabled:
        return SelectionDecision(accepted=False, rejection_code="SOURCE_DISABLED", reasons=("source_disabled",))

    selection = source_cfg.selection

    # Section exclusion check
    if doc.section:
        sec_upper = doc.section.upper()
        for ex in selection.exclude_sections:
            if ex.upper() in sec_upper:
                return SelectionDecision(
                    accepted=False,
                    rejection_code="EXCLUDED_SECTION",
                    reasons=(f"excluded_section:{doc.section}",),
                )

        if selection.include_sections:
            matched = any(inc.upper() in sec_upper for inc in selection.include_sections)
            if not matched:
                return SelectionDecision(
                    accepted=False,
                    rejection_code="SECTION_NOT_INCLUDED",
                    reasons=(f"section_not_included:{doc.section}",),
                )

    # Allowed document types check
    if selection.allowed_document_types and doc.document_type not in selection.allowed_document_types:
        return SelectionDecision(
            accepted=False,
            rejection_code="DOCUMENT_TYPE_NOT_ALLOWED",
            reasons=(f"disallowed_doc_type:{doc.document_type}",),
        )

    # Date range check
    if doc.publication_date:
        pub_str = (
            doc.publication_date.isoformat() if isinstance(doc.publication_date, date) else str(doc.publication_date)
        )
        if source_cfg.date_from and pub_str < source_cfg.date_from:
            return SelectionDecision(
                accepted=False,
                rejection_code="BEFORE_DATE_FROM",
                reasons=(f"date_before_from:{pub_str}",),
            )
        if source_cfg.date_to and pub_str > source_cfg.date_to:
            return SelectionDecision(
                accepted=False,
                rejection_code="AFTER_DATE_TO",
                reasons=(f"date_after_to:{pub_str}",),
            )

    reasons: tuple[str, ...] = ("allowed_selection",)
    if doc.selection_reasons:
        reasons = doc.selection_reasons

    return SelectionDecision(accepted=True, priority=doc.priority, reasons=reasons)
