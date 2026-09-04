"""Calibrate semantic retrieval only as a fallback behind the current ranker."""

from __future__ import annotations

import json
from pathlib import Path

from evaluate_retrieval_robustness import EDGE_FILE, OFF_TOPIC_FILES, load_json
from evaluate_semantic_retrieval_v2 import SemanticIndex
from query_normalization import normalize_query
from retrieval_runtime import RetrievalRuntime
from retrieval_semantics import extract_entities
from retrieval_semantics import has_agricultural_intent
import app as agribot


BASE = Path(__file__).resolve().parent
DATASET = BASE / "data/agribotgh_dataset_bilingual_563.json"
OLD = BASE / "data/evaluation/retrieval_paraphrase_cases.json"
NEW = BASE / "data/evaluation/retrieval_challenge_v2.json"
OUTPUT = BASE / "models/semantic_fallback_v2_evaluation.json"


def acceptable(case):
    return case.get("acceptable_record_ids", [case.get("expected_record_id")])


def specificity_safe(question, candidate_question, language):
    query = extract_entities(normalize_query(question, language), language)
    candidate = extract_entities(normalize_query(candidate_question, language), language)
    return not (
        (not query and candidate)
        or (query and candidate and not query & candidate)
    )


def main():
    records = load_json(DATASET)
    current = RetrievalRuntime(BASE, DATASET)
    semantic = {language: SemanticIndex(records, language) for language in ("English", "Twi")}
    new = load_json(NEW)
    positives = load_json(OLD)["cases"] + new["positive_cases"]
    negatives = []
    for path in OFF_TOPIC_FILES:
        negatives.extend(load_json(path)["cases"])
    negatives.extend(load_json(EDGE_FILE)["cases"])
    negatives.extend([
        {"id":"fallback_neg_capital","language":"English","question":"What is the capital of France?"},
        {"id":"fallback_neg_joke","language":"English","question":"Tell me a joke."},
        {"id":"fallback_neg_bitcoin","language":"English","question":"How can I start Bitcoin farming?"},
        {"id":"fallback_neg_server","language":"English","question":"How do I maintain a server farm?"},
    ])

    def signals(case):
        language = case["language"]
        code = "tw" if language == "Twi" else "en"
        base = current.retrieve(case["question"], code)
        base_top = base["candidates"][0]
        sem = semantic[language].retrieve(case["question"])
        normalized = normalize_query(case["question"], language)
        vague = (
            normalized in {
                "help", "help me", "i need help", "i have a problem",
                "i have a question", "i want to know", "tell me",
                "what can you do", "what do you know", "boa me", "mhia mmoa",
                "bisa", "kyerɛ me", "yɛ dɛn",
            }
            or len(normalized) < 6
        )
        return {
            **case,
            "base_state": base["state"], "base_id": base_top["id"],
            "base_safe": specificity_safe(case["question"],base_top["question"],language),
            "semantic": sem,
            "prehandled": vague or agribot.is_explicitly_off_topic(case["question"], code),
            "agricultural_intent": has_agricultural_intent(case["question"], language),
        }

    positive_results = [signals(x) for x in positives]
    negative_results = [signals(x) for x in negatives]
    ambiguous_results = [signals(x) for x in new["ambiguous_agriculture_cases"]]

    gates=[]
    for threshold in (0.35,0.40,0.45,0.50,0.55,0.60,0.65,0.70,0.75):
        for margin in (0.03,0.05,0.08,0.10,0.12,0.15):
            def decide(item):
                if item["prehandled"]: return None, "prehandled"
                if item["base_state"] == "A" and item["base_safe"]:
                    return item["base_id"], "base"
                if item["base_state"] == "C" and not item["agricultural_intent"]:
                    return None, "off_topic"
                sem=item["semantic"]
                if sem["specificity_safe"] and sem["retrieval_score"]>=threshold and sem["margin"]>=margin:
                    return sem["record_id"], "semantic_fallback"
                return None, "abstain"
            positive_decisions=[(*decide(x),x) for x in positive_results]
            negative_decisions=[(*decide(x),x) for x in negative_results]
            ambiguous_decisions=[(*decide(x),x) for x in ambiguous_results]
            correct=sum(record_id in acceptable(item) for record_id,_,item in positive_decisions if record_id is not None)
            wrong=[item["id"] for record_id,_,item in positive_decisions if record_id is not None and record_id not in acceptable(item)]
            negative_false=[item["id"] for record_id,_,item in negative_decisions if record_id is not None]
            ambiguous_false=[item["id"] for record_id,_,item in ambiguous_decisions if record_id is not None]
            gates.append({
                "semantic_threshold":threshold,"semantic_minimum_margin":margin,
                "correct_answers":correct,"incorrect_positive_answers":len(wrong),
                "negative_false_accepts":len(negative_false),"ambiguous_false_answers":len(ambiguous_false),
                "coverage":correct/len(positive_results),"incorrect_positive_ids":wrong,
                "negative_false_accept_ids":negative_false,"ambiguous_false_answer_ids":ambiguous_false,
                "semantic_fallback_answers":sum(source=="semantic_fallback" for _,source,_ in positive_decisions),
            })
    safe=[x for x in gates if x["incorrect_positive_answers"]==0 and x["negative_false_accepts"]==0 and x["ambiguous_false_answers"]==0]
    selection=max(safe,key=lambda x:(x["correct_answers"],x["semantic_threshold"],x["semantic_minimum_margin"]),default=None)
    language_selections={}
    for language in ("English","Twi"):
        pos=[x for x in positive_results if x["language"]==language]
        neg=[x for x in negative_results if x["language"]==language]
        amb=[x for x in ambiguous_results if x["language"]==language]
        language_gates=[]
        for threshold in (0.30,0.35,0.40,0.45,0.50,0.55,0.60,0.65,0.70,0.75):
            for margin in (0.02,0.03,0.05,0.08,0.10,0.12,0.15):
                def decide_language(item):
                    if item["prehandled"]: return None,"prehandled"
                    if item["base_state"]=="A" and item["base_safe"]: return item["base_id"],"base"
                    if item["base_state"]=="C" and not item["agricultural_intent"]: return None,"off_topic"
                    sem=item["semantic"]
                    if sem["specificity_safe"] and sem["retrieval_score"]>=threshold and sem["margin"]>=margin: return sem["record_id"],"semantic_fallback"
                    return None,"abstain"
                p=[(*decide_language(x),x) for x in pos]
                n=[(*decide_language(x),x) for x in neg]
                a=[(*decide_language(x),x) for x in amb]
                wrong=[item["id"] for rid,_,item in p if rid is not None and rid not in acceptable(item)]
                false_neg=[item["id"] for rid,_,item in n if rid is not None]
                false_amb=[item["id"] for rid,_,item in a if rid is not None]
                correct=sum(rid in acceptable(item) for rid,_,item in p if rid is not None)
                language_gates.append({"semantic_threshold":threshold,"semantic_minimum_margin":margin,"correct_answers":correct,"cases":len(pos),"coverage":correct/len(pos),"incorrect_positive_answers":len(wrong),"negative_false_accepts":len(false_neg),"ambiguous_false_answers":len(false_amb),"semantic_fallback_answers":sum(src=="semantic_fallback" for _,src,_ in p)})
        safe_language=[x for x in language_gates if x["incorrect_positive_answers"]==0 and x["negative_false_accepts"]==0 and x["ambiguous_false_answers"]==0]
        language_selections[language]=max(safe_language,key=lambda x:(x["correct_answers"],x["semantic_threshold"],x["semantic_minimum_margin"]),default=None)
    dual_gate_selections={}
    for language in ("English","Twi"):
        pos=[x for x in positive_results if x["language"]==language]; neg=[x for x in negative_results if x["language"]==language]; amb=[x for x in ambiguous_results if x["language"]==language]
        dual=[]
        for threshold in (0.25,0.30,0.35,0.40,0.45):
            for margin in (0.08,0.10,0.12,0.15):
                for strong in (0.50,0.55,0.60,0.65,0.70):
                    def dual_decide(item):
                        if item["prehandled"]: return None,"prehandled"
                        if item["base_state"]=="A" and item["base_safe"]: return item["base_id"],"base"
                        if item["base_state"]=="C" and not item["agricultural_intent"]: return None,"off_topic"
                        sem=item["semantic"]
                        semantic_accept=sem["retrieval_score"]>=strong or (sem["retrieval_score"]>=threshold and sem["margin"]>=margin)
                        if sem["specificity_safe"] and semantic_accept: return sem["record_id"],"semantic_fallback"
                        return None,"abstain"
                    p=[(*dual_decide(x),x) for x in pos]; n=[(*dual_decide(x),x) for x in neg]; a=[(*dual_decide(x),x) for x in amb]
                    wrong=[item["id"] for rid,_,item in p if rid is not None and rid not in acceptable(item)]; fn=[item["id"] for rid,_,item in n if rid is not None]; fa=[item["id"] for rid,_,item in a if rid is not None]
                    correct=sum(rid in acceptable(item) for rid,_,item in p if rid is not None)
                    dual.append({"semantic_threshold":threshold,"semantic_minimum_margin":margin,"semantic_strong_threshold":strong,"correct_answers":correct,"cases":len(pos),"coverage":correct/len(pos),"incorrect_positive_answers":len(wrong),"negative_false_accepts":len(fn),"ambiguous_false_answers":len(fa),"semantic_fallback_answers":sum(src=="semantic_fallback" for _,src,_ in p),"incorrect_positive_ids":wrong,"negative_false_accept_ids":fn,"ambiguous_false_answer_ids":fa})
        safe_dual=[x for x in dual if x["incorrect_positive_answers"]==0 and x["negative_false_accepts"]==0 and x["ambiguous_false_answers"]==0]
        dual_gate_selections[language]=max(safe_dual,key=lambda x:(x["correct_answers"],x["semantic_strong_threshold"],x["semantic_threshold"],x["semantic_minimum_margin"]),default=None)
    report={"schema_version":1,"positive_cases":len(positive_results),"negative_cases":len(negative_results),"ambiguous_cases":len(ambiguous_results),"selection":selection,"selection_by_language":language_selections,"dual_gate_selection_by_language":dual_gate_selections,"gates":gates,"positive_results":positive_results,"negative_results":negative_results,"ambiguous_results":ambiguous_results}
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(selection,indent=2))
    print(json.dumps(language_selections,indent=2))
    print(json.dumps(dual_gate_selections,indent=2))
    print(f"Report: {OUTPUT}")


if __name__=="__main__": main()
