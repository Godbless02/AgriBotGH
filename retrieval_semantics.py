"""Language-aware farming concepts and entity compatibility for retrieval."""

from __future__ import annotations

import re


ENGLISH_CONCEPTS = {
    "start": r"\b(?:start|begin|establish|set up|launch|go into|take up)\b",
    "grow": r"\b(?:grow|growing|cultivate|cultivation|raise|raising|produce|production)\b",
    "fertile": r"\b(?:fertile|fertility|productive|good soil|good land)\b",
    "make": r"\b(?:make|create|prepare|turn .{0,25} into|produce)\b",
    "acidic low ph": r"\b(?:acidic|acidity|low ph|very low ph)\b",
    "working effect help": r"\b(?:working|work|effect|effective|helping|started helping|improvement)\b",
    "plant sow planting": r"\b(?:plant|planting|sow|sowing|put .{0,20} (?:soil|ground))\b",
    "time season month year": r"\b(?:when|time|season|month|part of the year)\b",
    "depth deep below soil": r"\b(?:depth|deep|below (?:the )?(?:soil|ground)|how far .{0,20} (?:soil|ground))\b",
    "pest insect bug attack damage": r"\b(?:pest|pests|insect|insects|bugs?|attack|destroying|damage)\b",
    "control prevent stop protect": r"\b(?:control|prevent|stop|protect|keep .{0,20} away|avoid|fight)\b",
    "loan credit borrow finance": r"\b(?:loan|credit|borrow|financ(?:e|ing)|funding)\b",
    "harvest pick lift dig mature ready": r"\b(?:harvest|pick|lift|dig|uproot|mature|ready)\b",
    "site location place land field": r"\b(?:site|location|place|land|field|spot|area)\b",
    "tool equipment implement machinery": r"\b(?:tool|equipment|implement|machinery|machine)\b",
    "feed food diet eat nutrition": r"\b(?:feed|food|diet|eat|nutrition)\b",
    "lodging fall falling over": r"\b(?:lodging|falling over|fall over|falls? over|bend(?:ing)? over)\b",
    "pregnant pregnancy gestation expecting": r"\b(?:pregnant|pregnancy|gestation|expecting)\b",
    "sign recognize identify tell know": r"\b(?:signs?|recognize|identify|tell whether|know (?:if|when|whether))\b",
    "milk quantity amount quality": r"\b(?:milk|quantity|amount|quality)\b",
    "disease sick ill unwell": r"\b(?:disease|sick|ill|unwell|refuses? to eat|not eating)\b",
    "bitter taste": r"\b(?:bitter|taste)\b",
    "consider think before": r"\b(?:consider|think about|think of|before)\b",
    "records write down information": r"\b(?:records?|write down|information|notes?|document)\b",
    "drought rains fail no rain dry": r"\b(?:drought|rains? (?:fail|stop|stopped)|no rain|dry spell)\b",
    "store storage keep spoil": r"\b(?:store|storage|keep|kept|spoil|spoilage)\b",
    "erosion wash carry topsoil": r"\b(?:erosion|wash(?:ing)? away|carry(?:ing)? away|topsoil)\b",
    "fertilizer plant food nutrient npk urea": r"\b(?:fertili[sz]er|plant food|nutrients?|npk|urea)\b",
    "water irrigation moisture rain": r"\b(?:water|watering|irrigat(?:e|ion)|moisture|rain)\b",
}

TWI_CONCEPTS = {
    "start begin": r"(?:fi ase|hyɛ .{0,20} ase|mfi .{0,20} ase)",
    "grow farming": r"(?:kuayɛ|kuafo|dua|dɔ|yɛn)",
    "soil land": r"(?:asase|anhwea)",
    "good suitable fertile": r"(?:papa|yɛ yie|fata)",
    "make prepare": r"(?:yɛ|siesie|de .{0,25} ayɛ)",
    "plant sow": r"(?:dua|to mu|gu fam)",
    "time season when": r"(?:bere bɛn|da bɛn|bosome bɛn)",
    "depth deep soil": r"(?:tenten bɛn|kɔ asase mu|emu dɔ)",
    "pest insect damage": r"(?:mmoawa|adwummaker|sɛe|haw)",
    "control prevent protect": r"(?:gye .{0,20} ho|bɔ .{0,20} ho ban|gyina .{0,20} ano|amma)",
    "loan borrow money": r"(?:bosea|loan|sika)",
    "harvest uproot mature": r"(?:tutu|yie|anyin|boaboa)",
    "site place field": r"(?:beae|afuo|asase)",
    "feed food eat": r"(?:aduan|didi|di|mede ma)",
    "lodging fall": r"(?:tɔ fam|dabere|hwe fam)",
    "pregnant pregnancy gestation": r"(?:nyinsɛn|afa yafunu|wo mma)",
    "sign recognize know": r"(?:ahu|ahyɛnnam|nim sɛ|kyerɛ sɛ)",
    "milk quantity quality": r"(?:nufuo|pii|papa)",
    "disease sick unwell": r"(?:yare|mpɛ sɛ .{0,10} di|ɔnni apɔmuden)",
    "bitter taste": r"(?:nwene|dɛ)",
    "records write information": r"(?:nsɛm|kyerɛw|record)",
    "drought rain stopped": r"(?:ɔpɛ|osuo .{0,10} agyae|nsuo pa)",
    "store spoil": r"(?:kora|guina|ahunu|sɛe)",
    "fertilizer nutrient npk urea": r"(?:ferefere|npk|urea|aduan ma nnɔbae)",
    "water irrigation rain": r"(?:nsuo|osuo|gugu so)",
}

ENGLISH_ENTITIES = {
    "maize": r"\b(?:maize|corn)\b", "cassava": r"\bcassava\b",
    "plantain": r"\b(?:plantain|banana)\b", "yam": r"\byams?\b",
    "cocoa": r"\bcocoa\b", "tomato": r"\btomato(?:es)?\b",
    "pepper": r"\bpeppers?\b", "rice": r"\brice\b", "okra": r"\bokra\b",
    "cucumber": r"\bcucumbers?\b", "watermelon": r"\bwatermelons?\b",
    "mushroom": r"\bmushrooms?\b", "groundnut": r"\b(?:groundnuts?|peanuts?)\b",
    "cowpea": r"\bcowpeas?\b", "poultry": r"\b(?:poultry|chickens?|broilers?|layers?)\b",
    "fish": r"\b(?:fish|tilapia|catfish)\b", "goat": r"\bgoats?\b",
    "sheep": r"\bsheep\b", "cattle": r"\b(?:cattle|cows?|bulls?)\b",
    "pig": r"\b(?:pigs?|piglets?)\b", "rabbit": r"\brabbits?\b",
    "grasscutter": r"\bgrasscutters?\b", "snail": r"\bsnails?\b",
    "bee": r"\b(?:bees?|beekeeping|beehives?)\b",
}

TWI_ENTITIES = {
    "maize": r"(?:aburo|aburoɔ)", "cassava": r"bankye",
    "tomato": r"tomato", "rice": r"(?:rice|aburow)", "okra": r"okra",
    "cucumber": r"cucumber", "poultry": r"(?:akoko|akrɔma)",
    "fish": r"apataa", "goat": r"(?:birekyie|abirekyi|mmirekyie)",
    "cattle": r"(?:nantwie|boo)", "rabbit": r"rabbits?",
    "cocoa": r"(?:cocoa|kookoo)", "bee": r"(?:nkyene|bee)",
}


def expand_semantic_text(text, language):
    """Append matched concept labels without deleting the farmer's wording."""
    value = str(text or "").casefold()
    concepts = ENGLISH_CONCEPTS if language == "English" else TWI_CONCEPTS
    matched = [label for label, pattern in concepts.items() if re.search(pattern, value)]
    return f"{value} {' '.join(matched)}".strip()


def extract_entities(text, language):
    patterns = ENGLISH_ENTITIES if language == "English" else TWI_ENTITIES
    value = str(text or "").casefold()
    return {name for name, pattern in patterns.items() if re.search(pattern, value)}


def entity_compatibility(query_entities, candidate_entities):
    """Return 1 for compatible, 0.25 for unspecified, and 0 for conflict."""
    if not query_entities:
        return 0.25 if candidate_entities else 1.0
    if not candidate_entities:
        return 0.65
    return 1.0 if query_entities & candidate_entities else 0.0


AGRICULTURAL_INTENT_PATTERNS = {
    "English": re.compile(
        r"\b(?:agriculture|farm|farming|farmer|soil|land|crop|crops|seed|seeds|"
        r"fertili[sz]er|compost|manure|harvest|irrigat(?:e|ion)|livestock|"
        r"vegetables?|pests?|insects?|drought|planting|plants?|topsoil)\b"
    ),
    "Twi": re.compile(
        r"(?:kuayɛ|okuafo|afuo|asase|nnɔbae|aba|ferefere|mmoawa|adwummaker|"
        r"osuo|nsuo|dua|tutu|yie)"
    ),
}


def has_agricultural_intent(text, language):
    """Recognize clear farming context; this signal may only rescue to B."""
    return bool(
        extract_entities(text, language)
        or AGRICULTURAL_INTENT_PATTERNS[language].search(str(text or "").casefold())
    )
