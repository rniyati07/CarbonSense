# CarbonSense — Product Requirements Document

**Version:** 2.0
**Status:** Active Product & Research Planning
**Supersedes:** v1.0 (hackathon MVP scope — see Appendix: Migration Map)
**Document Owner:** Product
**Parallel Tracks:** Commercial SaaS Platform · IEEE Research Contribution

---

## 1. Executive Summary

CarbonSense is an energy intelligence platform that turns raw building meter data into a continuously updated, explainable decarbonization program — replacing the episodic, expensive energy audit (₹4L–₹40L, once every 3–5 years) with always-on AI monitoring that any facility manager, sustainability officer, or compliance team can act on without hiring a consultant. The product ingests submeter and building-level energy data, runs it through a seven-layer anomaly intelligence pipeline, models counterfactual savings scenarios, and produces a prioritized, ROI-ranked action plan — with every finding traceable back to a defensible, root-cause explanation rather than a black-box score.

**Business model, in one sentence:** CarbonSense is a tiered SaaS subscription priced per building and per tenant, with a freemium single-building entry point for SME facility managers and a second revenue line from a platform/API tier that lets integrators and channel partners embed CarbonSense's detection and scenario-modeling engine into their own building-management and ESG-reporting products.

**Research contribution, in one sentence:** CarbonSense's research track contributes a graph-aware anomaly localization method that models a building's submeter circuit topology as a graph and uses a graph neural network to localize faults more accurately than topology-agnostic baselines (Isolation Forest, Autoencoder, STL-residual decomposition), validated through synthetic fault injection against the COMBED instrumented-building dataset.

These two tracks are intentionally coupled, not parallel curiosities. The same explainability requirement that makes the product defensible to an ESG auditor or regulator is the requirement that forces the research team to produce localization that is interpretable, not just accurate — and the same root-cause attribution layer (Layer 6 of the AnomalyAgent pipeline) is the production surface where the GNN's output, once validated, would ship. The product justifies the rigor of the research; the research justifies the durability of the product's core differentiation against incumbents that ship dashboards without explanations.

CarbonSense exists because buildings account for 37% of global CO₂ emissions, the tooling gap between "enterprise BMS buyer" and "everyone else" is enormous, and the explainability bar in this category has historically been low. This document defines the platform, the research requirements, and the operating discipline needed to build both at once.

---

## 2. Problem Statement & Market Context

### 2.1 The Core Problem

Buildings generate more CO₂ than the entire transportation sector. Smart meters and submeters increasingly exist inside commercial buildings, but metering is not intelligence: raw kWh time series do not tell a facility manager which piece of equipment is wasting money, whether an anomaly is worth investigating, or what to do about it in priority order. The traditional answer — a professional energy audit — is expensive (₹4L–₹40L), infrequent (every 3–5 years), and produces a static PDF that's stale within months. The result is a market where:

- **SME and mid-market facility managers** have a smart meter and a bill, but no software layer between the two. They are flying blind on a recurring operating expense that is also a sustainability liability.
- **Enterprise commercial real estate (CRE) portfolios** often *do* have building-management systems (BMS), but those systems are built for control (HVAC scheduling, access, lighting), not for prioritized, financially-quantified waste detection across a multi-building estate — and the analytics layers bolted onto them are frequently opaque scoring engines that sustainability and facilities teams don't trust enough to act on without independent verification.
- **Compliance and ESG functions** are increasingly required to produce auditable, defensible emissions and energy-performance data, but most existing anomaly-detection tooling was not designed with an auditor or regulator as a stakeholder — it has no notion of "explain this finding well enough that it survives external scrutiny."

90% of the buildings that will exist in 2050 are already standing today. Decarbonization at the pace policy and capital markets now expect cannot come from new construction alone — it has to come from intelligently retrofitting and operationally optimizing the existing stock, at a cost and cadence far below the traditional audit cycle.

### 2.2 Market Sizing Logic

CarbonSense addresses two distinct buyer segments with different sales motions, price sensitivity, and product needs. Rather than asserting a single headline TAM figure (precise sizing requires primary research the team has not yet completed), this section lays out the sizing *logic* the business should validate and refine during go-to-market planning:

**SME / single-building segment (bottom-up, usage-based logic):**
- Addressable population = commercial buildings above a minimum size/spend threshold (large enough that energy spend is material, small enough that an enterprise BMS deployment is not commercially justified) that already have smart-meter or submeter data available, directly or via utility export.
- Within India alone, commercial and institutional building stock numbers in the hundreds of millions of structures; the *addressable* slice — buildings with digital meter access, an identifiable facilities decision-maker, and discretionary opex budget for a software subscription — is a much smaller filtered subset that should be sized via utility smart-meter rollout data and commercial real estate registries rather than total building counts.
- Monetization logic: low-friction freemium entry (single building, limited history) converting to a paid per-building subscription tier once value (identified waste, generated action plan) is demonstrated — a self-serve, product-led-growth motion.

**Enterprise / multi-building portfolio segment (top-down, account-based logic):**
- Addressable population = corporate real estate and facilities organizations managing portfolios of 10+ buildings, typically with an existing sustainability or ESG reporting function and a BMS vendor relationship already in place.
- Sizing should be approached account-by-account (portfolio size × buildings × expected per-building or per-portfolio price point) rather than population-counted, since enterprise CRE is a relationship-driven, RFP-influenced sale with a small number of large accounts per geography rather than a long tail of self-serve buyers.
- Monetization logic: tiered annual contracts priced on portfolio size and feature tier (including API/platform access), sold through a direct enterprise motion and, longer-term, through systems-integrator and BMS-vendor channel partnerships.

Both segments benefit from the same core technology; they differ in packaging, price point, sales motion, and the weight placed on explainability and compliance features (heavier for enterprise) versus simplicity and speed-to-first-insight (heavier for SME).

### 2.3 Competitive Landscape

CarbonSense competes in a category with several adjacent incumbents, none of which occupy the same position:

| Competitor | Core Offering | Where CarbonSense Differs |
|---|---|---|
| **EnergyHub** | Demand-response and DER (distributed energy resource) orchestration platform, focused on utility and grid-program participation | EnergyHub is grid-program-centric, not building-operations-centric; it optimizes for utility incentive programs rather than producing a facility manager's prioritized waste-reduction action plan |
| **Siemens (Desigo / building intelligence)** | Enterprise building-management and automation hardware-and-software stack | Siemens' analytics are typically sold attached to Siemens building-automation hardware, creating a high switching cost and hardware dependency; CarbonSense is hardware-agnostic and ingests data from whatever metering already exists |
| **Schneider Electric EcoStruxure** | Broad industrial and building IoT platform spanning energy, automation, and asset management | EcoStruxure's breadth is also its friction: enterprise deployments typically require systems-integrator involvement and a long implementation cycle; CarbonSense targets a materially faster time-to-first-insight as a wedge, then expands into the same accounts EcoStruxure serves |
| **IBM Envizi** | ESG and carbon-accounting data management and disclosure reporting platform | Envizi is strong on aggregating utility-bill-level data for regulatory disclosure, but is not built for submeter-level, equipment-specific anomaly detection or prescriptive ROI-ranked action plans; CarbonSense is operationally prescriptive where Envizi is reporting-centric |

**Positioning statement:** CarbonSense sits between "BMS hardware platforms" (Siemens, Schneider) and "ESG disclosure platforms" (Envizi) — it is the vertical-specialist layer that takes whatever meter or submeter data already exists, regardless of hardware vendor, and produces both (a) actionable, ROI-quantified operational recommendations for facilities teams and (b) explainable, audit-defensible evidence for compliance and ESG teams. No incumbent occupies both halves of that position with the same level of per-finding explainability.

### 2.4 Regulatory Tailwinds

Regulatory pressure on building energy performance and corporate sustainability disclosure is a meaningful but uneven tailwind, and the specifics vary by geography and have been actively shifting:

- **India:** The Energy Conservation (Amendment) Act, 2022 establishes the legal basis for a domestic carbon credit trading scheme and tightens energy-efficiency obligations on designated consumers, creating compliance-driven demand for measurement and reporting tooling. Listed companies above SEBI-defined thresholds are also subject to Business Responsibility and Sustainability Reporting (BRSR) requirements, which depend on credible underlying energy and emissions data.
- **EU:** The Corporate Sustainability Reporting Directive (CSRD) was a major early driver of enterprise ESG-data-platform demand, but the EU's "Omnibus I" simplification package, finalized in February 2026, materially narrowed CSRD's scope — raising the threshold to companies with more than 1,000 employees and over €450M net turnover, with the related due-diligence directive (CSDDD/CS3D) narrowed even further. This does not eliminate the tailwind, but it does mean enterprise CRE prospects should be qualified individually against the revised thresholds rather than assumed to be in-scope by default.
- **General direction:** Even where mandatory disclosure thresholds have moved, voluntary ESG commitments, green building certifications, tenant and investor pressure, and energy-cost volatility continue to drive demand for credible, granular building energy data independent of regulatory mandate.

This section should be revisited at least annually by Product and Compliance — regulatory scope in this category is actively moving, and specific claims made to customers about "what the platform helps you comply with" must be reviewed by legal/compliance counsel before being used in sales or marketing material.

---

## 3. Product Vision & Three-Year Roadmap Narrative

CarbonSense's trajectory runs from single-building intelligence, to multi-tenant portfolio platform, to an ecosystem that other companies build on.

**Year 1 — Prove the core loop, single building at a time.** The product earns trust one building at a time: ingest data, detect waste with explanations a facility manager actually believes, model savings scenarios, and close the loop by learning from which flags get confirmed versus dismissed. The seven-layer AnomalyAgent architecture and the explainability layer are not "advanced features" reserved for later — they are the wedge from day one, because the credibility gap (not the detection gap) is what differentiates CarbonSense from a generic outlier-detection tool. Early customers are SME and mid-market facility managers who self-serve onto a freemium tier and convert once the first action plan demonstrates real, defensible savings.

**Year 2 — Become a multi-building, multi-tenant platform.** Once the single-building loop is reliable, the platform expands along two axes simultaneously: *horizontally* into true multi-tenancy (data isolation, per-tenant model registries, role-based access for facilities teams versus sustainability/compliance teams) and *vertically* into the enterprise CRE portfolio use case (cross-building benchmarking, portfolio-level rollups, audit-log retention sufficient for external ESG assurance). This is also the year the research track matures from "promising offline benchmark" to a deployed capability: if the graph-aware localization method clears its publication and validation bar, it becomes a production option inside the root-cause attribution layer for buildings with sufficient submeter topology data.

**Year 3 — Open the platform into an ecosystem.** CarbonSense stops being only a destination product and becomes infrastructure other products build on: a documented, versioned API platform for systems integrators and BMS vendors to embed CarbonSense's detection and scenario-modeling engine into their own offerings; formal integrator partnerships that extend distribution without a linear increase in CarbonSense's own enterprise sales headcount; and an integration layer connecting verified, quantified savings and emissions-reduction findings to carbon credit registries and marketplaces, so that a building's documented efficiency gains can be translated into a monetizable instrument, not just a report. By the end of Year 3, the research contribution should also be a recognized reference point in the building-fault-detection-and-diagnosis (FDD) literature, with the production system citing its own published methodology as a credibility asset in enterprise and compliance sales conversations.

The throughline across all three years: explainability and data trust are not a feature, they are the moat. Any competitor can run an anomaly detector. Far fewer can make a sustainability officer comfortable putting the output in front of an external auditor.

---

## 4. Personas

### 4.1 SME Facility Manager — "Operational Owner"

**Profile:** Rajan, 38, Facilities Manager at a single mid-sized commercial office building. Manages electricity costs as one of several operational responsibilities, with no dedicated energy-analytics tooling. Reports to a managing director who has set a general "do something on sustainability" mandate without a defined budget or technical roadmap.

**Pain:** No software layer exists between his smart meter and a decision. A professional audit is too expensive and too slow to justify for a single building. He cannot tell, from a bill alone, whether HVAC scheduling, lighting, or an equipment fault is the dominant source of waste, and he has no way to quantify a fix in terms his MD will fund.

**Scenario:** Rajan connects his building's meter data (via CSV export or, increasingly, a direct smart-meter API integration) to CarbonSense. Within the freemium tier, he sees his building's anomalies surfaced with plain-language root-cause explanations, a ranked action plan with cost and CO₂ impact per action, and a "what changed" view as the feedback loop incorporates his confirmations and dismissals over time. He upgrades to a paid tier once the platform has identified savings that clearly exceed the subscription cost.

### 4.2 Enterprise Sustainability Officer — "Portfolio Owner"

**Profile:** Meera, 41, Head of Sustainability for a corporate real estate portfolio spanning dozens of buildings across multiple cities. Owns the company's energy-performance and emissions-reduction targets and reports progress to executive leadership and, increasingly, to external ESG disclosure processes.

**Pain:** Existing BMS analytics are siloed per building and per vendor, with no consistent way to benchmark performance across the portfolio or prioritize capital and operating spend where it will have the largest impact. She needs portfolio-level rollups, not just building-level dashboards, and she needs confidence that any number she puts in front of the board or an external auditor can survive scrutiny.

**Scenario:** Meera uses CarbonSense's multi-tenant, multi-building view to see normalized performance across her entire portfolio, identify which buildings are the largest sources of avoidable waste, and direct capital toward the highest-ROI interventions first. She relies on the platform's audit-log retention and root-cause attribution to support both internal capital-allocation decisions and external disclosure requirements.

### 4.3 SaaS Platform Integrator / API Consumer — "Ecosystem Partner"

**Profile:** Arvind, a product manager at a systems-integration firm that deploys and supports building-management software for mid-market commercial clients. His company does not want to build anomaly-detection and scenario-modeling capability in-house, but wants to offer it as part of its own branded product.

**Pain:** Building a credible anomaly-detection and explainability engine from scratch is a multi-year investment his company doesn't want to make, but his clients are increasingly asking for exactly this kind of capability inside the product he already sells them.

**Scenario:** Arvind integrates CarbonSense's API platform into his company's existing offering, using a documented, versioned API contract to ingest his clients' building data, retrieve anomaly findings and scenario models, and present them under his own product's branding. CarbonSense becomes infrastructure inside his product rather than a competing, customer-facing tool — a distribution channel that doesn't require CarbonSense's own sales team to close each end customer.

### 4.4 ESG Auditor / Regulator-Facing Reviewer — "Compliance Verifier"

**Profile:** Dr. Lakshmi, an independent ESG assurance reviewer (or, in some engagements, a regulatory compliance examiner) engaged to verify a client company's reported energy-performance and emissions claims before they are disclosed externally or submitted to a regulator.

**Pain:** Most building-analytics platforms produce a score or a flag with no inspectable reasoning behind it. An assurance reviewer cannot sign off on a claim she cannot trace back to a defensible methodology — "the model said so" is not evidence, and a black-box anomaly score is functionally unauditable.

**Scenario:** Dr. Lakshmi is given access to CarbonSense's explainability and reporting layer for a client building under review. For each flagged anomaly contributing to a reported savings or emissions-reduction claim, she can inspect the root-cause attribution (which features and which submeter circuits drove the finding), the confidence calibration behind it, and the audit log showing when the finding was raised, confirmed, or adjusted. She is able to either sign off on the claim or flag specific findings for further investigation — because the system was built to be inspected, not just trusted.

**Why this persona matters:** Dr. Lakshmi's persona is not a "nice to have" addition — it is the persona that makes the explainability and root-cause attribution layer (Section 5.4) a hard product requirement rather than an internal nicety. If no real-world reviewer like her can use the platform's output as evidence, the enterprise and compliance value proposition in Sections 2 and 4.2 does not hold up under scrutiny. Every requirement in the Anomaly Intelligence Platform's confidence-calibration and explainability layers should be designed, from the start, to survive a conversation with this persona.

---

## 5. Functional Requirements

Functional requirements are organized by platform capability, reflecting how the product is actually built and sold — not by individual agent names.

### 5.1 Data Ingestion & Multi-Tenancy

**Capability:** The platform must ingest building energy data from multiple sources into a strictly tenant-isolated data model.

**Requirements:**
- **Real smart-meter API integration:** Support direct, ongoing data ingestion from smart-meter and submeter providers via API (OAuth-based authentication where required), not only one-time file upload. This is a first-class ingestion path, not a stretch goal — recurring, low-friction data flow is what enables the continuous-monitoring value proposition (versus a one-time audit).
- **CSV upload:** Continue to support manual CSV upload for buildings or customers without API-accessible metering, with auto-detection of column mappings and graceful handling of malformed or incomplete files.
- **Per-tenant data isolation:** Every customer's building data, model artifacts, and findings must be logically (and where required by customer contract, physically) isolated from every other tenant's data. No query path, batch job, or model-training process may cross tenant boundaries without explicit, auditable authorization (e.g., an enterprise customer's own multi-building portfolio is one tenant; two unrelated customers are never co-mingled).
- **Building and portfolio modeling:** The data model must natively represent a tenant owning one or many buildings, each with one or many submeter circuits, supporting both the SME single-building case and the enterprise multi-building portfolio case without a schema migration between them.
- **Onboarding validation:** New data sources (API or CSV) must pass a validation and normalization step before being eligible for anomaly detection, surfacing data-quality issues to the customer rather than silently producing low-confidence findings.

### 5.2 Anomaly Intelligence Platform

**Capability:** Detect, validate, and explain energy waste with a multi-layer pipeline that replaces any single-model framing. This section defines what each layer must *guarantee to the user* — not its internal implementation.

The Anomaly Intelligence Platform is a seven-layer pipeline. A finding is not surfaced to a user until it has passed through all relevant layers; the layers exist precisely so that a flagged anomaly is something a facility manager — or an external auditor — can trust.

1. **Data Quality Gate.** Guarantees that no anomaly is computed on data the platform cannot vouch for. Must detect and quarantine data with insufficient coverage, implausible values, sensor dropout, or schema drift before it reaches detection logic, and must surface a clear data-quality status to the customer rather than silently degrading.
2. **Domain Rule Engine.** Guarantees that known, deterministic energy-waste patterns (e.g., after-hours HVAC operation, weekend vampire loads, scheduling violations against a building's declared occupancy profile) are caught even when they are too subtle, too rare, or too domain-specific for a general statistical model to reliably flag. This layer encodes building-operations domain knowledge directly, and its findings are not contingent on the ML layers below working correctly.
3. **STL Residual Detection.** Guarantees that anomalies are detected relative to a building's own seasonal and trend-decomposed baseline, not a naive raw-value threshold — so that a finding reflects "unusual for this building, this time of year, this day type," not just "a high number."
4. **ML Ensemble (Isolation Forest + Autoencoder).** Guarantees broad-spectrum anomaly coverage beyond what rule-based and decomposition-based layers catch, combining a tree-based outlier detector with a reconstruction-error-based detector so that the two methods' blind spots do not overlap.
5. **Drift Detection.** Guarantees that the platform notices, and surfaces to operations, when a building's underlying consumption pattern has fundamentally shifted (renovation, occupancy change, equipment replacement, seasonal regime change) such that the existing model baseline is no longer valid — preventing the platform from either silently degrading or burying the customer in stale-baseline false positives.
6. **Confidence Calibration (Conformal Prediction).** Guarantees that every finding ships with a statistically grounded confidence/uncertainty bound, not an arbitrary score. This is the layer that makes "we are not sure about this one" a first-class, honest output rather than a binary flag — directly supporting the trust requirement raised by both the enterprise sustainability officer and the ESG auditor personas.
7. **Root-Cause Attribution / Explainability (SHAP).** Guarantees that every surfaced finding can be decomposed into the specific features and signals that drove it, in language a non-technical facility manager can read and an auditor can inspect. This layer is the platform's connective tissue between detection and the compliance/research value proposition described in Sections 2, 4.4, and 7 — it is what turns "the model flagged this" into "here is why, specifically."

**Cross-layer requirement:** The pipeline must guarantee end-to-end traceability — for any finding surfaced to a user, it must be possible to reconstruct which layers fired, what evidence each contributed, and what the final confidence and explanation were, and to retain that record for the duration required by the audit-log retention policy (Section 6).

### 5.3 Optimization & Scenario Modeling

**Capability:** Translate detected waste into financially and physically grounded counterfactual scenarios.

**Requirements:**
- Model load-shifting scenarios (time-of-use tariff arbitrage), setpoint-adjustment scenarios (HVAC efficiency interventions), and, where applicable building data supports it, on-site generation offset scenarios (e.g., rooftop solar), with the scenario catalog designed to be extensible rather than fixed at three.
- Every scenario must report current versus optimized consumption and emissions, percentage reduction, estimated annualized cost savings, and simple payback period, with confidence bands rather than bare point estimates wherever the underlying estimate carries meaningful uncertainty.
- Savings estimates must be bounded to physically plausible ranges and validated against known reference cases before being shown to a customer; an implausible scenario output is a trust failure, not a minor bug.
- Scenario modeling must support both the single-building case and portfolio-level aggregation (e.g., "if these three interventions were rolled out across all buildings in this portfolio").

### 5.4 Explainability & Reporting

**Capability:** Surface root-cause attribution to the end user as a primary, persistent product surface — not an internal debugging tool.

**Requirements:**
- Every anomaly and every action-plan recommendation must be accompanied by a user-facing explanation of *why* it was flagged or recommended, derived directly from the Root-Cause Attribution layer (Section 5.2, Layer 7), expressed in plain language for operational users and in full technical detail (on demand) for compliance/audit users.
- Reporting must support both a continuously updated in-product view (for day-to-day operational use) and a generated, exportable report (for board presentations, ESG disclosure support, or external audit) — the exportable report is a downstream rendering of the same underlying explainability data, not a separately maintained artifact.
- Reports must be defensible: any number in a generated report must be traceable, on request, back to the underlying finding, its confidence calibration, and its root-cause attribution.

### 5.5 Continuous Learning

**Capability:** Treat the feedback loop as a first-class, core-UX product feature, not a backend afterthought.

**Requirements:**
- Facility managers and other operational users must be able to confirm or dismiss flagged anomalies and recommended actions directly within the primary workflow they already use to review findings — not in a separate, optional feedback form.
- Confirmation and dismissal data must feed back into the Anomaly Intelligence Platform (Section 5.2) to reduce false-positive rates over time, on a per-building and, where statistically appropriate, cross-building basis.
- The product must make the value of this loop visible to the user (e.g., a visible trend showing false-positive rate improving over time for their building), so that providing feedback is legibly worth the user's time, not an unrewarded chore.
- Feedback data is itself tenant-isolated data subject to the same privacy and access controls as raw building data (Section 6).

### 5.6 Platform & API

**Capability:** Support multi-tenant model management and external integrator consumption as core platform infrastructure.

**Requirements:**
- **Multi-tenant model registry:** The platform must maintain and version models per building (and, where appropriate, per portfolio), supporting independent retraining, rollback, and performance monitoring per model instance rather than a single global model shared indiscriminately across all tenants.
- **Per-building model versioning:** Every deployed model version must be traceable to the data it was trained on and the time window it covers, supporting both operational debugging and the audit-log retention requirement in Section 6.
- **Integrator-facing API contract:** Define, at the product-requirements level, the API surface integrator partners (Section 4.3) will consume — including authentication/authorization model, rate limits and tiering, versioning and deprecation policy, and the data contract for ingestion, findings retrieval, and scenario-modeling endpoints. The detailed technical API specification is an engineering deliverable, but the product-level commitments (what an integrator can rely on, and for how long) must be defined here.
- **Partner sandboxing:** Integrators must be able to develop and test against a sandboxed environment with synthetic or anonymized data before being granted production access to real tenant data.

---

## 6. Non-Functional Requirements

Non-functional requirements are promoted to a primary section because they did not exist as such in v1 and are now load-bearing for a paid, multi-tenant product.

**Multi-tenant data isolation and privacy:**
- Tenant data must be logically isolated at every layer of the stack (storage, processing, model artifacts, logs), with isolation enforced by the platform itself rather than relying solely on application-layer query discipline.
- Customer building data, which can reveal occupancy patterns and operational behavior, must be treated as sensitive operational data requiring access controls, encryption in transit and at rest, and a documented data-retention and deletion policy aligned to applicable data-protection regulation in each operating jurisdiction.

**Scalability targets:**
- The platform must support a growing number of buildings per tenant (from a single building up to large enterprise portfolios) and a growing number of tenants on shared platform infrastructure, with capacity planning and load testing defined against concrete near-term and one-year-out targets to be set jointly by Product and Engineering before general availability.

**Model drift monitoring (ongoing operational requirement):**
- Drift detection (Section 5.2, Layer 5) must be monitored as an ongoing platform-health metric, not only as a per-building feature — Engineering and Data Science must have visibility into aggregate drift rates across the tenant base to detect systemic data-quality or model-staleness issues before they erode customer trust at scale.

**Audit-log retention for regulatory defensibility:**
- All findings, confidence scores, explanations, model versions, and user confirmation/dismissal actions must be retained in an immutable or tamper-evident audit log for a retention period sufficient to support customer ESG assurance and regulatory review cycles (specific retention duration to be finalized with Legal/Compliance, informed by the regulatory landscape in Section 2.4).

**Uptime / SLA targets appropriate to a paid product:**
- The platform must define and meet uptime commitments appropriate to its role in customer compliance and operational workflows, with tiered SLA commitments differentiated between self-serve/freemium and contracted enterprise tiers.
- Latency targets for specific user-facing operations (e.g., time from data upload or sync to first findings surfaced) remain a meaningful UX commitment, but are one operational metric among several defined in Section 8 — not the platform's headline success criterion.

---

## 7. Research Contribution Requirements

The research track is a primary deliverable of this PRD, not a footnote to the product.

**7.1 The Novel Claim**

CarbonSense's research contribution is graph-aware anomaly localization: modeling a building's submeter circuit topology as a graph (nodes = circuits/meters, edges = electrical or spatial relationships between them) and applying a graph neural network (GNN) to localize the source of an anomaly within that topology — as opposed to treating each submeter's time series independently, as topology-agnostic baseline methods do.

**7.2 Baseline Comparison**

The research must benchmark the GNN approach against the following baselines, all evaluated on the same fault-localization task:
- Isolation Forest (the ensemble baseline already in production, Section 5.2 Layer 4)
- Autoencoder reconstruction-error detection (also in production, Section 5.2 Layer 4)
- STL-residual decomposition detection (also in production, Section 5.2 Layer 3)
- The proposed GNN, using submeter topology as structural input

Because COMBED (the primary research dataset; see 7.4) has no labeled ground truth for real building faults, evaluation must be conducted via **synthetic fault injection**: programmatically injecting realistic fault signatures (e.g., simulated equipment degradation, stuck sensors, abnormal load patterns) into known circuits within the COMBED topology, then measuring each method's ability to correctly localize the injected fault's true source circuit — not just to flag that *some* anomaly occurred in the building.

**7.3 What "Publishable" Means as an Acceptance Criterion**

For the research output to be considered complete against this PRD, it must meet a bar consistent with submission to a relevant peer-reviewed venue (e.g., an IEEE conference or workshop in smart buildings, applied ML for sustainability, or fault detection and diagnosis). Concretely, that means:
- A clearly articulated, novel methodological contribution (the graph-aware localization approach), positioned explicitly against existing building fault-detection-and-diagnosis (FDD) literature so reviewers can assess incremental novelty.
- A rigorous, reproducible evaluation methodology (the synthetic fault-injection protocol) with results reported against all baselines in 7.2, including honest reporting of cases where the GNN does *not* outperform a baseline.
- A frank, explicit discussion of the dataset limitation (7.4) and the steps taken to mitigate it, rather than an attempt to understate it.
- Internal review by someone with relevant ML/research methodology expertise before external submission, checking the evaluation protocol for leakage, overfitting to the single instrumented building, and statistical validity of the comparison.

**7.4 Honest Statement of the Data Limitation**

The primary dataset, COMBED (IIT Delhi), is **one instrumented building with 200+ submeter circuits over roughly a month of data — not a multi-building dataset.** This is a structural fact that shapes the data architecture and the research design; it is not a temporary hackathon constraint to be waved away once "real" data arrives.

This has two direct consequences the research methodology must address head-on:
- **Generalization risk:** A method validated on one building's topology may not generalize to buildings with materially different electrical layouts, equipment mixes, or occupancy patterns. The research write-up must state this limitation explicitly rather than imply broader validation than the data supports.
- **Mitigation strategy:** The methodology should address this limitation through (a) the synthetic fault-injection protocol described in 7.2, which allows many more *evaluation* scenarios than the one building's natural variation alone would provide, and (b) where feasible, transfer learning — pretraining representations on a larger public non-intrusive load monitoring (NILM) dataset before fine-tuning or evaluating on COMBED's topology, to reduce the degree to which the method's learned representations are purely an artifact of one building's idiosyncrasies.

**7.5 Path to Production**

If the GNN approach clears the publishable bar and demonstrates a meaningful localization improvement over the production baselines, it becomes a candidate addition to the Root-Cause Attribution layer (Section 5.2, Layer 7) for tenants whose buildings have sufficiently rich submeter topology data to make graph-based localization meaningful — this is the Year 2 product/research convergence point referenced in Section 3. Buildings without sufficient submeter granularity continue to be served by the existing topology-agnostic layers without degradation.

---

## 8. Business Model & Success Metrics

### 8.1 Pricing Model Hypothesis

- **Freemium entry (SME, single building):** Free tier with a limited data-history window and a capped number of monthly action-plan refreshes, designed to demonstrate clear value (identified waste, a usable action plan) before asking for payment.
- **Paid tiers (SME/mid-market):** Per-building monthly or annual subscription unlocking continuous monitoring, full history, unlimited action-plan refreshes, and the continuous-learning feedback loop at full strength.
- **Enterprise tier (multi-building portfolio):** Annual contract priced on portfolio size and feature scope (multi-building rollups, advanced compliance/audit features, dedicated support), sold through a direct enterprise motion.
- **Platform/API tier (integrators):** Usage-based or seat-based pricing for partner access to the integrator-facing API (Section 5.6), positioned as a second, structurally different revenue line from the destination-product subscriptions above.

### 8.2 Unit Economics Assumptions (to be validated)

- Per-tenant infrastructure cost (data storage, model training/inference compute, API serving) must be modeled explicitly per pricing tier, since the multi-tenant model registry (Section 5.6) means cost scales with both buildings *and* tenants, not buildings alone.
- Customer acquisition cost (CAC) and payback period assumptions should be modeled separately for the self-serve SME motion versus the direct enterprise sales motion, given their materially different sales cycles and price points.
- Gross margin assumptions should explicitly account for LLM/API inference costs (for narrative generation and reporting) and ML training/inference costs (for the seven-layer detection pipeline) as variable costs that scale with usage, not fixed costs.

### 8.3 Pilot Customer Targets

- Define a near-term pilot cohort spanning both buyer segments (a small number of SME single-building pilots and at least one enterprise multi-building portfolio pilot) to validate both the freemium-to-paid conversion hypothesis and the enterprise sales motion before broader go-to-market investment.
- Pilot success should be defined jointly on product metrics (engagement with the feedback loop, conversion from free to paid) and qualitative trust signals (would the customer's facilities or sustainability lead put this report in front of their own leadership or an external auditor).

### 8.4 Model Performance SLAs

- **False-positive rate ceiling:** Define and enforce a maximum acceptable false-positive rate for surfaced anomalies, monitored on an ongoing basis via the continuous-learning feedback loop (Section 5.5) and treated as a platform-health metric, not a one-time launch gate.
- **Detection latency:** Define a target latency from new data arrival to findings being available to the user, calibrated separately for the real-time API ingestion path versus the batch CSV-upload path. (As noted in Section 6, this is one operational SLA among several — not the platform's headline metric.)

### 8.5 Research Milestones (Separate Metrics Track)

Research milestones are tracked independently from business metrics, since they are evaluated against academic and methodological standards rather than commercial ones:
- Target venue identification and submission-window planning (a specific IEEE conference/workshop track and deadline) should be set jointly by the research lead and Product once the baseline comparison (Section 7.2) produces credible preliminary results.
- Progress should be milestone-tracked against the acceptance-criteria checklist in Section 7.3, with an explicit go/no-go review before committing to a specific submission deadline.

---

## 9. Assumptions & Constraints

**Data privacy and regulatory assumptions:**
- The platform must be designed to comply with applicable data-protection regulation in each jurisdiction where it operates customer data (e.g., India's data-protection framework, and relevant regional frameworks for any customer operating in the EU or elsewhere), with the specific compliance posture confirmed by Legal before each new geography's general availability.
- Building energy data, while not classically "personal data" in most frameworks, can reveal occupancy and operational patterns and should be handled with privacy-conscious defaults even where not strictly legally mandated.

**Expected customer data volume:**
- The platform must be architected to handle a wide range of per-tenant data volume — from a single SME building with coarse-grained billing data up to an enterprise portfolio with hundreds of high-frequency submeter circuits per building (informed directly by the COMBED reality of 200+ circuits in a single instrumented building, Section 7.4) — without requiring a different underlying data architecture for each case.

**Model retraining cadence:**
- Per-building and per-tenant models should be retrained on a defined cadence informed by observed drift rates (Section 6) rather than a fixed calendar schedule alone, with drift detection (Section 5.2, Layer 5) acting as the trigger for out-of-cycle retraining when needed.

**Infrastructure cost assumptions:**
- The platform is built on paid cloud and AI-API infrastructure appropriate to a production SaaS product; "free tier only" is no longer an architectural constraint. Infrastructure cost modeling should inform the unit-economics assumptions in Section 8.2, with cost-per-tenant tracked as a first-class operating metric from early pilots onward.

---

## 10. Risks

**Risk: Data privacy / multi-tenancy breach.**
A failure of tenant data isolation (Section 6) would be catastrophic for a product whose core value proposition depends on customer trust, particularly for enterprise and compliance-facing customers. Mitigation requires isolation enforced at the platform layer (not just application logic), regular access audits, and incident-response planning treated as a launch-blocking requirement, not a post-launch improvement.

**Risk: Model drift across heterogeneous building types.**
As the customer base diversifies beyond the buildings the detection pipeline was originally tuned against, drift may manifest differently across building types (office vs. retail vs. mixed-use) in ways a single global drift threshold won't catch. Mitigation requires per-building-type validation as new segments are onboarded, not just per-building drift monitoring.

**Risk: Cold-start for new buildings with no history.**
A newly onboarded building has no baseline, making several detection layers (notably STL Residual Detection and the ML Ensemble) unreliable until sufficient history accumulates. Mitigation requires an explicit cold-start mode that leans more heavily on the Domain Rule Engine (Section 5.2, Layer 2) and communicates reduced confidence to the user honestly, rather than producing falsely confident findings on day one.

**Risk: Customer trust failure if explainability is weak.**
Given that explainability is positioned as the core differentiator (Sections 2.3, 4.4), any gap between what the Root-Cause Attribution layer promises and what it can actually deliver in edge cases is a disproportionately damaging risk — it undermines the specific claim the product is built around. Mitigation requires explicit handling (and honest communication) of cases where attribution confidence is low, rather than always producing a confident-sounding explanation.

**Risk: IEEE reviewer novelty risk.**
Graph-based and topology-aware approaches to building fault detection are an active research area; the contribution in Section 7 must be positioned with a clear, specific delta against existing FDD literature, or it risks being assessed as incremental. Mitigation requires a thorough literature review before committing to a submission timeline, and a willingness to sharpen or reframe the specific claim if the delta against prior work proves smaller than hoped.

**Risk: Dataset limitation undermining research credibility.**
The single-building, ~1-month COMBED dataset (Section 7.4) is a real constraint a reviewer will scrutinize closely. Mitigation requires the synthetic fault-injection and transfer-learning strategies in Section 7.4 to be methodologically sound enough to withstand that scrutiny, plus complete transparency about the limitation in any write-up rather than minimizing it.

---

## 11. Open Questions

| # | Question |
|---|---|
| OQ-1 | What is the final pricing tier structure (freemium thresholds, per-building price points, enterprise contract structure) and who owns that decision? |
| OQ-2 | Which compliance certifications (e.g., SOC 2, ISO 27001) does v1 of the production platform need before enterprise customers will sign, and on what timeline? |
| OQ-3 | What is the minimum viable labeled/synthetic dataset size and evaluation protocol needed before the GNN research contribution can be submitted for external review? |
| OQ-4 | Which smart-meter API providers should be prioritized for the first wave of real-time ingestion integrations, and in which geographies? |
| OQ-5 | What is the target data-retention period for the audit log (Section 6), and does it vary by jurisdiction or customer contract? |
| OQ-6 | Should the integrator-facing API (Section 5.6) launch with a self-serve developer sandbox, or gated partner-by-partner access for the first cohort? |
| OQ-7 | What is the go/no-go threshold for deciding the GNN method is ready to move from research benchmark to production candidate (Section 7.5)? |
| OQ-8 | Which specific IEEE venue and submission window should the research track target, and what is the latest date that decision needs to be locked to hit it? |
| OQ-9 | How should pricing and packaging differ, if at all, between the SME freemium-to-paid motion and the integrator/API motion, given they may eventually compete for the same end customer's attention? |

---

## Appendix: Migration Map

This table maps every section and major requirement from PRD v1.0 to its location in v2.0, or states explicitly why it was removed. Every v1 item appears exactly once.

| v1 Section / Requirement | Where it lives in v2 (or "removed, see reason") |
|---|---|
| §1 Executive Summary (hackathon framing, 90-second pipeline headline) | Rewritten as §1 Executive Summary; the 90-second figure is removed as a headline metric — see §6 latency note and §8.4 detection-latency SLA, where latency becomes one operational target among several |
| §2 Problem Statement & Why Now — Scale, Data gap, Access gap, SME blind spot, India-specific table | Carried forward and expanded into §2.1 The Core Problem |
| §2 Why Now — regulatory push (India EC Amendment Act 2022) | Carried forward into §2.4 Regulatory Tailwinds, with added EU regulatory context and a compliance-review caveat |
| §2 Why Now — data availability (COMBED, ETH Zurich ECO) | COMBED's single-building, ~1-month reality reframed as a structural data-architecture fact in §7.4 and §9, not a temporary constraint; ETH Zurich ECO dataset is not carried forward as a named requirement — removed, see reason: v1 used it only as "supplementary validation," and v2's data architecture (§9) is designed to be source-agnostic rather than naming a fixed secondary dataset |
| §2 Why Now — LLM maturity / NarratorAgent narrative claim | Reframed without the "NarratorAgent" agent-naming convention into §5.4 Explainability & Reporting's plain-language explanation requirement |
| §2 Why Now — "no multi-agent competitor exists" claim | Removed, see reason: reframed as a substantive competitive-positioning analysis in §2.3 Competitive Landscape (EnergyHub, Siemens, Schneider, IBM Envizi) rather than an architecture-novelty claim |
| §3 Primary Persona — Rajan, SME Facility Manager | Carried forward and expanded into §4.1 SME Facility Manager — "Operational Owner" |
| §3 Secondary Persona — Priya, building owner seeking peer benchmarking | Folded into §4.2 Enterprise Sustainability Officer's portfolio-benchmarking needs; the standalone "green marketing" framing is removed, see reason: peer/portfolio benchmarking is now a multi-building enterprise capability (§5.1, §6 scalability), not a single-owner marketing use case |
| §3 Out-of-Scope Personas — large enterprise portfolio managers | Removed from out-of-scope; now §4.2 Enterprise Sustainability Officer, a primary persona |
| §3 Out-of-Scope Personas — residential users | Removed, see reason: residential remains out of scope for v2 as well; the platform's data model, tenancy model, and personas are all built around commercial/enterprise buildings, and no v2 requirement contemplates residential users |
| §3 Out-of-Scope Personas — municipal government procurement | Removed, see reason: not addressed in v2; municipal/government procurement as a buyer segment is not in scope for this PRD and would require separate market and sales-motion analysis not undertaken here |
| §4 Goals — CSV/sample building upload | Carried forward into §5.1 Data Ingestion & Multi-Tenancy (CSV upload requirement); the "3-5 pre-loaded sample buildings" framing is removed, see reason: sample-building fallback was a demo-specific convenience, superseded by real onboarding and validation flows |
| §4 Goals — visualize 4 agents in real time | Removed, see reason: "watching agents light up" was a demo-credibility device; v2 replaces it with substantive trust mechanisms (confidence calibration, root-cause attribution, audit logs) defined in §5.2, §5.4, and §6 |
| §4 Goals — detect ≥3 waste categories | Carried forward and superseded by the full seven-layer detection guarantee in §5.2 |
| §4 Goals — model ≥2 counterfactual scenarios | Carried forward and expanded (extensible scenario catalog) into §5.3 Optimization & Scenario Modeling |
| §4 Goals — downloadable PDF action plan | Carried forward into §5.4 Explainability & Reporting as one rendering of the underlying explainability data, no longer the sole output format |
| §4 Goals — ≤90-second end-to-end demo SLA | Removed as headline metric, see reason: explicitly instructed to demote; reappears only as one latency target among several in §6 and §8.4 |
| §4 Goals — zero paid dependencies / free-tier-only | Removed, see reason: explicitly instructed to delete; superseded by §9 Infrastructure cost assumptions, which assumes paid production infrastructure |
| §4 Non-Goals — real-time smart meter API integration | Moved into scope; now a first-class requirement in §5.1 Data Ingestion & Multi-Tenancy |
| §4 Non-Goals — multi-building portfolio dashboard | Moved into scope; now addressed throughout §5.1, §5.6, §6, and §4.2 |
| §4 Non-Goals — user authentication / accounts | Moved into scope; implicit in §5.1 per-tenant data isolation and §5.6 integrator authentication/authorization requirements |
| §4 Non-Goals — carbon credit generation/registry integration | Moved into scope; now addressed in §3 Year 3 roadmap narrative (ecosystem integration with carbon credit marketplaces) |
| §4 Non-Goals — IoT sensor hardware | Removed, see reason: remains out of scope in v2 as well; CarbonSense remains hardware-agnostic and does not manufacture or require proprietary sensors — no v2 section reverses this |
| §4 Non-Goals — mobile app | Removed, see reason: not addressed in v2; web-first remains the assumed delivery surface and mobile is not evaluated in this document |
| §4 Non-Goals — production-grade security / data privacy | Moved into scope; now a primary requirement throughout §6 Non-Functional Requirements |
| §4 Non-Goals — fine-tuned ML models | Superseded; §5.2's seven-layer architecture (including a trainable ML Ensemble and per-building model registry in §5.6) supersedes the "pre-trained models are sufficient" framing entirely |
| §5 User Stories US-01 (Upload & Validate) | Carried forward into §5.1 onboarding validation requirement |
| §5 User Stories US-02 (Sample Building Fallback) | Removed, see reason: judge-demo-specific convenience with no equivalent enterprise/SME need; superseded by real onboarding flows |
| §5 User Stories US-03 (Live Agent Visibility) | Removed, see reason: demo-credibility device superseded by substantive trust mechanisms (confidence calibration, audit logs) per §5.2 and §6 |
| §5 User Stories US-04 (Waste Detection with timestamps/cost) | Carried forward into §5.2 Anomaly Intelligence Platform layer guarantees |
| §5 User Stories US-05 (Counterfactual Savings) | Carried forward into §5.3 Optimization & Scenario Modeling |
| §5 User Stories US-06 (PDF Action Plan) | Carried forward into §5.4 Explainability & Reporting |
| §5 User Stories US-07 (Carbon Benchmark vs. peers) | Carried forward into §4.2 Enterprise Sustainability Officer persona and §5.1 multi-building data modeling (portfolio/peer comparison) |
| §5 User Stories US-08 (Plain-Language Narrative) | Carried forward into §5.4 Explainability & Reporting plain-language requirement |
| §6.1 SensorAgent (ingestion, normalization, derived signals) | Functionality carried forward into §5.1 Data Ingestion & Multi-Tenancy; the "SensorAgent" agent-naming convention is dropped per instruction to organize by platform capability, not by agent |
| §6.2 AnomalyAgent (single Isolation Forest + rule-based detection) | Fully superseded by the seven-layer Anomaly Intelligence Platform in §5.2 — explicitly replacing the single-model framing per instruction |
| §6.3 OptimizerAgent (load shifting, setpoint, solar scenarios) | Functionality carried forward into §5.3 Optimization & Scenario Modeling; "OptimizerAgent" naming dropped |
| §6.4 NarratorAgent (LLM narrative + action plan generation) | Functionality carried forward into §5.4 Explainability & Reporting; "NarratorAgent" naming dropped; the schema-validated 10-action-plan structure is generalized rather than fixed at exactly 10 |
| §6.5 Dashboard (Streamlit-specific UI, agent progress panel) | Removed as a named implementation (Streamlit, agent progress panel), see reason: v2 is implementation-agnostic at the PRD level; the underlying user-facing capabilities (results views, anomaly tables, scenario comparisons, action-plan display) are carried forward into §5.2–§5.4 as capability requirements, not UI-framework-specific designs |
| §6.6 Report Engine (WeasyPrint PDF, page-by-page spec) | Removed as a named implementation (WeasyPrint, fixed 4–6 page spec), see reason: carried forward at the requirements level only into §5.4 Explainability & Reporting; specific report layout is an engineering/design deliverable, not a PRD-level constraint |
| §7 Hackathon Demo Metrics table (full table) | Removed in its entirety, see reason: explicitly instructed to delete hackathon-specific success metrics; superseded by §8 Business Model & Success Metrics |
| §7 Real-World Impact Metrics table | Carried forward and reframed (with hedged, logic-based rather than asserted figures) into §2.2 Market Sizing Logic and §8 Business Model & Success Metrics |
| §8 Data Assumptions (COMBED, ETH Zurich, CO2Signal API) | COMBED assumption carried forward into §7.4 and §9; ETH Zurich and CO2Signal-specific assumptions removed, see reason: these were demo-specific data-source choices; v2's data architecture (§9) is designed to be source-agnostic rather than naming fixed third-party datasets/APIs |
| §8 Technical Constraints (free tiers, Streamlit Cloud, Claude API call limits, no paid infra) | Removed in its entirety, see reason: explicitly instructed to delete "free tier only" framing; superseded by §9 Infrastructure cost assumptions, which assumes paid production infrastructure |
| §8 Timeline Constraints (Day 1/3 hard cutoffs, Day 4 polish-only) | Removed in its entirety, see reason: explicitly instructed to delete all hackathon Day 1–4 language; no equivalent v2 section, as production roadmap timing is addressed at the strategic level in §3, not as build-day cutoffs |
| §9 Risk 1 — COMBED dataset gaps/format inconsistencies | Reframed as the broader data-quality concern addressed structurally by §5.2 Layer 1 (Data Quality Gate) and the honest data-limitation discussion in §7.4 |
| §9 Risk 2 — Claude API latency/rate limit during demo | Removed, see reason: demo-specific risk tied to the deleted 90-second SLA and judging context; no equivalent production risk is carried forward, as production LLM/API reliability is an engineering SLA concern (§6, §8.4), not a top-level product risk |
| §9 Risk 3 — CrewAI/LangGraph version incompatibilities | Removed, see reason: implementation-framework risk, not a product-requirements-level concern; PRD v2 does not specify or depend on a named orchestration framework |
| §9 Risk 4 — OptimizerAgent unrealistic/negative savings estimates | Carried forward into §5.3's requirement that savings estimates be bounded and validated, and into the Risks section as the "customer trust failure if explainability is weak" risk in §10 |
| §9 Risk 5 — PDF generation failure (WeasyPrint dependency) | Removed, see reason: implementation-specific (WeasyPrint/Streamlit Cloud) risk; not a product-requirements-level concern in v2 |
| §9 Risk 6 — team coordination bottleneck at agent integration point | Removed, see reason: a 4-day hackathon team-process risk with no equivalent in a production PRD; team coordination is an engineering-management concern, not a product risk to be documented here |
| §10 Open Questions OQ-1 through OQ-8 (schema, sample buildings, API choice, tariff defaults, deployment fallback, Day 1–3 deadlines) | Removed in their entirety, see reason: every original open question was either a hackathon build-logistics decision (deadlines, team ownership, deployment fallback) or has been resolved/superseded by becoming a firm v2 requirement (e.g., inter-agent schema is superseded by the data architecture in §5.1–§5.2); new open questions appropriate to this scope are defined fresh in §11 |
| Appendix: Team Responsibility Matrix (4-person hackathon team roles) | Removed in its entirety, see reason: hackathon team-staffing artifact with no equivalent in a production company PRD; organizational structure and role ownership are an operating-model decision for leadership, not a PRD appendix |

