"""One-off validation of both configured editorial providers, no Telegram posts.

Never print API keys, response bodies or request URLs containing secrets.
"""
from __future__ import annotations

import os
import sys
import requests

def probe_groq() -> bool:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        print("Groq: key missing")
        return False
    print("Groq: key configured")
    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": "Reply only with a valid JSON object."},
            {"role": "user", "content": "Return JSON {\"ok\":true,\"note\":\"проверка\"}. Nothing else."},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "reasoning_effort": "low",
        "include_reasoning": False,
        "max_completion_tokens": 160,
        "stream": False,
    }
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=payload, timeout=22,
        )
        if r.status_code != 200:
            print(f"Groq: HTTP {r.status_code} (response body withheld)")
            return False
        result = r.json()
        content = result["choices"][0]["message"]["content"]
        if not isinstance(content, str) or "ok" not in content:
            print("Groq: unexpected format")
            return False
        print("Groq: success, JSON editorial API ready")
        return True
    except (requests.RequestException, KeyError, TypeError, ValueError, IndexError) as exc:
        print("Groq: request or parsing error:", type(exc).__name__)
        return False

def probe_gemini() -> bool:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        print("Gemini: key missing")
        return False
    print("Gemini: key configured")
    model = "gemini-3.5-flash-lite"
    payload = {
        "contents": [{"role": "user", "parts": [{
            "text": "Верни JSON с одним полем ok=true. Больше ничего не добавляй."
        }]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 256,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {"ok": {"type": "BOOLEAN"}},
                "required": ["ok"],
            },
        },
    }
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key},
            json=payload, timeout=22,
        )
        if r.status_code != 200:
            print(f"Gemini: HTTP {r.status_code} (response body withheld)")
            return False
        result = r.json()
        txt = result["candidates"][0]["content"]["parts"][0].get("text", "")
        if not isinstance(txt, str) or "ok" not in txt:
            print("Gemini: unexpected format")
            return False
        print("Gemini: success, structured output API ready")
        return True
    except (requests.RequestException, KeyError, TypeError, ValueError, IndexError) as exc:
        print("Gemini: request or parsing error:", type(exc).__name__)
        return False

if __name__ == "__main__":
    groq = probe_groq()
    gemini = probe_gemini()
    print(f"Summary: Groq={'OK' if groq else 'NOT_READY'}, Gemini={'OK' if gemini else 'NOT_READY'}")
    if not groq and not gemini:
        sys.exit(1)
