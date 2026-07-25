"""Phase 0: consolidate 12 raw question batch files into data/questions_master.json.

- Normalizes common key-name variants from separate LLM generation calls.
- Validates strictly against the target schema; failures are logged to
  data/discarded_questions_log.json and excluded (never auto-fixed).
- Deduplicates question_ids across files by regenerating the ID of the
  second occurrence (rename logged, question kept).
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw_batches"
MASTER_PATH = ROOT / "data" / "questions_master.json"
DISCARD_LOG_PATH = ROOT / "data" / "discarded_questions_log.json"

VALID_DIFFICULTIES = {"easy", "medium", "hard"}
THETA_SEED_BY_DIFFICULTY = {"easy": 900, "medium": 1200, "hard": 1500}
CANONICAL_MARKING_SCHEME = {"correct": 4, "incorrect": -1, "unattempted": 0}

# key-name variants seen across separate LLM generation calls -> canonical key
KEY_ALIASES = {
    "question_id": ["question_id", "id", "qid"],
    "text": ["text", "question_text", "question"],
    "options": ["options", "choices", "answer_options"],
    "correct_answer": ["correct_answer", "answer", "correct_option", "correct"],
    "subject": ["subject"],
    "topic": ["topic"],
    "sub_topic": ["sub_topic", "subtopic", "sub_topic_name"],
    "difficulty_tag": ["difficulty_tag", "difficulty", "difficulty_level"],
    "theta_q_seed": ["theta_q_seed", "theta_seed", "theta_q"],
    "marking_scheme": ["marking_scheme", "marks", "scoring"],
    "solution_steps": ["solution_steps", "steps", "solution"],
    "formulas_used": ["formulas_used", "formulas", "formula_list"],
}

REQUIRED_FIELDS = [
    "question_id", "text", "options", "correct_answer",
    "topic", "sub_topic", "difficulty_tag", "solution_steps",
]


def normalize_keys(raw: dict) -> dict:
    out = {}
    for canonical, aliases in KEY_ALIASES.items():
        for alias in aliases:
            if alias in raw:
                out[canonical] = raw[alias]
                break
    return out


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def validate(q: dict) -> list:
    """Return list of rejection reasons (empty = valid)."""
    reasons = []

    missing = [f for f in REQUIRED_FIELDS if f not in q or q[f] in (None, "", [])]
    if missing:
        reasons.append(f"missing required fields: {', '.join(missing)}")
        return reasons  # can't meaningfully run deeper checks

    if not isinstance(q["options"], list) or len(q["options"]) != 4:
        reasons.append("options is not a list of exactly 4 entries")
    elif not all(isinstance(o, str) for o in q["options"]):
        reasons.append("options contains non-string entries")
    elif q["correct_answer"] not in q["options"]:
        reasons.append(
            f"correct_answer {q['correct_answer']!r} does not exactly match any option"
        )

    if q["difficulty_tag"] not in VALID_DIFFICULTIES:
        reasons.append(f"invalid difficulty_tag: {q['difficulty_tag']!r}")

    steps = q["solution_steps"]
    if not isinstance(steps, list) or len(steps) < 2:
        reasons.append("solution_steps missing or has fewer than 2 steps")
    else:
        for i, step in enumerate(steps):
            if not isinstance(step, dict) or "step_text" not in step or not step["step_text"]:
                reasons.append(f"solution_steps[{i}] missing step_text")
                break

    return reasons


def canonicalize(q: dict) -> dict:
    """Build final schema object from a validated, key-normalized question."""
    difficulty = q["difficulty_tag"]
    steps = []
    for i, step in enumerate(q["solution_steps"]):
        steps.append({
            "step_order": step.get("step_order", i + 1),
            "step_text": step["step_text"],
            "formula_used": step.get("formula_used"),
            "concept_tested": step.get("concept_tested", ""),
        })
    return {
        "question_id": q["question_id"],
        "text": q["text"],
        "options": q["options"],
        "correct_answer": q["correct_answer"],
        "subject": q.get("subject", "Physics"),
        "topic": q["topic"],
        "sub_topic": q["sub_topic"],
        "difficulty_tag": difficulty,
        # derived strictly from difficulty_tag, overwriting any inconsistent seed
        "theta_q_seed": THETA_SEED_BY_DIFFICULTY[difficulty],
        "marking_scheme": CANONICAL_MARKING_SCHEME,
        "solution_steps": steps,
        "formulas_used": q.get("formulas_used", []),
    }


def main():
    files = sorted(RAW_DIR.glob("*.json"))
    print(f"Loading {len(files)} raw batch files from {RAW_DIR}\n")

    total_raw = 0
    discarded = []
    renames = []
    accepted = []
    seen_ids = set()
    seq_by_slug = defaultdict(int)  # for regenerated IDs

    for path in files:
        try:
            batch = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            discarded.append({
                "source_file": path.name,
                "question_id": None,
                "reason": f"file is not valid JSON: {e}",
            })
            continue
        if not isinstance(batch, list):
            discarded.append({
                "source_file": path.name,
                "question_id": None,
                "reason": "file root is not a JSON array",
            })
            continue

        for raw in batch:
            total_raw += 1
            q = normalize_keys(raw if isinstance(raw, dict) else {})
            reasons = validate(q)
            if reasons:
                discarded.append({
                    "source_file": path.name,
                    "question_id": q.get("question_id"),
                    "reason": "; ".join(reasons),
                })
                continue

            final = canonicalize(q)

            if final["question_id"] in seen_ids:
                slug = slugify(final["sub_topic"])
                while True:
                    seq_by_slug[slug] += 1
                    new_id = f"physics_{slug}_{seq_by_slug[slug]:03d}"
                    if new_id not in seen_ids:
                        break
                renames.append({
                    "source_file": path.name,
                    "old_id": final["question_id"],
                    "new_id": new_id,
                })
                final["question_id"] = new_id

            seen_ids.add(final["question_id"])
            accepted.append(final)

    MASTER_PATH.write_text(
        json.dumps(accepted, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    DISCARD_LOG_PATH.write_text(
        json.dumps({"discarded": discarded, "id_renames": renames}, indent=2,
                   ensure_ascii=False),
        encoding="utf-8",
    )

    # ---- summary ----
    print("=" * 60)
    print("CONSOLIDATION SUMMARY")
    print("=" * 60)
    print(f"Total raw questions loaded : {total_raw}")
    print(f"Discarded                  : {len(discarded)}")
    if discarded:
        reason_counts = Counter(d["reason"] for d in discarded)
        for reason, n in reason_counts.most_common():
            print(f"    [{n}] {reason}")
    print(f"Duplicate IDs renamed      : {len(renames)}")
    for r in renames:
        print(f"    {r['old_id']} -> {r['new_id']}  ({r['source_file']})")
    print(f"Final validated count      : {len(accepted)}")

    print("\nBy topic:")
    for topic, n in sorted(Counter(q["topic"] for q in accepted).items()):
        print(f"    {topic:30s} {n}")

    print("\nBy sub_topic:")
    for st, n in sorted(Counter(q["sub_topic"] for q in accepted).items()):
        print(f"    {st:30s} {n}")

    print("\nBy difficulty_tag:")
    for d, n in sorted(Counter(q["difficulty_tag"] for q in accepted).items()):
        print(f"    {d:10s} {n}")

    print(f"\nWrote {MASTER_PATH}")
    print(f"Wrote {DISCARD_LOG_PATH}")


if __name__ == "__main__":
    main()
