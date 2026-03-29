# Diagram-to-IaC Generation: Production-Grade Requirements

## Background
Current generate flow produces starter templates but misses key production details for complex diagrams, including:
- Availability zone modeling
- Connectivity and dependency wiring between services
- Security, IAM, and networking depth
- Validation and confidence reporting

## Product Goal
Build a production-grade system that can analyze complex architecture diagrams and generate highly accurate, deployable IaC templates with explicit topology, connectivity, and safety checks.

## Core Requirements

### 1. Multi-Modal Diagram Understanding
- Support image and PDF diagram inputs.
- Extract text labels via OCR.
- Detect cloud service icons and map to canonical resource types.
- Detect connectors/arrows and infer direction of traffic and event flow.
- Detect visual boundaries (for example VPCs, subnets, AZs, accounts, trust zones).

### 2. Canonical Architecture IR (Intermediate Representation)
- Convert every parsed diagram into a strict, typed architecture graph.
- Represent nodes (resources), edges (connectivity), scopes (region/AZ/account), and constraints.
- Preserve unresolved ambiguities and confidence scores per inferred entity.
- Store provenance for each entity (what in the diagram produced it).

### 3. Topology and Connectivity Synthesis
- Infer required network primitives from diagram intent:
  - VPC, public/private subnets, route tables, internet gateway, NAT gateway
- Synthesize service-to-service connectivity:
  - Security groups, port/protocol rules, IAM trust relationships, event source mappings
- Generate explicit dependencies and references across resources.
- Ensure generated architecture includes multi-AZ placement where implied.

### 4. IaC Generation Quality
- Generate Terraform and CloudFormation from the same IR.
- Prefer module-oriented output for reusable patterns.
- Include variables, outputs, and environment-aware naming conventions.
- Include encryption defaults, tagging standards, and least-privilege IAM baselines.

### 5. Validation and Guardrails
- Run post-generation checks before returning output:
  - Formatting and syntax validation
  - Linting
  - Security scanning
  - Policy checks
- Block or flag output that fails critical checks.
- Return a structured validation report with actionable remediation items.

### 6. Confidence and Clarification Workflow
- Compute confidence for parse accuracy, topology inference, and generated IaC validity.
- If confidence is below threshold, ask targeted clarification questions instead of guessing.
- Return an assumptions section that is explicit and reviewable.

### 7. Explainability
- Provide mapping from diagram elements to generated resources.
- Show inferred relationships and why they were created.
- Highlight unresolved ambiguities and fallback assumptions.

### 8. Regression and Quality Measurement
- Build a benchmark dataset of simple to highly complex diagrams.
- Track objective quality metrics:
  - Parse completeness
  - Topology correctness
  - Connectivity correctness
  - Security correctness
  - Deployability rate
- Add regression tests to prevent quality drift.

## API and Workflow Requirements
- Pass raw diagram content into backend generation service (not filename and notes only).
- Introduce a two-stage pipeline:
  1. Diagram -> Architecture IR
  2. Architecture IR -> IaC templates
- Return enriched response payload containing:
  - Generated template
  - Validation results
  - Confidence scores
  - Assumptions
  - Clarification prompts (when required)
  - Diagram-to-resource mapping

## Non-Functional Requirements
- Deterministic behavior for identical inputs where possible.
- Clear latency targets for medium and complex diagrams.
- Robust error handling with user-readable failure reasons.
- Auditability of generation decisions.
- Secure processing of uploaded diagrams.

## Phased Delivery Plan

### Phase 1: Foundation
- Wire diagram bytes through API to generation service.
- Add Architecture IR schema and serialization.
- Add minimal topology-aware generation (AZs, subnet types, core connectivity).

### Phase 2: Intelligence
- Add OCR, icon detection, connector parsing, boundary detection.
- Expand inference rules for networking, IAM, and event-driven paths.
- Add confidence scoring and clarification workflow.

### Phase 3: Hardening
- Integrate validation toolchain and policy gates.
- Add explainability output and mapping reports.
- Build benchmark suite and CI regression checks.

### Phase 4: Scale and Reliability
- Improve performance for large diagrams.
- Add caching for repeated parse/generation patterns.
- Add enterprise policy packs and organization-specific conventions.

## Acceptance Criteria
- Complex diagrams produce templates with explicit AZ, network, and connectivity details.
- Generated templates pass baseline validation gates by default.
- Low-confidence inference paths trigger clarification prompts.
- Quality metrics meet agreed thresholds on benchmark diagram suite.
- Output includes traceable mapping from diagram elements to IaC resources.
