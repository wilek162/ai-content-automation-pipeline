"""Optional SDK adapters; the runner owns reservations and retry policy."""

import json
import os


def call(stage, request, config):
    provider = config["provider"]
    key_name = "GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
    if not os.environ.get(key_name, "").strip():
        raise ValueError(f"Set {key_name} before selecting a live provider")
    try:
        if provider == "gemini":
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=os.environ[key_name],
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(attempts=1), timeout=60000
                ),
            )
            try:
                response = client.models.generate_content(
                    model=config["model"],
                    contents=json.dumps(request["input"]),
                    config=types.GenerateContentConfig(
                        system_instruction=request["prompt"],
                        max_output_tokens=config["max_output_tokens"],
                        response_mime_type="application/json",
                        response_json_schema=request["schema"],
                        thinking_config=types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                return response.text or ""
            finally:
                client.close()
        import anthropic

        with anthropic.Anthropic(api_key=os.environ[key_name], max_retries=0, timeout=60) as client:
            response = client.messages.create(
                model=config["model"],
                max_tokens=config["max_output_tokens"],
                system=request["prompt"],
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(request["input"])
                        + "\nReturn JSON matching this schema: "
                        + json.dumps(request["schema"]),
                    }
                ],
            )
            return "".join(block.text for block in response.content if block.type == "text")
    except ImportError as exc:
        raise ValueError(f"Install the '{provider}' optional extra before live execution") from exc
