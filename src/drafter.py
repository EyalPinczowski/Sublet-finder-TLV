from __future__ import annotations

from anthropic import Anthropic

from .config import Config

MODEL = "claude-sonnet-5"

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
    client = Anthropic(api_key=config.anthropic_api_key)
    message = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=DRAFT_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Apartment details:\n{config.apartment_summary}\n\n"
                    f"Their post:\n{post_text}\n\n"
                    f"Screening notes:\n{screening_notes}"
                ),
            }
        ],
    )
    return message.content[0].text.strip()
