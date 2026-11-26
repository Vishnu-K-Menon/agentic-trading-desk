# Agentic Trading Desk

## What it is

A live trading floor run by four autonomous AI traders. Each trader has $10,000 of paper money, its
own investing style and its own language model. Every hour while the US market is open they research,
propose trades to a risk desk, and trade. The dashboard shows who is winning and why.

It is a portfolio project about multi-agent systems and the Model Context Protocol (MCP), deployed
as a public Hugging Face Space.

## Who uses it

- **The owner**, on a laptop, several times a day: checks the standings, reads why a trader did what
  it did, starts a round, swaps a model or edits a strategy.
- **Visitors to the public Space** (recruiters, other engineers), for a minute or two: need to grasp
  at once what this is, who is ahead and whether any trader beats the market. They can look, not change.

## The traders

| Trader | Style | Default model |
| --- | --- | --- |
| Warren Patience | Value, long term | GPT 5.5 |
| George Bold | Aggressive macro, contrarian | Claude Sonnet 5.5 |
| Ray Systematic | Risk parity across asset classes | GPT 6 Luna |
| Cathie Crypto | Disruptive innovation, crypto ETFs | Claude Haiku 5.5 |

## Jobs, most frequent first

1. See the standings: each trader's value and return, and whether it beats the S&P 500.
2. Understand a trader: holdings, each trade with its rationale, what the risk desk decided, the
   closing appraisal of each session, what it has remembered.
3. Run the floor (owner only): start a round, pause or resume, change a model, edit a strategy, reset.

## Words of the trade

Round (one session for every trader), trading round and rebalancing round, risk desk, approved /
resized / rejected, holdings, cash, appraisal, research library, knowledge graph.

## Truths the interface must respect

- Prices on the free market data plan are the previous trading day's close. Say so; never imply live quotes.
- Every buy costs a 0.2% spread, so a fully invested trader starts about $20 down. That is not a loss in skill.
- This is paper money. Nothing here is investment advice.
- Changes need the admin token on the public Space; visitors are read-only.

## Platform

Web. Desktop first, usable on a phone.
