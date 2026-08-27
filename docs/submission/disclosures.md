# Implementation, reuse, and data disclosures

## Authorship and build period

Veritas was created during the All Things Agentic Hackathon submission period. The repository history begins on August 21, 2026, after the official August 3 start. No pre-existing Veritas project code was incorporated.

Rudra Bhaskar is the current repository author and intended entrant. The Devpost project must list every person who contributed to the submission before it is submitted.

## AI assistance

OpenAI ChatGPT/Codex was used as an AI coding assistant for research, scaffolding, implementation, debugging, test generation, documentation, and deployment support. The entrant chose the product concept and constraints, reviewed the implementation, controlled the Google accounts and Cloud project, executed the live Workspace tests, and is responsible for the final submission. AI coding assistants are standard development tools expressly allowed by the contest rules.

Gemini 3.5 Flash is also part of the product runtime. It performs a schema-bound safety review over an already-registered consequence set; it does not determine lineage, approve its own actions, execute arbitrary tools, or issue integrity certificates.

## Third-party components and services

The project uses standard open-source packages declared in `pyproject.toml`, `services/runtime/pyproject.toml`, `package.json`, and their lockfiles. Those packages remain subject to their respective licenses. The project also uses Google Cloud, Vertex AI, Google Gen AI SDK, and Google Workspace APIs under the terms applicable to the entrant's accounts.

No third-party proprietary source code, private dataset, customer database, or purchased template is included in the submission. No project-specific commercial license, contract work, investment, or preferential development support from Google or Devpost was used. Generally offered Google Cloud trial or hackathon credits pay only for ordinary service usage.

## Data sources and privacy

The demonstration uses synthetic Q3 business values and resources owned by the entrant's dedicated Google Workspace test account. Veritas does not scrape public data. Submitted screenshots and video must exclude OAuth tokens, secret values, billing details, unrelated email, personal documents, and third-party personal data.

The public judge walkthrough contains deterministic demonstration records only. Authenticated production data is subject-scoped and remains behind the account's Google OAuth grant. Gmail automation accepts only an authorized sender and thread-bound route, never sends mail, and limits changes to the manifest-bound Google Task.

## Claim boundary

Veritas proves that named, registered targets match named evidence versions after repair. It does not guarantee general factual correctness, legal compliance, or that an entire document is true.
