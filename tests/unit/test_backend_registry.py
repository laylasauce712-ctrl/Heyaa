import unittest

from src.heyaa.backends import (
    BackendExecutionError,
    BackendRegistry,
    BackendResult,
    BackendUnavailableError,
    NormalizedBox,
    SceneCut,
    execute_with_fallback,
)


class FakeSceneBackend:
    def __init__(self, backend_id="fake"):
        self.backend_id = backend_id

    def detect(self, media_path, *, start_seconds=0.0, end_seconds=None):
        return BackendResult(self.backend_id, "ok", (SceneCut(1.0, 0.9),))


class FakeBeatBackend:
    backend_id = "beat-fake"

    def analyze(self, media_path, *, duration_seconds=None):
        return BackendResult(self.backend_id, "ok")


class RegistryTests(unittest.TestCase):
    def test_register_and_resolve_backend_by_explicit_id(self):
        registry = BackendRegistry()
        backend = FakeSceneBackend()
        registry.register("scene_detector", backend)
        self.assertIs(registry.get("scene_detector", "fake"), backend)
        self.assertEqual(registry.names("scene_detector"), ("fake",))

    def test_registry_does_not_choose_a_backend_implicitly(self):
        registry = BackendRegistry()
        self.assertEqual(registry.names("scene_detector"), ())
        with self.assertRaises(BackendUnavailableError):
            registry.get("scene_detector", "default")

    def test_rejects_unknown_role(self):
        with self.assertRaises(ValueError):
            BackendRegistry().register("renderer", FakeSceneBackend())

    def test_rejects_missing_backend_id(self):
        class MissingId:
            def detect(self, media_path, *, start_seconds=0.0, end_seconds=None):
                return None
        with self.assertRaises(ValueError):
            BackendRegistry().register("scene_detector", MissingId())

    def test_rejects_wrong_role_interface(self):
        with self.assertRaises(TypeError):
            BackendRegistry().register("scene_detector", FakeBeatBackend())

    def test_rejects_duplicate_backend_ids(self):
        registry = BackendRegistry()
        registry.register("scene_detector", FakeSceneBackend())
        with self.assertRaises(ValueError):
            registry.register("scene_detector", FakeSceneBackend())

    def test_same_backend_id_can_exist_under_different_roles(self):
        registry = BackendRegistry()
        scene = FakeSceneBackend("shared")
        beat = FakeBeatBackend()
        beat.backend_id = "shared"
        registry.register("scene_detector", scene)
        registry.register("beat_analyzer", beat)
        self.assertIs(registry.get("beat_analyzer", "shared"), beat)


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.primary = FakeSceneBackend("primary")
        self.fallback = FakeSceneBackend("fallback")

    def test_successful_primary_does_not_run_fallback(self):
        calls = []
        outcome = execute_with_fallback(
            self.primary, self.fallback,
            run=lambda backend: (
                calls.append(backend.backend_id)
                or BackendResult(backend.backend_id, "ok", (SceneCut(2.0),))
            ),
        )
        self.assertEqual(calls, ["primary"])
        self.assertFalse(outcome.fallback_used)
        self.assertEqual(outcome.result.backend_id, "primary")

    def test_missing_optional_dependency_uses_explicit_fallback(self):
        calls = []
        def run(backend):
            calls.append(backend.backend_id)
            if backend is self.primary:
                raise BackendUnavailableError("optional package missing")
            return BackendResult(backend.backend_id, "ok")
        outcome = execute_with_fallback(self.primary, self.fallback, run=run)
        self.assertEqual(calls, ["primary", "fallback"])
        self.assertTrue(outcome.fallback_used)
        self.assertEqual(outcome.attempts[0].status, "unavailable")
        self.assertEqual(outcome.result.backend_id, "fallback")

    def test_failed_status_uses_explicit_fallback(self):
        def run(backend):
            status = "failed" if backend is self.primary else "ok"
            return BackendResult(backend.backend_id, status)
        outcome = execute_with_fallback(self.primary, self.fallback, run=run)
        self.assertTrue(outcome.fallback_used)
        self.assertEqual(outcome.result.status, "ok")

    def test_insufficient_evidence_does_not_trigger_hidden_retry(self):
        calls = []
        outcome = execute_with_fallback(
            self.primary, self.fallback,
            run=lambda backend: (
                calls.append(backend.backend_id)
                or BackendResult(backend.backend_id, "insufficient_evidence")
            ),
        )
        self.assertEqual(calls, ["primary"])
        self.assertFalse(outcome.fallback_used)
        self.assertEqual(outcome.result.status, "insufficient_evidence")

    def test_without_fallback_returns_explicit_failure(self):
        outcome = execute_with_fallback(
            self.primary, None,
            run=lambda backend: BackendResult(
                backend.backend_id, "failed", warnings=("crashed",)
            ),
        )
        self.assertIsNotNone(outcome.result)
        self.assertEqual(outcome.result.status, "failed")
        self.assertFalse(outcome.fallback_used)
        self.assertEqual(outcome.error, "crashed")

    def test_expected_execution_error_uses_fallback(self):
        def run(backend):
            if backend is self.primary:
                raise BackendExecutionError("backend process returned nonzero")
            return BackendResult(backend.backend_id, "ok")
        outcome = execute_with_fallback(self.primary, self.fallback, run=run)
        self.assertTrue(outcome.fallback_used)
        self.assertEqual(outcome.result.backend_id, "fallback")

    def test_unexpected_programming_error_is_not_silenced(self):
        def run(_backend):
            raise ValueError("programming bug")
        with self.assertRaises(ValueError):
            execute_with_fallback(self.primary, self.fallback, run=run)

    def test_provenance_mismatch_is_rejected(self):
        def run(_backend):
            return BackendResult("different-backend", "ok")
        with self.assertRaises(ValueError):
            execute_with_fallback(self.primary, self.fallback, run=run)


class EvidenceContractTests(unittest.TestCase):
    def test_normalized_box_must_stay_inside_frame(self):
        self.assertEqual(NormalizedBox(0.1, 0.2, 0.3, 0.4).width, 0.3)
        with self.assertRaises(ValueError):
            NormalizedBox(0.8, 0.1, 0.3, 0.2)

    def test_scene_cut_rejects_negative_timestamp(self):
        with self.assertRaises(ValueError):
            SceneCut(-0.1)

    def test_backend_result_rejects_invalid_confidence(self):
        with self.assertRaises(ValueError):
            BackendResult("model", "ok", confidence=1.5)

    def test_backend_result_requires_tuple_items(self):
        with self.assertRaises(ValueError):
            BackendResult("model", "ok", items=[])


if __name__ == "__main__":
    unittest.main()
