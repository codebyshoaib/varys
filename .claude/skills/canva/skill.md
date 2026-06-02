# Canva Design Skill

Kamil's on-demand Canva design interface. Triggered when Kamil asks to create
any visual content: post, carousel, thumbnail, banner, graphic, design.

## Trigger phrases
"make a post", "create a carousel", "design a thumbnail", "make a banner",
"create a graphic", "make an image for", "design something for", "canva"

## What this skill does
Collects a complete design brief, then runs `kamil_canva_agent.py` to create
designs for all 3 channels (LinkedIn, Instagram, YouTube) in parallel with
self-eval and retry built in.

## Required brief fields
- **topic**: What is this design about? (e.g. "Django REST Framework tips")
- **copy**: The headline/main text for the design (max ~8 words)
- **brand_kit_id**: From `CANVA_BRAND_KIT_ID` env var (check `.env` or ask Kamil)

## Process

1. If any required field is missing, ask Kamil for it (one question at a time).
2. Once brief is complete, run:

```bash
python3 /home/oye/Documents/free_work/personal-agent-v2/agents/kamil_canva_agent.py \
  --topic "<topic>" \
  --copy "<copy>" \
  --brand-kit-id "$CANVA_BRAND_KIT_ID"
```

3. Report results: for each channel+format, show design_url, eval scores, and status.
4. If any status is `Needs-Kamal`, tell Kamil which ones and why (include scores).
5. If any status is `draft`, confirm designs are saved to Notion Design DB.

## Auth failure handling
If the agent returns a Canva auth error, tell Kamil:
"Canva needs re-authentication. In this Claude session, I'll call the Canva MCP
authenticate tool now."
Then call `mcp__claude_ai_Canva__authenticate` and `mcp__claude_ai_Canva__complete_authentication`.
