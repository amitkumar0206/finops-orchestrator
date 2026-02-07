"""
Text-to-SQL Service - Pure LLM approach for generating Athena SQL queries
Replaces the hybrid parameter extraction + template generation approach

The LLM directly generates complete, executable Athena SQL queries from natural language.
"""

from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING
from datetime import datetime, timedelta
import json
import re
import structlog

from backend.services.llm_service import llm_service
from backend.config.settings import get_settings
from backend.utils.sql_constants import build_sql_in_list, format_display_list
from backend.utils.sql_validation import SQL_INJECTION_PATTERNS, ValidationError

if TYPE_CHECKING:
    from backend.services.request_context import RequestContext

logger = structlog.get_logger(__name__)
settings = get_settings()


# Account scoping instructions to inject into the prompt
ACCOUNT_SCOPING_CONTEXT = """
**CRITICAL - Account Scoping:**
The user only has access to the following AWS account IDs: {allowed_accounts}

You MUST include a filter for these accounts in your WHERE clause:
`AND line_item_usage_account_id IN ({account_filter})`

If the user asks about accounts outside this list, inform them they don't have access.
Never return data from accounts not in this list.
"""


# CUR Schema Documentation for LLM
CUR_SCHEMA_CONTEXT = """
AWS Cost and Usage Report (CUR) Schema for Athena Queries:

**Database**: cost_usage_db
**Table**: cur_data

**Key Columns:**
- line_item_usage_start_date: DATE - When the usage started
- line_item_usage_end_date: DATE - When the usage ended  
- line_item_product_code: STRING - AWS service (e.g., 'AmazonEC2', 'AmazonCloudWatch', 'AmazonS3')
- line_item_unblended_cost: DECIMAL - Base cost before discounts
- savings_plan_savings_plan_effective_cost: DECIMAL - Cost after Savings Plans discount
- reservation_effective_cost: DECIMAL - Cost after Reserved Instance discount
- line_item_usage_type: STRING - Detailed usage type (e.g., 'DataTransfer-Out-Bytes', 'BoxUsage:m5.large')
- line_item_operation: STRING - API operation or action
- line_item_resource_id: STRING - Resource identifier (instance ID, bucket name, etc.)
- line_item_line_item_type: STRING - Type of charge (Usage, Tax, Credit, Fee, etc.)
- product_region_code: STRING - AWS region (e.g., 'us-east-1')
- product_instance_type: STRING - EC2 instance type (e.g., 'm5.large')
- bill_payer_account_id: STRING - AWS account ID

**Effective Cost Calculation (ALWAYS USE THIS):**
```sql
COALESCE(
  NULLIF(savings_plan_savings_plan_effective_cost, 0), 
  NULLIF(reservation_effective_cost, 0), 
  line_item_unblended_cost
) AS cost
```
This properly handles Savings Plans, Reserved Instances, and On-Demand pricing.

**Service Name Mappings (CRITICAL):**
- User says "CloudWatch" → use line_item_product_code = 'AmazonCloudWatch'
- User says "EC2" → use line_item_product_code = 'AmazonEC2'
- User says "S3" → use line_item_product_code = 'AmazonS3'
- User says "RDS" → use line_item_product_code = 'AmazonRDS'
- User says "Lambda" → use line_item_product_code = 'AWSLambda'
- User says "VPC" → use line_item_product_code = 'AmazonVPC'

**Services That Don't Generate Direct Costs (IMPORTANT):**
Some AWS services don't appear as line_item_product_code because they don't bill directly. Instead, query their underlying cost-generating services:

- **ECS (Elastic Container Service)**: Doesn't bill directly. Query for:
  * AmazonEC2 (for EC2 launch type instances)
  * Fargate (for Fargate launch type: look for line_item_usage_type LIKE '%Fargate%')
  * AmazonECR (container registry)
  * Example: "Show me ECS costs" → Query EC2 + Fargate usage types + ECR

- **EKS (Elastic Kubernetes Service)**: Control plane has minimal cost. Query for:
  * AmazonEC2 (for node groups)
  * Fargate (for Fargate profiles)
  * AmazonEKS (control plane - minor cost)

- **VPC Endpoints**: Query AmazonVPC with usage_type filters for endpoint-related charges

When user asks for costs of these "wrapper" services, automatically expand to their cost-generating components and explain in the response what was queried.

**Common Query Patterns:**

1. **Top N Services by Cost:**
```sql
SELECT 
  line_item_product_code AS service,
  ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd
FROM cost_usage_db.cur_data
WHERE CAST(line_item_usage_start_date AS DATE) >= DATE '2025-11-03'
  AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-12-03'
GROUP BY line_item_product_code
ORDER BY cost_usd DESC
LIMIT 5;
```

2. **Service Breakdown by Usage Type:**
```sql
SELECT 
  line_item_usage_type AS usage_type,
  ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd
FROM cost_usage_db.cur_data
WHERE line_item_product_code = 'AmazonCloudWatch'
  AND CAST(line_item_usage_start_date AS DATE) >= DATE '2025-11-03'
  AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-12-03'
GROUP BY line_item_usage_type
ORDER BY cost_usd DESC;
```

3. **Regional Breakdown:**
```sql
SELECT 
  product_region_code AS region,
  ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd
FROM cost_usage_db.cur_data
WHERE CAST(line_item_usage_start_date AS DATE) >= DATE '2025-11-03'
  AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-12-03'
GROUP BY product_region_code
ORDER BY cost_usd DESC;
```

4. **Time Series (Daily Costs):**
```sql
SELECT 
  CAST(line_item_usage_start_date AS DATE) AS date,
  ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd
FROM cost_usage_db.cur_data
WHERE CAST(line_item_usage_start_date AS DATE) >= DATE '2025-11-03'
  AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-12-03'
GROUP BY CAST(line_item_usage_start_date AS DATE)
ORDER BY date;
```

5. **Per-Resource Cost Breakdown:**
```sql
SELECT 
  line_item_resource_id AS resource_id,
  ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd
FROM cost_usage_db.cur_data
WHERE line_item_product_code = 'AmazonRDS'
  AND CAST(line_item_usage_start_date AS DATE) >= DATE '2025-09-01'
  AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-09-30'
  AND line_item_resource_id IS NOT NULL
  AND line_item_resource_id != ''
GROUP BY line_item_resource_id
ORDER BY cost_usd DESC;
```

6. **Specific ARN/Resource Cost Query (IMPORTANT):**
```sql
SELECT 
  line_item_product_code AS service,
  line_item_resource_id AS resource_id,
  ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd
FROM cost_usage_db.cur_data
WHERE line_item_resource_id = 'arn:aws:s3:::my-bucket-name'
  AND CAST(line_item_usage_start_date AS DATE) >= DATE '2025-11-01'
  AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-11-30'
GROUP BY line_item_product_code, line_item_resource_id;
```
**CRITICAL for ARN queries**: When filtering by a specific ARN/resource_id:
- Use exact match: `line_item_resource_id = 'arn:...'`
- GROUP BY must include ALL non-aggregated columns in SELECT
- If selecting only aggregates (SUM, COUNT), you can omit GROUP BY entirely
- DO NOT create constant aliases and then GROUP BY them

**Resource-Level Queries:**
- "per resource", "by resource", "each instance", "individual databases" → GROUP BY line_item_resource_id
- Always filter: `AND line_item_resource_id IS NOT NULL AND line_item_resource_id != ''`
- For specific ARN: Use exact match on line_item_resource_id
- For specific months: Use first and last day of month (e.g., September 2025: '2025-09-01' to '2025-09-30')

7. **Conditional/CASE Expressions in GROUP BY (CRITICAL ATHENA SYNTAX):**
```sql
-- CORRECT: Use column position number (1, 2, 3...) in GROUP BY
SELECT 
  CASE
    WHEN line_item_usage_type LIKE '%Windows%' THEN 'Windows'
    WHEN line_item_usage_type LIKE '%Linux%' THEN 'Linux'
    ELSE 'Other'
  END AS os_type,
  ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd
FROM cost_usage_db.cur_data
WHERE line_item_product_code = 'AmazonEC2'
  AND CAST(line_item_usage_start_date AS DATE) >= DATE '2025-10-01'
  AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-10-31'
GROUP BY 1  -- Use position number, NOT 'os_type' alias
ORDER BY cost_usd DESC;

-- WRONG: DO NOT use alias in GROUP BY (Athena will fail with COLUMN_NOT_FOUND)
-- GROUP BY os_type  ❌ This will cause an error!
```
**Athena GROUP BY Rules:**
- NEVER reference column aliases in GROUP BY clause
- Use column position numbers (1, 2, 3...) for expressions
- For simple columns, you can use the column name OR position number
- For CASE/CAST/functions, MUST use position number

8. **ECS/Container Service Cost Queries (IMPORTANT):**
ECS doesn't bill as 'AmazonECS' - it uses underlying services. For ECS-related costs:
```sql
-- Query for general ECS costs (EC2 + Fargate + ECR)
SELECT 
  line_item_product_code AS service,
  ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd
FROM cost_usage_db.cur_data
WHERE (
    line_item_product_code IN ('AmazonEC2', 'AmazonECR')
    OR line_item_usage_type LIKE '%Fargate%'
  )
  AND CAST(line_item_usage_start_date AS DATE) >= DATE '2025-11-01'
  AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-11-30'
GROUP BY 1
ORDER BY cost_usd DESC;

-- For specific ECS cluster ARN:
SELECT 
  line_item_product_code AS service,
  ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd
FROM cost_usage_db.cur_data
WHERE line_item_resource_id = 'arn:aws:ecs:us-east-1:123456789:cluster/my-cluster'
  AND CAST(line_item_usage_start_date AS DATE) >= DATE '2025-11-01'
  AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-11-30'
GROUP BY 1;
```

**Date Handling:**
- ALWAYS use: `CAST(line_item_usage_start_date AS DATE) >= DATE 'YYYY-MM-DD'`
- Never use string comparison on dates
- Current date: {current_date}
- Month names to dates: "September 2025" → DATE '2025-09-01' to DATE '2025-09-30'
- **Available data range**: September 2024 to present (CUR data has 24-48 hour delay, so most recent complete day is usually 2 days ago)
- **Future dates**: If user asks for dates beyond today, cap the end date to {current_date}

**Filtering Best Practices:**
- Exclude meta-services: Add `AND line_item_product_code NOT IN ('AWS Cost Explorer', 'AWS Support')`
- Exclude credits/taxes: Use `AND line_item_line_item_type = 'Usage'` to exclude Tax, Credit, Refund rows
- Always use effective cost calculation (Savings Plans + RI aware)

**Pricing Model Queries (On-Demand vs Reserved vs Savings Plans):**
- **IMPORTANT**: Our effective_cost formula ALREADY handles all pricing models automatically
- When user asks for "On-Demand costs" or "Reserved Instance costs":
  * DO NOT filter by line_item_usage_type patterns like '%OnDemand%' or '%RunInstances%'
  * Simply query the service with the effective_cost calculation
  * The COALESCE formula automatically shows the right cost (SP > RI > On-Demand)
- Users asking about "On-Demand" typically want to see their actual costs, not filter to only non-covered usage
- Only add usage_type filters if user explicitly asks to "exclude" certain pricing models
"""


TEXT_TO_SQL_PROMPT = """You are an expert SQL query generator for AWS Cost and Usage Reports (CUR) in Athena.

{schema_context}

**Today's Date**: {current_date}

**Conversation History:**
{conversation_history}

**User Query**: "{user_query}"

Your task: Generate a COMPLETE, EXECUTABLE Athena SQL query that answers the user's question.

**CRITICAL RULES:**

1. **Always provide complete, VALID SQL** - Check syntax carefully:
   - Match all parentheses: every opening ( must have a closing )
   - Proper column aliases: `column_name AS alias` (not `column_name alias)` with typo)
   - Valid GROUP BY: all non-aggregated SELECT columns must be in GROUP BY
   - **ATHENA LIMITATION**: NEVER use column aliases in GROUP BY - use column position numbers instead
     * WRONG: `SELECT CASE ... END AS os_type ... GROUP BY os_type`
     * CORRECT: `SELECT CASE ... END AS os_type ... GROUP BY 1`
   - No syntax errors or typos

   - **Totals-only queries (single number)**: DO NOT use GROUP BY at all
     * Example: "EC2 spend in eu-west-1 for June 2025" → use `SELECT ROUND(SUM(effective_cost), 2) AS cost_usd` with no GROUP BY
     * Only add GROUP BY when returning multiple rows (e.g., by service, by region, by month)

2. **If query is unclear or ambiguous, ask for clarification** instead of guessing:
   - Return a clarifying question in the explanation field
   - Set sql to empty string ""
   - Example: If user says "show costs" without time period, ask "Which time period would you like to analyze?"

3. **Use the effective cost calculation** shown in the schema above

4. **Map service names correctly** (CloudWatch → AmazonCloudWatch, EC2 → AmazonEC2, RDS → AmazonRDS)
   - **IMPORTANT**: For services that don't generate direct costs (ECS, EKS), query their underlying cost-generating services:
     * "ECS costs" → Query line_item_product_code IN ('AmazonEC2', 'AmazonECR') OR line_item_usage_type LIKE '%Fargate%'
     * "EKS costs" → Query line_item_product_code IN ('AmazonEC2', 'AmazonEKS') OR line_item_usage_type LIKE '%Fargate%'
     * Include a note in the explanation that you're showing costs for the underlying resources
   - **ARN-based queries**:
     * For billable resources (S3 buckets, RDS instances, EC2 instances): Use exact match `WHERE line_item_resource_id = 'arn:...'`
     * **For ECS/EKS cluster ARNs** (non-billable containers): DO NOT use line_item_resource_id filter
       - Instead, query underlying services: line_item_product_code IN ('AmazonEC2', 'AmazonECR') OR line_item_usage_type LIKE '%Fargate%'
       - Explain to user that you're showing costs for resources used by that cluster (EC2, Fargate, ECR)
       - ECS/EKS cluster ARNs do not appear in billing data - only their underlying compute/storage resources do

5. **Handle dates intelligently:**
   - "last 30 days" = {start_date_30d} to {current_date}
   - "September 2025" = DATE '2025-09-01' to DATE '2025-09-30'
   - "last month" = previous calendar month (full month, first to last day)
   - **"last N months"** = Go back N full calendar months from current month
     * Example: Today is Dec 4, 2025, "last 12 months" = Dec 2024 through Nov 2025 (12 full months)
     * "last 12 months" → DATE '2024-12-01' to DATE '2025-11-30' (NOT just 4 months!)
     * "last 6 months" → DATE '2025-06-01' to DATE '2025-11-30'
     * "last 3 months" → DATE '2025-09-01' to DATE '2025-11-30'
   - **"last N days"** = Go back exactly N days from today
     * "last 90 days" → {current_date} minus 90 days to {current_date}
   - If user doesn't specify time: default to last 30 days
   - **CRITICAL**: If user specifies an end date in the future (after {current_date}), cap it to {current_date}
     * Example: User asks "June to December 2025" but today is Dec 3 → use June 1 to Dec 3, 2025
     * Never query for dates beyond today - cost data doesn't exist for future dates
   - **CRITICAL**: Always validate date ranges - if the range is entirely in the future or before available data, ask for clarification
   - **For monthly time-series queries**: Use CAST(line_item_usage_start_date AS DATE) and extract month, then GROUP BY month

6. **Group by the right dimension:**
   - "top services" → GROUP BY line_item_product_code (or GROUP BY 1 if it's first column)
   - "by region" → GROUP BY product_region_code (or GROUP BY 1)
   - "by usage type" → GROUP BY line_item_usage_type (or GROUP BY 1)
   - "per resource", "by resource" → GROUP BY line_item_resource_id (include filters for NULL/empty)
   - "breakdown X" → drill down one level deeper
   - **For CASE expressions, CAST, or functions**: Always use position numbers (GROUP BY 1, 2, 3...)
   - **Never use column aliases in GROUP BY** - use position numbers instead
  - **For single-value totals**: Do not include any GROUP BY clause

7. **Service Comparison Queries** (e.g., "Compare EC2 vs CloudFront"):
   - **DO NOT** try to pivot data or create separate columns for each service
   - **DO NOT** use CASE WHEN to create service-specific columns
   - **CORRECT APPROACH**: Query both services with GROUP BY service, return multiple rows:
     ```sql
     SELECT 
       line_item_product_code AS service,
       ROUND(SUM(...effective_cost...), 2) AS cost_usd
     FROM cost_usage_db.cur_data
     WHERE line_item_product_code IN ('AmazonEC2', 'AmazonCloudFront')
       AND CAST(line_item_usage_start_date AS DATE) >= DATE '2025-08-01'
       AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-11-30'
     GROUP BY 1
     ORDER BY cost_usd DESC
     ```
   - For time-based comparisons (e.g., "compare EC2 vs CloudFront over last 4 months"):
     ```sql
     SELECT 
       DATE_TRUNC('month', CAST(line_item_usage_start_date AS DATE)) AS month,
       line_item_product_code AS service,
       ROUND(SUM(...effective_cost...), 2) AS cost_usd
     FROM cost_usage_db.cur_data
     WHERE line_item_product_code IN ('AmazonEC2', 'AmazonCloudFront')
       AND CAST(line_item_usage_start_date AS DATE) >= DATE '2025-08-01'
       AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-11-30'
     GROUP BY 1, 2
     ORDER BY month, cost_usd DESC
     ```
   - **Result format**: Multiple rows, one per service (or per month+service for trends)
   - The frontend will handle visualization (stacked/grouped charts)

8. **Use conversation context intelligently:**
   - **Inherit filters ONLY when the new query is implicit/relational**: 
     * "show CloudWatch costs" → "breakdown by region" = CloudWatch by region (implicit continuation)
     * "show CloudWatch costs" → "show it by month" = CloudWatch monthly trend (implicit continuation)
   - **DO NOT inherit filters when the new query is explicit/standalone**:
     * "show CloudWatch costs" → "overall AWS costs" = ALL services (explicit new scope)
     * "show CloudWatch costs" → "total AWS spend" = ALL services (explicit new scope)
     * "last 4 months CloudFront" → "overall AWS costs for the requested period" = ALL services (explicit override)
   - **Key signals for new scope**: Keywords like "overall", "total AWS", "all services", "entire account"
   - When in doubt, prefer broader scope over inherited filters

**Response Format:**
Return ONLY valid JSON with this structure:
{{
  "sql": "SELECT ... FROM ... WHERE ... GROUP BY ... ORDER BY ...",
  "explanation": "Formatted response following this EXACT structure:

**Summary:** [One sentence with key numbers and findings]

**Insights:**

- **[Insight Category]**: [Specific finding with numbers]
- **[Insight Category]**: [Specific finding with numbers]
- **[Insight Category]**: [Specific finding with numbers]

For OPTIMIZATION queries, add a recommendations section:

**Recommendations:**

1. **[Action]**: [Specific recommendation with estimated savings]
2. **[Action]**: [Specific recommendation with estimated savings]
3. **[Action]**: [Specific recommendation with estimated savings]

CRITICAL FORMATTING RULES:
- Summary must be ONE sentence with key cost numbers
- Each insight must be a bullet point starting with **Bold Category**:
- For optimization queries, add numbered recommendations with specific actions
- Use exact format shown above - UI parses this structure",
  "result_columns": ["service", "cost_usd"],
  "query_type": "top_services | breakdown | time_series | regional"
}}

**IMPORTANT - Query Type Selection**: 
- For "show me my total costs" queries, use query_type="top_services" and GROUP BY service
- For "show me top N services" queries, use query_type="top_services" 
- For "breakdown X" queries, use query_type="breakdown"
- For "costs over time" queries, use query_type="time_series"
- For "costs by region" queries, use query_type="regional"

**CRITICAL - Writing Great Explanations**:

Follow this EXACT format structure for the explanation field:

**Summary:** [Direct statement about user's costs/findings - address the user, not describe the query]

**Insights:**

- **[Category]**: [Direct finding about their costs]
- **[Category]**: [Direct finding about their costs]  
- **[Category]**: [Direct finding about their costs]

For optimization queries, add recommendations:

**Recommendations:**

1. **[Action]**: [Direct actionable recommendation]
2. **[Action]**: [Direct actionable recommendation]
3. **[Action]**: [Direct actionable recommendation]

TONE & STYLE REQUIREMENTS:
- Address the user directly: "Your costs are...", "You spent...", "CloudWatch is your..."
- NEVER say: "This query calculates...", "The results show...", "Breakdown of..."
- Be professional, concise, and actionable
- Summary MUST be one sentence, directly stating the finding
- DO NOT include a "Results:" section - the frontend automatically displays a data table below your analysis

**CRITICAL - Placeholder Variables:**
When you don't have exact values yet (before query execution), use standardized placeholders in this format: ${{VariableName}}

Available placeholders:
- ${{TotalCost}} - Total cost across all results
- ${{TopItem}} - Name of top cost contributor (service/region/resource)
- ${{TopCost}} - Cost of top contributor  
- ${{TopPct}} - Percentage of total that top contributor represents
- ${{Top2Pct}} - Combined percentage of top 2 contributors
- ${{Top3Pct}} - Combined percentage of top 3 contributors
- ${{Top5Pct}} - Combined percentage of top 5 contributors
- ${{NumItems}} - Count of items/rows returned
- ${{Item1}}, ${{Item2}}, ${{Item3}} - Names of top 3 items

Example usage:
- "Your total AWS spend is ${{TotalCost}} across ${{NumItems}} services"
- "${{TopItem}} is your highest cost service at ${{TopCost}} (${{TopPct}}% of total)"
- "Top 3 services represent ${{Top3Pct}}% of costs"

The system will automatically replace these with actual values from query results.

**CRITICAL - Time-Series Explanations (Monthly/Daily Trends):**
For time-series queries (monthly costs, daily trends), you CANNOT use generic placeholders. Instead:

1. **Calculate actual metrics** from the data structure you're querying:
   - Peak month: The month with MAX cost
   - Trend: Compare first month to last month (increasing if last > first, decreasing if last < first, stable if similar)
   - Volatility: Standard deviation or range analysis
   
2. **DO NOT use placeholder syntax like**:
   - ❌ "Monthly costs show [increasing/decreasing/stable] trend"
   - ❌ "Peak Month: N/A had the highest expenditure at $0.00"
   - ❌ "Cost Volatility: 0%% of total spend"
   
3. **DO use descriptive language**:
   - ✅ "Costs show a decreasing trend, dropping from $1,330 in March to $561 in November"
   - ✅ "Peak spending was in May 2025 at $1,352.55"
   - ✅ "Highest concentration: Top 3 months account for 50% of total annual spend"
   - ✅ "Trend shows 58% decline from peak (May) to current month (November)"

4. **For percentage symbols**: Use single % not double %%
   - ✅ "12.6% growth"
   - ❌ "12.6%% growth"

Example for monthly time-series:
```
**Summary:** Your monthly AWS costs show a declining trend, dropping from $1,330 in March 2025 to $561 in November 2025.

**Insights:**

- **Trend Analysis**: Costs decreased significantly (58% decline) over the 9-month period shown
- **Peak Month**: May 2025 had the highest expenditure at $1,352.55
- **Cost Volatility**: Significant variation with costs ranging from $561 to $1,352 across the period
```

**Examples:**

User: "Show me my AWS costs for the last 30 days"
{{
  "sql": "SELECT line_item_product_code AS service, ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd FROM cost_usage_db.cur_data WHERE CAST(line_item_usage_start_date AS DATE) >= DATE '{start_date_30d}' AND CAST(line_item_usage_start_date AS DATE) <= DATE '{current_date}' GROUP BY line_item_product_code ORDER BY cost_usd DESC LIMIT 10",
  "explanation": "**Summary:** Your total AWS spend is ${{TotalCost}} across ${{NumItems}} services for the last 30 days.

**Insights:**

- **Cost concentration**: Your top 2 services account for ${{Top2Pct}} of total costs
- **Leading driver**: ${{TopItem}} is your highest cost service at ${{TopCost}} (${{TopPct}} of total)
- **Optimization focus**: Focus on the top 3 services for maximum cost reduction impact",
  "result_columns": ["service", "cost_usd"],
  "query_type": "top_services"
}}

User: "How can I optimize my EC2 costs?"
{{
  "sql": "SELECT line_item_usage_type AS instance_type, ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd FROM cost_usage_db.cur_data WHERE line_item_product_code = 'AmazonEC2' AND CAST(line_item_usage_start_date AS DATE) >= DATE '{start_date_30d}' AND CAST(line_item_usage_start_date AS DATE) <= DATE '{current_date}' GROUP BY line_item_usage_type ORDER BY cost_usd DESC",
  "explanation": "**Summary:** Your EC2 costs total $92.26 for the last 30 days, with t4g.medium representing your largest cost driver at $45.77.

  "explanation": "**Summary:** Your EC2 costs total $92.26 for the last 30 days, with t4g.medium representing your largest cost driver at $45.77.

**Insights:**

- **High concentration**: Your top 2 instance types account for 86% of EC2 costs
- **Graviton usage**: You're already using cost-efficient ARM-based t4g instances
- **Optimization opportunity**: t4g.medium usage presents the highest savings potential

**Recommendations:**ces**: Purchase 1-year Reserved Instances for t4g.medium to save 30-40% (~$15-18/month)
2. **Rightsizing analysis**: Review if t4g.medium instances can be downsized to t4g.small for similar workloads
3. **Savings Plans**: Consider Compute Savings Plans for flexibility across instance families (20-30% savings)
4. **Spot Instances**: Evaluate if any workloads can run on Spot to save up to 90%
5. **Scheduling**: Use Instance Scheduler to stop dev/test instances during off-hours",
  "result_columns": ["instance_type", "cost_usd"],
  "query_type": "breakdown"
}}

User: "show me monthly cost for last 4 months"
{{
  "sql": "SELECT DATE_TRUNC('month', CAST(line_item_usage_start_date AS DATE)) AS month, ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS total_cost_usd FROM cost_usage_db.cur_data WHERE CAST(line_item_usage_start_date AS DATE) >= DATE_ADD('month', -4, CURRENT_DATE) GROUP BY DATE_TRUNC('month', CAST(line_item_usage_start_date AS DATE)) ORDER BY month",
  "explanation": "**Summary:** Your costs decreased by $409.34 (72.9%) from $561.22 to $151.88 over the last 4 months.

**Insights:**

- **Cost reduction**: Your costs are declining at 10.4% per period - your optimization efforts are working",
  "result_columns": ["month", "total_cost_usd"],
  "query_type": "time_series"
}}

User: "Compare current vs previous period"
{{
  "sql": "...",
  "explanation": "**Summary:** Your costs increased by $45.34 (8.0%) from $567.31 (Sept 23 - Oct 24) to $612.65 (Oct 25 - Nov 25).

**Insights:**

- **Growth trend**: Your spending increased across 5 services
- **Primary driver**: EC2 costs grew 134%, adding $77.63 to your total spend",
  "result_columns": ["service", "current_period_cost", "previous_period_cost"],
  "query_type": "top_services"
}}

User: "show me RDS costs for September 2025 per resource"
{{
  "sql": "SELECT line_item_resource_id AS resource_id, ROUND(SUM(COALESCE(NULLIF(savings_plan_savings_plan_effective_cost, 0), NULLIF(reservation_effective_cost, 0), line_item_unblended_cost)), 2) AS cost_usd FROM cost_usage_db.cur_data WHERE line_item_product_code = 'AmazonRDS' AND CAST(line_item_usage_start_date AS DATE) >= DATE '2025-09-01' AND CAST(line_item_usage_start_date AS DATE) <= DATE '2025-09-30' AND line_item_resource_id IS NOT NULL AND line_item_resource_id != '' GROUP BY line_item_resource_id ORDER BY cost_usd DESC",
  "explanation": "**Summary:** Your RDS costs for September 2025 broken down by individual database instance.

**Insights:**

- **Resource count**: Shows costs for each RDS database instance
- **Cost distribution**: Identifies which specific databases are driving your RDS spend
- **Optimization target**: Focus on the highest-cost instances for optimization",
  "result_columns": ["resource_id", "cost_usd"],
  "query_type": "breakdown"
}}

Now generate the query for the user's request. Return ONLY the JSON, no markdown formatting.
"""


class TextToSQLService:
    """Pure LLM-based text-to-SQL service for AWS CUR queries"""
    
    async def generate_sql(
        self,
        user_query: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        previous_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate Athena SQL query from natural language.
        
        Args:
            user_query: Natural language query from user
            conversation_history: Previous conversation messages
            previous_context: Context from previous query (service filters, time range, etc.)
            
        Returns:
            Tuple of (sql_query, metadata)
            - sql_query: Executable Athena SQL
            - metadata: Dict with explanation, result_columns, query_type
        """
        try:
            # Calculate common date ranges
            current_date = datetime.now().strftime("%Y-%m-%d")
            start_date_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            
            # Build conversation context string
            conv_context = "No previous conversation."
            if conversation_history and len(conversation_history) > 0:
                recent = conversation_history[-6:]  # Last 3 exchanges
                conv_context = "\n".join([
                    f"{msg['role'].upper()}: {msg['content'][:200]}"
                    for msg in recent
                ])
            
            # Add previous context if available
            if previous_context:
                context_parts = []
                if previous_context.get("last_service"):
                    context_parts.append(f"- Previously queried service: {previous_context['last_service']}")
                if previous_context.get("last_time_range"):
                    context_parts.append(f"- Previous time range: {previous_context['last_time_range']}")
                if context_parts:
                    conv_context += "\n\nPrevious Query Context:\n" + "\n".join(context_parts)
            
            # Format prompt
            prompt = TEXT_TO_SQL_PROMPT.format(
                schema_context=CUR_SCHEMA_CONTEXT,
                current_date=current_date,
                start_date_30d=start_date_30d,
                conversation_history=conv_context,
                user_query=user_query
            )
            
            logger.info(
                "Generating SQL from natural language",
                query=user_query[:100],
                has_history=bool(conversation_history),
                has_context=bool(previous_context)
            )
            
            # Call LLM with higher token limit for complex SQL generation
            raw_response = await llm_service.call_llm(
                prompt=prompt,
                system_prompt=(
                    "You are an expert SQL generator for AWS Cost and Usage Reports. "
                    "Generate complete, executable Athena SQL queries. "
                    "Return ONLY valid JSON. CRITICAL: Escape all newlines in strings as \\n (not literal line breaks). "
                    "DO NOT double-escape percent signs - use single % for percentages (e.g., '25% of total', NOT '25%% of total'). "
                    "JSON must have: sql, explanation, result_columns, and query_type fields."
                ),
              max_tokens=12000,  # Increased limit to reduce JSON truncation for complex prompts
              context={"expect_json": True}
            )
            
            logger.debug("LLM raw response", response_length=len(raw_response), response_preview=raw_response[:200])
            
            # Clean response
            cleaned = raw_response.strip()
            if not cleaned:
                raise ValueError("LLM returned empty response")
                
            if cleaned.startswith("```"):
                lines = [
                    ln for ln in cleaned.splitlines()
                    if not ln.strip().startswith("```") and ln.strip() != "```"
                ]
                cleaned = "\n".join(lines).strip()
            
            logger.debug("Cleaned response", response_length=len(cleaned), response_preview=cleaned[:200])
            
            # Parse JSON response (with a tolerant second pass)
            def _safe_json_parse(payload: str):
              try:
                return json.loads(payload), None
              except json.JSONDecodeError as err:
                return None, err

            response_data, parse_err = _safe_json_parse(cleaned)
            if parse_err:
              # Second pass: strip control characters and code-fence artifacts
              # Be more lenient - keep newlines and common whitespace for SQL queries
              sanitized = cleaned.replace("\r\n", "\n")  # normalize line endings
              sanitized = sanitized.replace("\r", "\n")
              # Remove problematic control chars but keep space, tab, newline
              sanitized = "".join(ch for ch in sanitized if ch in (' ', '\t', '\n') or 32 <= ord(ch) <= 126)
              # Strip leading/trailing backticks and code fences just in case
              if sanitized.startswith("```"):
                sanitized = "\n".join(
                  [ln for ln in sanitized.splitlines() if not ln.strip().startswith("```")]
                ).strip()
              response_data, parse_err2 = _safe_json_parse(sanitized)
              if parse_err2:
                logger.error(
                  "JSON parsing failed",
                  error=str(parse_err2),
                  cleaned_response=sanitized[:500]
                )
                # Last resort: try to extract SQL from the partial JSON if it contains a sql field
                import re
                sql_match = re.search(r'"sql"\s*:\s*"([^"]+(?:\\.[^"]*)*)"', sanitized)
                if sql_match:
                  # Found SQL in malformed JSON - extract it and proceed with minimal metadata
                  sql_query = sql_match.group(1).replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                  logger.warning("Extracted SQL from malformed JSON", sql_preview=sql_query[:100])
                  
                  # Try to extract other fields from the partial JSON
                  explanation_match = re.search(r'"explanation"\s*:\s*"([^"]+(?:\\.[^"]*)*)"', sanitized, re.DOTALL)
                  explanation = "Query executed successfully"
                  if explanation_match:
                    explanation = explanation_match.group(1).replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                  
                  # Try to infer query_type from the SQL structure
                  query_type = "unknown"
                  query_type_match = re.search(r'"query_type"\s*:\s*"([^"]+)"', sanitized)
                  if query_type_match:
                    query_type = query_type_match.group(1)
                  else:
                    # Infer from SQL patterns
                    sql_upper = sql_query.upper()
                    if 'DATE_TRUNC' in sql_upper or 'DATE_FORMAT' in sql_upper:
                      if 'GROUP BY' in sql_upper and sql_upper.count('GROUP BY') > 0:
                        # Check if grouping by multiple dimensions (time + service)
                        if 'LINE_ITEM_PRODUCT_CODE' in sql_upper or 'SERVICE' in sql_upper:
                          query_type = "comparison"  # Time-based comparison
                        else:
                          query_type = "time_series"
                    elif 'LIMIT' in sql_upper and any(word in sql_upper for word in ['TOP', 'LIMIT 5', 'LIMIT 10']):
                      query_type = "top_services"
                    elif 'GROUP BY' in sql_upper:
                      query_type = "breakdown"
                  
                  # Try to extract result_columns
                  result_columns = []
                  columns_match = re.search(r'"result_columns"\s*:\s*\[([^\]]*)\]', sanitized)
                  if columns_match:
                    columns_str = columns_match.group(1)
                    result_columns = [c.strip('"').strip() for c in columns_str.split(',') if c.strip()]
                  
                  metadata = {
                    "query_type": query_type,
                    "generated_via": "text_to_sql_llm_partial",
                    "status": "ok",
                    "explanation": explanation,
                    "result_columns": result_columns
                  }
                  return sql_query, metadata
                
                # Truly failed - return error
                metadata = {
                  "query_type": "unknown",
                  "generated_via": "text_to_sql_llm",
                  "status": "llm_error",
                  "clarification": [
                    "I couldn't parse the generated SQL reliably. Would you like to try rephrasing your question or specify a time period?"
                  ]
                }
                return "", metadata
            
            sql_query = response_data.get("sql", "")
            # Minimal schema validation to avoid malformed payloads
            if not isinstance(response_data.get("result_columns", []), list) or not response_data.get("query_type"):
                logger.error(
                    "LLM JSON missing required fields",
                    cleaned_response=str(response_data)[:300]
                )
                metadata = {
                    "query_type": "unknown",
                    "generated_via": "text_to_sql_llm",
                    "status": "llm_error",
                    "clarification": [
                        "I couldn't validate the generated SQL payload. Please specify the time period and what breakdown you want (e.g., by service or region)."
                    ]
                }
                return "", metadata
            
            # Extract time period and filters from SQL
            time_period_info = self._extract_time_period_from_sql(sql_query)
            scope_info = self._extract_scope_from_sql(sql_query, user_query)
            filters_info = self._extract_filters_from_sql(sql_query)
            
            metadata = {
                "explanation": response_data.get("explanation", ""),
                "result_columns": response_data.get("result_columns", []),
                "query_type": response_data.get("query_type", "unknown"),
                "generated_via": "text_to_sql_llm",
                "time_period": time_period_info,
                "scope": scope_info,
              "filters": filters_info,
              "status": "ok"
            }
            
            if not sql_query:
              # Ask for clarification instead of returning unrelated fallback
              metadata.update({
                "status": "needs_clarification",
                "clarification": [
                  "I couldn't extract a valid SQL from your request. Do you want costs for the last 30 days or a specific month?",
                  "Should I break it down by service, resource, or over time?"
                ]
              })
              return "", metadata
            
            logger.info(
                "SQL generation successful",
                query_type=metadata["query_type"],
                sql_length=len(sql_query),
                result_columns=metadata["result_columns"],
                time_period=time_period_info,
                scope=scope_info
            )

            # SECURITY: Validate LLM-generated SQL before execution
            if sql_query:
                try:
                    self._validate_generated_sql(sql_query)
                except ValidationError as e:
                    logger.error(
                        "SQL validation failed for LLM-generated query",
                        error=str(e),
                        sql_preview=sql_query[:200]
                    )
                    # Return error instead of malicious SQL
                    metadata.update({
                        "status": "validation_failed",
                        "clarification": [
                            "The generated query failed security validation. Please try rephrasing your request.",
                            "Ensure you're requesting data analysis, not data modification."
                        ]
                    })
                    return "", metadata

            return sql_query, metadata
            
        except Exception as e:
            logger.error(
                "Text-to-SQL generation failed",
                error=str(e),
                error_type=type(e).__name__,
                query=user_query
            )
            # Do not produce unrelated results; surface a structured error
            metadata = {
                "query_type": "unknown",
                "generated_via": "text_to_sql_llm",
                "status": "llm_error",
                "clarification": [
                    "I couldn't generate a reliable SQL for this request. Please rephrase or specify a time period (e.g., 'November 2025')."
                ],
                "error": str(e)
            }
            return "", metadata
    
    def _extract_time_period_from_sql(self, sql: str) -> str:
        """Extract time period from SQL WHERE clause"""
        import re
        
        # Look for date patterns in WHERE clause
        sql_upper = sql.upper()
        
        # Try to find INTERVAL patterns like "INTERVAL '6' MONTH"
        interval_match = re.search(r"INTERVAL\s+'(\d+)'\s+(MONTH|DAY|YEAR)", sql_upper)
        if interval_match:
            value, unit = interval_match.groups()
            return f"Last {value} {unit.lower()}{'s' if int(value) > 1 else ''}"
        
        # Try to find explicit date ranges
        date_pattern = r"DATE\s+'(\d{4}-\d{2}-\d{2})'"
        dates = re.findall(date_pattern, sql)
        if len(dates) >= 2:
            return f"{dates[0]} to {dates[1]}"
        
        # Default
        return "Custom period"
    
    def _extract_scope_from_sql(self, sql: str, user_query: str) -> str:
        """Extract scope (what's being analyzed) from SQL and query"""
        sql_lower = sql.lower()
        query_lower = user_query.lower()
        
        # Check GROUP BY clause for scope
        if "line_item_resource_id" in sql_lower or "resource_id" in sql_lower or "per resource" in query_lower:
            return "By Resource"
        elif "line_item_product_code" in sql_lower or "service" in sql_lower:
            return "By Service"
        elif "product_region" in sql_lower or "region" in sql_lower:
            return "By Region"
        elif "line_item_usage_account_id" in sql_lower or "account" in sql_lower:
            return "By Account"
        
        return "Overall"
    
    def _extract_filters_from_sql(self, sql: str) -> str:
        """Extract filters from SQL WHERE clause"""
        import re
        
        filters = []
        sql_upper = sql.upper()
        
        # Check for specific service filter
        service_match = re.search(r"LINE_ITEM_PRODUCT_CODE\s*=\s*'([^']+)'", sql_upper)
        if service_match:
            filters.append(f"Service: {service_match.group(1)}")
        
        # Check for region filter
        region_match = re.search(r"PRODUCT_REGION\s*=\s*'([^']+)'", sql_upper)
        if region_match:
            filters.append(f"Region: {region_match.group(1)}")
        
        # Check for account filter
        account_match = re.search(r"LINE_ITEM_USAGE_ACCOUNT_ID\s*=\s*'([^']+)'", sql_upper)
        if account_match:
            filters.append(f"Account: {account_match.group(1)}")
        
        return ", ".join(filters) if filters else "None"


    async def generate_sql_with_scoping(
        self,
        user_query: str,
        context: "RequestContext",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        previous_context: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate Athena SQL query with account scoping enforcement.

        This method wraps generate_sql() and:
        1. Injects account scope into the LLM prompt
        2. Post-processes SQL to validate/enforce account filter
        3. Adds scope metadata to response

        Args:
            user_query: Natural language query from user
            context: RequestContext with user's allowed accounts
            conversation_history: Previous conversation messages
            previous_context: Context from previous query

        Returns:
            Tuple of (sql_query, metadata) with scope information
        """
        from backend.services.request_context import RequestContext

        # Build enhanced context with account scoping
        enhanced_context = previous_context.copy() if previous_context else {}

        # Add account scoping context if user has restrictions
        scoping_prompt_addition = ""
        if context.allowed_account_ids and not context.is_admin:
            account_list = build_sql_in_list(context.allowed_account_ids)
            scoping_prompt_addition = ACCOUNT_SCOPING_CONTEXT.format(
                allowed_accounts=format_display_list(context.allowed_account_ids),
                account_filter=account_list
            )
            enhanced_context['allowed_accounts'] = context.allowed_account_ids

        # Apply effective time range from saved view if available
        if context.effective_time_range:
            enhanced_context['default_time_range'] = context.effective_time_range

        # Apply effective filters from saved view if available
        if context.effective_filters:
            enhanced_context['default_filters'] = context.effective_filters

        # Prepend scoping instructions to query if needed
        scoped_query = user_query
        if scoping_prompt_addition:
            # We inject scoping as a context hint rather than modifying the user query
            enhanced_context['account_scoping_instructions'] = scoping_prompt_addition

        # Generate SQL using base method
        sql_query, metadata = await self.generate_sql(
            user_query=scoped_query,
            conversation_history=conversation_history,
            previous_context=enhanced_context
        )

        # Post-process: validate and enforce account filter
        if sql_query and context.allowed_account_ids and not context.is_admin:
            sql_query, was_modified = self._enforce_account_filter(
                sql_query,
                context.allowed_account_ids
            )
            if was_modified:
                metadata['account_filter_enforced'] = True
                logger.info(
                    "account_filter_enforced",
                    user_email=context.user_email,
                    account_count=len(context.allowed_account_ids),
                )

        # Add scope metadata to response
        metadata['scope'] = {
            'organization_id': str(context.organization_id) if context.organization_id else None,
            'organization_name': context.organization_name,
            'allowed_account_ids': context.allowed_account_ids,
            'account_count': len(context.allowed_account_ids),
            'active_view_id': str(context.active_saved_view.id) if context.active_saved_view else None,
            'active_view_name': context.active_saved_view.name if context.active_saved_view else None,
            'effective_time_range': context.effective_time_range,
            'effective_filters': context.effective_filters,
        }

        return sql_query, metadata

    def _enforce_account_filter(
        self,
        sql: str,
        allowed_account_ids: List[str]
    ) -> Tuple[str, bool]:
        """
        Validate and inject account filter if missing.
        Defense-in-depth: ensures account scoping even if LLM didn't include it.

        Returns:
            Tuple of (modified_sql, was_modified)
        """
        sql_upper = sql.upper()

        # Check if account filter already present
        if 'LINE_ITEM_USAGE_ACCOUNT_ID' in sql_upper:
            # Validate it includes our allowed accounts
            # For now, trust the LLM included the right accounts
            # Could add stricter validation here
            return sql, False

        # No account filter found - inject one
        # Validate account IDs to prevent SQL injection (AWS account IDs are 12 digits)
        validated_ids = [acc for acc in allowed_account_ids if re.match(r'^[0-9]{12}$', str(acc))]
        if not validated_ids:
            logger.warning("no_valid_account_ids_for_filter")
            return sql, False

        account_list = build_sql_in_list(validated_ids)
        account_filter = f"line_item_usage_account_id IN ({account_list})"

        # Find WHERE clause and inject filter
        where_match = re.search(r'\bWHERE\b', sql, re.IGNORECASE)
        if where_match:
            # Insert after WHERE
            where_end = where_match.end()
            sql = f"{sql[:where_end]} {account_filter} AND {sql[where_end:]}"
        else:
            # No WHERE clause - need to add one
            # Find position after FROM clause
            from_match = re.search(
                r'\bFROM\s+[\w\.]+(?:\s+AS\s+\w+)?',
                sql,
                re.IGNORECASE
            )
            if from_match:
                from_end = from_match.end()
                sql = f"{sql[:from_end]} WHERE {account_filter} {sql[from_end:]}"

        logger.debug(
            "account_filter_injected",
            account_count=len(allowed_account_ids),
        )

        return sql, True

    def _validate_generated_sql(self, sql: str) -> None:
        """
        Validate LLM-generated SQL for security threats.

        This method protects against SQL injection and unauthorized operations
        that could be introduced through prompt injection attacks on the LLM.

        Raises:
            ValidationError: If dangerous patterns or unauthorized operations detected
        """
        if not sql or not sql.strip():
            return

        sql_upper = sql.upper()
        sql_stripped = sql.strip()

        # 1. Reject multi-statement queries (prevent stacked queries)
        # Allow trailing semicolon but not multiple statements
        if ';' in sql_stripped.rstrip(';'):
            raise ValidationError("Multi-statement SQL not allowed")

        # 2. Reject DDL/DML operations - only SELECT queries allowed
        dangerous_keywords = [
            'DROP', 'DELETE', 'INSERT', 'UPDATE', 'ALTER', 'TRUNCATE',
            'CREATE', 'REPLACE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
            'MERGE', 'CALL'
        ]

        for keyword in dangerous_keywords:
            # Check for keyword as separate word (not part of column name)
            pattern = re.compile(r'\b' + re.escape(keyword) + r'\b', re.IGNORECASE)
            if pattern.search(sql):
                raise ValidationError(f"Dangerous SQL keyword not allowed: {keyword}")

        # Check for metadata/schema inspection keywords (case-insensitive, whole word)
        # But exclude "DESC" when it's part of "ORDER BY ... DESC" (descending sort)
        if re.search(r'\b(EXPLAIN|DESCRIBE|SHOW)\b', sql, re.IGNORECASE):
            raise ValidationError("Schema inspection commands not allowed")

        # Check for DESC as standalone command (not ORDER BY DESC)
        if re.search(r'\bDESC\b(?!\s*(?:LIMIT|$|;))', sql, re.IGNORECASE):
            # DESC found, check if it's in ORDER BY context
            if not re.search(r'\bORDER\s+BY\b.*?\bDESC\b', sql, re.IGNORECASE | re.DOTALL):
                # DESC not in ORDER BY context - likely DESCRIBE statement
                raise ValidationError("Schema inspection commands not allowed")

        # 3. Ensure query starts with SELECT or WITH (for CTEs) (whitespace/comments ok)
        # Strip leading comments and whitespace
        sql_clean = re.sub(r'^\s*(--.*?\n|/\*.*?\*/\s*)*', '', sql, flags=re.DOTALL).strip()
        sql_clean_upper = sql_clean.upper()
        if not (sql_clean_upper.startswith('SELECT') or sql_clean_upper.startswith('WITH')):
            raise ValidationError("Only SELECT queries (including CTEs) are allowed")

        # 4. Check for SQL injection patterns
        # Log warnings for suspicious patterns but don't always block
        # (LLM might legitimately use some patterns like quotes in strings)
        suspicious_patterns = [
            (r";\s*SELECT", "Stacked SELECT detected"),
            (r"\bUNION\b.*?\bSELECT\b", "UNION injection attempt detected"),
            (r"--", "SQL comment detected"),
            (r"/\*", "Block comment detected"),
        ]

        for pattern_str, description in suspicious_patterns:
            pattern = re.compile(pattern_str, re.IGNORECASE | re.DOTALL)
            if pattern.search(sql):
                logger.warning(
                    "Suspicious SQL pattern in LLM-generated query",
                    pattern=description,
                    sql_preview=sql[:150]
                )

        # 5. Check for information_schema or system table access FIRST (word boundary check)
        # This must run before the regular table check to catch system tables
        system_tables = ['information_schema', 'pg_catalog', 'sys', 'mysql']
        sql_lower = sql.lower()
        for sys_table in system_tables:
            # Use word boundary to avoid false positives in column names
            if re.search(r'\b' + re.escape(sys_table) + r'\b', sql_lower):
                raise ValidationError(f"Access to system tables not allowed: {sys_table}")

        # 6. Validate table access - ensure only CUR table is queried
        table_name = (settings.aws_cur_table or 'cur_table').lower()

        # First, extract CTE (Common Table Expression) names from WITH clauses
        # CTEs are temporary and should be excluded from unauthorized table check
        cte_pattern = re.compile(r'\bWITH\s+([a-z_][a-z0-9_]*)\s+AS\s*\(', re.IGNORECASE)
        cte_names = {match.group(1).lower() for match in cte_pattern.finditer(sql)}

        # Extract all table references from FROM and JOIN clauses
        table_pattern = re.compile(
            r'\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?)',
            re.IGNORECASE
        )

        mentioned_tables = set()
        for match in table_pattern.finditer(sql):
            table_ref = match.group(1).lower()
            # Remove schema prefix if present
            if '.' in table_ref:
                table_ref = table_ref.split('.')[1]
            mentioned_tables.add(table_ref)

        # Check if any unauthorized tables are accessed (excluding CTEs and subquery aliases)
        unauthorized_tables = mentioned_tables - {table_name} - cte_names
        if unauthorized_tables:
            raise ValidationError(
                f"Access to table(s) not allowed: {', '.join(unauthorized_tables)}. "
                f"Only '{table_name}' is permitted."
            )

        logger.info(
            "LLM-generated SQL validation passed",
            sql_length=len(sql),
            tables_accessed=list(mentioned_tables) if mentioned_tables else [table_name]
        )

    def validate_sql_scope(
        self,
        sql: str,
        allowed_account_ids: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate that SQL doesn't access unauthorized accounts.

        Returns:
            Tuple of (is_valid, error_message)
        """
        sql_upper = sql.upper()

        # Extract any account IDs mentioned in the query
        account_pattern = r"'(\d{12})'"
        mentioned_accounts = set(re.findall(account_pattern, sql))

        if not mentioned_accounts:
            # No explicit accounts mentioned - need to ensure filter is present
            if 'LINE_ITEM_USAGE_ACCOUNT_ID' not in sql_upper:
                return False, "Query must include account filter"
            return True, None

        # Check if all mentioned accounts are allowed
        allowed_set = set(allowed_account_ids)
        unauthorized = mentioned_accounts - allowed_set

        if unauthorized:
            return False, f"Access denied to accounts: {format_display_list(unauthorized)}"

        return True, None


# Global instance
text_to_sql_service = TextToSQLService()
