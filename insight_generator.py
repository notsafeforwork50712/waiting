import requests

OLLAMA_URL   = "http://localhost:11434/api/generate"
MODEL_NAME   = "gemma3:1b"
#MODEL_NAME   = "gemma3:4b"

PROMPT_TEMPLATE = """
You are a financial assistant at a credit union reviewing a member’s transaction history:

{transactions}

Generate **exactly five** numbered insights (1–5), each 1–2 sentences.  
**Each insight must**:
- Include at least one concrete example or numeric detail from the data (e.g. “spent $1,200 more on dining this month”).
- Be focused on patterns, trends, or anomalies.
- Omit any introductions, conclusions, or follow‑up questions—return only the numbered list.

Format **exactly** as:

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
