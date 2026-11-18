"""Writing a reply in your voice with Claude."""

import os

import anthropic

from . import conversations

MODEL = os.environ.get("SAVANNAH_MODEL", "claude-sonnet-5-5")


class DraftError(Exception):
    pass


class KeyRejected(DraftError):
    """The Claude key was refused."""


SYSTEM = """You write replies to short-term rental guests on behalf of the host, {host}.

Write exactly the way {host} writes. Copy the tone, length, greeting, sign-off and emoji habits you see in the past replies below.
Only use facts that appear in this conversation or in {host}'s past replies for the same home.
If the guest asks for something you can't find (a door code, a specific time, a price, a yes/no decision), put a short note in square brackets like [ADD: wifi password] instead of guessing.
Never promise refunds, discounts or exceptions to house rules unless {host} has clearly done so before in a past reply.
Reply with the message text only. No preamble, no quotes around it."""

ADJUST = {
    "shorter": "Make it noticeably shorter.",
    "warmer": "Make it a bit warmer and friendlier.",
    "detail": "Add a bit more helpful detail.",
}


def _format_examples(examples: list[dict]) -> str:
    blocks = []
    for i, ex in enumerate(examples, 1):
        blocks.append(f"<example {i} home=\"{ex['property']}\">\nGuest: {ex['guest']}\nYou: {ex['host']}\n</example>")
    return "\n\n".join(blocks) or "(No past replies yet. Write in a friendly, concise host voice.)"


def _format_thread(messages: list[dict]) -> str:
    lines = []
    for m in messages[-14:]:
        who = "Guest" if m["role"] == "guest" else "You"
        lines.append(f"{who} ({m['at'][:16].replace('T', ' ')}): {m['body']}")
    return "\n".join(lines)


async def write_reply(api_key: str, host_name: str, reservation: dict, messages: list[dict], adjust: str = "") -> str:
    last_guest = "\n".join(m["body"] for m in messages[-3:] if m["role"] == "guest") or messages[-1]["body"]
    examples = conversations.similar(last_guest, reservation.get("property_name", ""))

    prompt = f"""Past replies you've written to guests with similar questions:

{_format_examples(examples)}

Now the current conversation.
Home: {reservation.get('property_name') or 'unknown'}
Guest: {reservation.get('guest_name')}  ·  Booked on: {reservation.get('platform') or 'unknown'}
Stay: {reservation.get('arrival')} to {reservation.get('departure')}

<conversation>
{_format_thread(messages)}
</conversation>

Write your next reply to the guest. {ADJUST.get(adjust, '')}"""

    return await _ask(api_key, SYSTEM.format(host=host_name or "the host"), prompt)


IMPROVE = """You polish replies that {host}, a short-term rental host, typed to a guest.

Keep {host}'s meaning, every fact, time, number, name and promise exactly as written. Never add new facts or promises.
Fix spelling, grammar and punctuation, make it clear and friendly, and match {host}'s usual voice from the past replies.
Keep any [ADD: ...] notes as they are.
Reply with the improved message text only. No preamble, no quotes around it."""


async def improve_reply(api_key: str, host_name: str, reservation: dict, messages: list[dict], typed: str, adjust: str = "") -> str:
    """Make what you typed better, instead of starting over."""
    context = "\n".join(m["body"] for m in messages[-3:] if m["role"] == "guest") or typed
    examples = conversations.similar(context, reservation.get("property_name", ""))[:4]
    prompt = f"""A few of your past replies, for your voice:

{_format_examples(examples)}

The conversation so far (home: {reservation.get('property_name') or 'unknown'}, guest: {reservation.get('guest_name')}):
<conversation>
{_format_thread(messages) if messages else '(no messages yet)'}
</conversation>

What you typed:
<typed>
{typed}
</typed>

Improve what you typed. {ADJUST.get(adjust, '')}"""
    return await _ask(api_key, IMPROVE.format(host=host_name or "the host"), prompt)


async def _ask(api_key: str, system: str, prompt: str) -> str:
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        res = await client.messages.create(
            model=MODEL,
            max_tokens=700,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        raise DraftError("The Claude key wasn't accepted. Paste a fresh key in Settings.")
    except anthropic.PermissionDeniedError:
        raise DraftError("The Claude key can't be used right now. Check your Claude account's billing.")
    except anthropic.APIConnectionError:
        raise DraftError("Can't reach Claude. Check this computer's internet connection.")
    except anthropic.APIStatusError as e:
        raise DraftError(f"Claude couldn't write a draft ({e.status_code}). Try Rewrite in a minute.")
    finally:
        await client.close()
    text = "".join(b.text for b in res.content if getattr(b, "type", "") == "text").strip()
    if not text:
        raise DraftError("Claude returned an empty draft. Try Rewrite.")
    return text


async def test_key(api_key: str) -> None:
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        await client.messages.create(model=MODEL, max_tokens=5, messages=[{"role": "user", "content": "Say ok"}])
    except anthropic.AuthenticationError:
        raise KeyRejected("That Claude key wasn't accepted. Check you copied all of it.")
    except anthropic.PermissionDeniedError:
        raise DraftError("That key works but can't be used yet. Add credit under Billing at console.anthropic.com.")
    except anthropic.APIConnectionError:
        raise DraftError("Can't reach Claude. Check this computer's internet connection.")
    except anthropic.APIStatusError as e:
        raise DraftError(f"Claude said no ({e.status_code}). Check your account at console.anthropic.com.")
    finally:
        await client.close()
