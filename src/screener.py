from __future__ import annotations

import json

from anthropic import Anthropic

from .config import Config

MODEL = "claude-sonnet-5"

SCREEN_SYSTEM_PROMPT = """\
You screen Facebook group posts to find people looking for a sublet apartment \
that could match a specific apartment listing. You will be given the \
apartment's details and a single post's text (which may be in Hebrew, \
English, or mixed). Decide:

1. Is the poster looking FOR an apartment/room to rent or sublet (not \
   offering one, not asking about something unrelated)?
2. If so, how well do they fit the apartment (dates, budget, area, \
   household size, pets)? Score 0-100 (0 = clearly not looking for housing \
   or offering one themselves, 100 = excellent match).
3. Briefly note any extracted details (desired dates, budget, number of \
   people, area preference) and why the score is what it is.

Respond ONLY with JSON: {"is_seeking_apartment": bool, "fit_score": int, "notes": str}
"""


def screen_post(config: Config, post_text: str) -> dict:
    client = Anthropic(api_key=config.anthropic_api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=SCREEN_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Apartment details:\n{config.apartment_summary}\n\n"
                    f"Post text:\n{post_text}"
                ),
            }
        ],
    )
    text = message.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"is_seeking_apartment": False, "fit_score": 0, "notes": f"Unparseable response: {text}"}
