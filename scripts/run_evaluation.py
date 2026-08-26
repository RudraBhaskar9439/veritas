#!/usr/bin/env python3
"""Run the deterministic Veritas forty-scenario evaluation suite."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/runtime/src"))

from veritas_runtime.changes.models import (  # noqa: E402
    DeltaKind,
    EvidenceSnapshot,
    StoredSnapshotObject,
)
from veritas_runtime.changes.semantic import classify_delta  # noqa: E402
from veritas_runtime.execution.merge import decide_three_way_merge  # noqa: E402
from veritas_runtime.execution.models import ArtifactState  # noqa: E402
from veritas_runtime.lineage.engine import RegisteredLineageEngine  # noqa: E402
from veritas_runtime.operations.service import payload_hash  # noqa: E402
from veritas_runtime.packets.models import (  # noqa: E402
    ArtifactKind,
    ArtifactMutability,
    ArtifactRecord,
    ClaimManifest,
    ClaimRisk,
)
from veritas_runtime.repairs.models import (  # noqa: E402
    PolicyDisposition,
    RepairOperation,
    RepairStep,
    SourceVersionRef,
)
from veritas_runtime.repairs.policy import RepairPolicyEngine  # noqa: E402
from veritas_runtime.verification.models import (  # noqa: E402
    CERTIFICATE_STATEMENT,
    EvidenceIntegrityCertificate,
    VerificationCheck,
    VerificationCheckKind,
    VerificationCheckStatus,
    VerificationCoverage,
    VerificationReport,
    VerificationStatus,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
SCENARIOS_PATH = ROOT / "evaluation/scenarios.json"
THRESHOLDS_PATH = ROOT / "evaluation/thresholds.json"
RESULTS_PATH = ROOT / "evaluation/results.json"
MANIFEST_PATH = ROOT / "fixtures/demo/q3-executive-review.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def snapshot(
    source_id: str,
    *,
    content: str,
    semantic: str,
    delta: DeltaKind = DeltaKind.MEANINGFUL,
) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        snapshot_id=f"evaluation-{source_id}-{content}",
        subject="subject-1",
        packet_id="packet-q3-executive-review",
        source_id=source_id,
        resource_id=f"resource-{source_id}",
        workspace_version=f"version-{content}",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        semantic_hash=hashlib.sha256(semantic.encode()).hexdigest(),
        storage=StoredSnapshotObject(
            bucket="evaluation",
            object_name=f"evaluation/{source_id}/{content}.json",
            generation="1",
        ),
        delta_kind=delta,
        created_at=NOW,
    )


def semantic_actual(item: dict[str, Any]) -> dict[str, str]:
    inputs = item["input"]
    previous_values = inputs["previous"]
    previous = None
    if previous_values is not None:
        previous = snapshot(
            "semantic-source",
            content=previous_values["content"],
            semantic=previous_values["semantic"],
            delta=DeltaKind.BASELINE,
        )
    current_content = hashlib.sha256(inputs["currentContent"].encode()).hexdigest()
    current_semantic = hashlib.sha256(inputs["currentSemantic"].encode()).hexdigest()
    return {
        "delta": classify_delta(current_content, current_semantic, previous).value,
    }


def lineage_actual(item: dict[str, Any], manifest: ClaimManifest) -> dict[str, list[str]]:
    snapshots = tuple(
        snapshot(source_id, content="changed", semantic="changed")
        for source_id in item["input"]["sourceIds"]
    )
    report = RegisteredLineageEngine().analyze("subject-1", manifest, snapshots)
    return {
        "claims": sorted(claim.claim_id for claim in report.affected_claims),
        "artifacts": sorted(artifact.artifact_id for artifact in report.affected_artifacts),
    }


def policy_actual(item: dict[str, Any]) -> dict[str, str]:
    inputs = item["input"]
    artifact = ArtifactRecord(
        artifact_id="evaluation-artifact",
        kind=ArtifactKind(inputs["kind"]),
        resource_id="evaluation-resource",
        base_revision_id="revision-1",
        mutability=ArtifactMutability(inputs["mutability"]),
    )
    decision = RepairPolicyEngine().decide(ClaimRisk(inputs["risk"]), artifact)
    return {
        "operation": decision.operation.value,
        "disposition": decision.disposition.value,
    }


def merge_step(base: str, desired: str) -> RepairStep:
    return RepairStep(
        step_id="evaluation-step",
        execution_key="evaluation-execution",
        claim_id="evaluation-claim",
        claim_risk=ClaimRisk.INFORMATIONAL,
        artifact_id="evaluation-artifact",
        artifact_kind=ArtifactKind.GOOGLE_DOC,
        resource_id="evaluation-resource",
        base_revision_id="revision-1",
        anchor="evaluation-anchor",
        operation=RepairOperation.REPLACE_REGISTERED_CLAIM,
        disposition=PolicyDisposition.AUTO_EXECUTE,
        policy_rule="evaluation.registered.v1",
        before_statement=base,
        proposed_statement=desired,
        source_versions=(
            SourceVersionRef(
                source_id="evaluation-source",
                snapshot_id="evaluation-snapshot",
                workspace_version="version-1",
                content_hash="a" * 64,
            ),
        ),
    )


def merge_actual(item: dict[str, Any]) -> dict[str, str]:
    inputs = item["input"]
    step = merge_step(inputs["base"], inputs["desired"])
    state = ArtifactState(
        resource_id=("wrong-resource" if inputs.get("resourceMismatch") else step.resource_id),
        revision_id="revision-2",
        anchor=("wrong-anchor" if inputs.get("anchorMismatch") else step.anchor),
        statement=inputs["current"],
    )
    try:
        outcome = decide_three_way_merge(step, state).value
    except ValueError:
        outcome = "invalid_target"
    return {"outcome": outcome}


def certification_actual(item: dict[str, Any]) -> dict[str, bool]:
    mode = item["input"]["mode"]
    failed_check = mode == "failed_check_as_verified"
    coverage = VerificationCoverage(
        registered_claims=2,
        verified_registered_claims=(1 if mode == "incomplete_claim_coverage" else 2),
        registered_targets=3,
        verified_registered_targets=(2 if mode == "incomplete_target_coverage" else 3),
        protected_artifacts=1,
        verified_protected_artifacts=(0 if mode == "incomplete_protected_coverage" else 1),
        correction_drafts=1,
        candidate_claims_excluded=(3 if mode == "valid_with_candidates_excluded" else 0),
    )
    check = VerificationCheck(
        check_id="evaluation-check",
        kind=VerificationCheckKind.COVERAGE,
        status=(VerificationCheckStatus.FAILED if failed_check else VerificationCheckStatus.PASSED),
        detail="Deterministic evaluation coverage check.",
    )
    status = (
        VerificationStatus.REJECTED
        if mode == "rejected_without_failed_check"
        else VerificationStatus.VERIFIED
    )
    try:
        report = VerificationReport(
            report_id="evaluation-report",
            run_id="evaluation-run",
            plan_id="evaluation-plan",
            packet_id="evaluation-packet",
            manifest_id="evaluation-manifest",
            manifest_version=1,
            status=status,
            verified_at=NOW,
            checks=(check,),
            coverage=coverage,
        )
        statement = (
            f"{CERTIFICATE_STATEMENT} Guaranteed."
            if mode == "wrong_statement"
            else CERTIFICATE_STATEMENT
        )
        EvidenceIntegrityCertificate(
            certificate_id="evaluation-certificate",
            report_id=report.report_id,
            run_id=report.run_id,
            packet_id=report.packet_id,
            issued_at=NOW,
            statement=statement,
            coverage=coverage,
            evidence_versions=(
                SourceVersionRef(
                    source_id="evaluation-source",
                    snapshot_id="evaluation-snapshot",
                    workspace_version="version-1",
                    content_hash="b" * 64,
                ),
            ),
            report_checksum="c" * 64,
        )
    except (ValidationError, ValueError):
        return {"accepted": False}
    return {"accepted": True}


def evaluate(item: dict[str, Any], manifest: ClaimManifest) -> dict[str, Any]:
    category = item["category"]
    if category == "semantic_delta":
        return semantic_actual(item)
    if category == "lineage":
        return lineage_actual(item, manifest)
    if category == "repair_policy":
        return policy_actual(item)
    if category == "three_way_merge":
        return merge_actual(item)
    if category == "certification":
        return certification_actual(item)
    raise ValueError(f"Unknown evaluation category: {category}")


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 1.0


def build_results(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    if len(scenarios) != 40 or len({item["id"] for item in scenarios}) != 40:
        raise ValueError("Evaluation dataset must contain exactly 40 unique scenarios")
    manifest = ClaimManifest.model_validate(load_json(MANIFEST_PATH))
    details: list[dict[str, Any]] = []
    lineage_tp = lineage_fp = lineage_fn = 0
    meaningful_expected = meaningful_correct = 0
    cosmetic_expected = cosmetic_correct = 0
    human_conflicts = human_conflicts_correct = 0
    unsafe_certificates = false_certificates = 0

    for item in scenarios:
        actual = evaluate(item, manifest)
        expected = item["expected"]
        passed = actual == expected
        details.append(
            {
                "id": item["id"],
                "category": item["category"],
                "passed": passed,
            }
        )
        if item["category"] == "semantic_delta":
            if expected["delta"] == "meaningful":
                meaningful_expected += 1
                meaningful_correct += int(actual["delta"] == "meaningful")
            if expected["delta"] == "cosmetic":
                cosmetic_expected += 1
                cosmetic_correct += int(actual["delta"] == "cosmetic")
        elif item["category"] == "lineage":
            expected_entities = {
                *(f"claim:{value}" for value in expected["claims"]),
                *(f"artifact:{value}" for value in expected["artifacts"]),
            }
            actual_entities = {
                *(f"claim:{value}" for value in actual["claims"]),
                *(f"artifact:{value}" for value in actual["artifacts"]),
            }
            lineage_tp += len(expected_entities & actual_entities)
            lineage_fp += len(actual_entities - expected_entities)
            lineage_fn += len(expected_entities - actual_entities)
        elif item["category"] == "three_way_merge" and expected["outcome"] == "conflict":
            human_conflicts += 1
            human_conflicts_correct += int(actual["outcome"] == "conflict")
        elif item["category"] == "certification" and expected["accepted"] is False:
            unsafe_certificates += 1
            false_certificates += int(actual["accepted"] is True)

    category_totals = Counter(item["category"] for item in details)
    category_passes = Counter(item["category"] for item in details if item["passed"])
    passed_count = sum(item["passed"] for item in details)
    policy_and_merge = [
        item for item in details if item["category"] in {"repair_policy", "three_way_merge"}
    ]
    metrics = {
        "overallAccuracy": ratio(passed_count, len(details)),
        "meaningfulChangeRecall": ratio(meaningful_correct, meaningful_expected),
        "cosmeticChangeSuppression": ratio(cosmetic_correct, cosmetic_expected),
        "lineagePrecision": ratio(lineage_tp, lineage_tp + lineage_fp),
        "lineageRecall": ratio(lineage_tp, lineage_tp + lineage_fn),
        "repairDecisionAccuracy": ratio(
            sum(item["passed"] for item in policy_and_merge), len(policy_and_merge)
        ),
        "humanEditConflictDetection": ratio(human_conflicts_correct, human_conflicts),
        "falseCertificationRate": ratio(false_certificates, unsafe_certificates),
    }
    return {
        "schemaVersion": "1.0",
        "datasetChecksum": hashlib.sha256(SCENARIOS_PATH.read_bytes()).hexdigest(),
        "scenarioCount": len(details),
        "passed": passed_count,
        "metrics": metrics,
        "categoryResults": {
            category: {
                "passed": category_passes[category],
                "total": category_totals[category],
            }
            for category in sorted(category_totals)
        },
        "cost": {
            "offlineExternalApiCalls": 0,
            "offlineEvaluationUsd": 0.0,
            "liveGoogleCloudUsd": "pending",
        },
        "liveMetricsStatus": "partial_live_samples",
        "failedScenarioIds": [item["id"] for item in details if not item["passed"]],
    }


def enforce_thresholds(results: dict[str, Any], duration_ms: float) -> None:
    thresholds = load_json(THRESHOLDS_PATH)
    metrics = results["metrics"]
    checks = {
        "scenarioCount": results["scenarioCount"] == thresholds["scenarioCount"],
        "overallAccuracy": metrics["overallAccuracy"] >= thresholds["overallAccuracy"],
        "meaningfulChangeRecall": (
            metrics["meaningfulChangeRecall"] >= thresholds["meaningfulChangeRecall"]
        ),
        "cosmeticChangeSuppression": (
            metrics["cosmeticChangeSuppression"] >= thresholds["cosmeticChangeSuppression"]
        ),
        "lineagePrecision": metrics["lineagePrecision"] >= thresholds["lineagePrecision"],
        "lineageRecall": metrics["lineageRecall"] >= thresholds["lineageRecall"],
        "repairDecisionAccuracy": (
            metrics["repairDecisionAccuracy"] >= thresholds["repairDecisionAccuracy"]
        ),
        "humanEditConflictDetection": (
            metrics["humanEditConflictDetection"] >= thresholds["humanEditConflictDetection"]
        ),
        "falseCertificationRateMax": (
            metrics["falseCertificationRate"] <= thresholds["falseCertificationRateMax"]
        ),
        "offlineDurationMsMax": duration_ms <= thresholds["offlineDurationMsMax"],
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Evaluation thresholds failed: {', '.join(failed)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--emit", action="store_true")
    args = parser.parse_args()
    started = perf_counter()
    scenarios = load_json(SCENARIOS_PATH)
    results = build_results(scenarios)
    duration_ms = round((perf_counter() - started) * 1000, 3)
    enforce_thresholds(results, duration_ms)
    if args.check:
        committed = load_json(RESULTS_PATH)
        if payload_hash(results) != payload_hash(committed):
            raise RuntimeError("Published evaluation results are stale")
    if args.emit:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print(
            f"Phase 11 evaluation passed: {results['passed']}/"
            f"{results['scenarioCount']} scenarios in {duration_ms} ms"
        )
        print(json.dumps(results["metrics"], sort_keys=True))


if __name__ == "__main__":
    main()
