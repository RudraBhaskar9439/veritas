# ADR 0013: Judge-first consequence room

- Status: accepted
- Date: 2026-08-22

## Context

The first Command Center proved the entire evidence-to-certificate story, but its opening view still read like a polished enterprise report. Recent Google hackathon winners make autonomous behavior legible faster: a single memorable promise, an obvious causal trigger, a visible execution spine, domain-specific evidence, and a result that a judge can understand without reading supporting copy.

The reviewed set included every winner-tagged entry in the Google Cloud Rapid Agent Hackathon gallery, the official Gemini API Developer Competition winner set, and the Google Cloud x MLB grand-prize recap. Representative interfaces were inspected in detail for Cassandra, ComplianceOS, BLUEPRINT, KickOff, and AutoSRE.

Research sources:

- <https://rapid-agent.devpost.com/project-gallery>
- <https://devpost.com/software/cassandra-jilmgy>
- <https://devpost.com/software/compilanceos>
- <https://devpost.com/software/blueprint-ai-property-due-diligence>
- <https://devpost.com/software/trustos>
- <https://devpost.com/software/autosre-the-autonomous-on-call-engineer>
- <https://ai.google.dev/competition>
- <https://info.devpost.com/customer-stories/google-cloud-x-mlb-hackathon-recap>

## Decision

Veritas will use a hybrid **consequence room** rather than a generic chatbot, admin dashboard, or copied winner aesthetic.

The opening viewport must communicate five things in order:

1. the registered source changed from 4% to 9%;
2. no prompt was required after the change;
3. four registered claims and five Workspace artifacts entered the exact blast radius;
4. human prose and immutable sent email were protected by policy;
5. an independent verifier re-read 13 targets before issuing a scoped certificate.

The primary visual object is a manifest-derived consequence map: evidence → affected claims → repaired artifacts. It uses only registered manifest collections already exposed by the canonical incident model. It does not invent claim-to-artifact edges in the frontend.

The visual language combines a cinematic dark incident stage with an evidence-oriented light workspace. Green represents verified progress, amber represents decision boundaries, red is reserved for superseded evidence, and application colors identify Workspace surfaces. Motion is limited to the replayed state transition and is disabled under reduced-motion preferences.

## Winner patterns adopted

- one sentence that makes the value obvious in under five seconds;
- one replay action that demonstrates the whole product loop;
- a live stage spine rather than a spinner or hidden chain-of-thought;
- a domain-specific visual centerpiece instead of generic metric cards;
- exact sources, timestamps, counts, guardrails, and receipts visible in the product;
- progressive disclosure from outcome to causal details;
- honest labels distinguishing deterministic replay from future live Cloud proof.

## Patterns deliberately rejected

- chat as the primary interface;
- decorative multi-agent avatars with no observable state;
- fabricated reasoning text or chain-of-thought;
- gradients and glass effects without information value;
- animated candidate lineage that could imply unregistered relationships;
- claims of universal correctness or live Google Cloud operation before deployment evidence exists.

## Consequences

- Judges see the autonomous result and its safety boundary before technical detail.
- The demo can remain a single continuous run with a clear visual payoff at certification.
- The existing lineage, diff, journal, and independent verification views remain available for architectural review.
- Hosted browser, responsive, and accessibility acceptance still remains a live deployment gate.
