"""Mask -> call a model -> restore, with and without streaming.

pip install saaf openai
python examples/python/quickstart.py
"""

from __future__ import annotations

import os

from saaf import Policy, Saaf

prompt = "Customer Smt. Lakshmi Iyer, PAN ABCPE1234F, mobile +91 98765 43210, wants a KYC summary."

saaf = Saaf(Policy(mode="enforce"))
masked = saaf.mask(prompt)
print("sent to model:", masked.text)
print("summary      :", masked.summary())

if os.environ.get("OPENAI_API_KEY"):
    from openai import OpenAI

    client = OpenAI()
    reply = client.chat.completions.create(
        model=os.environ.get("MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": masked.text}],
    )
    print("restored     :", saaf.restore(reply.choices[0].message.content or "").text)

    stream = client.chat.completions.create(
        model=os.environ.get("MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": masked.text}],
        stream=True,
    )
    restorer = saaf.stream_restorer()
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            print(restorer.feed(delta), end="", flush=True)
    print(restorer.flush())
else:
    fake_reply = "Summary for [PERSON_1]: PAN [pan_1] verified; contact PHONE_IN_1."
    print("restored     :", saaf.restore(fake_reply).text)
