import unittest

from retrieval_assistance import attempt_retrieval_assistance


def retrieval(state, score):
    return {"state": state, "candidates": [{"raw_tfidf_similarity": score}]}


class FakeRuntime:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def retrieve(self, query, language):
        self.calls.append((query, language))
        return self.result


class FakeService:
    def __init__(self, result=None, available=True, reason="configured"):
        self.result = result or {"success": True, "interpreted_query": "clear maize query"}
        self.available = available
        self.reason = reason
        self.calls = []

    def availability(self):
        return {"available": self.available, "reason": self.reason}

    def interpret_query(self, query, language):
        self.calls.append((query, language))
        return self.result


class RetrievalAssistanceTests(unittest.TestCase):
    def test_strong_result_never_calls_gemini(self):
        service = FakeService()
        result = attempt_retrieval_assistance("maize", "en", retrieval("A", .8), FakeRuntime(None), service)
        self.assertFalse(result["called"])
        self.assertEqual(service.calls, [])

    def test_missing_configuration_preserves_first_result(self):
        first = retrieval("B", .2)
        service = FakeService(available=False, reason="missing_api_key")
        result = attempt_retrieval_assistance("maize", "en", first, FakeRuntime(None), service)
        self.assertIs(result["selected_retrieval"], first)
        self.assertEqual(result["reason"], "missing_api_key")

    def test_strong_non_regressing_second_pass_is_accepted(self):
        runtime = FakeRuntime(retrieval("A", .7))
        service = FakeService()
        result = attempt_retrieval_assistance("unclear maize words", "en", retrieval("B", .2), runtime, service)
        self.assertTrue(result["accepted"])
        self.assertEqual(len(service.calls), 1)
        self.assertEqual(runtime.calls, [("clear maize query", "en")])

    def test_second_weak_result_is_rejected(self):
        first = retrieval("B", .2)
        result = attempt_retrieval_assistance("unclear maize words", "en", first, FakeRuntime(retrieval("B", .4)), FakeService())
        self.assertFalse(result["accepted"])
        self.assertIs(result["selected_retrieval"], first)

    def test_regressing_strong_result_is_rejected(self):
        first = retrieval("B", .4)
        result = attempt_retrieval_assistance("unclear maize words", "en", first, FakeRuntime(retrieval("A", .3)), FakeService())
        self.assertFalse(result["accepted"])
        self.assertEqual(result["reason"], "second_pass_score_regressed")

    def test_unchanged_interpretation_does_not_retry(self):
        runtime = FakeRuntime(retrieval("A", .8))
        service = FakeService({"success": True, "interpreted_query": "same query"})
        result = attempt_retrieval_assistance("same query", "en", retrieval("B", .2), runtime, service)
        self.assertEqual(result["reason"], "unchanged_interpretation")
        self.assertEqual(runtime.calls, [])


if __name__ == "__main__":
    unittest.main()
