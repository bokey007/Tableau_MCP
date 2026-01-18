# Email Draft: AI Analytics POC - Strategy & Go-Forward Plan

---

**To:** Ragi  
**From:** Bokey Deshmukh  
**Subject:** Approval Request: Proceeding with AI-Powered Analytics for Patient Data (POC Complete)

---

Following the successful completion of our technical feasibilty study, I am seeking your approval to move forward with implementing AI-powered natural language analytics for patient data in BI env.


**Approach 1: The "Landing Zone" Model (Used for OCTOPODA/Digital Data)**

- **How it worked:** Data was exported from Redshift to S3, then loaded into an intermediate PostgreSQL "Landing Zone" for analysis.
- **Why it worked:** The data was not sensitive; the landing zone allowed for high-performance, complex SQL query generation and customisation. The soulution was flexible, reliable and scalable.
- **Limitation:** This model is **not permissible for Patient Data** as it involves creating secondary copies of PHI outside of highly governed systems.

**Approach 2: The "Tableau-Native" Model (Proposed for PERSIST/Patient Data)**

- **How it works:** The AI Agent communicates directly with Tableau Cloud via the **Model Context Protocol (MCP)**.
- **Goverance Advantage:** This enables **in-place analysis**. No PHI data is ever copied or moved. The agent inherits all existing Tableau security, permissions, and Row-Level Security (RLS) automatically.
- **POC Status:** Verified with a **100% functional success rate** (56/56 test cases passed) using native integration.

---

### 2. Requirements & Limitations for Approach 2

To ensure success with this native approach, we must manage the following technical guardrails:
 
**Enablement Requirements:** (OPS team must support on this)

- **Tableau Config:** Enabling "Connected Apps (Direct Trust)" and "VizQL Data Service API" in our BI environment.
- **Infrastructure:** Leveraging the **ARES environment** (as per Greg's guidance) to host the Agent locally.
- **LLM Access:** Secure access to Azure OpenAI (or standard OpenAI) for the intelligence layer.

**Known Limitations & Expectations:**

- **API Quotas:** Tableau limits capacity to 100 queries/hour per Creator license. We will monitor usage and scale licenses or implement caching as volume grows.
- **Query Complexity:** The current API does not support advanced Tableau "Table Calculations" (e.g., LOOKUP, RUNNING_SUM, JOINS, etc.) or multi-datasource blending. These must be pre-handled within the published Tableau datasource.
- **Data Volume:** Single query retrievals are capped at 100,000 rows, making this tool ideal for aggregated insights rather than massive data dumps.

---

### 3. Proposed 3-WEEK Roadmap

With your go-ahead, we will proceed as follows:

- **Week 1 (Setup):** Configure BI environment access and service enablement. Relavant data sources and dashboards must be set up (OPS team must help here).
- **Week 2 (Focus):** Identify **2 Patient Analytics KPIs** with the business team to build the POC. This will be the direty implemetation (Will not be perfect in any way)
- **Week 3 (Demo):** Gen AI team will build the DEMO
- **Week 3 (Demo):** Conduct a stakeholder demo and present the roadmap for scale-up.

**Request:** Please provide your **go-ahead signal** to trigger Phase 1.

I am available for a brief demo or technical walkthrough to discuss these guardrails in more detail.

Best regards,  
Bokey Deshmukh
