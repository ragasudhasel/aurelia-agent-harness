"""Main CLI entrypoint for Task D: Multi-Agent AI Harness."""

import argparse
import asyncio
import logging
import os
import sys

from core.config import load_config
from core.orchestrator import Orchestrator
from core.trace import replay_trace
from benchmarks.evaluate import run_all_benchmarks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("harness_cli")


async def async_main():
    parser = argparse.ArgumentParser(description="Task D: Configuration-Driven Multi-Agent AI Harness")
    parser.add_argument(
        "--config",
        type=str,
        default="configs/reposentinel.yaml",
        help="Path to YAML configuration file"
    )
    parser.add_argument(
        "--task",
        type=str,
        default="Perform thorough analysis of workspace code and logs.",
        help="Custom user task prompt"
    )
    parser.add_argument(
        "--chaos",
        choices=["timeout", "tool_error"],
        default=None,
        help="Induce simulated chaos mode failure for demonstration"
    )
    parser.add_argument(
        "--replay",
        type=str,
        default=None,
        help="Path to trace.jsonl to perform offline replay"
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run comprehensive benchmark suite (Multi-Agent vs Baseline across 3 tasks)"
    )

    args = parser.parse_args()

    # 1. Offline Replay Mode
    if args.replay:
        print(f"\nReplaying trace from: {args.replay}")
        summary = replay_trace(args.replay)
        print(f"Run ID: {summary['run_id']}")
        print(f"Status: {summary['run_status']}")
        print(f"Total Events: {summary['total_events']}")
        print(f"Tool Calls: {summary['tool_calls_count']}")
        print(f"Checker Events: {summary['checker_events_count']}")
        print(f"Failures: {summary['failures_count']}")
        return

    # 2. Benchmark Suite Mode
    if args.benchmark:
        await run_all_benchmarks()
        return

    # 3. Standard Orchestration Run
    if not os.path.exists(args.config):
        print(f"Error: Configuration file '{args.config}' not found.")
        sys.exit(1)

    print(f"\nLoading configuration: {args.config}")
    config = load_config(args.config)

    # Apply chaos mode flag if passed via CLI
    if args.chaos:
        config.chaos_config.enabled = True
        config.chaos_config.failure_type = args.chaos
        # Target the first configured specialist
        first_agent = list(config.agents.keys())[0]
        config.chaos_config.target_agent = first_agent
        print(f"[CHAOS MODE ACTIVE] Inducing '{args.chaos}' on agent '{first_agent}'")

    print(f"Task: {config.task_name} ({config.task_type})")
    print(f"Workspace Root: {config.workspace_root}")
    print(f"Configured Specialists: {list(config.agents.keys())}")
    print("-" * 70)

    orchestrator = Orchestrator(config=config)
    report = await orchestrator.run(user_task=args.task)

    print("\n" + "=" * 70)
    print("ORCHESTRATION EXECUTION REPORT")
    print("=" * 70)
    print(f"Run ID:          {report.run_id}")
    print(f"Overall Status:  {report.overall_status.value.upper()}")
    print(f"Total Duration:  {report.metrics.total_duration_sec}s")
    print(f"Total Steps:     {report.metrics.step_count}")
    print(f"Tool Invocations:{report.metrics.tool_calls}")
    print(f"Tokens Used:     {report.metrics.token_count}")
    print(f"Verified Findings: {len(report.verified_findings)}")
    print(f"Partial Failures:  {len(report.partial_failures)}")
    print("-" * 70)
    print(f"Summary: {report.summary}")

    if report.verified_findings:
        print("\nVerified Findings:")
        for idx, f in enumerate(report.verified_findings, 1):
            print(f"  [{idx}] [{f.severity.value.upper()}] {f.title} ({f.file_path or 'General'}:{f.line_number or 'N/A'})")
            if f.suggested_fix:
                print(f"      Fix: {f.suggested_fix}")

    if report.partial_failures:
        print("\nPartial Failures / Errors:")
        for pf in report.partial_failures:
            print(f"  - Agent '{pf.get('agent_id')}': {pf.get('error')}")

    print("\nTrace written to: runs/" + report.run_id + "/trace.jsonl")
    print("Open 'ui/trace_viewer.html' in your browser to inspect execution visually.")


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
