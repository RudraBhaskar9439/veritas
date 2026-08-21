from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from veritas_runtime.packets.models import CamelModel
from veritas_runtime.repairs.models import SourceVersionRef

CERTIFICATE_STATEMENT = (
    "All monitored claims in this Decision Packet are consistent with their registered "
    "evidence versions as of the stated timestamp."
)


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    REJECTED = "rejected"
    STALE = "stale"


class VerificationCheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class VerificationCheckKind(StrEnum):
    REPAIR_RUN = "repair_run"
    SOURCE_FRESHNESS = "source_freshness"
    DETERMINISTIC_CLAIM = "deterministic_claim"
    REGISTERED_TARGET = "registered_target"
    IMMUTABLE_ORIGINAL = "immutable_original"
    CORRECTION_DRAFT = "correction_draft"
    PROTECTED_REGION = "protected_region"
    COVERAGE = "coverage"


class VerificationCheck(CamelModel):
    check_id: str = Field(min_length=1)
    kind: VerificationCheckKind
    status: VerificationCheckStatus
    detail: str = Field(min_length=1)
    source_id: str | None = None
    claim_id: str | None = None
    artifact_id: str | None = None
    expected_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    observed_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class VerificationCoverage(CamelModel):
    registered_claims: int = Field(ge=0)
    verified_registered_claims: int = Field(ge=0)
    registered_targets: int = Field(ge=0)
    verified_registered_targets: int = Field(ge=0)
    protected_artifacts: int = Field(ge=0)
    verified_protected_artifacts: int = Field(ge=0)
    correction_drafts: int = Field(ge=0)
    candidate_claims_excluded: int = Field(ge=0)

    @model_validator(mode="after")
    def verified_counts_do_not_exceed_totals(self) -> "VerificationCoverage":
        if self.verified_registered_claims > self.registered_claims:
            raise ValueError("Verified claim coverage exceeds registered claims")
        if self.verified_registered_targets > self.registered_targets:
            raise ValueError("Verified target coverage exceeds registered targets")
        if self.verified_protected_artifacts > self.protected_artifacts:
            raise ValueError("Verified protected coverage exceeds protected artifacts")
        return self


class ProtectedArtifactBaseline(CamelModel):
    run_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    anchor_set_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    protected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    captured_at: datetime


class ProtectedArtifactState(CamelModel):
    artifact_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    anchor_set_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    protected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ObservedStatement(CamelModel):
    resource_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)


class VerificationReport(CamelModel):
    report_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    manifest_version: int = Field(ge=1)
    status: VerificationStatus
    verified_at: datetime
    checks: tuple[VerificationCheck, ...] = Field(min_length=1)
    coverage: VerificationCoverage

    @model_validator(mode="after")
    def status_matches_checks_and_coverage(self) -> "VerificationReport":
        failures = [
            check for check in self.checks if check.status == VerificationCheckStatus.FAILED
        ]
        if self.status == VerificationStatus.VERIFIED:
            if failures:
                raise ValueError("A verified report cannot contain failed checks")
            if (
                self.coverage.verified_registered_claims != self.coverage.registered_claims
                or self.coverage.verified_registered_targets != self.coverage.registered_targets
                or self.coverage.verified_protected_artifacts != self.coverage.protected_artifacts
            ):
                raise ValueError("A verified report requires complete registered coverage")
        elif not failures:
            raise ValueError("A non-verified report must contain a failed check")
        return self


class EvidenceIntegrityCertificate(CamelModel):
    certificate_id: str = Field(min_length=1)
    report_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    packet_id: str = Field(min_length=1)
    issued_at: datetime
    statement: str = Field(pattern=r"^All monitored claims in this Decision Packet")
    coverage: VerificationCoverage
    evidence_versions: tuple[SourceVersionRef, ...] = Field(min_length=1)
    report_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def statement_is_scoped_and_coverage_is_complete(self) -> "EvidenceIntegrityCertificate":
        if self.statement != CERTIFICATE_STATEMENT:
            raise ValueError("Certificate language must use the approved scoped statement")
        if (
            self.coverage.verified_registered_claims != self.coverage.registered_claims
            or self.coverage.verified_registered_targets != self.coverage.registered_targets
            or self.coverage.verified_protected_artifacts != self.coverage.protected_artifacts
        ):
            raise ValueError("A certificate requires complete registered coverage")
        return self


class VerificationResult(CamelModel):
    report: VerificationReport
    report_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    certificate: EvidenceIntegrityCertificate | None = None
    certificate_checksum: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reused: bool

    @model_validator(mode="after")
    def certificate_matches_report_status(self) -> "VerificationResult":
        has_certificate = self.certificate is not None
        if has_certificate != (self.report.status == VerificationStatus.VERIFIED):
            raise ValueError("Only a verified report may carry a certificate")
        if has_certificate != (self.certificate_checksum is not None):
            raise ValueError("Certificate and checksum must be present together")
        return self


class VerifyRepairRequest(CamelModel):
    request_id: str = Field(min_length=1)
