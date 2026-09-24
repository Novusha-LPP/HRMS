# HRMS Platform: pre-implementation docs

Architecture analysis for building the SURAJ Group HRMS requirements (v2.0, 17 Sep 2026) as a multi-tenant enterprise platform. SURAJ Group is the first tenant. Performance/KPI is excluded from this analysis.

The same content, plus design tokens, component styles and live previews, is published as the design system artifact: https://claude.ai/artifact/8aT6uK81pa21ku7f1H2Zjv

| File | Contents |
|---|---|
| [architecture/01-overview.md](architecture/01-overview.md) | Conclusions, principles, requirement-to-mechanism map, suggested stack |
| [architecture/02-requirements-analysis.md](architecture/02-requirements-analysis.md) | Module-by-module analysis, findings, gaps, phasing issues |
| [architecture/03-tenancy-isolation-deployment.md](architecture/03-tenancy-isolation-deployment.md) | Tenant definition, isolation tiers and mechanics, shared resources, control plane, regions, tenant lifecycle |
| [architecture/04-organization-people-history.md](architecture/04-organization-people-history.md) | Organisation dimensions, person/employment/assignment, personnel actions, effective dating |
| [architecture/05-identity-access-security.md](architecture/05-identity-access-security.md) | Identity, authorization layers, data classes, audit, security, DPDP |
| [architecture/06-configuration-workflow-rules.md](architecture/06-configuration-workflow-rules.md) | Configuration layers, workflow engine, obligations, exceptions, notifications, extensibility |
| [architecture/07-application-data-integration-scale.md](architecture/07-application-data-integration-scale.md) | Modular monolith, data, payroll input contract, integrations, scalability |
| [architecture/08-assumptions-risks-decisions.md](architecture/08-assumptions-risks-decisions.md) | Assumptions, risks, scalability concerns, future expansion, decisions, revised phasing |
| [ui/](ui/) | Tenant theming, terminology and locale, status vocabulary, restricted data on screen |

Section references such as §12 point to the requirements document.

## System design

[system-design/README.md](system-design/README.md) is the complete system design for the platform and the public API product: capability map, containers, data model, events, integrations, API standards and catalogue, AWS topology, delivery, security, technology stack and roadmap. Diagrams are in [system-design/diagrams/](system-design/diagrams/), and the Mermaid diagrams render on GitHub. Published version: https://claude.ai/artifact/F7VaQJo7B7Sd5sD7qFhSbZ
