# ADR 0014: Preview cost containment

## Status

Accepted for the hackathon preview environment.

## Context

Veritas needs real Google Cloud proof without silently turning a demo deployment into an open-ended financial commitment. Cloud Billing budgets are observability controls, not universal hard caps, and reported cost can lag actual usage. Promotional credits also reduce a bill without necessarily stopping resources when the credit is exhausted.

## Decision

The preview environment uses layered containment:

1. The billing account must remain an unupgraded **Free trial account**. A paid account is a deployment stop condition.
2. The project receives a monthly gross-cost warning budget in the billing account's native currency. Credits are excluded from threshold calculations so consumption remains visible before offsets. The current INR preview uses ₹4,000, with alerts at ₹800, ₹2,000, ₹3,200, and ₹4,000.
3. Cloud Run keeps minimum instances at zero. Preview API, ingress, and web services are capped at two instances; the worker is capped at three.
4. Preview Cloud SQL uses the smallest accepted tier, a 10 GB initial disk, and a 20 GB autosize ceiling.
5. Only the APIs listed in Terraform may be enabled. Marketplace products, prepayment, paid-account activation, and quota increases are outside the preview runbook.
6. A console spend cap is added when the billing account exposes that feature. Its status is captured as evidence instead of assumed.
7. After judging, billing is disabled on the project, resources are destroyed through the audited teardown, the billing account is closed, and only then is the UPI mandate cancelled.

## Consequences

- A compromised or looping runtime has small, explicit scale boundaries.
- Gross cost remains visible even while credits pay the bill.
- Budget notifications alone are never described as a hard stop.
- Preview throughput is intentionally lower than production throughput.
- The live deployment remains blocked until both billing status and cost controls are verified.

## Verification

- `terraform validate` proves the budget, scale ceilings, and disk ceiling are structurally valid.
- The live gate records Billing Overview status, budget thresholds, spend-cap availability, service scaling, and Cloud SQL disk settings.
- The final proof manifest continues to report live cost as pending until measured from the deployed system.
