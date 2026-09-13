from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from control_plane.hashes import sha256_hex
from control_plane.ingest import ingest_request
from control_plane.pipeline import RunConfig, run
from control_plane.policy import evaluate_policy
from control_plane.states import InvalidTransition, State, StateMachine


def _policy(**overrides):
    base = {
        "protected_services": ["alpha"],
        "production_requires_rollback": True,
        "high_risk_request_types": ["risk_rule_change"],
        "incident_exception_allows_missing_tests": True,
        "incident_exception_allows_missing_rollback": False,
        "llm_generated_changes_require_human_review": True,
        "max_auto_approve_blast_radius": "single_service",
        "blocked_without_simulation_for": ["risk_rule_change"],
        "latency_sensitive_services": ["alpha"],
        "max_latency_impact_auto_approve_ms": 2,
        "required_evidence_by_type": {
            "runtime_config_change": ["staging_smoke_test_passed"],
            "risk_rule_change": ["simulation_passed"],
            "code_deployment": ["unit_tests_passed"],
        },
    }
    base.update(overrides)
    return base


def _request(**overrides):
    base = {
        "id": "REQ-1",
        "title": "Tune cache",
        "request_type": "runtime_config_change",
        "service": "beta",
        "environment": "staging",
        "requested_by": "engineer",
        "summary": "small ttl change",
        "proposed_change": {"field": "ttl", "old_value": 1, "new_value": 2},
        "blast_radius": "single_service",
        "rollback_defined": True,
        "test_evidence": ["staging_smoke_test_passed"],
        "change_window": "business_hours",
        "llm_generated": False,
    }
    base.update(overrides)
    return base


class StateMachineTests(unittest.TestCase):
    def test_enforces_order(self):
        machine = StateMachine()
        machine.enter(State.INGESTED, "start")
        with self.assertRaises(InvalidTransition):
            machine.enter(State.LLM_REVIEWED, "skip policy")
        machine.enter(State.POLICY_CHECKED, "policy")
        machine.enter(State.LLM_REVIEWED, "llm")
        machine.enter(State.DECISION_RECONCILED, "reconcile")
        with self.assertRaises(InvalidTransition):
            machine.enter(State.EXECUTING, "skip finalise and auth")


class PolicyTests(unittest.TestCase):
    def test_missing_rollback_in_production_is_mandatory_block(self):
        request = _request(environment="production", rollback_defined=False, change_window="incident_exception")
        policy = _policy()
        context = {"current_incident": True}
        result = evaluate_policy(request, policy, context, [], "r", "p", "c")
        self.assertIn("rollback_required", result.blockers)

    def test_simulation_gap_blocks_even_with_partial_evidence(self):
        request = _request(
            request_type="risk_rule_change",
            environment="production",
            test_evidence=["simulation_partial"],
        )
        result = evaluate_policy(request, _policy(), {"current_incident": False}, [], "r", "p", "c")
        self.assertIn("simulation_required", result.blockers)
        self.assertIn("required_evidence", result.blockers)

    def test_llm_generated_requires_human_review(self):
        request = _request(llm_generated=True)
        result = evaluate_policy(request, _policy(), {}, [], "r", "p", "c")
        self.assertIn("ai_generated_change", result.human_review_reasons)
        self.assertFalse(result.has_mandatory_block)

    def test_invalid_incident_exception_blocks(self):
        request = _request(change_window="incident_exception")
        result = evaluate_policy(request, _policy(), {"current_incident": False}, [], "r", "p", "c")
        self.assertIn("invalid_incident_exception", result.blockers)


class PipelineTests(unittest.TestCase):
    def _write_inputs(self, root: Path, requests, policy, context, reviews=None):
        input_dir = root / "input"
        output_dir = root / "outputs"
        input_dir.mkdir()
        output_dir.mkdir()
        (input_dir / "change_requests.json").write_text(json.dumps(requests), encoding="utf-8")
        (input_dir / "policy_config.json").write_text(json.dumps(policy), encoding="utf-8")
        (input_dir / "system_context.json").write_text(json.dumps(context), encoding="utf-8")
        if reviews is not None:
            (input_dir / "human_reviews.json").write_text(json.dumps(reviews), encoding="utf-8")
        return input_dir, output_dir

    def _seed_llm(self, output_dir: Path, request, policy, context, body: dict):
        from control_plane.llm import build_prompt
        from control_plane.policy import evaluate_policy as ev

        ingested = ingest_request(request, policy, context)
        pol = ev(
            request,
            policy,
            context,
            ingested.ingest_errors,
            ingested.request_hash,
            ingested.policy_hash,
            ingested.context_hash,
        )
        prompt = build_prompt(request, policy, context, pol.to_dict())
        entry = {
            "request_id": request["id"],
            "request_hash": ingested.request_hash,
            "prompt_hash": sha256_hex(prompt),
            "model": "test-replay",
            "response_text": json.dumps(body),
        }
        with (output_dir / "llm_calls.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def test_auto_approve_path_and_replay(self):
        request = _request()
        policy = _policy()
        context = {"current_incident": False, "deployment_freeze": False}
        llm_body = {
            "risk_level": "low",
            "confidence": "high",
            "recommendation": "auto_approve",
            "estimated_latency_impact_ms": 0,
            "reversibility": "high",
            "testing_adequacy": "adequate",
            "justification_adequacy": "adequate",
            "hidden_failure_modes": [],
            "rationale": "Bounded staging config change.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir, output_dir = self._write_inputs(root, [request], policy, context)
            self._seed_llm(output_dir, request, policy, context, llm_body)
            records = run(
                RunConfig(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    replay=True,
                    execute=True,
                    allow_live_llm=False,
                )
            )
            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record.system_recommendation, "auto_approve")
            self.assertTrue(record.executable)
            self.assertEqual(record.state, State.VERIFIED)
            self.assertTrue((output_dir / "final_decisions.json").exists())
            self.assertTrue(record.llm and record.llm.replayed)
            history = [event.to_state for event in record.machine.history]
            self.assertEqual(
                history[:5],
                [
                    "INGESTED",
                    "POLICY_CHECKED",
                    "LLM_REVIEWED",
                    "DECISION_RECONCILED",
                    "FINALISED",
                ],
            )

    def test_llm_cannot_bypass_mandatory_block(self):
        request = _request(
            environment="production",
            rollback_defined=False,
            request_type="code_deployment",
            test_evidence=["unit_tests_passed"],
            blast_radius="global",
        )
        policy = _policy()
        context = {"current_incident": False, "deployment_freeze": False}
        llm_body = {
            "risk_level": "low",
            "confidence": "high",
            "recommendation": "auto_approve",
            "estimated_latency_impact_ms": 0,
            "reversibility": "high",
            "testing_adequacy": "adequate",
            "justification_adequacy": "adequate",
            "hidden_failure_modes": [],
            "rationale": "Should not matter.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir, output_dir = self._write_inputs(root, [request], policy, context)
            self._seed_llm(output_dir, request, policy, context, llm_body)
            record = run(
                RunConfig(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    replay=True,
                    execute=True,
                    allow_live_llm=False,
                )
            )[0]
            self.assertEqual(record.system_recommendation, "block")
            self.assertFalse(record.executable)
            self.assertEqual(record.execution.result, "skipped")

    def test_human_cannot_override_block(self):
        request = _request(
            environment="production",
            rollback_defined=False,
            request_type="code_deployment",
            test_evidence=["unit_tests_passed"],
        )
        policy = _policy()
        context = {"current_incident": False}
        llm_body = {
            "risk_level": "high",
            "confidence": "high",
            "recommendation": "block",
            "estimated_latency_impact_ms": 10,
            "reversibility": "low",
            "testing_adequacy": "partial",
            "justification_adequacy": "weak",
            "hidden_failure_modes": ["no rollback"],
            "rationale": "Unsafe.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviews = [
                {
                    "request_id": request["id"],
                    "action": "approve",
                    "justification": "ship anyway",
                    "reviewer": "oncall",
                }
            ]
            input_dir, output_dir = self._write_inputs(root, [request], policy, context, reviews)
            self._seed_llm(output_dir, request, policy, context, llm_body)
            record = run(
                RunConfig(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    replay=True,
                    allow_live_llm=False,
                )
            )[0]
            self.assertEqual(record.final_decision, "block")
            self.assertFalse(record.executable)

    def test_missing_llm_replay_fails_closed(self):
        request = _request()
        policy = _policy()
        context = {}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir, output_dir = self._write_inputs(root, [request], policy, context)
            record = run(
                RunConfig(
                    input_dir=input_dir,
                    output_dir=output_dir,
                    replay=True,
                    allow_live_llm=False,
                )
            )[0]
            self.assertEqual(record.system_recommendation, "block")
            self.assertIn("llm_review_incomplete", record.system_rationale)


if __name__ == "__main__":
    unittest.main()
