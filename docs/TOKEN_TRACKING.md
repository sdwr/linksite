# Token Usage Tracking - Anthropic Claude API

## Overview

This document describes how token usage is tracked from the Anthropic Claude API and how it's implemented in the Linksite AI Engine.

## How Anthropic Reports Token Usage

The Anthropic Messages API returns token usage in the response body under the `usage` field:

```json
{
  "id": "msg_...",
  "type": "message",
  "role": "assistant",
  "content": [...],
  "model": "claude-sonnet-4-20250514",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 1234,
    "output_tokens": 567
  }
}
```

### Fields Returned

| Field | Description |
|-------|-------------|
| `input_tokens` | Number of tokens in the input (system prompt + user message) |
| `output_tokens` | Number of tokens in the model's response |

**Note:** There are no usage headers in the response - all usage data is in the response body.

## Our Implementation

### Database Schema

We track token usage in the `ai_token_usage` table:

```sql
CREATE TABLE ai_token_usage (
    id uuid PRIMARY KEY,
    run_id uuid REFERENCES ai_runs(id),
    model text NOT NULL,
    input_tokens integer DEFAULT 0,
    output_tokens integer DEFAULT 0,
    total_tokens integer DEFAULT 0,
    estimated_cost_usd numeric(10,6) DEFAULT 0,
    operation_type text,  -- 'summary', 'comment', 'description', 'tags', 'discovery'
    link_id bigint REFERENCES links(id),
    created_at timestamptz DEFAULT now()
);
```

### Cost Calculation

We calculate estimated costs based on published pricing (as of 2024):

```python
MODEL_PRICING = {
    "claude-3-5-haiku-20241022": {"input": 0.25, "output": 1.25},  # per 1M tokens
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
}
```

Cost formula:
```
cost = (input_tokens * input_price + output_tokens * output_price) / 1,000,000
```

### Tracking Flow

1. Every `_call_claude()` invocation extracts usage from the response
2. Token usage is recorded to `ai_token_usage` table
3. Aggregate stats available via `/api/ai/token-usage` endpoint
4. Run-level stats show in `/api/ai/stats`

### API Endpoints

#### GET /api/ai/token-usage?days=30

Returns usage statistics for the specified period:

```json
{
  "period_days": 30,
  "total_calls": 156,
  "total_input_tokens": 234567,
  "total_output_tokens": 45678,
  "total_tokens": 280245,
  "total_cost_usd": 1.2345,
  "by_model": {
    "claude-3-5-haiku-20241022": {"tokens": 200000, "cost": 0.5, "calls": 120},
    "claude-sonnet-4-20250514": {"tokens": 80245, "cost": 0.7345, "calls": 36}
  },
  "by_operation": {
    "summary": {"tokens": 50000, "cost": 0.15, "calls": 50},
    "comment": {"tokens": 100000, "cost": 0.6, "calls": 60},
    "description": {"tokens": 30000, "cost": 0.1, "calls": 30},
    "tags": {"tokens": 20000, "cost": 0.05, "calls": 16}
  }
}
```

#### GET /api/ai/stats

Includes token usage in the overall stats response.

#### GET /api/ai/runs/{run_id}

Shows detailed token usage for a specific run.

## Future Improvements

1. **Alerts**: Add alerting when daily/monthly spend exceeds thresholds
2. **Budgets**: Implement per-operation budgets to control costs
3. **Streaming**: For streaming responses, track tokens differently (partial updates)
4. **Caching**: Consider caching common prompts to reduce token usage
5. **Optimization**: Track token efficiency (useful output per input token)

## References

- [Anthropic API Documentation - Messages](https://docs.anthropic.com/en/api/messages)
- [Anthropic Pricing](https://www.anthropic.com/pricing)
