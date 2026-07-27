"""Phase 0: consolidate raw question batch files into
backend/data/questions_master.json.

- Normalizes common key-name variants from separate LLM generation calls,
  including topic name aliases (e.g. "E&M" -> "Electricity and Magnetism").
- Validates strictly against the target schema; failures are logged to
  backend/data/discarded_questions_log.json and excluded (never auto-fixed).
- Deduplicates question_ids across files by regenerating the ID of the
  second occurrence (rename logged, question kept).
- Carries through an optional distractor_analysis field (misconception per
  wrong option) used by the MCQ-based failure-diagnosis feature; nulls it
  out with a logged warning if its keys don't exactly match the question's
  wrong options, rather than discarding an otherwise-good question over it.
- Flags likely near-duplicate questions (same topic, high text similarity)
  in a separate report for manual review — never auto-discarded, since
  templated-but-distinct questions are expected and fine.
"""

import difflib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "backend" / "data"
RAW_DIR = DATA_DIR / "raw_batches"
MASTER_PATH = DATA_DIR / "questions_master.json"
DISCARD_LOG_PATH = DATA_DIR / "discarded_questions_log.json"
NEAR_DUP_REPORT_PATH = DATA_DIR / "near_duplicates_report.json"

VALID_DIFFICULTIES = {"easy", "medium", "hard"}
THETA_SEED_BY_DIFFICULTY = {"easy": 900, "medium": 1200, "hard": 1500}
CANONICAL_MARKING_SCHEME = {"correct": 4, "incorrect": -1, "unattempted": 0}
NEAR_DUP_SIMILARITY_THRESHOLD = 0.82

# topic names seen across separate LLM generation calls -> canonical topic.
# The app's four topics are fixed (used for topic ratings + frontend filter
# list), so any variant spelling has to be normalized here or it silently
# becomes an invisible 5th topic bucket.
TOPIC_ALIASES = {
    "e&m": "Electricity and Magnetism",
    "electricity and magnetism": "Electricity and Magnetism",
    "electricity & magnetism": "Electricity and Magnetism",
    "electromagnetism": "Electricity and Magnetism",
    "mechanics": "Mechanics",
    "optics": "Optics",
    "modern physics": "Modern Physics",
}

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
    "distractor_analysis": ["distractor_analysis", "distractor_map", "misconceptions"],
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
    if "topic" in out and isinstance(out["topic"], str):
        out["topic"] = TOPIC_ALIASES.get(out["topic"].strip().lower(), out["topic"].strip())
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


def validate_distractor_analysis(q: dict) -> tuple:
    """Return (cleaned_distractor_analysis_or_None, warning_or_None).

    Never rejects the question over this — a good physics question with a
    malformed annotation is still worth keeping for quizzing; the annotation
    just gets dropped (with a logged reason) rather than shipping bad data
    for the MCQ-diagnosis feature to trip over later.
    """
    da = q.get("distractor_analysis")
    if not da:
        return None, None
    if not isinstance(da, dict):
        return None, "distractor_analysis is not an object"

    wrong_options = [o for o in q["options"] if o != q["correct_answer"]]
    if sorted(da.keys()) != sorted(wrong_options):
        return None, (
            f"distractor_analysis keys {sorted(da.keys())!r} don't exactly "
            f"match wrong options {sorted(wrong_options)!r}"
        )

    cleaned = {}
    for option, info in da.items():
        if not isinstance(info, dict) or not info.get("misconception"):
            return None, f"distractor_analysis[{option!r}] missing 'misconception'"
        cleaned[option] = {
            "misconception": str(info["misconception"]),
            "gap_step": info.get("gap_step"),
            "concept": info.get("concept", ""),
        }
    return cleaned, None


def canonicalize(q: dict) -> tuple:
    """Build final schema object from a validated, key-normalized question.

    Returns (final_question_dict, warning_or_None) — the warning covers
    non-fatal issues (currently just a malformed distractor_analysis) that
    don't disqualify the question but are worth surfacing.
    """
    difficulty = q["difficulty_tag"]
    steps = []
    for i, step in enumerate(q["solution_steps"]):
        steps.append({
            "step_order": step.get("step_order", i + 1),
            "step_text": step["step_text"],
            "formula_used": step.get("formula_used"),
            "concept_tested": step.get("concept_tested", ""),
        })

    distractor_analysis, warning = validate_distractor_analysis(q)

    final = {
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
        "distractor_analysis": distractor_analysis,
    }
    return final, warning


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def find_near_duplicates(accepted: list) -> list:
    """Flag same-topic question pairs with high text similarity for manual
    review. Never blocks consolidation — templated-but-distinct questions
    (same setup, different numbers) are expected and fine; this just
    surfaces likely true clones for a human to glance at."""
    by_topic = defaultdict(list)
    for q in accepted:
        by_topic[q["topic"]].append(q)

    near_dups = []
    for topic, qlist in by_topic.items():
        normed = [normalized_text(q["text"]) for q in qlist]
        for i in range(len(qlist)):
            for j in range(i + 1, len(qlist)):
                ratio = difflib.SequenceMatcher(None, normed[i], normed[j]).ratio()
                if ratio >= NEAR_DUP_SIMILARITY_THRESHOLD:
                    near_dups.append({
                        "topic": topic,
                        "similarity": round(ratio, 3),
                        "question_id_a": qlist[i]["question_id"],
                        "text_a": qlist[i]["text"],
                        "question_id_b": qlist[j]["question_id"],
                        "text_b": qlist[j]["text"],
                    })
    near_dups.sort(key=lambda d: d["similarity"], reverse=True)
    return near_dups


def main():
    files = sorted(RAW_DIR.glob("*.json"))
    print(f"Loading {len(files)} raw batch files from {RAW_DIR}\n")

    total_raw = 0
    discarded = []
    renames = []
    warnings = []
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

            final, warning = canonicalize(q)
            if warning:
                warnings.append({
                    "source_file": path.name,
                    "question_id": final["question_id"],
                    "warning": warning,
                })

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

    near_duplicates = find_near_duplicates(accepted)

    MASTER_PATH.write_text(
        json.dumps(accepted, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    DISCARD_LOG_PATH.write_text(
        json.dumps(
            {"discarded": discarded, "id_renames": renames,
             "distractor_analysis_warnings": warnings},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    NEAR_DUP_REPORT_PATH.write_text(
        json.dumps(near_duplicates, indent=2, ensure_ascii=False), encoding="utf-8"
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
    print(f"distractor_analysis present: "
          f"{sum(1 for q in accepted if q['distractor_analysis'])} / {len(accepted)}")
    print(f"distractor_analysis dropped (bad shape): {len(warnings)}")
    for w in warnings[:10]:
        print(f"    {w['question_id']}: {w['warning']}")
    print(f"Near-duplicate pairs flagged: {len(near_duplicates)} "
          f"(see {NEAR_DUP_REPORT_PATH.name}, not auto-discarded)")
    for d in near_duplicates[:5]:
        print(f"    [{d['similarity']}] {d['question_id_a']} ~ {d['question_id_b']}")

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
