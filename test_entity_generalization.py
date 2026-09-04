import json
import unittest
from unittest.mock import patch

import app


ORIGINAL_UNSEEN = (
    "How can I start raising turkeys commercially on a farm?",
    "What kind of housing do ducks need on a small farm?",
    "How can I rear camels for milk production on a farm?",
    "What shelter do geese need on a poultry farm?",
    "How do I start cricket farming for animal feed?",
    "How can I establish a silkworm farm for silk production?",
    "What fencing is needed for deer farming?",
    "How can I grow lavender commercially on my farm?",
    "What soil conditions are best for saffron farming?",
    "How can I start seaweed farming near the coast?",
)

SECOND_UNSEEN = (
    "How can I raise bison for meat on a farm?",
    "What feed is suitable for llamas on a small farm?",
    "What shelter do pheasants need when they are reared commercially?",
    "How should I house quails for egg production?",
    "How can I start rearing yaks for milk production?",
    "How do I grow asparagus commercially?",
    "What soil is suitable for vanilla farming?",
    "How can I establish a dragonfruit farm?",
    "What fertilizer should I use when growing hops?",
    "How do I grow artichokes on an organic farm?",
)


class FakeGeminiService:
    available = True

    def __init__(self, interpretations=None):
        self.interpretations = interpretations or {}
        self.calls = []

    def availability(self):
        return {"available": True, "reason": "configured", "model": "fake"}

    def interpret_query(self, query, language):
        self.calls.append((query, language))
        return {
            "success": True,
            "interpreted_query": self.interpretations.get(query, query),
        }


class EntityGeneralizationTests(unittest.TestCase):
    def test_original_unseen_set_is_ten_of_ten_state_d(self):
        interpretations = {
            ORIGINAL_UNSEEN[1]: "What housing is suitable for ducks on a small farm?",
            ORIGINAL_UNSEEN[6]: "What type of fence is suitable for a deer farm?",
        }
        with patch.object(app, "GEMINI_SERVICE", FakeGeminiService(interpretations)):
            results = [app.get_answer(question, "en") for question in ORIGINAL_UNSEEN]
        self.assertEqual([result["routing_state"] for result in results], ["D"] * 10)
        self.assertTrue(all(result["type"] == "knowledge_gap" for result in results))

    def test_second_unseen_set_is_absent_and_ten_of_ten_state_d(self):
        serialized_dataset = json.dumps(
            app.CANONICAL_RECORDS, ensure_ascii=False
        ).casefold()
        expected_absent_terms = (
            "bison", "llama", "pheasant", "quail", "yak", "asparagus",
            "vanilla", "dragonfruit", "hops", "artichoke",
        )
        for term in expected_absent_terms:
            with self.subTest(absence=term):
                self.assertNotIn(term, serialized_dataset)

        with patch.object(app, "GEMINI_SERVICE", FakeGeminiService()):
            results = [app.get_answer(question, "en") for question in SECOND_UNSEEN]
        self.assertEqual([result["routing_state"] for result in results], ["D"] * 10)

    def test_gemini_cannot_drop_an_unknown_salient_entity(self):
        question = "How should I house llamas on a farm?"
        service = FakeGeminiService({
            question: "What animal housing is suitable on a farm?",
        })
        with patch.object(app, "GEMINI_SERVICE", service):
            result = app.get_answer(question, "en")
        self.assertEqual(result["routing_state"], "D")
        self.assertEqual(
            result["retrieval_assistance"]["reason"],
            "salient_entity_not_preserved",
        )

    def test_dataset_supported_aliases_remain_compatible(self):
        cases = (
            ("How should I fertilize corn?", "How should I fertilize maize?", "Maize"),
            ("What feed is best for a cow?", "What feed is best for cattle?", "Cattle Rearing"),
            ("What housing does a chicken need?", "What housing does poultry need?", "Poultry Farming"),
        )
        for query, candidate, category in cases:
            with self.subTest(query=query):
                decision = app.ENTITY_GUARD.evaluate(query, candidate, category, "en")
                self.assertTrue(decision.compatible, decision)

    def test_live_weather_and_agricultural_weather_knowledge_are_separated(self):
        live_weather = (
            "What is the humidity in Kumasi today?",
            "Will it rain tomorrow in Tamale?",
            "What is the weather in Accra?",
            "How hot is it in Wa today?",
        )
        agricultural_knowledge = (
            "Why is humidity important in snail farming?",
            "How does rainfall affect maize production?",
            "What temperature is best for poultry chicks?",
            "Why does dry weather increase irrigation needs?",
        )
        self.assertTrue(all(app.is_weather_information_request(q) for q in live_weather))
        self.assertFalse(any(app.is_weather_information_request(q) for q in agricultural_knowledge))

    def test_snail_humidity_can_complete_normal_retrieval_assistance(self):
        question = "Why is humidity important when rearing snails?"
        service = FakeGeminiService({
            question: "Why does humidity matter in snail farming?",
        })
        with patch.object(app, "GEMINI_SERVICE", service):
            result = app.get_answer(question, "en")
        self.assertEqual(result["routing_state"], "A")
        self.assertEqual(result["record_id"], "qa-0465")
        self.assertTrue(result["gemini_assisted"])

    def test_supported_direct_questions_across_sixteen_categories_do_not_gap(self):
        categories = (
            "Maize", "Cassava", "Tomato", "Onion", "Soil & Land Preparation",
            "Fertilizer & Nutrients", "Poultry Farming", "Cattle Rearing",
            "Sheep Rearing", "Fish Farming", "Rabbit Farming", "Snail Farming",
            "Mushroom Farming", "Beekeeping", "Irrigation & Water",
            "Farm Records & Extension",
        )
        records = {
            category: next(
                record for record in app.CANONICAL_RECORDS
                if record["category"] == category
            )
            for category in categories
        }
        service = FakeGeminiService()
        with patch.object(app, "GEMINI_SERVICE", service):
            for category, record in records.items():
                for language, question_key in (
                    ("en", "question_en"), ("tw", "question_twi")
                ):
                    with self.subTest(category=category, language=language):
                        result = app.get_answer(record[question_key], language)
                        self.assertEqual(result["routing_state"], "A")
                        self.assertEqual(
                            result["record_id"], f"qa-{int(record['id']):04d}"
                        )
        self.assertEqual(service.calls, [])

    def test_supported_english_and_twi_paraphrases_retrieve_relevant_records(self):
        by_id = {int(record["id"]): record for record in app.CANONICAL_RECORDS}
        cases = (
            ("en", "Which fertilizer works well for corn?", 2),
            ("en", "How do I pick healthy cassava cuttings for planting?", 219),
            ("en", "What is a successful way to grow onion in Ghana?", 245),
            ("en", "Why is humidity important when rearing snails?", 465),
            ("en", "Which basic environment helps mushrooms grow?", 424),
            ("en", "What should I consider before keeping bees?", 474),
            ("en", "Which irrigation method suits a small farm?", 61),
            ("en", "Which farm records should a new farmer keep first?", 524),
            ("tw", "Aburo ferefere bɛn na ɛyɛ papa?", 2),
            ("tw", "Nnuru bɛn na mede bɛko nhaban bɔne wɔ m'aburo afuo mu?", 212),
            ("tw", "Nsuo to kwan bɛn na ɛfata afuo ketewa?", 61),
            ("tw", "Adɛn nti na nwini ho hia wɔ snail kuayɛ mu?", 465),
        )
        interpretations = {
            query: by_id[record_id][
                "question_twi" if language == "tw" else "question_en"
            ]
            for language, query, record_id in cases
        }
        service = FakeGeminiService(interpretations)
        with patch.object(app, "GEMINI_SERVICE", service):
            for language, query, record_id in cases:
                with self.subTest(language=language, query=query):
                    result = app.get_answer(query, language)
                    self.assertNotEqual(result["routing_state"], "D")
                    if record_id == 524:
                        # Record 101 is a related, adequate records answer and
                        # remains an intentionally measured top-1 ambiguity.
                        self.assertIn(result.get("record_id"), {"qa-0101", "qa-0524"})
                    else:
                        self.assertEqual(
                            result.get("record_id"), f"qa-{record_id:04d}"
                        )


if __name__ == "__main__":
    unittest.main()
