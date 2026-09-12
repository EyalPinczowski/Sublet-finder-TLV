from __future__ import annotations

import json

from google import genai
from google.genai import types

from .config import Config

MODEL = "gemini-flash-latest"  # free-tier eligible

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
"""

SCREEN_SCHEMA = {
    "type": "object",
    "properties": {
        "is_seeking_apartment": {"type": "boolean"},
        "fit_score": {"type": "integer"},
        "notes": {"type": "string"},
    },
    "required": ["is_seeking_apartment", "fit_score", "notes"],
}


def screen_post(config: Config, post_text: str) -> dict:
    client = genai.Client(api_key=config.gemini_api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=(
            f"Apartment details:\n{config.apartment_summary}\n\n"
            f"Post text:\n{post_text}"
        ),
        config=types.GenerateContentConfig(
            system_instruction=SCREEN_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=SCREEN_SCHEMA,
        ),
    )
    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, TypeError):
        return {
            "is_seeking_apartment": False,
            "fit_score": 0,
            "notes": f"Unparseable response: {response.text}",
        }
