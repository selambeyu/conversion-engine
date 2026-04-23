"""
eval/benchmark_harness.py  —  Act I
─────────────────────────────────────────────────────
This file does one job: run the tau2-bench test,
score your AI, and save everything to log files.

Think of it like a school exam:
  - 30 questions (tasks) loaded from tau2-bench
  - Your AI answers each one (a conversation)
  - We grade each answer pass or fail
  - We run the whole exam 5 times (trials)
  - We calculate your average score with a confidence interval
  - We save every answer as evidence

Run it:
  python eval/benchmark_harness.py --trials 5 --tasks 30
─────────────────────────────────────────────────────
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

import numpy as np
from scipy import stats
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

# So Python can find logger.py one folder up
sys.path.insert(0, str(Path(__file__).parent.parent))
from logger import log_benchmark_task

load_dotenv()

# ── Config ────────────────────────────────────────────────
DEV_MODEL  = os.getenv("DEV_MODEL", "deepseek/deepseek-chat")
LOGS_DIR   = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
SCORE_LOG  = LOGS_DIR / "score_log.json"
TRACE_LOG  = LOGS_DIR / "trace_log.jsonl"

# Published world record on tau2-bench retail (Feb 2026)
# Your score will be below this — that's normal and expected
PUBLISHED_CEILING = 0.42


# ─────────────────────────────────────────────────────────
# PART 1: Connect to the AI
# ─────────────────────────────────────────────────────────

def get_ai_client():
    """
    Create a connection to OpenRouter.
    OpenRouter lets you use DeepSeek, Claude, GPT all
    through one API key — just a different base URL.
    """
    return OpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1"
    )


def ask_ai(messages, model, temperature=0.0, max_tokens=500):
    """
    Send a conversation to the AI and get a reply.

    messages    = the conversation history so far
    temperature = 0.0 means the AI gives the same answer
                  every time — important for reproducible benchmarks

    Returns: (reply_text, cost_in_dollars, time_in_milliseconds)
    """
    client = get_ai_client()
    start  = time.time()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as e:
        raise RuntimeError(f"AI call failed: {e}")

    latency_ms = int((time.time() - start) * 1000)
    reply      = response.choices[0].message.content or ""

    # Estimate cost — DeepSeek is extremely cheap
    # (~$0.14 per million input tokens = fractions of a cent per call)
    tokens_in  = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens
    cost_usd   = (tokens_in * 0.00000014) + (tokens_out * 0.00000028)

    return reply, round(cost_usd, 7), latency_ms


# ─────────────────────────────────────────────────────────
# PART 2: Load the test questions (tasks)
# ─────────────────────────────────────────────────────────

def load_tasks(domain="retail", slice_type="dev"):
    """
    Load test conversations from tau2-bench.

    slice_type "dev"      → 30 tasks  (use for Acts I, II, III)
    slice_type "held_out" → 20 tasks  (ONLY use in Act IV final run)
                            Like a sealed exam — don't open early

    If tau2-bench is not cloned yet, we use realistic practice
    tasks so your code still runs and you can see it working.
    """
    tau2_path = Path(os.getenv("TAU2_BENCH_PATH", "../tau2-bench"))

    if tau2_path.exists():
        # Look for the real task file
        for candidate in [
            tau2_path / "data" / "tau2" / "domains" / domain / "tasks.json",
            tau2_path / "tasks" / f"{domain}_tasks.json",
            tau2_path / f"{domain}_tasks.json",
            tau2_path / "data" / f"{domain}.json",
        ]:
            if candidate.exists():
                with open(candidate) as f:
                    all_tasks = json.load(f)
                tasks = all_tasks[:30] if slice_type == "dev" else all_tasks[30:50]
                print(f"  Loaded {len(tasks)} real tau2-bench tasks from {candidate}")
                return tasks

    # ── Practice tasks (used if tau2-bench not found yet) ──
    # These are realistic B2B sales scenarios — same structure
    # as real tau2-bench tasks so your code works identically
    print("  tau2-bench not found — using practice tasks")
    print("  To use real tasks: git clone https://github.com/sierra-research/tau2-bench ../tau2-bench\n")

    scenarios = [
        {
            "description": "prospect wants to know about engineering team pricing",
            "outcome":     "pricing_discussed",
            "first_msg":   "Hi, we're a Series B startup. How much does it cost to hire a team of 5 Python engineers through Tenacious?",
            "must_have":   ["engineer", "team"],
            "must_not":    ["i don't know", "impossible"],
        },
        {
            "description": "prospect asks about bench availability for Go engineers",
            "outcome":     "availability_checked",
            "first_msg":   "We need Go developers urgently. Do you have anyone available right now?",
            "must_have":   ["go", "available"],
            "must_not":    ["cannot help", "no engineers"],
        },
        {
            "description": "CTO asks about AI/ML team capability",
            "outcome":     "capability_explained",
            "first_msg":   "We're building an LLM-based product. Does your bench include ML engineers?",
            "must_have":   ["ml", "engineer"],
            "must_not":    ["we don't", "impossible"],
        },
        {
            "description": "prospect asks about contract length",
            "outcome":     "contract_explained",
            "first_msg":   "What's the minimum engagement length? We only need help for 3 months.",
            "must_have":   ["month", "engagement"],
            "must_not":    ["cannot", "minimum is 12"],
        },
        {
            "description": "prospect objects to offshore engineering",
            "outcome":     "objection_handled",
            "first_msg":   "We've had bad experiences with offshore teams before. Why would Tenacious be different?",
            "must_have":   ["quality", "team"],
            "must_not":    ["offshore is always better", "you're wrong"],
        },
        {
            "description": "prospect asks about data engineering capability",
            "outcome":     "data_eng_discussed",
            "first_msg":   "Do you have data engineers who know dbt and Snowflake?",
            "must_have":   ["data", "engineer"],
            "must_not":    ["no", "we don't have"],
        },
        {
            "description": "inbound lead asks for a discovery call",
            "outcome":     "call_scheduled",
            "first_msg":   "I'd like to learn more. Can we schedule a call this week?",
            "must_have":   ["call", "schedule"],
            "must_not":    ["no availability", "impossible"],
        },
        {
            "description": "prospect asks about team management structure",
            "outcome":     "management_explained",
            "first_msg":   "If we hire through Tenacious, who manages the engineers day to day?",
            "must_have":   ["manage", "team"],
            "must_not":    ["we don't manage", "not our problem"],
        },
        {
            "description": "post-layoff company asks about cost reduction",
            "outcome":     "cost_solution_offered",
            "first_msg":   "We just had layoffs. We need engineering output but our budget is tight. Can you help?",
            "must_have":   ["cost", "budget"],
            "must_not":    ["we're too expensive", "can't help"],
        },
        {
            "description": "prospect asks about infrastructure engineers",
            "outcome":     "infra_discussed",
            "first_msg":   "We need someone to manage our AWS infrastructure. Do you have DevOps engineers?",
            "must_have":   ["infrastructure", "engineer"],
            "must_not":    ["we only do", "no devops"],
        },
    ]

    tasks = []
    for i in range(30 if slice_type == "dev" else 20):
        s = scenarios[i % len(scenarios)]
        tasks.append({
            "task_id":          f"{domain}_{slice_type}_{i+1:03d}",
            "domain":           domain,
            "description":      s["description"],
            "expected_outcome": s["outcome"],
            "turns":            [{"role": "user", "content": s["first_msg"]}],
            "success_criteria": {
                "must_contain":     s["must_have"],
                "must_not_contain": s["must_not"],
            }
        })

    return tasks


# ─────────────────────────────────────────────────────────
# PART 3: What the AI is told it should be
# ─────────────────────────────────────────────────────────

# This is the "personality" of your agent.
# It reads this before every single conversation.
# Key rules:
#   - Never promise engineers you don't have
#   - Never make claims you can't back up
#   - Be honest when you don't know something

SYSTEM_PROMPT = """You are a sales assistant for Tenacious Consulting and Outsourcing.

Tenacious provides two services:
1. Managed talent outsourcing — dedicated engineering teams (Python, Go, data, ML, infra)
   working on the client's product under Tenacious management.
   Typical: 3-12 engineers, 6-24 month engagements.
2. Project consulting — time-boxed AI/data platform builds.

Your job in every conversation:
- Understand what the prospect needs
- Answer their questions honestly and helpfully
- Keep replies concise — under 120 words
- Never commit to specific engineer headcounts without saying you'll confirm availability
- Never make claims you cannot back up
- If they want to book a call, offer a booking link
- If they ask about detailed pricing, say you'll connect them with a specialist

Tone: warm, direct, professional. Not salesy. Not robotic."""


# ─────────────────────────────────────────────────────────
# PART 4: Run one task (one exam question)
# ─────────────────────────────────────────────────────────

def run_one_task(task, model, trial_num):
    """
    Run the AI through one test conversation and score it.

    How it works step by step:
    1. Give the AI the first message from the prospect
    2. AI replies
    3. Check if the reply counts as passing
    4. If not, give a follow-up message (simulating the prospect continuing)
    5. Repeat up to 5 turns
    6. Log everything to Langfuse
    7. Return the result as a dictionary
    """
    task_id       = task.get("task_id") or task.get("id")
    all_latencies = []
    total_cost    = 0.0
    chat_log      = []     # full conversation saved for evidence

    # Build the conversation starting with the system prompt
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add the first message from the prospect.
    # Real tau2-bench tasks store the scenario in user_scenario.instructions;
    # practice tasks use a "turns" list.
    if "turns" in task:
        first_message = task["turns"][0]["content"]
    else:
        instructions = task.get("user_scenario", {}).get("instructions", {})
        reason       = instructions.get("reason_for_call", "")
        known        = instructions.get("known_info", "")
        task_instr   = instructions.get("task_instructions", "")
        first_message = f"{task_instr} {reason} {known}".strip()

    messages.append({"role": "user", "content": first_message})
    chat_log.append({"role": "user", "content": first_message})

    passed      = False
    final_reply = ""

    # Follow-up messages that simulate a prospect continuing the conversation
    follow_ups = [
        "Can you tell me more about that?",
        "What would the next step look like from your side?",
        "How quickly could this be arranged?",
        None,   # None means end the conversation here
    ]

    for turn_num in range(5):    # max 5 turns per conversation
        # Ask the AI to reply
        try:
            reply, cost, latency = ask_ai(messages, model)
        except RuntimeError as e:
            print(f"      Error on {task_id}: {e}")
            break

        total_cost    += cost
        all_latencies.append(latency)
        final_reply    = reply

        # Add the AI's reply to the conversation
        messages.append( {"role": "assistant", "content": reply})
        chat_log.append({"role": "assistant", "content": reply})

        # Check if the AI passed this task
        passed = did_pass(task, reply, chat_log)
        if passed:
            break    # success — no need for more turns

        # Add the next follow-up message (if there is one)
        if turn_num < len(follow_ups) and follow_ups[turn_num]:
            follow = follow_ups[turn_num]
            messages.append( {"role": "user", "content": follow})
            chat_log.append({"role": "user", "content": follow})
        else:
            break    # no more follow-ups

    # Calculate latency stats
    p50 = int(np.percentile(all_latencies, 50)) if all_latencies else 0
    p95 = int(np.percentile(all_latencies, 95)) if all_latencies else 0

    # Log this conversation to Langfuse — get back a trace_id
    trace_id = log_benchmark_task(
        task_id      = task_id,
        domain       = task.get("domain", "retail"),
        model        = model,
        conversation = chat_log,
        passed       = passed,
        cost_usd     = total_cost,
        latency_ms   = sum(all_latencies),
        trial_num    = trial_num
    )

    return {
        "task_id":    task_id,
        "trial":      trial_num,
        "passed":     passed,
        "cost_usd":   round(total_cost, 7),
        "latency_ms": all_latencies,
        "p50_ms":     p50,
        "p95_ms":     p95,
        "trace_id":   trace_id,
        "timestamp":  datetime.utcnow().isoformat(),
        "preview":    final_reply[:200],   # first 200 chars of last reply
    }


def did_pass(task, last_reply, full_chat):
    """
    Decide if the AI successfully completed the task.

    Rules:
    - Certain words MUST appear somewhere in the conversation
    - Certain words must NOT appear in the last reply
    - The reply must be a real, substantive response

    In real tau2-bench, this is a sophisticated verifier function.
    These keyword checks are a practical proxy until you integrate
    the full tau2-bench verifier.
    """
    criteria   = task.get("success_criteria", {})
    reply_low  = last_reply.lower()
    all_text   = " ".join(m["content"].lower() for m in full_chat)

    # Required words — must appear somewhere in the full conversation
    for word in criteria.get("must_contain", []):
        if word.lower() not in all_text:
            return False

    # Banned words — must not appear in the final reply
    for word in criteria.get("must_not_contain", []):
        if word.lower() in reply_low:
            return False

    # Basic sanity check: reply must be real content, not an error
    if len(last_reply.strip()) < 20:
        return False
    if "error" in reply_low and "sorry" in reply_low:
        return False

    return True


# ─────────────────────────────────────────────────────────
# PART 5: Calculate your score
# ─────────────────────────────────────────────────────────

def calculate_scores(all_results):
    """
    Calculate pass@1 and 95% confidence interval.

    pass@1 means: if you give the AI ONE attempt at a task,
    what percentage of tasks does it pass?

    We estimate this by running 5 trials and averaging.

    The 95% CI is a range that tells you how reliable your
    number is. Example:
      pass@1 = 62%
      95% CI = [54%, 70%]
    This means: we're 95% confident the true value is
    between 54% and 70%.
    """
    # Group results by task_id
    by_task = {}
    for r in all_results:
        tid = r["task_id"]
        if tid not in by_task:
            by_task[tid] = []
        by_task[tid].append(1 if r["passed"] else 0)

    # For each task: what fraction of trials did it pass?
    per_task_rates = [
        sum(passes) / len(passes)
        for passes in by_task.values()
    ]

    n    = len(per_task_rates)
    mean = float(np.mean(per_task_rates))
    sem  = float(stats.sem(per_task_rates)) if n > 1 else 0.0

    # 95% confidence interval using t-distribution
    if n > 1:
        ci = stats.t.interval(0.95, df=n-1, loc=mean, scale=sem)
        ci_lower = max(0.0, float(ci[0]))
        ci_upper = min(1.0, float(ci[1]))
    else:
        ci_lower = ci_upper = mean

    return {
        "pass_at_1": round(mean, 4),
        "ci_lower":  round(ci_lower, 4),
        "ci_upper":  round(ci_upper, 4),
        "ci_width":  round(ci_upper - ci_lower, 4),
        "n_tasks":   n,
        "n_passed":  sum(1 for r in all_results if r["passed"]),
        "n_failed":  sum(1 for r in all_results if not r["passed"]),
        "n_total":   len(all_results),
    }


# ─────────────────────────────────────────────────────────
# PART 6: Save results to log files
# ─────────────────────────────────────────────────────────

def save_score_log(entry):
    """
    Append this run's score to score_log.json.
    This file grows with every run — it's your full history.
    Graders check this file to verify your Act I baseline.
    """
    existing = []
    if SCORE_LOG.exists():
        try:
            with open(SCORE_LOG) as f:
                existing = json.load(f)
        except Exception:
            existing = []

    existing.append(entry)

    with open(SCORE_LOG, "w") as f:
        json.dump(existing, f, indent=2)


def save_trace_log(all_results):
    """
    Append each task result as one line to trace_log.jsonl.
    One line = one task result = one piece of evidence.
    Graders recompute your numbers from this file.
    """
    with open(TRACE_LOG, "a") as f:
        for r in all_results:
            f.write(json.dumps(r) + "\n")


# ─────────────────────────────────────────────────────────
# PART 7: The main function — runs the whole benchmark
# ─────────────────────────────────────────────────────────

def run_benchmark(num_trials=5, num_tasks=30,
                  model=None, label="day1_baseline",
                  slice_type="dev"):
    """
    Run the full Act I benchmark.

    num_trials = how many times to run each task (5 is standard for Act I)
    num_tasks  = how many tasks to run (30 for dev slice)
    model      = AI model to use (reads DEV_MODEL from .env if not set)
    label      = name for this run in score_log.json
    slice_type = "dev" always for Acts I-III
    """
    model = model or DEV_MODEL

    print()
    print("=" * 56)
    print("  ACT I — BENCHMARK HARNESS")
    print("=" * 56)
    print(f"  Model:      {model}")
    print(f"  Tasks:      {num_tasks}")
    print(f"  Trials:     {num_trials}")
    print(f"  Label:      {label}")
    print(f"  Started:    {datetime.utcnow().strftime('%H:%M UTC')}")
    print("=" * 56)
    print()

    # Load the test tasks
    tasks      = load_tasks("retail", slice_type)[:num_tasks]
    all_results = []
    start_time = time.time()

    # Run each trial
    for trial in range(1, num_trials + 1):
        print(f"Trial {trial} of {num_trials}  ({len(tasks)} tasks)")
        print("-" * 40)

        trial_results = []
        for task in tqdm(tasks, desc="  Running", unit="task", ncols=60):
            result = run_one_task(task, model, trial)
            trial_results.append(result)
            all_results.append(result)

            # Show each task result inline
            status = "PASS" if result["passed"] else "fail"
            print(
                f"  {task.get('task_id') or task.get('id')}: {status}"
                f"  ${result['cost_usd']:.5f}"
                f"  {result['p50_ms']}ms"
            )

        # Trial summary
        n_pass = sum(1 for r in trial_results if r["passed"])
        print(f"\n  Trial {trial} result: "
              f"{n_pass}/{len(trial_results)} passed "
              f"({n_pass/len(trial_results):.1%})\n")

    # ── Calculate final statistics ────────────────────────
    total_time  = time.time() - start_time
    scores      = calculate_scores(all_results)
    all_lats    = [lat for r in all_results
                   for lat in r.get("latency_ms", [])]
    total_cost  = sum(r["cost_usd"] for r in all_results)

    p50_overall = int(np.percentile(all_lats, 50)) if all_lats else 0
    p95_overall = int(np.percentile(all_lats, 95)) if all_lats else 0

    # ── Build the score log entry ─────────────────────────
    score_entry = {
        "label":      label,
        "timestamp":  datetime.utcnow().isoformat(),
        "model":      model,
        "domain":     "retail",
        "slice":      slice_type,
        "num_tasks":  len(tasks),
        "num_trials": num_trials,
        "runtime_s":  round(total_time, 1),

        # THE NUMBERS THAT GO IN YOUR MEMO
        "pass_at_1":  scores["pass_at_1"],
        "ci_95":      [scores["ci_lower"], scores["ci_upper"]],
        "ci_width":   scores["ci_width"],

        "cost": {
            "total_usd":    round(total_cost, 5),
            "per_task_usd": round(total_cost / len(all_results), 7),
        },
        "latency": {
            "p50_ms": p50_overall,
            "p95_ms": p95_overall,
        },
        "counts": {
            "passed": scores["n_passed"],
            "failed": scores["n_failed"],
            "total":  scores["n_total"],
        },

        # Trace IDs for your evidence_graph.json
        "trace_ids": [r["trace_id"] for r in all_results
                      if r.get("trace_id")]
    }

    # ── Save both log files ───────────────────────────────
    save_score_log(score_entry)
    save_trace_log(all_results)

    # ── Print your final results ──────────────────────────
    gap = PUBLISHED_CEILING - scores["pass_at_1"]

    print()
    print("=" * 56)
    print("  FINAL RESULTS")
    print("=" * 56)
    print(f"  pass@1:            {scores['pass_at_1']:.1%}")
    print(f"  95% CI:            [{scores['ci_lower']:.1%} – {scores['ci_upper']:.1%}]")
    print(f"  CI width:          {scores['ci_width']:.1%}  "
          f"({'good' if scores['ci_width'] < 0.15 else 'wide — consider more trials'})")
    print(f"  Published ceiling: {PUBLISHED_CEILING:.1%}")
    print(f"  Gap to ceiling:    {gap:.1%}")
    print()
    print(f"  Total cost:        ${total_cost:.5f}")
    print(f"  Cost per task:     ${score_entry['cost']['per_task_usd']:.7f}")
    print(f"  Latency p50:       {p50_overall}ms")
    print(f"  Latency p95:       {p95_overall}ms")
    print(f"  Total runtime:     {total_time:.0f}s")
    print()
    print(f"  Saved → logs/score_log.json")
    print(f"  Saved → logs/trace_log.jsonl")
    print()
    print(f"  Next: python eval/generate_baseline_md.py")
    print("=" * 56)
    print()

    return score_entry


# ─────────────────────────────────────────────────────────
# CLI: run this file directly
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Act I — tau2-bench benchmark harness"
    )
    parser.add_argument("--trials", type=int, default=5,
                        help="Number of trials per task (default: 5)")
    parser.add_argument("--tasks",  type=int, default=30,
                        help="Number of tasks (default: 30)")
    parser.add_argument("--model",  type=str, default=None,
                        help="AI model override")
    parser.add_argument("--label",  type=str, default="day1_baseline",
                        help="Label for this run in score_log")
    parser.add_argument("--held-out", action="store_true",
                        help="Run on sealed held-out slice — ACT IV ONLY")
    args = parser.parse_args()

    # Safety: warn before touching the sealed test set
    if args.held_out:
        confirm = input(
            "\nWARNING: This runs on the SEALED held-out slice.\n"
            "Only do this in Act IV. Type YES to confirm: "
        )
        if confirm.strip() != "YES":
            print("Aborted.")
            sys.exit(0)
        slice_type = "held_out"
        label      = args.label or "act4_held_out"
    else:
        slice_type = "dev"
        label      = args.label

    run_benchmark(
        num_trials = args.trials,
        num_tasks  = args.tasks,
        model      = args.model,
        label      = label,
        slice_type = slice_type,
    )