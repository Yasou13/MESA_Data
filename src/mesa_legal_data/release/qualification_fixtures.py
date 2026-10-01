"""Deterministic Phase 7 Qualification Fixture Authority for MESA VM Certification.

Defines, builds, and semantically validates the authoritative 12-case Phase 7
adversarial scope/isolation qualification fixtures required by MESA_E2E_Certification.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

REQUIRED_SCOPE_CASE_IDS: tuple[str, ...] = (
    "cross_tenant_search",
    "cross_dataset_search",
    "cross_agent_search",
    "inactive_status_search",
    "wrong_jurisdiction_search",
    "stale_version_search",
    "effective_date_boundary_search",
    "context_visibility",
    "catalog_visibility",
    "document_visibility",
    "revision_visibility",
    "chunk_visibility",
)

CASE_FIXTURE_TYPES: dict[str, str] = {
    "cross_tenant_search": "evidence",
    "cross_dataset_search": "evidence",
    "cross_agent_search": "evidence",
    "inactive_status_search": "evidence",
    "wrong_jurisdiction_search": "evidence",
    "stale_version_search": "evidence",
    "effective_date_boundary_search": "evidence",
    "context_visibility": "chunk",
    "catalog_visibility": "catalog",
    "document_visibility": "document",
    "revision_visibility": "revision",
    "chunk_visibility": "chunk",
}

DEFAULT_QUALIFICATION_SCOPE: dict[str, Any] = {
    "tenant_id": "default",
    "workspace_id": "legal",
    "dataset_ids": ["tr_legislation"],
    "agent_id": "mesa_data_publisher",
    "expected_principal": "principal-user-1",
}

DEFAULT_FORBIDDEN_SCOPE: dict[str, str] = {
    "forbidden_tenant": "tenant-forbidden",
    "forbidden_dataset": "dataset-forbidden",
    "forbidden_agent": "agent-forbidden",
}

DEFAULT_AUTHORIZED_DOCUMENT = "tr:legislation:law:5237"

PHASE7_PROBE_TIME = datetime.fromisoformat("2026-06-01T00:00:00+00:00")
FIXTURE_NAMESPACE_PREFIX = "fixture:scope:"
PRODUCTION_DOCUMENT_PREFIXES = (
    "tr:legislation:law:",
    "tr:legislation:constitution:",
    "tr:legislation:communique:",
    "tr:legislation:decree:",
    "tr:legislation:regulation:",
    "tr:decision:",
)


class QualificationFixtureError(ValueError):
    """Raised when qualification fixture authority fails validation."""


class QualificationIdentityRow(BaseModel):
    """Schema-exact identity map row for qualification fixtures."""

    model_config = ConfigDict(extra="forbid")

    mesa_chunk_id: str = Field(min_length=1)
    source_chunk_id: str = Field(min_length=1)
    content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    delivery_state: str | None = None
    evidence_id: str | None = None
    catalog_id: str | None = None
    document_id: str | None = None
    remote_mutation_id: str | None = None
    version_id: str | None = None
    tenant_id: str | None = None
    dataset_id: str | None = None
    agent_id: str | None = None
    status: str | None = None
    jurisdiction: str | None = None
    is_current: bool | None = None
    valid_from: str | None = None
    valid_to: str | None = None


def canonical_json_bytes(obj: Any) -> bytes:
    """Deterministically serializes an object into UTF-8 JSON bytes."""
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _deterministic_uuid(namespace: str, name: str) -> str:
    """Generates a stable, reproducible UUIDv5 string."""
    ns_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, f"mesa.{namespace}")
    return str(uuid.uuid5(ns_uuid, name))


def _calculate_content_hash(text: str) -> str:
    """Computes SHA-256 digest of utf-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_qualification_fixtures(
    *,
    qualification_scope: dict[str, Any] | None = None,
    forbidden_scope: dict[str, str] | None = None,
    authorized_document: str = DEFAULT_AUTHORIZED_DOCUMENT,
) -> dict[str, Any]:
    """
    Builds real, deterministic, semantically valid Phase 7 adversarial qualification fixtures.

    Returns:
      A dictionary containing:
        - "qualification_scope": QualificationScope dictionary
        - "scope_test_authority": ScopeTestAuthority dictionary
        - "identity_rows": list of raw IdentityMapRow dictionaries
        - "canonical_records": list of canonical record dicts (legislation & article)
        - "release_index_entries": list of release-index dicts
    """
    scope = dict(DEFAULT_QUALIFICATION_SCOPE)
    if qualification_scope:
        scope.update(qualification_scope)

    forbidden = dict(DEFAULT_FORBIDDEN_SCOPE)
    if forbidden_scope:
        forbidden.update(forbidden_scope)

    # 1. Definitions of the 12 adversarial cases with retrieval-relevant legal texts
    fixture_definitions: dict[str, dict[str, Any]] = {
        "cross_tenant_search": {
            "case_id": "cross_tenant_search",
            "identity_type": "evidence",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-tenant:evidence:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-tenant:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-tenant:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-tenant:ver:0001",
            "title": "Adli Yargı ve Ceza Hukuku Temel İlkeleri Kanunu (Yasaklı Kiracı)",
            "article_heading": "Suçta ve Cezada Kanunilik İlkesi",
            "content": (
                "MADDE 1- Ceza kanunlarının tatbikinde kanunilik, kusur ve adil yargılanma "
                "ilkeleri esastır. Kanunun açıkça suç saymadığı bir fiil için kimseye ceza "
                "verilemez ve güvenlik tedbiri uygulanamaz. Hâkim takdir yetkisini kullanarak "
                "örf ve âdete göre ceza tayin edemez. Bu hüküm yasaklı kiracı alanına aittir."
            ),
            "tenant_id": forbidden["forbidden_tenant"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": scope["agent_id"],
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "is_current": True,
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2030-12-31T23:59:59Z",
        },
        "cross_dataset_search": {
            "case_id": "cross_dataset_search",
            "identity_type": "evidence",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-dataset:evidence:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-dataset:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-dataset:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-dataset:ver:0001",
            "title": "Mevzuat ve Yargısal Yorum Kuralları Kanunu (Yasaklı Veri Kümesi)",
            "article_heading": "Dürüstlük ve Kanunun Uygulanması",
            "content": (
                "MADDE 1- Kanun sözüyle ve özüyle uygulanır. Hukukta genel ispat yükü ve "
                "dürüstlük kuralı uyarınca herkes hakkını kullanırken objektif iyiniyet kaidelerine "
                "uymakla yükümlüdür; hakkın açık kötüye kullanımını kanun korumaz. Bu kayıt yasaklı "
                "veri kümesi tecrit sınırını test eder."
            ),
            "tenant_id": scope["tenant_id"],
            "dataset_id": forbidden["forbidden_dataset"],
            "agent_id": scope["agent_id"],
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "is_current": True,
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2030-12-31T23:59:59Z",
        },
        "cross_agent_search": {
            "case_id": "cross_agent_search",
            "identity_type": "evidence",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-agent:evidence:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-agent:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-agent:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}cross-agent:ver:0001",
            "title": "Ceza Muhakemesinde Delil Serbestisi Kanunu (Yasaklı Ajan)",
            "article_heading": "Maddi Gerçek ve Delil Değerlendirmesi",
            "content": (
                "MADDE 1- Ceza muhakemesinde hâkim ve mahkeme, yüklenen suçun sübuta erip ermediğini "
                "duruşmaya getirilmiş ve huzurunda tartışılmış delillere dayanarak serbestçe takdir eder. "
                "Yetkisiz ajan veya harici sistemlerce toplanan hukuka aykırı deliller hükme esas alınamaz. "
                "Bu kayıt yasaklı ajan yetki alanında yer almaktadır."
            ),
            "tenant_id": scope["tenant_id"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": forbidden["forbidden_agent"],
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "is_current": True,
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2030-12-31T23:59:59Z",
        },
        "inactive_status_search": {
            "case_id": "inactive_status_search",
            "identity_type": "evidence",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}inactive:evidence:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}inactive:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}inactive:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}inactive:ver:0001",
            "title": "Mülga Eski Ceza Hükümleri Kanunu (Tombstoned/Silinmiş Kayıt)",
            "article_heading": "Yürürlükten Kaldırılan Hüküm",
            "content": (
                "MADDE 1- (Mülga Hüküm - TOMBSTONED): Bu Kanun maddesi 5237 sayılı Türk Ceza Kanunu ile "
                "yürürlükten kaldırılmış olup adli kararlara dayanak oluşturamaz. Kanunsuz suç olmaz "
                "prensibi gereğince mülga yasa kuralları güncel uyuşmazlıklarda tatbik edilemez."
            ),
            "tenant_id": scope["tenant_id"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": scope["agent_id"],
            "status": "TOMBSTONED",
            "jurisdiction": "TR",
            "is_current": False,
            "valid_from": "1926-03-01T00:00:00Z",
            "valid_to": "2005-06-01T00:00:00Z",
        },
        "wrong_jurisdiction_search": {
            "case_id": "wrong_jurisdiction_search",
            "identity_type": "evidence",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}wrong-jurisdiction:evidence:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}wrong-jurisdiction:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}wrong-jurisdiction:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}wrong-jurisdiction:ver:0001",
            "title": "Avrupa Birliği Ceza Adaleti ve Temel Haklar Şartı (Yabancı Yargı Yetkisi)",
            "article_heading": "Yabancı Yargı Alanı Temel Kuralları",
            "content": (
                "ARTICLE 1- Kanunilik ve suçta orantılılık ilkeleri Avrupa İnsan Hakları Sözleşmesi "
                "ve Avrupa Birliği Temel Haklar Şartı uyarınca milletlerarası standart kabul edilir. "
                "Türkiye Cumhuriyeti yargı yetkisi (TR) dışında olan bu madde yalnızca Avrupa Birliği "
                "yargı yetkisi (EU) çerçevesinde bağlayıcıdır."
            ),
            "tenant_id": scope["tenant_id"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": scope["agent_id"],
            "status": "ACTIVE",
            "jurisdiction": "EU",
            "is_current": True,
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2030-12-31T23:59:59Z",
        },
        "stale_version_search": {
            "case_id": "stale_version_search",
            "identity_type": "evidence",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}stale-version:evidence:stale:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}stale-version:chunk:stale:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}stale-version:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}stale-version:ver:stale:0001",
            "title": "Türk Ceza Kanunu Değişiklik Öncesi Hükümleri (Eski/Geçersiz Sürüm)",
            "article_heading": "Eski Değişiklik Öncesi Metin (Mülga)",
            "content": (
                "MADDE 1- (Eski Mülga Versiyon): Ceza kanununun tatbikinde eski kanun metni uygulanır; "
                "değişiklikten önceki metin yürürlükten kalkmış olup tarihsel arşiv kaydı niteliğindedir. "
                "Bu fıkra güncel olmayıp yeni yasal düzenleme ile ilga edilmiştir."
            ),
            "tenant_id": scope["tenant_id"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": scope["agent_id"],
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "is_current": False,
            "valid_from": "2005-06-01T00:00:00Z",
            "valid_to": "2024-01-01T00:00:00Z",
        },
        "effective_date_boundary_search": {
            "case_id": "effective_date_boundary_search",
            "identity_type": "evidence",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}effective-date:evidence:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}effective-date:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}effective-date:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}effective-date:ver:0001",
            "title": "Geçici Ceza ve İnfaz Tedbirleri Kanunu (Süresi Dolmuş Yasa)",
            "article_heading": "Geçici Yürürlük Süresi Sona Eren Hüküm",
            "content": (
                "GEÇİCİ MADDE 1- Bu geçici hüküm 01.01.2024 ile 31.12.2025 tarihleri arasında "
                "vuku bulan hadiselere münhasıran tatbik edilir. 31.12.2025 tarihi itibarıyla yürürlük "
                "süresi sona ermiş olup 2026 yılı ve sonrasında herhangi bir hukuki tesir icra edemez."
            ),
            "tenant_id": scope["tenant_id"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": scope["agent_id"],
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "is_current": True,
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2025-12-31T23:59:59Z",
        },
        "context_visibility": {
            "case_id": "context_visibility",
            "identity_type": "chunk",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}context-vis:chunk:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}context-vis:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}context-vis:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}context-vis:ver:0001",
            "title": "Gizli Oturum Kayıtları ve Güvenlik Belgesi (Bağlam Görünürlük)",
            "article_heading": "Kısıtlı Oturum Bağlamı",
            "content": (
                "MADDE 1- Kısıtlı Oturum Belgesi: Yetkisiz kiracıların oturum bağlamına kapalı olan "
                "bu belgenin içeriği oturum bağlamı sorgularında (context visibility probe) filtrelenir "
                "ve izin verilmeyen oturumlara dahil edilmez."
            ),
            "tenant_id": forbidden["forbidden_tenant"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": scope["agent_id"],
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "is_current": True,
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2030-12-31T23:59:59Z",
        },
        "catalog_visibility": {
            "case_id": "catalog_visibility",
            "identity_type": "catalog",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}catalog-vis:cat:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}catalog-vis:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}catalog-vis:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}catalog-vis:ver:0001",
            "title": "Özel Çalışma Alanı Sicili (Katalog Görünürlük Testi)",
            "article_heading": "Kısıtlı Katalog Maddesi",
            "content": (
                "MADDE 1- Kısıtlı Katalog Kaydı: İşbu katalog girdisi yabancı ve yetkisiz kiracılara "
                "karşı korunmuş olup katalog listeleme uç noktalarında görünür olamaz."
            ),
            "tenant_id": forbidden["forbidden_tenant"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": scope["agent_id"],
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "is_current": True,
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2030-12-31T23:59:59Z",
        },
        "document_visibility": {
            "case_id": "document_visibility",
            "identity_type": "document",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}document-vis:doc:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}document-vis:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}document-vis:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}document-vis:ver:0001",
            "title": "Kısıtlı Belge Arşivi Kanunu (Belge Görünürlük Testi)",
            "article_heading": "Kısıtlı Belge Maddesi",
            "content": (
                "MADDE 1- Kısıtlı Belge Hükmü: Yalnızca yetkili kurumlarca incelenebilen bu belge, "
                "genel belge listesi ve katalog arama sonuçlarında yabancı kiracılara gizlenir."
            ),
            "tenant_id": forbidden["forbidden_tenant"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": scope["agent_id"],
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "is_current": True,
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2030-12-31T23:59:59Z",
        },
        "revision_visibility": {
            "case_id": "revision_visibility",
            "identity_type": "revision",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}revision-vis:ver:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}revision-vis:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}revision-vis:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}revision-vis:ver:0001",
            "title": "Kısıtlı Revizyon ve Sürüm Kanunu (Revizyon Görünürlük Testi)",
            "article_heading": "Kısıtlı Sürüm Maddesi",
            "content": (
                "MADDE 1- Kısıtlı Revizyon: Belgenin bu revizyonu özel güvenlik incelemesine tabi olup "
                "onaylı genel revizyonlar arasında yabancı kiracılara listelenemez."
            ),
            "tenant_id": forbidden["forbidden_tenant"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": scope["agent_id"],
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "is_current": True,
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2030-12-31T23:59:59Z",
        },
        "chunk_visibility": {
            "case_id": "chunk_visibility",
            "identity_type": "chunk",
            "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}chunk-vis:chunk:0001",
            "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}chunk-vis:chunk:0001",
            "document_id": f"{FIXTURE_NAMESPACE_PREFIX}chunk-vis:doc:0001",
            "version_id": f"{FIXTURE_NAMESPACE_PREFIX}chunk-vis:ver:0001",
            "title": "Kaynak Parça Tecrit Belgesi (Parça Düzeyi Görünürlük Testi)",
            "article_heading": "Kaynak Parça Tecriti",
            "content": (
                "MADDE 1- Kaynak Parça Kısıtlaması: Bu metin parçası (source chunk visibility probe) "
                "doğrudan parça arama ve bağlam isteklerinde yalnızca yetkili kiracıya sunulur; "
                "yasaklı kiracı bu parçayı göremez."
            ),
            "tenant_id": forbidden["forbidden_tenant"],
            "dataset_id": scope["dataset_ids"][0],
            "agent_id": scope["agent_id"],
            "status": "ACTIVE",
            "jurisdiction": "TR",
            "is_current": True,
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2030-12-31T23:59:59Z",
        },
    }

    # Also build the companion current version for stale_version_search to represent honest version lineage
    stale_doc_id = f"{FIXTURE_NAMESPACE_PREFIX}stale-version:doc:0001"
    companion_current_version = {
        "identity_type": "evidence",
        "fixture_id": f"{FIXTURE_NAMESPACE_PREFIX}stale-version:evidence:current:0001",
        "source_chunk_id": f"{FIXTURE_NAMESPACE_PREFIX}stale-version:chunk:current:0001",
        "document_id": stale_doc_id,
        "version_id": f"{FIXTURE_NAMESPACE_PREFIX}stale-version:ver:current:0001",
        "title": "Türk Ceza Kanunu Güncel Hükümleri (Geçerli Sürüm)",
        "article_heading": "Güncel Yasa Hükmü",
        "content": (
            "MADDE 1- (Güncel Versiyon): Ceza kanununun tatbikinde kanun koyucunun yürürlükteki "
            "son metni uygulanır; eski metinler yürürlükten kalkmıştır. Bu hüküm yürürlükteki "
            "güncel kanun sürümüdür (is_current=True)."
        ),
        "tenant_id": scope["tenant_id"],
        "dataset_id": scope["dataset_ids"][0],
        "agent_id": scope["agent_id"],
        "status": "ACTIVE",
        "jurisdiction": "TR",
        "is_current": True,
        "valid_from": "2024-01-01T00:00:00Z",
        "valid_to": "2030-12-31T23:59:59Z",
    }

    corpus_fixtures: dict[str, dict[str, Any]] = {}
    case_evidence_fixtures: dict[str, list[str]] = {}
    identity_rows: list[dict[str, Any]] = []
    canonical_records: list[dict[str, Any]] = []
    release_index_entries: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set()

    all_specs = list(fixture_definitions.values()) + [companion_current_version]

    for spec in all_specs:
        fid = spec["fixture_id"]
        case_id = spec.get("case_id")
        identity_type = spec["identity_type"]
        src_chunk_id = spec["source_chunk_id"]
        doc_id = spec["document_id"]
        v_id = spec["version_id"]
        content = spec["content"]
        c_hash = _calculate_content_hash(content)
        mutation_id = _deterministic_uuid("mutation", src_chunk_id)

        # In case_evidence_fixtures only include the 12 case fixtures
        if case_id:
            case_evidence_fixtures[case_id] = [fid]
            corpus_record: dict[str, Any] = {
                "identity_type": identity_type,
                "source_chunk_id": src_chunk_id,
                "tenant_id": spec["tenant_id"],
            }
            if "dataset_id" in spec:
                corpus_record["dataset_id"] = spec["dataset_id"]
            if "agent_id" in spec:
                corpus_record["agent_id"] = spec["agent_id"]
            if "status" in spec:
                corpus_record["status"] = spec["status"]
            if "jurisdiction" in spec:
                corpus_record["jurisdiction"] = spec["jurisdiction"]
            if "is_current" in spec:
                corpus_record["is_current"] = spec["is_current"]
            if "valid_from" in spec:
                corpus_record["valid_from"] = spec["valid_from"]
            if "valid_to" in spec:
                corpus_record["valid_to"] = spec["valid_to"]
            corpus_fixtures[fid] = corpus_record

        # Build IdentityMapRow
        row_dict: dict[str, Any] = {
            "mesa_chunk_id": src_chunk_id,
            "source_chunk_id": src_chunk_id,
            "content_hash": c_hash,
            "delivery_state": "COMMITTED",
            "document_id": doc_id,
            "version_id": v_id,
            "remote_mutation_id": mutation_id,
            "tenant_id": spec["tenant_id"],
            "dataset_id": spec.get("dataset_id"),
            "agent_id": spec.get("agent_id"),
            "status": spec.get("status"),
            "jurisdiction": spec.get("jurisdiction"),
            "is_current": spec.get("is_current"),
            "valid_from": spec.get("valid_from"),
            "valid_to": spec.get("valid_to"),
        }
        if identity_type == "evidence":
            row_dict["evidence_id"] = fid
        elif identity_type == "catalog":
            row_dict["catalog_id"] = fid
        # For document and revision, row_dict already has document_id and version_id
        # For chunk, mesa_chunk_id and source_chunk_id match fixture_id

        # Validate against schema
        QualificationIdentityRow.model_validate(row_dict)
        identity_rows.append(row_dict)

        # Build canonical legislation and article records (legislation once per doc_id)
        if doc_id not in seen_doc_ids:
            seen_doc_ids.add(doc_id)
            leg_record = {
                "id": doc_id,
                "record_type": "legislation",
                "jurisdiction": spec.get("jurisdiction") or "TR",
                "language": "tr",
                "legislation_type": "law",
                "number": "9901",
                "title": spec["title"],
                "short_title": spec["title"],
                "publication": {
                    "date": "2026-08-30",
                    "gazette_number": "33000",
                },
                "status": spec.get("status") or "ACTIVE",
                "version": {
                    "version_id": v_id,
                    "version_kind": "initial",
                    "snapshot_date": "2026-08-30",
                    "effective_from": spec.get("valid_from") or "2024-01-01T00:00:00Z",
                    "effective_to": spec.get("valid_to"),
                },
                "full_text": content,
                "schema_version": "1.0.0",
                "created_at": "2026-08-30T00:00:00Z",
                "source": {
                    "source_id": "resmi_gazete",
                    "source_url": f"https://www.resmigazete.gov.tr/qualification/{doc_id}.htm",
                    "retrieved_at": "2026-08-30T00:00:00Z",
                    "publication_date": "2026-08-30",
                    "artifact_sha256": c_hash,
                    "artifact_path": None,
                },
                "provenance": {
                    "parser_name": "qualification_fixture_generator",
                    "parser_version": "1.0.0",
                    "pipeline_run_id": "qualification-phase7",
                },
            }
            canonical_records.append(leg_record)
            leg_payload_sha = hashlib.sha256(
                (json.dumps(leg_record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            ).hexdigest()
            release_index_entries.append(
                {
                    "record_id": leg_record["id"],
                    "record_type": "legislation",
                    "record_sha256": leg_payload_sha,
                    "payload_sha256": leg_payload_sha,
                    "version_id": v_id,
                    "document_id": doc_id,
                }
            )

        art_id = f"{v_id}:art:0001"
        art_record = {
            "id": art_id,
            "record_type": "article",
            "legislation_id": doc_id,
            "legislation_version_id": v_id,
            "article_number": "1",
            "article_kind": "article",
            "heading": spec.get("article_heading") or "Madde 1",
            "ordinal": 1,
            "text": content,
            "structure": None,
            "status": spec.get("status") or "ACTIVE",
            "effective_from": spec.get("valid_from"),
            "effective_to": spec.get("valid_to"),
            "source_span": {
                "page_start": 1,
                "page_end": 1,
                "char_start": 0,
                "char_end": len(content),
            },
            "schema_version": "1.0.0",
            "created_at": "2026-08-30T00:00:00Z",
            "source": {
                "source_id": "resmi_gazete",
                "source_url": f"https://www.resmigazete.gov.tr/qualification/{doc_id}.htm",
                "retrieved_at": "2026-08-30T00:00:00Z",
                "publication_date": "2026-08-30",
                "artifact_sha256": c_hash,
                "artifact_path": None,
            },
            "provenance": {
                "parser_name": "qualification_fixture_generator",
                "parser_version": "1.0.0",
                "pipeline_run_id": "qualification-phase7",
            },
        }
        canonical_records.append(art_record)

        art_payload_sha = hashlib.sha256(
            (json.dumps(art_record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        ).hexdigest()
        release_index_entries.append(
            {
                "record_id": art_record["id"],
                "record_type": "article",
                "record_sha256": art_payload_sha,
                "payload_sha256": art_payload_sha,
                "version_id": v_id,
                "document_id": doc_id,
            }
        )

    scope_authority: dict[str, Any] = {
        "forbidden_tenant": forbidden["forbidden_tenant"],
        "forbidden_dataset": forbidden["forbidden_dataset"],
        "forbidden_agent": forbidden["forbidden_agent"],
        "authorized_document": authorized_document,
        "case_evidence_fixtures": case_evidence_fixtures,
        "corpus_fixtures": corpus_fixtures,
    }

    return {
        "qualification_scope": scope,
        "scope_test_authority": scope_authority,
        "identity_rows": identity_rows,
        "canonical_records": canonical_records,
        "release_index_entries": release_index_entries,
    }


def validate_qualification_fixtures(
    *,
    qualification_scope: dict[str, Any],
    scope_test_authority: dict[str, Any],
    identity_map_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Rigorously validates the Phase 7 qualification fixtures against the frozen qualification scope
    and identity map authority.

    Guarantees:
      - All 12 cases are present and distinct
      - All fixture identities are unique across cases
      - All fixtures resolve against identity map rows
      - Semantic properties are validated relative to the allowed scope (no self-referential validation)
      - Fails closed on any inconsistency or scope leak
    """
    # 1. Validate qualification_scope
    required_scope_fields = {
        "tenant_id",
        "workspace_id",
        "dataset_ids",
        "agent_id",
        "expected_principal",
    }
    missing_scope = sorted(required_scope_fields - qualification_scope.keys())
    if missing_scope:
        raise QualificationFixtureError(
            f"qualification_scope is missing required fields: {missing_scope}"
        )
    tenant_id = qualification_scope["tenant_id"]
    workspace_id = qualification_scope["workspace_id"]
    dataset_ids = qualification_scope["dataset_ids"]
    agent_id = qualification_scope["agent_id"]
    expected_principal = qualification_scope["expected_principal"]

    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise QualificationFixtureError("qualification_scope tenant_id must be non-empty")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise QualificationFixtureError("qualification_scope workspace_id must be non-empty")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise QualificationFixtureError("qualification_scope agent_id must be non-empty")
    if not isinstance(expected_principal, str) or not expected_principal.strip():
        raise QualificationFixtureError("qualification_scope expected_principal must be non-empty")
    if (
        not isinstance(dataset_ids, list)
        or not dataset_ids
        or any(not isinstance(d, str) or not d.strip() for d in dataset_ids)
    ):
        raise QualificationFixtureError("qualification_scope dataset_ids must be a non-empty list of strings")
    if len(dataset_ids) != len(set(dataset_ids)):
        raise QualificationFixtureError("qualification_scope dataset_ids contains duplicates")

    # 2. Validate scope_test_authority structure
    required_authority_fields = {
        "forbidden_tenant",
        "forbidden_dataset",
        "forbidden_agent",
        "authorized_document",
        "case_evidence_fixtures",
        "corpus_fixtures",
    }
    missing_auth = sorted(required_authority_fields - scope_test_authority.keys())
    if missing_auth:
        raise QualificationFixtureError(
            f"scope_test_authority is missing required fields: {missing_auth}"
        )

    forbidden_tenant = scope_test_authority["forbidden_tenant"]
    forbidden_dataset = scope_test_authority["forbidden_dataset"]
    forbidden_agent = scope_test_authority["forbidden_agent"]
    authorized_document = scope_test_authority["authorized_document"]
    case_evidence_fixtures = scope_test_authority["case_evidence_fixtures"]
    corpus_fixtures = scope_test_authority["corpus_fixtures"]

    if not isinstance(forbidden_tenant, str) or not forbidden_tenant.strip():
        raise QualificationFixtureError("forbidden_tenant must be non-empty string")
    if not isinstance(forbidden_dataset, str) or not forbidden_dataset.strip():
        raise QualificationFixtureError("forbidden_dataset must be non-empty string")
    if not isinstance(forbidden_agent, str) or not forbidden_agent.strip():
        raise QualificationFixtureError("forbidden_agent must be non-empty string")
    if not isinstance(authorized_document, str) or not authorized_document.strip():
        raise QualificationFixtureError("authorized_document must be non-empty string")

    # Relative scope checks (cannot be equal to or belong to allowed scope)
    if forbidden_tenant == tenant_id:
        raise QualificationFixtureError("forbidden_tenant belongs to allowed tenant")
    if forbidden_dataset in dataset_ids:
        raise QualificationFixtureError("forbidden_dataset belongs to allowed dataset scope")
    if forbidden_agent == agent_id:
        raise QualificationFixtureError("forbidden_agent belongs to allowed agent")

    # 3. Validate identity map rows and build lookups
    rows_by_source_chunk: dict[str, list[QualificationIdentityRow]] = {}
    rows_by_document_id: set[str] = set()
    seen_chunk_pairs: set[tuple[str, str]] = set()

    for idx, raw_row in enumerate(identity_map_rows, start=1):
        try:
            row = (
                raw_row
                if isinstance(raw_row, QualificationIdentityRow)
                else QualificationIdentityRow.model_validate(raw_row)
            )
        except ValidationError as exc:
            raise QualificationFixtureError(
                f"invalid identity map row at line {idx}: {exc}"
            ) from exc

        pair = (row.mesa_chunk_id, row.source_chunk_id)
        if pair in seen_chunk_pairs:
            raise QualificationFixtureError(
                f"duplicate identity mapping at line {idx}: {pair!r}"
            )
        seen_chunk_pairs.add(pair)

        rows_by_source_chunk.setdefault(row.source_chunk_id, []).append(row)
        if row.document_id:
            rows_by_document_id.add(row.document_id)

    # Authorized document presence in identity map
    if authorized_document not in rows_by_document_id:
        raise QualificationFixtureError(
            f"authorized_document {authorized_document!r} is absent from identity map"
        )

    # 4. Check case coverage
    if not isinstance(case_evidence_fixtures, dict):
        raise QualificationFixtureError("case_evidence_fixtures must be an object")

    actual_cases = set(case_evidence_fixtures.keys())
    required_cases = set(REQUIRED_SCOPE_CASE_IDS)
    if actual_cases != required_cases:
        missing = sorted(required_cases - actual_cases)
        unknown = sorted(actual_cases - required_cases)
        raise QualificationFixtureError(
            f"case_evidence_fixtures must cover exactly the 12 required cases; missing={missing}, unknown={unknown}"
        )

    all_fixture_ids: list[str] = []
    for case_id in REQUIRED_SCOPE_CASE_IDS:
        fixtures = case_evidence_fixtures[case_id]
        if (
            not isinstance(fixtures, list)
            or not fixtures
            or any(not isinstance(fid, str) or not fid.strip() for fid in fixtures)
        ):
            raise QualificationFixtureError(
                f"case {case_id} requires at least one non-empty fixture ID"
            )
        if len(fixtures) != len(set(fixtures)):
            raise QualificationFixtureError(
                f"case {case_id} contains duplicate fixture IDs"
            )
        all_fixture_ids.extend(fixtures)

    if len(all_fixture_ids) != len(set(all_fixture_ids)):
        raise QualificationFixtureError(
            "fixture IDs must be unique across all Phase 7 cases"
        )

    if not isinstance(corpus_fixtures, dict):
        raise QualificationFixtureError("corpus_fixtures must be an object")

    if set(corpus_fixtures.keys()) != set(all_fixture_ids):
        missing = sorted(set(all_fixture_ids) - set(corpus_fixtures.keys()))
        unreferenced = sorted(set(corpus_fixtures.keys()) - set(all_fixture_ids))
        raise QualificationFixtureError(
            f"corpus_fixtures mismatch; missing={missing}, unreferenced={unreferenced}"
        )

    # 5. Semantic validation of each fixture
    for case_id in REQUIRED_SCOPE_CASE_IDS:
        expected_type = CASE_FIXTURE_TYPES[case_id]
        fixture_ids = case_evidence_fixtures[case_id]

        for fixture_id in fixture_ids:
            # Check namespace safety
            if not fixture_id.startswith(FIXTURE_NAMESPACE_PREFIX):
                for prod_prefix in PRODUCTION_DOCUMENT_PREFIXES:
                    if fixture_id.startswith(prod_prefix):
                        raise QualificationFixtureError(
                            f"fixture {fixture_id!r} namespace collides with normal production identity"
                        )

            record = corpus_fixtures[fixture_id]
            if not isinstance(record, dict):
                raise QualificationFixtureError(f"fixture record {fixture_id!r} must be an object")

            identity_type = record.get("identity_type")
            source_chunk_id = record.get("source_chunk_id")

            if identity_type != expected_type:
                raise QualificationFixtureError(
                    f"fixture {fixture_id!r} has identity_type {identity_type!r}; case {case_id} requires {expected_type!r}"
                )
            if not isinstance(source_chunk_id, str) or not source_chunk_id:
                raise QualificationFixtureError(
                    f"fixture {fixture_id!r} lacks source_chunk_id binding"
                )

            # Resolve bound rows
            if source_chunk_id not in rows_by_source_chunk:
                raise QualificationFixtureError(
                    f"fixture {fixture_id!r} references unknown frozen identity {source_chunk_id!r}"
                )

            source_rows = rows_by_source_chunk[source_chunk_id]
            if identity_type == "chunk":
                bound_rows = [
                    r for r in source_rows if fixture_id in {r.mesa_chunk_id, r.source_chunk_id}
                ]
            elif identity_type == "evidence":
                bound_rows = [r for r in source_rows if r.evidence_id == fixture_id]
            elif identity_type == "catalog":
                bound_rows = [r for r in source_rows if r.catalog_id == fixture_id]
            elif identity_type == "document":
                bound_rows = [r for r in source_rows if r.document_id == fixture_id]
            elif identity_type == "revision":
                bound_rows = [r for r in source_rows if r.version_id == fixture_id]
            else:
                raise QualificationFixtureError(f"unsupported identity_type: {identity_type}")

            if not bound_rows:
                raise QualificationFixtureError(
                    f"{identity_type} fixture {fixture_id!r} is absent from frozen identity authority"
                )

            # Check semantic fields match
            semantic_fields = {
                "tenant_id",
                "dataset_id",
                "agent_id",
                "status",
                "jurisdiction",
                "is_current",
                "valid_from",
                "valid_to",
            }
            for field_name in semantic_fields.intersection(record):
                expected_val = record[field_name]
                if not any(getattr(r, field_name) == expected_val for r in bound_rows):
                    raise QualificationFixtureError(
                        f"fixture {fixture_id!r} {field_name} metadata differs from frozen identity authority"
                    )

            # Semantic isolation checks
            if case_id == "cross_tenant_search":
                if record.get("tenant_id") != forbidden_tenant:
                    raise QualificationFixtureError(
                        f"cross-tenant fixture {fixture_id!r} does not belong to forbidden tenant"
                    )
            elif case_id == "cross_dataset_search":
                if record.get("dataset_id") != forbidden_dataset:
                    raise QualificationFixtureError(
                        f"cross-dataset fixture {fixture_id!r} does not belong to forbidden dataset"
                    )
            elif case_id == "cross_agent_search":
                if record.get("agent_id") != forbidden_agent:
                    raise QualificationFixtureError(
                        f"cross-agent fixture {fixture_id!r} does not belong to forbidden agent"
                    )
            elif case_id == "inactive_status_search":
                if str(record.get("status", "")).upper() not in {"INACTIVE", "TOMBSTONED", "DELETED"}:
                    raise QualificationFixtureError(
                        f"inactive fixture {fixture_id!r} is not inactive/tombstoned/deleted"
                    )
            elif case_id == "wrong_jurisdiction_search":
                if record.get("jurisdiction") in {None, "TR"}:
                    raise QualificationFixtureError(
                        f"wrong-jurisdiction fixture {fixture_id!r} is not outside TR"
                    )
            elif case_id == "stale_version_search":
                if record.get("is_current") is not False:
                    raise QualificationFixtureError(
                        f"stale fixture {fixture_id!r} is not marked non-current"
                    )
            elif case_id == "effective_date_boundary_search":
                try:
                    vf = datetime.fromisoformat(str(record["valid_from"]).replace("Z", "+00:00"))
                    vt = datetime.fromisoformat(str(record["valid_to"]).replace("Z", "+00:00"))
                except (KeyError, TypeError, ValueError) as exc:
                    raise QualificationFixtureError(
                        f"temporal fixture {fixture_id!r} lacks valid ISO effective dates"
                    ) from exc
                if vf <= PHASE7_PROBE_TIME <= vt:
                    raise QualificationFixtureError(
                        f"temporal fixture {fixture_id!r} is valid at probe boundary {PHASE7_PROBE_TIME.isoformat()}"
                    )
            elif case_id.endswith("_visibility"):
                if record.get("tenant_id") != forbidden_tenant:
                    raise QualificationFixtureError(
                        f"visibility fixture {fixture_id!r} does not belong to forbidden tenant"
                    )

    authority_hash = hashlib.sha256(canonical_json_bytes(scope_test_authority)).hexdigest()
    return {
        "status": "PASS",
        "fixture_authority_hash": authority_hash,
        "case_count": len(REQUIRED_SCOPE_CASE_IDS),
        "total_fixtures": len(all_fixture_ids),
    }


def load_baseline_identity_map_rows(
    baseline_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Loads and validates the 5,721 baseline identity map rows."""
    if baseline_path is None:
        baseline_path = (
            Path(__file__).parent.parent
            / "resources"
            / "frozen_qualification_baseline_identity_map.jsonl"
        )

    if not baseline_path.exists():
        raise QualificationFixtureError(
            f"baseline identity map file not found: {baseline_path}"
        )

    raw_bytes = baseline_path.read_bytes()
    expected_sha256 = "960c4085e40082e88a5e1baf680c58fd2c5d8e00cefd2aaa180cb79e8338336d"
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise QualificationFixtureError(
            f"baseline identity map SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )

    rows: list[dict[str, Any]] = []
    for line in raw_bytes.decode("utf-8").splitlines():
        line_str = line.strip()
        if not line_str:
            continue
        row_dict = json.loads(line_str)
        QualificationIdentityRow.model_validate(row_dict)
        rows.append(row_dict)

    if len(rows) != 5721:
        raise QualificationFixtureError(
            f"expected exactly 5721 baseline identity map rows, got {len(rows)}"
        )

    return rows
