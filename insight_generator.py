import requests

OLLAMA_URL   = "http://localhost:11434/api/generate"
MODEL_NAME   = "gemma3:1b"
#MODEL_NAME   = "gemma3:4b"

PROMPT_TEMPLATE = """
You are an assistant for a credit-union sales rep. Review the member’s transactions
and suggest sales opportunities or anomalies that the rep can verify in the core system.

Example 1 transactions:
2025-12-12: Coffee Shop ($4.50)
2025-12-12: Coffee Shop ($4.50)

Example 1 insight:
1. A duplicate $4.50 charge at Coffee Shop on 2025-12-12 indicates a possible double posting.

Example 2 transactions:
2025-11-30: Savings Deposit ($5,000.00)
2025-12-01: Savings Deposit ($5,000.00)

Example 2 insight:
1. Two $5,000.00 savings deposits on 2025-11-30 and 2025-12-01 suggest a large influx that could qualify for a CD offer.

Example 3 transactions:
2025-12-10: Home Depot ($245.67)
2025-12-11: Home Depot ($312.45)
2025-12-12: Home Depot ($129.99)

Example 3 insight:
1. Three Home Depot purchases on 2025-12-10 ($245.67), 2025-12-11 ($312.45), and 2025-12-12 ($129.99) signal ongoing home improvement spending—consider discussing a home equity line.

Now, given these transactions:
{transactions}

Generate exactly five numbered insights (1–5), each 1–2 sentences.
Each insight must:
- Cite a specific transaction (date, merchant, amount).
- Highlight a sales opportunity or anomaly the rep can look up.
- Omit any intros or conclusions—return only the numbered list.

Format exactly as:

1. …
2. …
3. …
4. …
5. …
"""


def format_transactions(transactions):
    """
    Format each transaction dict into:
      YYYY-MM-DD: Description ($X,XXX.XX)
    """
    lines = []
    for tx in transactions:
        date = tx.get('date', '')
        desc = tx.get('description', '')
        amt  = tx.get('amount', '')
        lines.append(f"{date}: {desc} ({amt})")
    return "\n".join(lines)

def generate_insights(transactions):
    """
    Calls the local Ollama endpoint to get five detailed insights.
    Returns a list of five strings, each beginning with '1.', '2.', … '5.'.
    """
    prompt = PROMPT_TEMPLATE.format(
        transactions=format_transactions(transactions)
    )

    resp = requests.post(OLLAMA_URL, json={
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False
    })

    if resp.status_code != 200:
        return ["Insight generation failed."]

    text = resp.json().get("response", "")
    insights = []
    for line in text.splitlines():
        line = line.strip()
        # pick only numbered lines 1.–5.
        if any(line.startswith(f"{i}.") for i in range(1, 6)):
            insights.append(line)
        if len(insights) == 5:
            break

    return insights
