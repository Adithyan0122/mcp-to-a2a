"""
Scorecard — Supply Chain v1.0
Generates ASCII reliability scorecards from eval results.
"""


def build_bar(pct: float, width: int = 12) -> str:
    """Build ASCII progress bar."""
    filled = int(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def print_scorecard(results: dict):
    """Print formatted ASCII scorecard."""
    print()
    print("Agent Reliability Scorecard — v1.0")
    print("═" * 55)

    total_score = 0
    agent_count = 0

    for agent_name, metrics in results.get("agents", {}).items():
        score = metrics.get("score", 0)
        latency = metrics.get("avg_latency_ms", 0)
        bar = build_bar(score)
        note = f"  *{metrics.get('note', '')}" if metrics.get("note") else ""

        latency_str = f"latency: {latency:.0f}ms" if latency < 1000 else f"latency: {latency/1000:.1f}s"
        print(f"  {agent_name:<22} {bar} {score:>3.0f}%   {latency_str}{note}")

        total_score += score
        agent_count += 1

    print("═" * 55)
    overall = total_score / agent_count if agent_count > 0 else 0
    bar = build_bar(overall)
    print(f"  {'Overall pipeline':<22} {bar} {overall:>3.0f}%")
    print()

    # Scenario results
    if "scenarios" in results:
        print("Scenario Results")
        print("─" * 55)
        for scenario in results["scenarios"]:
            status = "✅ PASS" if scenario["passed"] else "❌ FAIL"
            print(f"  {scenario['name']:<30} {status}")
            if not scenario["passed"]:
                for reason in scenario.get("failures", []):
                    print(f"    └─ {reason}")
        print()

    passed = sum(1 for s in results.get("scenarios", []) if s.get("passed"))
    total = len(results.get("scenarios", []))
    print(f"Result: {passed}/{total} scenarios passed ({passed/total*100:.0f}%)")

    if overall >= 80 and passed == total:
        print("🎉 ALL CHECKS PASSED — System is production ready!")
    elif overall >= 80:
        print("⚠️  Overall score OK but some scenarios failed.")
    else:
        print("❌ System needs improvement before production deployment.")

    return overall >= 80 and passed == total
