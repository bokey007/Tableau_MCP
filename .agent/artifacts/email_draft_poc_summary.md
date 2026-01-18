# Email Draft: AI-Powered Analytics POC Summary & Next Steps

---

**To:** Ragi  
**From:** Bokey Deshmukh  
**Subject:** AI-Powered Analytics for Patient Data - POC Complete, Seeking Approval to Proceed  
**Date:** January 13, 2026

---

## Executive Summary

I'm pleased to share that the Proof of Concept (POC) for an **AI-powered natural language analytics assistant** has been successfully completed. This solution enables business users to ask questions in plain English and receive instant insights from their data—eliminating the need for SQL knowledge or manual report requests.

This email outlines two architectural approaches we've explored, their trade-offs, and seeks your approval to proceed to the next phase with patient data in the enterprise environment.

---

## Two Approaches Compared

### Approach 1: Data Landing Zone (Previously Implemented for OCTOPODA/Digital Data)

**Architecture:**

```
AWS Redshift (OCTOPODA) → S3 Export → PostgreSQL Landing Zone → Text-to-SQL Engine → AI Agent
```

**How it works:**

- Data from the OCTOPODA environment (AWS Redshift) is exported to S3 on a scheduled basis
- S3 data is loaded into an intermediate PostgreSQL database ("landing zone")
- A Text-to-SQL engine converts natural language questions into SQL queries
- The AI agent executes queries against this landing zone and presents results

**Why this approach was taken:**

- Direct database access to OCTOPODA's Redshift was not possible
- The Digital data was not sensitive, allowing storage in an intermediate zone
- Provided complete control over the data model and query performance

**Strengths:**

- ✅ Full SQL flexibility (complex joins, window functions, CTEs)
- ✅ No API rate limits
- ✅ Complete control over data refresh cadence
- ✅ Predictable performance

**Trade-offs:**

- ⚠️ Data latency (depends on ETL schedule)
- ⚠️ Requires maintaining an additional database infrastructure
- ⚠️ Not suitable for sensitive/governed data

---

### Approach 2: Tableau MCP + AI Agent (Current POC for Patient Data)

**Architecture:**

```
Tableau Cloud (Connected to PERSIST) ← VizQL Data Service API ← MCP Server ← AI Agent
```

**How it works:**

- The AI agent connects to Tableau Cloud via the **Model Context Protocol (MCP) Server**
- Tableau's **VizQL Data Service API** executes queries against published datasources
- All data governance, row-level security, and access controls defined in Tableau are automatically enforced
- No data leaves the Tableau environment—queries are executed in-place

**Why this approach is necessary for patient data:**

- Patient data resides in the highly governed **PERSIST** system
- Creating a landing zone copy is not permitted due to PHI regulations
- Tableau is already the authorized analytics layer with proper security controls
- This approach queries data **in place** without creating copies

**Strengths:**

- ✅ No data duplication—respects data governance requirements
- ✅ Inherits Tableau's row-level security and permissions
- ✅ Works with existing Tableau datasources and workbooks
- ✅ Can be embedded directly into Tableau dashboards via Extensions API
- ✅ Real-time data (as fresh as Tableau's connection)

**Trade-offs:**

- ⚠️ API rate limits (100 queries/hour per Creator license)
- ⚠️ Limited query complexity (no advanced table calculations like LOOKUP, RUNNING_SUM)
- ⚠️ Dependent on Tableau Cloud availability and performance
- ⚠️ Requires Tableau-specific configuration (Connected Apps, VizQL API enablement)

---

## Technical Requirements for Approach 2

The following must be enabled/configured in **Tableau Cloud** for this solution to work:

### 1. Tableau Cloud License Requirements

| Requirement           | Details                                                              |
| --------------------- | -------------------------------------------------------------------- |
| **Creator Licenses**  | Required for API access. Each Creator adds 100 queries/hour capacity |
| **Site Admin Access** | Needed for initial configuration                                     |

### 2. Tableau Cloud Configuration

| Setting                           | Location                                               | Purpose                                                  |
| --------------------------------- | ------------------------------------------------------ | -------------------------------------------------------- |
| **Connected Apps (Direct Trust)** | Settings → Connected Apps                              | Enables secure JWT-based authentication for the AI agent |
| **VizQL Data Service API**        | Must be enabled on the site                            | The API that executes queries against datasources        |
| **Published Datasources**         | Must exist and be accessible to the Connected App user | The data the AI agent can query                          |

### 3. Network & Security

| Requirement                   | Details                                                     |
| ----------------------------- | ----------------------------------------------------------- |
| **Outbound HTTPS (443)**      | The AI agent must be able to reach `*.online.tableau.com`   |
| **Connected App Credentials** | Client ID, Secret ID, Secret Value must be securely stored  |
| **Service Account**           | A dedicated Tableau user for the AI agent (for audit trail) |

### 4. Infrastructure for AI Agent

| Component                      | Purpose                                                  |
| ------------------------------ | -------------------------------------------------------- |
| **OpenShift/Kubernetes**       | Host the AI Agent backend and MCP server                 |
| **PostgreSQL**                 | Store query history and user feedback (not patient data) |
| **OpenAI API or Azure OpenAI** | LLM for natural language understanding                   |

---

## Known Limitations of Approach 2

I want to set clear expectations about what this approach can and cannot do:

### Query Limitations

| Limitation                | Impact                                              | Workaround                                               |
| ------------------------- | --------------------------------------------------- | -------------------------------------------------------- |
| **No Table Calculations** | LOOKUP, RUNNING*SUM, WINDOW*\* not supported        | Compute in analysis layer or pre-calculate in datasource |
| **No LOD Expressions**    | FIXED, INCLUDE, EXCLUDE LOD not available via API   | Pre-aggregate in datasource definition                   |
| **No Blending**           | Cannot blend multiple datasources in a single query | Create unified datasource in Tableau                     |
| **Max 100K rows**         | Single query result limited to 100,000 rows         | Aggregate data before retrieval                          |

### Performance Limitations

| Limitation                   | Impact                             | Mitigation                                   |
| ---------------------------- | ---------------------------------- | -------------------------------------------- |
| **100 queries/hour/Creator** | Heavy usage can hit rate limits    | Add more Creator licenses; implement caching |
| **Query timeout ~2 min**     | Complex queries may fail           | Simplify datasource, add extracts            |
| **Cold start latency**       | First query of the day may be slow | Health check ping on schedule                |

### Security Considerations

| Consideration           | Current State                         | Recommendation                    |
| ----------------------- | ------------------------------------- | --------------------------------- |
| **PHI in Prompts**      | User questions may contain PHI        | Sanitization layer implemented    |
| **Audit Logging**       | Query history stored locally          | Integrate with enterprise logging |
| **User Authentication** | Prototype uses shared service account | Integrate SSO for production      |

---

## POC Results Summary

| Metric                        | Result                                                   |
| ----------------------------- | -------------------------------------------------------- |
| **Functional Success Rate**   | 56/56 questions (100%)                                   |
| **Quality Score (LLM-Judge)** | 7.11/10 average                                          |
| **Avg Response Time**         | ~15-25 seconds                                           |
| **Categories Tested**         | Top-N, Aggregations, Filters, Time Series, Complex, Chat |

The solution successfully handles:

- "Who are the top 5 customers by sales?"
- "Show me sales trend since 2020"
- "Which products are losing money?"
- "Compare Technology vs Furniture sales by region"
- Conversational interactions ("Hello", "What can you do?")
- Ambiguous questions (asks for clarification instead of guessing)

---

## Next Steps (Pending Approval)

With your go-ahead, the proposed next steps are:

### Phase 1: Environment Setup (1-2 weeks)

- [ ] Configure Connected App in BI Tableau Cloud environment
- [ ] Deploy AI Agent to OpenShift (non-prod initially)
- [ ] Establish connectivity to Tableau Cloud from OpenShift
- [ ] Set up Azure OpenAI (or confirm OpenAI usage for enterprise)

### Phase 2: KPI Selection & Data Preparation (1 week)

- [ ] Identify 5 key patient analytics KPIs with the business team
  - Suggested starting points: Readmission rates, Length of stay, Patient outcomes, Resource utilization, Cost per encounter
- [ ] Ensure corresponding Tableau datasources are published and accessible
- [ ] Configure row-level security for POC user group

### Phase 3: POC Demonstration (1 week)

- [ ] Build working demo with selected KPIs
- [ ] Conduct demo with stakeholders
- [ ] Collect feedback and identify gaps

### Phase 4: Scale-Up Planning (Following Demo)

- [ ] Assess Tableau license requirements for production scale
- [ ] Plan Tableau Extension integration for dashboard embedding
- [ ] Define production security and audit requirements
- [ ] Create roadmap for broader rollout

---

## Request

I am seeking your explicit **go-ahead signal** to proceed with the next steps outlined above. Please let me know if you have any questions or concerns about the approach, limitations, or timeline.

Happy to schedule a call to walk through the technical details or demo the current POC on the Superstore sample data.

---

**Best regards,**  
Bokey Deshmukh

---

_Attachments:_

- GitHub Repository: https://github.com/bokey007/Tableau_MCP
- Regression Test Results: regression_data_20260113_105009.xlsx
