from __future__ import annotations

from google import genai
from google.genai import types

from .config import Config

MODEL = "gemini-flash-latest"  # free-tier eligible

DRAFT_SYSTEM_PROMPT = """\
You write short, warm, natural outreach messages (in the same language as \
the post you're replying to — Hebrew or English) from an apartment owner to \
someone who posted in a Facebook group looking for a sublet. Reference \
something specific from their post so it doesn't read as copy-pasted spam. \
Mention the key apartment details relevant to them (price, dates, area) and \
invite them to reply if interested. Keep it under 80 words. Do not include a \
greeting placeholder like [Name] — use "Hi!" or the Hebrew equivalent if \
their name isn't clearly known. Output only the message text, nothing else.
"""


def draft_message(config: Config, post_text: str, screening_notes: str) -> str:
    client = genai.Client(api_key=config.gemini_api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=(
            f"Apartment details:\n{config.apartment_summary}\n\n"
            f"Their post:\n{post_text}\n\n"
            f"Screening notes:\n{screening_notes}"
        ),
        config=types.GenerateContentConfig(
            system_instruction=DRAFT_SYSTEM_PROMPT,
            max_output_tokens=300,
        ),
    )
    return response.text.strip()
