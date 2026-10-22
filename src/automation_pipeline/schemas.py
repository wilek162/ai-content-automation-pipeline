"""Versioned contracts validated locally for every provider."""

from jsonschema import Draft202012Validator


def obj(properties, required=None):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


TEXT = {"type": "string", "minLength": 1}
STRINGS = {"type": "array", "items": TEXT}
CLAIM = obj(
    {
        "id": {"type": "string", "pattern": "^[A-Za-z0-9_-]+$"},
        "sentence": TEXT,
        "source_id": TEXT,
        "source_excerpt": TEXT,
    }
)
SCHEMAS = {
    "research": obj({"claims": {"type": "array", "minItems": 1, "items": CLAIM}}),
    "outline": obj(
        {
            "title": TEXT,
            "sections": {
                "type": "array",
                "minItems": 1,
                "items": obj({"heading": TEXT, "points": STRINGS, "claim_ids": STRINGS}),
            },
        }
    ),
    "write": obj({"markdown": TEXT}),
    "format": obj(
        {
            "title": TEXT,
            "excerpt": TEXT,
            "slug": {"type": "string", "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$"},
            "tags": STRINGS,
        }
    ),
}
BUDGET = obj(
    {
        "enabled": {"type": "boolean"},
        "monthly_limit_usd": TEXT,
        "input_usd_per_million": TEXT,
        "output_usd_per_million": TEXT,
        "pricing_verified_on": TEXT,
        "model": TEXT,
    }
)
CONFIG = obj(
    {
        "schema_version": {"const": 1},
        "topic": TEXT,
        "locale": TEXT,
        "editorial_brief": TEXT,
        "target_words": {"type": "integer", "minimum": 100, "maximum": 5000},
        "provider": {"enum": ["fixture", "gemini", "anthropic"]},
        "model": TEXT,
        "max_output_tokens": {"type": "integer", "minimum": 128, "maximum": 16000},
        "source_manifest": TEXT,
        "allowed_source_hosts": {"type": "array", "minItems": 1, "items": TEXT},
        "output_dir": TEXT,
        "fixture_scenario": {"enum": ["default", "red", "revised"]},
        "word_count_tolerance": {"type": "number", "minimum": 0, "maximum": 1},
        "budget": BUDGET,
        "wordpress": obj({"category_ids": {"type": "array", "items": {"type": "integer", "minimum": 1}}}),
    },
    [
        "schema_version",
        "topic",
        "locale",
        "editorial_brief",
        "target_words",
        "provider",
        "max_output_tokens",
        "source_manifest",
        "allowed_source_hosts",
        "output_dir",
        "word_count_tolerance",
    ],
)
SOURCE_MANIFEST = {
    "type": "array",
    "minItems": 1,
    "items": obj(
        {
            "id": TEXT,
            "title": TEXT,
            "origin_url": TEXT,
            "text_file": TEXT,
            "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        }
    ),
}


def validate(value, schema):
    Draft202012Validator(schema).validate(value)
    return value
