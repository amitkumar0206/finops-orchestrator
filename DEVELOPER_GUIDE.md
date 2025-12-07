# FinOps AI Cost Intelligence Platform - Developer Guide

**Last Updated:** December 4, 2025  
**Version:** 1.0  
**Target Audience:** Developers new to AI/NLP systems

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Overview](#2-system-overview)
3. [Core Concepts](#3-core-concepts)
4. [Architecture](#4-architecture)
5. [Request Flow](#5-request-flow)
6. [Key Components](#6-key-components)
7. [LLM Integration](#7-llm-integration)
8. [Data Layer](#8-data-layer)
9. [Sample User Flows](#9-sample-user-flows)
10. [Development Guide](#10-development-guide)
11. [Testing](#11-testing)
12. [Deployment](#12-deployment)

---

## 1. Introduction

### What is FinOps Orchestrator?

FinOps Orchestrator is an **AI-powered AWS cost analysis platform** that lets users query their cloud costs using natural language. Instead of writing SQL queries or navigating complex dashboards, users simply ask questions like:

- "Show me my AWS costs for the last 30 days"
- "What are my top 5 most expensive services?"
- "How can I optimize my EC2 costs?"

The system uses **Large Language Models (LLMs)** to understand these questions, generate SQL queries, execute them against AWS Cost and Usage Report (CUR) data, and return insights with visualizations.

### Why This Guide?

This guide explains the system from first principles, assuming **no prior knowledge of AI or NLP systems**. You'll learn:

- How natural language gets transformed into SQL queries
- How the LLM understands context and intent
- How data flows from user query to visual response
- How to extend and maintain the system

---

## 2. System Overview

### High-Level Architecture

```
┌─────────────┐
│   User      │
│   Browser   │
└──────┬──────┘
       │ "Show me EC2 costs"
       ▼
┌─────────────────────────────────────────────┐
│         React Frontend (Port 3000)          │
│  • Chat Interface                           │
│  • Chart Rendering                          │
│  • Conversation History                     │
└──────┬──────────────────────────────────────┘
       │ HTTP POST /api/v1/chat
       ▼
┌─────────────────────────────────────────────┐
│       FastAPI Backend (Port 8000)           │
│                                             │
│  ┌─────────────────────────────────────┐  │
│  │   Chat API (chat.py)                │  │
│  │   • Receives user message           │  │
│  │   • Manages conversation context    │  │
│  └───────────┬─────────────────────────┘  │
│              ▼                              │
│  ┌─────────────────────────────────────┐  │
│  │   Text-to-SQL Service                │  │
│  │   • Calls LLM (AWS Bedrock)         │  │
│  │   • Generates Athena SQL            │  │
│  └───────────┬─────────────────────────┘  │
│              ▼                              │
│  ┌─────────────────────────────────────┐  │
│  │   Athena Executor                    │  │
│  │   • Executes SQL query              │  │
│  │   • Returns cost data               │  │
│  └───────────┬─────────────────────────┘  │
│              ▼                              │
│  ┌─────────────────────────────────────┐  │
│  │   Response Formatter                 │  │
│  │   • Formats insights                │  │
│  │   • Recommends charts               │  │
│  │   • Builds suggestions              │  │
│  └───────────┬─────────────────────────┘  │
└──────────────┼─────────────────────────────┘
               │ JSON Response
               ▼
┌─────────────────────────────────────────────┐
│         External Services                   │
│  • AWS Bedrock (LLM)                       │
│  • AWS Athena (SQL Query Engine)           │
│  • PostgreSQL (Conversation Storage)       │
└─────────────────────────────────────────────┘
```

### Technology Stack

**Frontend:**
- React 18 + TypeScript
- Material-UI (MUI) for components
- Chart.js for visualizations
- Axios for HTTP requests

**Backend:**
- Python 3.11+
- FastAPI (async web framework)
- AWS Bedrock (LLM service)
- AWS Athena (query engine)
- PostgreSQL (conversation storage)

**Infrastructure:**
- Docker containers
- AWS ECS Fargate
- Application Load Balancer
- S3 for CUR data storage

---

## 3. Core Concepts

### 3.1 What is a Large Language Model (LLM)?

An LLM is an AI model trained on vast amounts of text to understand and generate human language. Think of it as an extremely sophisticated autocomplete that can:

- **Understand context**: "Show me costs" → knows we're talking about AWS costs
- **Extract information**: "Last 30 days" → extracts date range
- **Generate code**: Natural language → SQL query
- **Provide insights**: Raw data → human-readable analysis

**Example:**
```
Input: "Show me EC2 costs for last month by region"

LLM Processing:
- Service: EC2 (maps to 'AmazonEC2')
- Time: Last month (calculates date range)
- Grouping: By region (GROUP BY region)

Output: SQL Query + Explanation
```

### 3.2 Text-to-SQL: The Core Innovation

Traditional approach:
```
User query → Parse parameters → Build SQL template → Execute
```

Our approach:
```
User query → LLM generates complete SQL → Execute
```

**Why better?**
- No need to maintain SQL templates
- Handles complex queries naturally
- Adapts to variations in phrasing
- Understands context from conversation

### 3.3 Conversation Context

The system remembers previous questions:

```
User: "Show me CloudWatch costs for November"
System: [Returns data for CloudWatch in November]

User: "Break it down by region"
System: [Inherits CloudWatch + November, adds regional breakdown]
```

This is achieved through:
- **Conversation History**: Stored in PostgreSQL
- **Context Manager**: Tracks current filters and time ranges
- **LLM Context Window**: Includes recent messages in prompts

### 3.4 AWS Cost and Usage Report (CUR)

CUR is AWS's detailed billing data export to S3. Each row represents a line item:

```
| line_item_usage_start_date | line_item_product_code | cost |
|----------------------------|------------------------|------|
| 2025-11-01                | AmazonEC2              | 45.23|
| 2025-11-01                | AmazonS3               | 12.50|
```

The system queries this data using **AWS Athena** (serverless SQL engine).

---

## 4. Architecture

### 4.1 Component Diagram

```
┌────────────────────────────────────────────────────────────┐
│                     FRONTEND LAYER                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ ChatInterface│  │ ChartDisplay │  │ Conversation │    │
│  │              │  │              │  │   History    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
└────────────────────────────────────────────────────────────┘
                            │
                            │ HTTP REST API
                            ▼
┌────────────────────────────────────────────────────────────┐
│                      API LAYER                             │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  /api/v1/chat (chat.py)                              │ │
│  │  • Validates request                                 │ │
│  │  • Manages conversation threading                    │ │
│  │  • Orchestrates workflow                             │ │
│  └──────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                  ORCHESTRATION LAYER                       │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  multi_agent_workflow.py                             │ │
│  │  • Routes to text-to-SQL service                     │ │
│  │  • Handles errors and fallbacks                      │ │
│  └──────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                    SERVICE LAYER                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ Text-to-SQL  │  │   Athena     │  │  Response    │    │
│  │   Service    │  │  Executor    │  │  Formatter   │    │
│  │              │  │              │  │              │    │
│  │ • LLM calls  │  │ • SQL exec   │  │ • Insights   │    │
│  │ • SQL gen    │  │ • Results    │  │ • Charts     │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │Conversation  │  │     Chart    │  │     LLM      │    │
│  │  Manager     │  │    Engine    │  │   Service    │    │
│  │              │  │              │  │              │    │
│  │ • History    │  │ • Chart type │  │ • Bedrock    │    │
│  │ • Context    │  │ • Data prep  │  │ • Prompts    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
└────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                     DATA LAYER                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  PostgreSQL  │  │   AWS S3     │  │  AWS Bedrock │    │
│  │              │  │              │  │              │    │
│  │ • Convos     │  │ • CUR Data   │  │ • LLM API    │    │
│  │ • Context    │  │ • Raw costs  │  │ • Models     │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
└────────────────────────────────────────────────────────────┘
```

### 4.2 Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: User sends message                                  │
│                                                             │
│  User: "Show me EC2 costs for last month"                  │
│         ↓                                                   │
│  Frontend → POST /api/v1/chat                              │
│  {                                                          │
│    "message": "Show me EC2 costs for last month",          │
│    "conversation_id": "uuid-1234",                         │
│    "context": {}                                           │
│  }                                                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 2: API receives request                                │
│                                                             │
│  chat.py:chat()                                            │
│  • Validates request                                        │
│  • Creates/gets conversation thread                         │
│  • Persists user message to PostgreSQL                     │
│  • Retrieves conversation context                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 3: Execute multi-agent workflow                        │
│                                                             │
│  multi_agent_workflow.py:execute_multi_agent_query()       │
│  • Calls execute_query_simple()                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 4: Generate SQL via LLM                                │
│                                                             │
│  text_to_sql_service.generate_sql()                        │
│  • Builds prompt with:                                      │
│    - User query                                             │
│    - CUR schema documentation                              │
│    - Conversation history                                   │
│    - Current date                                           │
│  • Calls AWS Bedrock LLM                                   │
│  • Receives JSON response:                                  │
│    {                                                        │
│      "sql": "SELECT ...",                                  │
│      "explanation": "Your EC2 costs...",                   │
│      "query_type": "breakdown"                             │
│    }                                                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 5: Execute SQL query                                   │
│                                                             │
│  athena_executor.execute_sql()                             │
│  • Submits query to AWS Athena                             │
│  • Polls for completion (async)                            │
│  • Retrieves results from S3                               │
│  • Parses into list of dicts:                              │
│    [                                                        │
│      {"service": "AmazonEC2", "cost_usd": 1234.56},       │
│      {"service": "AmazonS3", "cost_usd": 234.67}          │
│    ]                                                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 6: Generate visualizations                             │
│                                                             │
│  chart_engine.recommend_charts()                           │
│  • Analyzes data structure                                  │
│  • Recommends chart types (bar, pie, line)                 │
│                                                             │
│  chart_data_builder.build_chart_data()                     │
│  • Transforms data for Chart.js format                     │
│  • Returns chart specifications                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 7: Format response                                     │
│                                                             │
│  • Uses LLM explanation from Step 4                        │
│  • Replaces placeholders with actual values:               │
│    ${TotalCost} → $1,469.23                               │
│  • Generates follow-up suggestions                         │
│  • Packages everything into ChatResponse                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 8: Persist and return                                  │
│                                                             │
│  • Saves assistant response to PostgreSQL                  │
│  • Logs execution metrics                                   │
│  • Returns JSON to frontend:                               │
│    {                                                        │
│      "message": "Your EC2 costs total $1,234...",         │
│      "charts": [...],                                      │
│      "suggestions": [...],                                 │
│      "athena_query": "SELECT ..."                          │
│    }                                                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STEP 9: Render in browser                                   │
│                                                             │
│  • Displays formatted message (markdown)                   │
│  • Renders charts (Chart.js)                               │
│  • Shows clickable suggestions                             │
│  • Updates conversation history                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Request Flow

### 5.1 Sequence Diagram: Complete Request Flow

```mermaid
sequenceDiagram
    participant U as User
    participant FE as React Frontend
    participant API as FastAPI Backend
    participant CM as Conversation Manager
    participant MAW as Multi-Agent Workflow
    participant T2S as Text-to-SQL Service
    participant LLM as AWS Bedrock (LLM)
    participant AE as Athena Executor
    participant ATH as AWS Athena
    participant RF as Response Formatter
    participant CE as Chart Engine
    participant DB as PostgreSQL

    U->>FE: Types "Show me EC2 costs"
    FE->>API: POST /api/v1/chat
    API->>CM: Create/get conversation thread
    CM->>DB: Query conversation_threads
    DB-->>CM: Return thread_id
    CM-->>API: thread_id + context
    
    API->>DB: Save user message
    API->>MAW: execute_multi_agent_query(query, context)
    MAW->>T2S: generate_sql(query, history)
    
    T2S->>LLM: Prompt + CUR schema
    Note over T2S,LLM: "Generate SQL for EC2 costs"
    LLM-->>T2S: {sql: "SELECT...", explanation: "..."}
    
    T2S-->>MAW: SQL + metadata
    MAW->>AE: execute_sql(sql_query)
    AE->>ATH: start_query_execution()
    ATH-->>AE: query_execution_id
    
    loop Poll for results
        AE->>ATH: get_query_execution(id)
        ATH-->>AE: status
    end
    
    AE->>ATH: get_query_results()
    ATH-->>AE: ResultSet
    AE-->>MAW: Parsed data (list of dicts)
    
    MAW->>CE: recommend_charts(data)
    CE-->>MAW: Chart specs
    
    MAW->>RF: Format with LLM explanation
    RF-->>MAW: Formatted response
    
    MAW-->>API: Complete response
    API->>DB: Save assistant message
    API-->>FE: JSON response
    FE->>FE: Render message + charts
    FE-->>U: Display results
```

### 5.2 Follow-Up Query Flow

```mermaid
sequenceDiagram
    participant U as User
    participant FE as Frontend
    participant API as Backend
    participant CM as Conversation Manager
    participant T2S as Text-to-SQL
    participant LLM as LLM

    Note over U,LLM: Previous: "Show CloudWatch costs for November"
    
    U->>FE: "Break it down by region"
    FE->>API: POST /chat (with conversation_id)
    API->>CM: get_context_for_query(conversation_id)
    CM->>CM: Retrieve recent messages
    CM->>CM: Extract: service=CloudWatch, month=November
    CM-->>API: {services: [CloudWatch], time_range: Nov}
    
    API->>T2S: generate_sql(query, context)
    Note over T2S: Prompt includes:<br/>Previous: CloudWatch, November<br/>New: "by region"
    
    T2S->>LLM: Enhanced prompt with context
    LLM-->>T2S: SQL with inherited filters
    Note over LLM: Generates:<br/>WHERE service=CloudWatch<br/>AND month=Nov<br/>GROUP BY region
    
    T2S-->>API: SQL + explanation
    API->>API: Execute query (as before)
    API-->>FE: Response with regional breakdown
```

---

## 6. Key Components

### 6.1 Chat API (`backend/api/chat.py`)

**Purpose:** Main entry point for user queries.

**Key Functions:**

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, ...):
    """
    Main chat endpoint.
    
    Flow:
    1. Get/create conversation thread
    2. Save user message
    3. Retrieve conversation context
    4. Execute multi-agent workflow
    5. Save assistant response
    6. Return formatted response
    """
```

**Input:**
```json
{
  "message": "Show me my costs",
  "conversation_id": "uuid-123",
  "context": {},
  "chat_history": []
}
```

**Output:**
```json
{
  "message": "Your total AWS spend is $1,234...",
  "charts": [{...}],
  "suggestions": ["...", "..."],
  "athena_query": "SELECT ...",
  "execution_time": 2.5
}
```

### 6.2 Text-to-SQL Service (`backend/services/text_to_sql_service.py`)

**Purpose:** Convert natural language to SQL using LLM.

**Key Method:**

```python
async def generate_sql(
    user_query: str,
    conversation_history: List[Dict],
    previous_context: Dict
) -> Tuple[str, Dict]:
    """
    Generate Athena SQL from natural language.
    
    Returns:
        (sql_query, metadata) where metadata contains:
        - explanation: Human-readable analysis
        - query_type: breakdown|time_series|top_services
        - result_columns: Expected column names
    """
```

**The Prompt:**

The service builds a comprehensive prompt including:

1. **CUR Schema Documentation**: Complete table structure, column descriptions
2. **Service Mappings**: "EC2" → "AmazonEC2", "S3" → "AmazonS3"
3. **Query Patterns**: Examples of common query structures
4. **Conversation Context**: Recent messages and inherited filters
5. **Current Date**: For relative time calculations
6. **Instructions**: Format requirements, best practices

**Example Prompt Structure:**

```
You are an expert SQL query generator for AWS Cost and Usage Reports.

Database: cost_usage_db
Table: cur_data

Key Columns:
- line_item_usage_start_date: DATE
- line_item_product_code: STRING (service name)
- line_item_unblended_cost: DECIMAL
...

Today's Date: 2025-12-04

Conversation History:
USER: Show me CloudWatch costs
ASSISTANT: Here are your CloudWatch costs...

User Query: "break it down by region"

Generate SQL that:
1. Inherits CloudWatch filter from context
2. Groups by region
3. Returns valid JSON with sql, explanation, query_type

Response Format:
{
  "sql": "SELECT ...",
  "explanation": "Your CloudWatch costs by region...",
  "query_type": "breakdown"
}
```

### 6.3 Athena Executor (`backend/services/athena_executor.py`)

**Purpose:** Execute SQL queries against AWS Athena.

**Key Features:**

```python
class AthenaExecutor:
    async def execute_sql(self, sql_query: str) -> List[Dict]:
        """
        Execute SQL and return results.
        
        Process:
        1. Submit query to Athena
        2. Poll for completion (async)
        3. Retrieve results from S3
        4. Parse and type-convert data
        5. Return as list of dicts
        """
```

**Execution Flow:**

```
1. start_query_execution()
   ↓
2. get_query_execution() [poll every 1s, max 30s]
   ↓
3. get_query_results()
   ↓
4. Parse ResultSet:
   - Row 0: Column headers
   - Rows 1+: Data rows
   ↓
5. Type conversion:
   - Numeric strings → float/int
   - Keep strings as-is
   ↓
6. Return: [{"col1": val1, "col2": val2}, ...]
```

### 6.4 Conversation Manager (`backend/services/conversation_manager.py`)

**Purpose:** Manage conversation threads and context in PostgreSQL.

**Key Methods:**

```python
class ConversationManager:
    def create_thread(self, user_id: str, title: str) -> str:
        """Create new conversation thread."""
    
    def add_message(self, thread_id: str, role: str, content: str, ...):
        """Add message to thread."""
    
    def get_context_for_query(self, thread_id: str) -> Dict:
        """
        Extract context from recent messages.
        
        Returns:
            {
                "services": ["AmazonEC2"],
                "time_range": {"start": "2025-11-01", "end": "2025-11-30"},
                "last_query_type": "breakdown"
            }
        """
```

**Context Extraction:**

The manager looks at recent messages to extract:
- **Services**: Mentioned AWS services
- **Time Ranges**: Date references
- **Dimensions**: Grouping preferences (region, account, etc.)
- **Filters**: Applied constraints

This context is passed to the LLM to enable follow-up queries.

### 6.5 Chart Engine (`backend/services/chart_recommendation.py`)

**Purpose:** Recommend appropriate chart types based on data.

**Logic:**

```python
def recommend_charts(intent, data_results, extracted_params):
    """
    Recommend charts based on:
    - Query type (breakdown, time_series, comparison)
    - Data cardinality (number of unique values)
    - Data structure (columns present)
    
    Returns:
        List of chart specs:
        [
          {
            "type": "bar",
            "title": "Costs by Service",
            "data": {...}
          }
        ]
    """
```

**Chart Selection Rules:**

| Query Type | Cardinality | Chart Type |
|------------|-------------|------------|
| breakdown | 2-10 items | Pie chart |
| breakdown | >10 items | Bar chart |
| time_series | Any | Line chart |
| comparison | 2 periods | Grouped bar |
| top_services | <20 items | Bar chart |

### 6.6 LLM Service (`backend/services/llm_service.py`)

**Purpose:** Interface with AWS Bedrock LLM.

**Key Method:**

```python
async def call_llm(
    prompt: str,
    system_prompt: str,
    max_tokens: int = 4000
) -> str:
    """
    Call AWS Bedrock LLM.
    
    Args:
        prompt: User's specific query context
        system_prompt: Role/expertise definition
        max_tokens: Response length limit
    
    Returns:
        LLM response as string
    """
```

**System Prompts:**

The service uses different system prompts for different purposes:

1. **SQL Generation**: "You are an expert SQL generator for AWS CUR..."
2. **Insights**: "You are a FinOps expert providing cost analysis..."
3. **Recommendations**: "You are an optimization consultant..."

---

## 7. LLM Integration

### 7.1 Understanding LLM Interactions

**What happens when we call the LLM:**

```
Input (Prompt):
  System: "You are an AWS cost expert"
  User: "Generate SQL for: Show EC2 costs by region for November"
  Context: Current date, CUR schema, examples

LLM Processing (inside AWS Bedrock):
  • Understands: User wants EC2 service data
  • Maps: EC2 → AmazonEC2 (from schema docs)
  • Calculates: November → 2025-11-01 to 2025-11-30
  • Structures: GROUP BY region
  • Formats: Valid Athena SQL syntax

Output (Response):
  {
    "sql": "SELECT product_region_code AS region, ...",
    "explanation": "Your EC2 costs for November by region...",
    "query_type": "breakdown"
  }
```

### 7.2 Prompt Engineering Best Practices

**1. Be Specific:**
```
❌ Bad: "Generate SQL for the user's query"
✅ Good: "Generate executable Athena SQL that queries the cost_usage_db.cur_data table for the user's request"
```

**2. Provide Examples:**
```
Include 3-5 example queries in the prompt:
- Simple: Top services
- Complex: Multi-dimensional breakdown
- Time-based: Monthly trends
```

**3. Define Output Format:**
```
❌ Bad: "Return SQL"
✅ Good: "Return ONLY valid JSON with these exact keys: sql, explanation, query_type"
```

**4. Include Schema:**
```
Provide complete table schema in prompt:
- Column names and types
- Sample values
- Relationships
- Best practices
```

### 7.3 Handling LLM Responses

**Parsing JSON:**

```python
# LLM may return markdown code blocks
response = """```json
{
  "sql": "SELECT ...",
  "explanation": "..."
}
```"""

# Clean it
cleaned = response.strip()
if cleaned.startswith("```"):
    cleaned = "\n".join([
        line for line in cleaned.split("\n")
        if not line.strip().startswith("```")
    ])

# Parse
data = json.loads(cleaned)
```

**Error Handling:**

```python
try:
    sql_query, metadata = await text_to_sql_service.generate_sql(...)
except Exception as e:
    # LLM failed - return clarification request
    return {
        "message": "I couldn't understand your query. Could you rephrase?",
        "suggestions": [
            "Show me costs for last 30 days",
            "What are my top 5 services?"
        ]
    }
```

### 7.4 Cost Optimization

**Token Usage:**

Each LLM call costs money based on tokens (roughly words):
- Input tokens: Your prompt
- Output tokens: LLM response

**Optimization strategies:**

1. **Minimize prompt size**: Only include relevant context
2. **Cache schema**: Don't repeat full schema in every call
3. **Limit output**: Set max_tokens appropriately
4. **Batch when possible**: Combine related queries

**Example:**

```python
# ❌ Inefficient: Full schema every time (10,000 tokens)
prompt = f"{FULL_CUR_SCHEMA}\n{user_query}"

# ✅ Efficient: Reference schema (2,000 tokens)
prompt = f"{SCHEMA_SUMMARY}\n{user_query}"
```

---

## 8. Data Layer

### 8.1 AWS Cost and Usage Report (CUR)

**Structure:**

CUR data is stored in S3 as Parquet files:

```
s3://bucket/prefix/
  ├── year=2025/
  │   ├── month=11/
  │   │   ├── part-00001.parquet
  │   │   ├── part-00002.parquet
  │   └── month=12/
  │       ├── part-00001.parquet
```

**Athena Table:**

```sql
CREATE EXTERNAL TABLE cur_data (
  line_item_usage_start_date DATE,
  line_item_product_code STRING,
  line_item_unblended_cost DECIMAL(16,8),
  product_region_code STRING,
  line_item_usage_type STRING,
  ...
)
PARTITIONED BY (year INT, month INT)
STORED AS PARQUET
LOCATION 's3://bucket/prefix/'
```

**Key Columns:**

| Column | Description | Example |
|--------|-------------|---------|
| line_item_usage_start_date | When usage occurred | 2025-11-15 |
| line_item_product_code | AWS service | AmazonEC2 |
| line_item_unblended_cost | Base cost | 45.23 |
| savings_plan_savings_plan_effective_cost | SP discount applied | 32.16 |
| line_item_usage_type | Specific usage | BoxUsage:t3.medium |
| product_region_code | AWS region | us-east-1 |
| line_item_resource_id | Resource ARN | arn:aws:ec2:... |

### 8.2 Effective Cost Calculation

**Critical Formula:**

```sql
COALESCE(
  NULLIF(savings_plan_savings_plan_effective_cost, 0),
  NULLIF(reservation_effective_cost, 0),
  line_item_unblended_cost
) AS cost
```

**Why?**
- Savings Plans: Apply discounts to on-demand rates
- Reserved Instances: Pre-purchased capacity discounts
- On-Demand: Full price

The COALESCE ensures we use the best (lowest) applicable cost.

### 8.3 PostgreSQL Schema

**Conversation Storage:**

```sql
-- Threads
CREATE TABLE conversation_threads (
  thread_id UUID PRIMARY KEY,
  user_id VARCHAR(255),
  title VARCHAR(500),
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  is_active BOOLEAN DEFAULT true
);

-- Messages
CREATE TABLE conversation_messages (
  message_id UUID PRIMARY KEY,
  thread_id UUID REFERENCES conversation_threads,
  role VARCHAR(50), -- 'user' or 'assistant'
  content TEXT,
  message_type VARCHAR(50), -- 'query', 'response'
  metadata JSONB,
  created_at TIMESTAMP
);

-- Agent Executions (for debugging)
CREATE TABLE agent_executions (
  execution_id UUID PRIMARY KEY,
  thread_id UUID,
  agent_name VARCHAR(100),
  input_query TEXT,
  output_response JSONB,
  execution_time_ms INT,
  status VARCHAR(50),
  created_at TIMESTAMP
);
```

---

## 9. Sample User Flows

### 9.1 Simple Cost Query

**User Journey:**

```
Step 1: User asks
  "Show me my AWS costs for the last 30 days"

Step 2: System processes
  • LLM extracts: time_range = last 30 days
  • Generates SQL: SELECT service, SUM(cost) ... WHERE date >= ...
  • Executes query
  • Formats response

Step 3: User sees
  ┌─────────────────────────────────────────┐
  │ Your total AWS spend is $5,432 across   │
  │ 12 services for the last 30 days.       │
  │                                         │
  │ Top 3 services:                         │
  │ • EC2: $2,345 (43%)                    │
  │ • CloudWatch: $1,234 (23%)             │
  │ • S3: $876 (16%)                       │
  │                                         │
  │ [Bar Chart]                            │
  │                                         │
  │ Suggestions:                            │
  │ • Break down EC2 by region              │
  │ • Compare with previous month           │
  └─────────────────────────────────────────┘
```

### 9.2 Follow-Up Drill-Down

**Conversation:**

```
User: "Show me CloudWatch costs for November"
System: [Shows CloudWatch costs = $1,234]

User: "Break it down by usage type"
System processes:
  • Inherits: service=CloudWatch, month=November
  • Adds: GROUP BY usage_type
  • Generates SQL with both filters

User sees:
  ┌─────────────────────────────────────────┐
  │ CloudWatch costs for November by usage: │
  │                                         │
  │ • DataProcessing-Bytes: $654 (53%)     │
  │ • Requests: $321 (26%)                 │
  │ • TimedStorage-ByteHrs: $259 (21%)     │
  │                                         │
  │ [Pie Chart]                            │
  └─────────────────────────────────────────┘

User: "How can I reduce these costs?"
System processes:
  • Switches intent: optimization
  • Keeps context: CloudWatch, November
  • Generates recommendations

User sees:
  ┌─────────────────────────────────────────┐
  │ CloudWatch Cost Optimization:           │
  │                                         │
  │ 1. Log Retention: Reduce retention from │
  │    90 to 30 days → Save ~$200/month    │
  │                                         │
  │ 2. Filter Verbose Logs: Implement log   │
  │    filters → Save ~$150/month          │
  │                                         │
  │ 3. Metric Resolution: Switch to 5-min   │
  │    resolution → Save ~$100/month       │
  └─────────────────────────────────────────┘
```

### 9.3 Time-Series Analysis

**User Journey:**

```
User: "Show me monthly costs for the last 6 months"

System generates:
  SQL: SELECT DATE_TRUNC('month', date) AS month, SUM(cost)
       GROUP BY month
       ORDER BY month

User sees:
  ┌─────────────────────────────────────────┐
  │ Your monthly costs show declining trend │
  │                                         │
  │ Jun 2025: $6,234                       │
  │ Jul 2025: $5,876 ↓                     │
  │ Aug 2025: $5,432 ↓                     │
  │ Sep 2025: $5,123 ↓                     │
  │ Oct 2025: $4,987 ↓                     │
  │ Nov 2025: $4,654 ↓                     │
  │                                         │
  │ [Line Chart showing downward trend]    │
  │                                         │
  │ Insights:                               │
  │ • 25% cost reduction over 6 months     │
  │ • Optimization efforts working well    │
  └─────────────────────────────────────────┘
```

### 9.4 Complex Multi-Filter Query

**Advanced Example:**

```
User: "Show me EC2 costs in us-east-1 for Linux instances, 
       excluding taxes and credits, for October 2025"

System processes:
  • Service: EC2
  • Region: us-east-1
  • Platform: Linux
  • Exclude: taxes, credits
  • Time: October 2025

Generated SQL:
  SELECT line_item_usage_type, SUM(cost)
  FROM cur_data
  WHERE line_item_product_code = 'AmazonEC2'
    AND product_region_code = 'us-east-1'
    AND line_item_usage_type LIKE '%Linux%'
    AND line_item_line_item_type = 'Usage'
    AND date >= '2025-10-01'
    AND date <= '2025-10-31'
  GROUP BY line_item_usage_type

User sees:
  ┌─────────────────────────────────────────┐
  │ EC2 Linux costs in us-east-1 (Oct):    │
  │                                         │
  │ • t3.medium: $1,234                    │
  │ • t3.large: $987                       │
  │ • m5.xlarge: $765                      │
  │                                         │
  │ Total: $2,986 (taxes/credits excluded) │
  └─────────────────────────────────────────┘
```

---

## 10. Development Guide

### 10.1 Setting Up Development Environment

**Prerequisites:**

```bash
# Install system dependencies
brew install python@3.11 node postgresql docker

# Verify installations
python3 --version  # 3.11+
node --version     # 18+
docker --version
```

**Backend Setup:**

```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your AWS credentials

# Run migrations
alembic upgrade head

# Start backend
uvicorn main:app --reload --port 8000
```

**Frontend Setup:**

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm start  # Runs on port 3000
```

**Database:**

```bash
# Start PostgreSQL via Docker
docker-compose up -d postgres

# Or use local PostgreSQL
createdb finops_dev
```

### 10.2 Project Structure

```
finops-orchestrator/
├── backend/
│   ├── agents/                    # Query orchestration
│   │   ├── multi_agent_workflow.py   # Main workflow
│   │   └── execute_query_v2.py       # Query executor
│   │
│   ├── api/                       # API endpoints
│   │   ├── chat.py                   # Chat endpoint
│   │   ├── health.py                 # Health checks
│   │   └── athena_queries.py         # Direct SQL
│   │
│   ├── services/                  # Business logic
│   │   ├── text_to_sql_service.py    # LLM SQL generation
│   │   ├── llm_service.py            # Bedrock integration
│   │   ├── athena_executor.py        # Athena client
│   │   ├── conversation_manager.py   # Context management
│   │   ├── response_formatter.py     # Output formatting
│   │   ├── chart_recommendation.py   # Chart selection
│   │   └── chart_data_builder.py     # Chart data prep
│   │
│   ├── models/                    # Data models
│   │   ├── schemas.py                # Pydantic models
│   │   └── database_models.py        # SQLAlchemy models
│   │
│   ├── config/                    # Configuration
│   │   └── settings.py               # Environment config
│   │
│   ├── utils/                     # Utilities
│   │   ├── date_parser.py            # Date handling
│   │   └── logging.py                # Structured logging
│   │
│   └── main.py                    # FastAPI app
│
├── frontend/
│   └── src/
│       ├── components/
│       │   └── Chat/
│       │       ├── ChatInterface.tsx  # Main UI
│       │       ├── MessageList.tsx    # Message display
│       │       └── ChartDisplay.tsx   # Chart rendering
│       │
│       ├── api/
│       │   └── chatApi.ts            # API client
│       │
│       └── App.tsx                   # Root component
│
├── infrastructure/                # IaC
│   ├── cloudformation/               # AWS CloudFormation
│   └── sql/                          # Database schemas
│
├── scripts/                       # Operational scripts
│   ├── deployment/                   # Deploy scripts
│   └── setup/                        # Setup scripts
│
└── tests/                         # Test suite
    ├── test_chat.py
    ├── test_text_to_sql.py
    └── test_athena.py
```

### 10.3 Adding New Features

**Example: Add a new chart type**

**Step 1: Update Chart Engine**

```python
# backend/services/chart_recommendation.py

def recommend_charts(intent, data_results, extracted_params):
    # Add new condition
    if intent == "resource_utilization":
        return [{
            "type": "gauge",  # New chart type
            "title": "Resource Utilization",
            "data": data_results
        }]
```

**Step 2: Update Chart Builder**

```python
# backend/services/chart_data_builder.py

def build_chart_data(chart_specs, data_results, conv_context):
    for spec in chart_specs:
        if spec["type"] == "gauge":
            # Build gauge chart data
            chart_data = {
                "type": "gauge",
                "data": {
                    "value": data_results[0]["utilization"],
                    "max": 100
                }
            }
```

**Step 3: Add Frontend Rendering**

```typescript
// frontend/src/components/Chat/ChartDisplay.tsx

function renderChart(chart: ChartSpec) {
  switch (chart.type) {
    case 'gauge':
      return <GaugeChart data={chart.data} />;
    // ... other cases
  }
}
```

### 10.4 Debugging Tips

**Enable Debug Logging:**

```python
# backend/config/settings.py
LOG_LEVEL = "DEBUG"  # Change from INFO

# Now you'll see detailed logs
logger.debug("SQL generated", sql=sql_query)
```

**Test LLM Prompts:**

```python
# Quick script to test prompts
from services.llm_service import llm_service

async def test_prompt():
    response = await llm_service.call_llm(
        prompt="Show EC2 costs for last month",
        system_prompt="You are an SQL generator"
    )
    print(response)

import asyncio
asyncio.run(test_prompt())
```

**Debug SQL Queries:**

```python
# Add to athena_executor.py
logger.info("Executing SQL", query=sql_query)

# Check results
logger.info("Query results", 
           row_count=len(results),
           sample=results[:3])
```

---

## 11. Testing

### 11.1 Test Structure

```
tests/
├── test_chat.py                   # API endpoint tests
├── test_text_to_sql.py           # LLM SQL generation tests
├── test_athena.py                # Athena execution tests
├── test_conversation_manager.py  # Context tests
└── test_chart_engine.py          # Chart recommendation tests
```

### 11.2 Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_chat.py

# Run with coverage
pytest --cov=backend --cov-report=html

# Run specific test
pytest tests/test_chat.py::test_simple_query
```

### 11.3 Writing Tests

**Example: Test Text-to-SQL**

```python
# tests/test_text_to_sql.py

import pytest
from backend.services.text_to_sql_service import text_to_sql_service

@pytest.mark.asyncio
async def test_simple_cost_query():
    """Test basic cost query generates valid SQL"""
    
    sql, metadata = await text_to_sql_service.generate_sql(
        user_query="Show me EC2 costs for last month",
        conversation_history=[],
        previous_context={}
    )
    
    # Assertions
    assert "SELECT" in sql
    assert "AmazonEC2" in sql
    assert metadata["query_type"] == "breakdown"
    assert "explanation" in metadata
```

**Example: Test API Endpoint**

```python
# tests/test_chat.py

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_chat_endpoint():
    """Test chat endpoint returns valid response"""
    
    response = client.post("/api/v1/chat", json={
        "message": "Show me my costs",
        "conversation_id": None
    })
    
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "conversation_id" in data
```

---

## 12. Deployment

### 12.1 Production Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    AWS Cloud                            │
│                                                         │
│  ┌──────────────┐                                      │
│  │ Route 53     │ DNS                                  │
│  └──────┬───────┘                                      │
│         │                                               │
│  ┌──────▼────────────────────────────────────────┐    │
│  │   Application Load Balancer (ALB)             │    │
│  │   • SSL/TLS termination                        │    │
│  │   • Health checks                              │    │
│  └──────┬────────────────────────────────────────┘    │
│         │                                               │
│  ┌──────▼────────────────────────────────────────┐    │
│  │   ECS Fargate Cluster                         │    │
│  │                                                │    │
│  │   ┌─────────────┐    ┌─────────────┐         │    │
│  │   │  Backend    │    │  Frontend   │         │    │
│  │   │  Container  │    │  Container  │         │    │
│  │   │  (FastAPI)  │    │  (Nginx)    │         │    │
│  │   └─────────────┘    └─────────────┘         │    │
│  └───────────────────────────────────────────────┘    │
│         │                      │                       │
│  ┌──────▼──────┐        ┌────▼─────┐                 │
│  │  RDS        │        │  S3      │                  │
│  │  PostgreSQL │        │  • CUR   │                  │
│  └─────────────┘        │  • Assets│                  │
│                         └──────────┘                  │
│                                                         │
│  External Services:                                    │
│  • AWS Bedrock (LLM)                                  │
│  • AWS Athena (Queries)                               │
└─────────────────────────────────────────────────────────┘
```

### 12.2 Deployment Process

**Using Automated Script:**

```bash
# Complete deployment
./deploy.sh deploy

# Update existing deployment
./deploy.sh update

# The script handles:
# 1. Infrastructure provisioning (CloudFormation)
# 2. Docker image building
# 3. ECR push
# 4. ECS service deployment
# 5. Health checks
```

**Manual Deployment Steps:**

```bash
# 1. Build Docker images
docker build -t finops-backend:latest ./backend
docker build -t finops-frontend:latest ./frontend

# 2. Tag for ECR
aws ecr get-login-password | docker login --username AWS ...
docker tag finops-backend:latest $ECR_REPO/backend:latest

# 3. Push to ECR
docker push $ECR_REPO/backend:latest

# 4. Update ECS service
aws ecs update-service \
  --cluster finops-cluster \
  --service finops-backend \
  --force-new-deployment
```

### 12.3 Environment Configuration

**Production `.env`:**

```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIAXXXXXXXX
AWS_SECRET_ACCESS_KEY=XXXXXXXX

# Bedrock
BEDROCK_MODEL_ID=us.amazon.nova-pro-v1:0
BEDROCK_REGION=us-east-1

# Athena
ATHENA_DATABASE=cost_usage_db
ATHENA_TABLE=cur_data
ATHENA_OUTPUT_LOCATION=s3://finops-results/

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@rds-host:5432/finops

# Application
ENVIRONMENT=production
LOG_LEVEL=INFO
ALLOWED_ORIGINS=https://finops.company.com
```

### 12.4 Monitoring

**Key Metrics:**

1. **API Performance**
   - Request latency
   - Error rate
   - Requests per minute

2. **LLM Usage**
   - Token consumption
   - Cost per query
   - Success rate

3. **Athena Queries**
   - Query execution time
   - Data scanned
   - Query failures

**CloudWatch Dashboard:**

```python
# Automatic metrics via Prometheus middleware
from prometheus_client import Counter, Histogram

request_count = Counter('http_requests_total', 
                       ['method', 'endpoint', 'status'])

request_duration = Histogram('http_request_duration_seconds',
                             'HTTP request duration')
```

---

## Appendix A: Common Patterns

### Pattern 1: Adding a New LLM Prompt

```python
# 1. Define the prompt template
NEW_PROMPT = """
You are a [role].

[Instructions]

User Query: {user_query}

Response format:
{
  "key": "value"
}
"""

# 2. Create service method
async def generate_something(query: str) -> Dict:
    response = await llm_service.call_llm(
        prompt=NEW_PROMPT.format(user_query=query),
        system_prompt="You are an expert..."
    )
    return json.loads(response)
```

### Pattern 2: Adding Conversation Context

```python
# 1. Update ConversationManager
def get_context_for_query(self, thread_id: str) -> Dict:
    messages = self.get_recent_messages(thread_id, limit=10)
    
    # Extract new context type
    new_context = extract_new_context(messages)
    
    return {
        **existing_context,
        "new_field": new_context
    }

# 2. Use in LLM prompt
prompt = f"""
Previous context: {context.get('new_field')}
User query: {query}
"""
```

### Pattern 3: Adding a New API Endpoint

```python
# backend/api/new_endpoint.py

from fastapi import APIRouter
router = APIRouter()

@router.post("/new-feature")
async def new_feature(request: RequestModel):
    """
    New feature endpoint.
    """
    result = await process_request(request)
    return ResponseModel(result=result)

# backend/main.py
from api import new_endpoint
app.include_router(new_endpoint.router, prefix="/api/v1")
```

---

## Appendix B: Troubleshooting

### Issue: LLM Returns Invalid JSON

**Problem:** JSON parsing fails

**Solution:**
```python
# Add cleaning step
response = llm_response.strip()
if response.startswith("```"):
    response = "\n".join([
        line for line in response.split("\n")
        if not line.startswith("```")
    ])
```

### Issue: Athena Query Timeout

**Problem:** Query takes >30 seconds

**Solutions:**
1. Add partition filters
2. Limit date range
3. Increase timeout
4. Optimize SQL (avoid SELECT *)

### Issue: Context Not Inherited

**Problem:** Follow-up query doesn't use previous context

**Debug:**
```python
# Check what context is available
logger.info("Context", context=conversation_manager.get_context_for_query(thread_id))

# Verify LLM receives it
logger.info("Prompt", prompt=prompt)
```

---

## Appendix C: Glossary

**Terms:**

- **LLM**: Large Language Model - AI trained on text
- **Prompt**: Input text sent to LLM
- **CUR**: Cost and Usage Report - AWS billing data
- **Athena**: AWS serverless SQL query engine
- **Bedrock**: AWS managed LLM service
- **FastAPI**: Python async web framework
- **Conversation Thread**: Sequence of related messages
- **Context**: Information carried between queries
- **Chart Spec**: JSON definition of chart structure
- **SQL Generation**: Converting natural language to SQL
- **Token**: Unit of text for LLM (roughly a word)

---

## Appendix D: Resources

**Documentation:**
- AWS Athena: https://docs.aws.amazon.com/athena/
- AWS Bedrock: https://docs.aws.amazon.com/bedrock/
- FastAPI: https://fastapi.tiangolo.com/
- React: https://react.dev/

**Internal Docs:**
- [AWS Deployment Guide](./docs/AWS_DEPLOYMENT_GUIDE.md)
- [Quick Start](./docs/QUICK_START.md)
- [Troubleshooting](./docs/TROUBLESHOOTING.md)

**Support:**
- Technical Lead: amit.kumar2@dazn.com
- Slack: #finops-platform

---

**End of Developer Guide**

*This guide is maintained by the FinOps Platform team. Last updated: December 4, 2025*
