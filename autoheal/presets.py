"""Deterministic lab datasets with an independent semantic validator."""
import copy
import math


SALES_DATA = [
    {"region": "North", "amount": "120.50"},
    {"region": "South", "amount": "80"},
    {"region": "North", "amount": "39.50"},
    {"region": "South", "amount": "N/A"},
    {"region": "West", "amount": "200.00"},
    {"region": "West", "amount": " -20 "},
    {"region": "North", "amount": ""},
    {"region": "South", "amount": "100.00"},
]
TEXT_DATA = ["AI heals code. Code helps AI!", "Reliable code, reliable results.", "AI + tests = reliable code."]
GRADES_DATA = [
    {"name": "Asha", "scores": [80, 90, 70]},
    {"name": "Kabir", "scores": [60, 75, 85]},
    {"name": "Mira", "scores": [95, 92, 98]},
    {"name": "Dev", "scores": [45, 55, 50]},
]

PRESETS = {
    "sales": {
        "id": "sales", "title": "Clean sales summary",
        "description": "Clean dirty numeric rows, preserve negative adjustments, and aggregate sales by region.",
        "prompt": "DATA is a list of sales dictionaries. Strip each amount and convert it to float. Reject and count every empty or non-numeric amount; preserve valid negative adjustments. Output a single JSON object with total (2 decimals), valid_rows, rejected_rows, by_region (2 decimals), and top_region. top_region is the region with the greatest aggregate total; choose the alphabetically first region only when greatest totals tie. Every input row must contribute to exactly one of valid_rows or rejected_rows.",
        "data": SALES_DATA,
        "expected": {"total": 520.0, "valid_rows": 6, "rejected_rows": 2, "by_region": {"North": 160.0, "South": 180.0, "West": 180.0}, "top_region": "South"},
        "challenge": "The controlled first attempt tries to sum raw strings and raises TypeError.",
        "seed_code": "total = sum(row['amount'] for row in DATA)\nprint(json.dumps({'total': total}))",
        "replay_code": """totals = {}
valid = 0
rejected = 0

for row in DATA:
    try:
        value = float(row['amount'].strip())
    except (ValueError, TypeError):
        rejected += 1
        continue
    valid += 1
    region = row['region']
    totals[region] = totals.get(region, 0.0) + value

result = {
    'total': round(sum(totals.values()), 2),
    'valid_rows': valid,
    'rejected_rows': rejected,
    'by_region': {
        region: round(total, 2)
        for region, total in sorted(totals.items())
    },
    'top_region': sorted(totals, key=lambda region: (-totals[region], region))[0],
}
print(json.dumps(result, indent=2))""",
    },
    "text": {
        "id": "text", "title": "Normalized text analytics",
        "description": "Count lowercase alphabetic tokens and produce stable frequency rankings.",
        "prompt": "DATA is a list of text documents. Tokenize using only contiguous ASCII letters A-Z or a-z, and lowercase each token. Output exactly one JSON object with document_count, token_count, unique_tokens, frequencies (all lowercase token counts), and top_tokens (up to 3 objects with token and count). Rank by count descending, then token ascending for ties.",
        "data": TEXT_DATA,
        "expected": {"document_count": 3, "token_count": 14, "unique_tokens": 7, "frequencies": {"ai": 3, "heals": 1, "code": 4, "helps": 1, "reliable": 3, "results": 1, "tests": 1}, "top_tokens": [{"token": "code", "count": 4}, {"token": "ai", "count": 3}, {"token": "reliable", "count": 3}]},
        "challenge": "The controlled first attempt calls a missing lowercase method and raises AttributeError.",
        "seed_code": "words = ' '.join(DATA).lowercase().split()\nprint(json.dumps({'token_count': len(words)}))",
        "replay_code": """import re
from collections import Counter

words = re.findall(r'[A-Za-z]+', ' '.join(DATA).lower())
counts = dict(Counter(words))
ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]

result = {
    'document_count': len(DATA),
    'token_count': len(words),
    'unique_tokens': len(counts),
    'frequencies': counts,
    'top_tokens': [
        {'token': token, 'count': count}
        for token, count in ranked
    ],
}
print(json.dumps(result, indent=2))""",
    },
    "grades": {
        "id": "grades", "title": "Weighted grade evaluation",
        "description": "Apply assessment weights, classify passing students, and calculate the class mean.",
        "prompt": "DATA is a list of students, each with name and 3 scores. Weights for the 3 scores are 0.2, 0.3, 0.5. Compute weighted averages rounded to 2 decimals. Passing means average >= 60. Output a single JSON object with averages (mapping names to average), class_average (2 decimals, computed from unrounded individual averages), passed (alphabetically sorted names), and highest (the name whose unrounded weighted average is greatest; choose the alphabetically first name only when the greatest scores tie). DATA is already defined; compute all outputs from it without redefining or copying the dataset into source.",
        "data": GRADES_DATA,
        "expected": {"averages": {"Asha": 78.0, "Kabir": 77.0, "Mira": 95.6, "Dev": 50.5}, "class_average": 75.28, "passed": ["Asha", "Kabir", "Mira"], "highest": "Mira"},
        "challenge": "The controlled first attempt runs successfully but uses an unweighted mean, so the semantic validator rejects it.",
        "seed_code": """# Controlled fault: this uses a simple mean instead of assessment weights.
averages = {}
for student in DATA:
    scores = student['scores']
    averages[student['name']] = round(sum(scores) / 3, 2)

result = {
    'averages': averages,
    'class_average': round(sum(averages.values()) / len(averages), 2),
    'passed': sorted(name for name, value in averages.items() if value >= 60),
    'highest': max(averages, key=averages.get),
}
print(json.dumps(result, indent=2))""",
        "replay_code": """weights = [0.2, 0.3, 0.5]
raw_scores = {}

for student in DATA:
    weighted_score = sum(
        score * weight
        for score, weight in zip(student['scores'], weights)
    )
    raw_scores[student['name']] = weighted_score

result = {
    'averages': {
        name: round(value, 2)
        for name, value in raw_scores.items()
    },
    'class_average': round(sum(raw_scores.values()) / len(raw_scores), 2),
    'passed': sorted(
        name for name, value in raw_scores.items() if value >= 60
    ),
    'highest': sorted(
        raw_scores, key=lambda name: (-raw_scores[name], name)
    )[0],
}
print(json.dumps(result, indent=2))""",
    },
}

FIELD_RULES = {
    "sales": {
        "total": "Sum every valid numeric amount, including negative adjustments, then round to two decimals.",
        "valid_rows": "Count rows that convert to numeric amounts after stripping whitespace.",
        "rejected_rows": "Count EVERY skipped row, including empty strings and conversion errors. valid_rows + rejected_rows must equal len(DATA). Validate using float in try/except; isdigit rejects valid signed numbers.",
        "by_region": "Aggregate valid amounts by their region, including signed negative adjustments. Use float conversion in try/except, not isdigit. Round totals to two decimals.",
        "top_region": "Compute the greatest total AFTER all rows are aggregated, including negative adjustments. Use alphabetical order only to break a tie at the greatest FINAL total.",
    },
    "text": {
        "document_count": "Count input documents, not words.",
        "token_count": "Count all lowercase matches of [A-Za-z]+, including repeated tokens.",
        "unique_tokens": "Count distinct lowercase tokens, not total occurrences.",
        "frequencies": "Count every alphabetic token after lowercasing; punctuation is a separator.",
        "top_tokens": "Rank by count descending and token ascending for ties; return at most three objects with token and count.",
    },
    "grades": {
        "averages": "Use weights 0.2, 0.3, 0.5 in score order, then round individual values to two decimals.",
        "class_average": "Average the UNROUNDED weighted values, then round the class result to two decimals.",
        "passed": "Include students with weighted score >= 60; sort names alphabetically.",
        "highest": "Choose the name with the GREATEST unrounded weighted score. Alphabetical order breaks only a tie at the greatest score.",
    },
}

# Expected values are checked by a separate reference path in the tests.


def public_presets():
    result = []
    for preset in PRESETS.values():
        item = {k: copy.deepcopy(v) for k, v in preset.items() if not k.endswith("code")}
        item["task"] = item["prompt"]
        item["expected_keys"] = list(item["expected"])
        item["seed_preview"] = {"code": preset["seed_code"], "description": preset["challenge"], "provenance": "Prewritten controlled first failure; not model generated.", "expected_failure": "ValidationError" if preset["id"] == "grades" else "TypeError" if preset["id"] == "sales" else "AttributeError"}
        item["task_contract"] = {"validation_kind": "semantic", "expected_keys": list(preset["expected"]), "rules": copy.deepcopy(FIELD_RULES[preset["id"]])}
        result.append(item)
    return result


def _equal(actual, expected):
    if isinstance(expected, bool):
        return actual is expected
    if isinstance(expected, (int, float)):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8)
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(actual) == set(expected) and all(_equal(actual[k], value) for k, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(_equal(a, e) for a, e in zip(actual, expected))
    return actual == expected


def _mismatches(actual, expected, path="$", limit=12):
    """Identify failing fields without disclosing their expected values."""
    if limit <= 0 or _equal(actual, expected):
        return []
    if isinstance(expected, dict) and isinstance(actual, dict):
        result = []
        for key in sorted(expected):
            field = path + "." + key
            if key not in actual:
                result.append({"path": field, "issue": "required field missing"})
            else:
                result.extend(_mismatches(actual[key], expected[key], field, limit - len(result)))
            if len(result) >= limit:
                return result[:limit]
        for key in sorted(set(actual) - set(expected)):
            result.append({"path": path + "." + str(key)[:80], "issue": "unexpected field"})
            if len(result) >= limit:
                break
        return result[:limit]
    if isinstance(expected, list) and isinstance(actual, list):
        if len(actual) != len(expected):
            return [{"path": path, "issue": "list length differs"}]
        result = []
        for index, (value, reference) in enumerate(zip(actual, expected)):
            result.extend(_mismatches(value, reference, f"{path}[{index}]", limit - len(result)))
            if len(result) >= limit:
                break
        return result[:limit]
    kinds = {dict: "object", list: "array", str: "string", bool: "boolean", int: "number", float: "number", type(None): "null"}
    return [{"path": path, "issue": "value or type differs", "expected_type": kinds.get(type(expected), "unsupported"), "actual_type": kinds.get(type(actual), "unsupported")}]


def validate_result(result, preset_id):
    if preset_id not in PRESETS:
        passed = isinstance(result, dict) and bool(result)
        return {"passed": passed, "kind": "structural", "message": "Non-empty JSON object received. Custom tasks have no independent correctness oracle." if passed else "Custom tasks must print a non-empty JSON object.", "actual": result}
    expected = PRESETS[preset_id]["expected"]
    passed = _equal(result, expected)
    mismatches = [] if passed else _mismatches(result, expected)
    for mismatch in mismatches:
        field = mismatch["path"].split(".")[1].split("[")[0] if "." in mismatch["path"] else ""
        if field in FIELD_RULES[preset_id]:
            mismatch["rule"] = FIELD_RULES[preset_id][field]
    message = "All expected fields and values match the independent reference." if passed else "Output violates the task contract at " + ", ".join(item["path"] for item in mismatches) + "; recompute these fields from DATA and the stated rules."
    return {"passed": passed, "kind": "semantic", "message": message, "mismatches": mismatches, "expected": expected, "actual": result}
