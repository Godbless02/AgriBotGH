from flask import Flask, request, jsonify, send_from_directory
import json
import os
import re
from pathlib import Path

from entity_guard import DatasetEntityGuard
from retrieval_runtime import RetrievalRuntime, sha256_file
from retrieval_assistance import attempt_retrieval_assistance
from retrieval_semantics import has_agricultural_intent
from services.abena_tts_service import AbenaTTSService, MAX_TTS_TEXT_LENGTH
from services.gemini_service import GeminiService
from services.weather_service import WeatherService

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024
WEATHER_SERVICE = WeatherService()
GEMINI_SERVICE = GeminiService()
ABENA_TTS_SERVICE = AbenaTTSService()

DATA_FILE = DATA_DIR / 'data' / 'agribotgh_dataset_bilingual_563.json'
SUGGESTION_LINKS_FILE = BASE_DIR / 'models' / 'suggestion_links.json'
QUICK_QUESTIONS_FILE = BASE_DIR / 'models' / 'quick_questions.json'
MODEL_FREEZE_FILE = BASE_DIR / 'models' / 'production' / 'model_freeze.json'

# ── MODEL LOADING ─────────────────────────────────────────────────
print("Loading chatbot data...")

def load_canonical_dataset(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    required = (
        'id', 'category', 'question_en', 'answer_en', 'question_twi', 'answer_twi'
    )
    if len(data) != 563:
        raise RuntimeError(f'Canonical dataset must contain 563 records, found {len(data)}')
    for item in data:
        if any(field not in item or not str(item[field]).strip() for field in required):
            raise RuntimeError(f"Invalid canonical dataset record: {item.get('id')}")
    return data


if not DATA_FILE.exists():
    raise RuntimeError(f'Canonical dataset is missing: {DATA_FILE}')
print(f"Loading canonical local dataset from {DATA_FILE}")
CANONICAL_RECORDS = load_canonical_dataset(DATA_FILE)
ENTITY_GUARD = DatasetEntityGuard(CANONICAL_RECORDS)
AVAILABLE_CATEGORIES = tuple(sorted(
    {
        str(record.get('category', '')).strip()
        for record in CANONICAL_RECORDS
        if str(record.get('category', '')).strip()
    },
    key=str.casefold,
))
en_qs = [record['question_en'].strip() for record in CANONICAL_RECORDS]
en_as = [record['answer_en'].strip() for record in CANONICAL_RECORDS]
tw_qs = [record['question_twi'].strip() for record in CANONICAL_RECORDS]
tw_as = [record['answer_twi'].strip() for record in CANONICAL_RECORDS]
RETRIEVAL_RUNTIME = RetrievalRuntime(BASE_DIR, DATA_FILE)


def load_final_model_freeze(path):
    if not path.exists():
        raise RuntimeError(f'Final model freeze is missing: {path}')
    with path.open('r', encoding='utf-8') as handle:
        freeze = json.load(handle)
    metadata = RETRIEVAL_RUNTIME.metadata
    manifest = RETRIEVAL_RUNTIME.manifest
    checks = (
        (freeze.get('status') == 'frozen', 'Model freeze is not active'),
        (freeze.get('semantic_version') == metadata['semantic_version'], 'Frozen model version differs from active model'),
        (freeze.get('dataset_sha256') == metadata['canonical_dataset_sha256'], 'Frozen dataset differs from active dataset'),
        (freeze.get('metadata_sha256') == manifest['metadata_sha256'], 'Frozen metadata differs from active metadata'),
        (freeze.get('comparison_sha256') == sha256_file(BASE_DIR / freeze['comparison_file']), 'Frozen comparison checksum mismatch'),
    )
    for passed, message in checks:
        if not passed:
            raise RuntimeError(message)
    return freeze


FINAL_MODEL_FREEZE = load_final_model_freeze(MODEL_FREEZE_FILE)
print(
    f"Ready! {len(en_qs)} EN + {len(tw_qs)} TW canonical pairs; "
    f"{RETRIEVAL_RUNTIME.metadata['model_version']} loaded."
)


def normalize_known_question(value):
    """Normalize only for exact known-record identity checks."""
    return re.sub(r"[^\w]+", " ", str(value or "").casefold(), flags=re.UNICODE).strip()


def build_known_record_registry():
    """Build stable suggestion IDs directly from canonical dataset record IDs."""
    registry = {}
    for item in CANONICAL_RECORDS:
        dataset_id = item.get('id')
        if not isinstance(dataset_id, int):
            raise ValueError('Every canonical dataset record must have an integer ID.')
        record_id = f"qa-{dataset_id:04d}"
        record = {
            "id": record_id,
            "dataset_id": dataset_id,
            "category": item.get('category', '').strip(),
            "question_en": item.get('question_en', '').strip(),
            "answer_en": item.get('answer_en', '').strip(),
            "question_tw": item.get('question_twi', '').strip(),
            "answer_tw": item.get('answer_twi', '').strip(),
        }
        if record_id in registry:
            raise ValueError(f"Duplicate canonical dataset ID: {dataset_id}")
        if not all(record[key] for key in (
            'category', 'question_en', 'answer_en', 'question_tw', 'answer_tw'
        )):
            raise ValueError(f"Incomplete canonical dataset record: {dataset_id}")
        registry[record_id] = record
    return registry


KNOWN_RECORDS = build_known_record_registry()
def load_quick_questions(path):
    """Load display-only prompts; answers are always selected by retrieval."""
    if not path.exists():
        raise RuntimeError(f'Missing quick-question catalogue: {path}')
    with path.open('r', encoding='utf-8') as handle:
        artifact = json.load(handle)
    if artifact.get('canonical_dataset') != 'data/agribotgh_dataset_bilingual_563.json':
        raise RuntimeError('Quick questions do not name the canonical dataset')
    quick = artifact.get('questions')
    if not isinstance(quick, dict):
        raise RuntimeError('Quick-question catalogue must contain a questions object')
    for language in ('en', 'tw'):
        if not isinstance(quick.get(language), list):
            raise RuntimeError(f'Quick-question catalogue is missing {language}')
        if any(
            not isinstance(item, dict)
            or set(item) != {'text'}
            or not isinstance(item['text'], str)
            or not item['text'].strip()
            for item in quick[language]
        ):
            raise RuntimeError('Quick questions must be non-empty display text only')
    if len(quick['en']) != 8 or len(quick['tw']) != 6:
        raise RuntimeError('Quick-question catalogue must contain 8 English and 6 Twi entries')
    return quick


QUICK_QUESTIONS = load_quick_questions(QUICK_QUESTIONS_FILE)

# ── TOPICS ────────────────────────────────────────────────────────
# All 28 UI topics with their retrieval keywords, Twi names, and icons.
# Suggested questions are loaded only from the canonical linkage artifact.

TOPICS = {
    "Soil & Land Preparation": {
        "icon": "🌍",
        "tw_name": "Asase ne Afuo Siesie",
        "keywords_en": ["soil","land","ph","acidic","erosion","compost",
                        "organic","tillage","raised bed","nursery","transplant",
                        "germina","seed","planting","spacing","rotation","mulch","biochar"],
        "keywords_tw": ["asase","afuo","pH","acidic","huru","compost","nhwiren-tew",
                        "nursery","aba","to mu","siesie","mulch","biochar","asintiɛ"],
    },
    "Fertilizer & Nutrients": {
        "icon": "🧪",
        "tw_name": "Ferefere ne Aduan",
        "keywords_en": ["fertilizer","npk","nutrient","manure","green manure",
                        "nitrogen","phosphorus","potassium","foliar","deficien"],
        "keywords_tw": ["ferefere","NPK","nutrient","mmoa dɔteɛ","nhwiren-tew",
                        "nitrogen","phosphorus","potassium","foliar","hia"],
    },
    "Maize": {
        "icon": "🌽",
        "tw_name": "Aburoɔ",
        "keywords_en": ["maize","corn","armyworm","streak","aburow"],
        "keywords_tw": ["aburow","aburo","aborɔnoma adwummaker","streak","aburoɔ"],
    },
    "Cassava": {
        "icon": "🥔",
        "tw_name": "Bankye",
        "keywords_en": ["cassava","gari","mosaic","starch","fufu"],
        "keywords_tw": ["bankye","gari","mosaic","starch","fufu"],
    },
    "Plantain & Banana": {
        "icon": "🍌",
        "tw_name": "Boɔde ne Kwadu",
        "keywords_en": ["plantain","banana","sigatoka","sucker"],
        "keywords_tw": ["boɔde","kwadu","sigatoka","sucker","borɔdɔ"],
    },
    "Yam": {
        "icon": "🍠",
        "tw_name": "Bayerɛ",
        "keywords_en": ["yam","sett","mound"],
        "keywords_tw": ["bayerɛ","sett","afe","stake"],
    },
    "Cocoyam": {
        "icon": "🌿",
        "tw_name": "Kɔkɔnte",
        "keywords_en": ["cocoyam","kontomire","taro","eddoe"],
        "keywords_tw": ["kɔkɔnte","kontomire","taro","eddoe"],
    },
    "Tomatoes": {
        "icon": "🍅",
        "tw_name": "Ntomatoes",
        "keywords_en": ["tomato","blight","blossom","leaf miner"],
        "keywords_tw": ["ntomato","tomato","blight","ntomate"],
    },
    "Pepper": {
        "icon": "🌶️",
        "tw_name": "Mako",
        "keywords_en": ["pepper","scotch bonnet","bell pepper"],
        "keywords_tw": ["mako","pepper","bell pepper"],
    },
    "Onion": {
        "icon": "🧅",
        "tw_name": "Gyene / Abɔnkɔ",
        "keywords_en": ["onion","downy","thrips"],
        "keywords_tw": ["gyene","abɔnkɔ","onion","thrips","downy"],
    },
    "Carrot": {
        "icon": "🥕",
        "tw_name": "Carrot",
        "keywords_en": ["carrot"],
        "keywords_tw": ["carrot"],
    },
    "Garden Eggs": {
        "icon": "🍆",
        "tw_name": "Ntorɔ / Mako Ntorɔ",
        "keywords_en": ["garden egg","eggplant","epilachna"],
        "keywords_tw": ["ntorɔ","ntoro","garden egg","epilachna"],
    },
    "Palm Oil & Coconut": {
        "icon": "🌴",
        "tw_name": "Abɛ ne Kuuku",
        "keywords_en": ["palm","coconut","kernel"],
        "keywords_tw": ["abɛ","kuuku","coconut","palm","ɔman"],
    },
    "Groundnut & Legumes": {
        "icon": "🥜",
        "tw_name": "Nkatie ne Abɔdweɛ",
        "keywords_en": ["groundnut","cowpea","soybean","legume"],
        "keywords_tw": ["nkatie","abɔdweɛ","soya","legume"],
    },
    "Rice": {
        "icon": "🌾",
        "tw_name": "Ɔmo / Ɔtɛ",
        "keywords_en": ["rice","striga"],
        "keywords_tw": ["ɔtɛ","ɔmo","rice","striga"],
    },
    "Cocoa": {
        "icon": "🍫",
        "tw_name": "Kookoo",
        "keywords_en": ["cocoa","black pod","cacao"],
        "keywords_tw": ["kookoo","cocoa","black pod"],
    },
    "Other Vegetables": {
        "icon": "🥦",
        "tw_name": "Nnuan Foforo",
        "keywords_en": ["cucumber","watermelon","moringa","vegetable","pineapple","mango","cashew"],
        "keywords_tw": ["nnuan","kakaduro","watermelon","moringa","aborɔfo","pineapple","mango"],
    },
    "Pest & Disease Control": {
        "icon": "🐛",
        "tw_name": "Adwummaker ne Yadeɛ Tia",
        "keywords_en": ["pest","disease","aphid","mite","fungus","nematode",
                        "weevil","armyworm","ipm","integrated","pesticide","neem"],
        "keywords_tw": ["adwummaker","yadeɛ","aphid","mite","fungus","nematode",
                        "weevil","armyworm","IPM","dawuro","neem"],
    },
    "Irrigation & Water": {
        "icon": "💧",
        "tw_name": "Nsuo ne Quench",
        "keywords_en": ["irrigat","water","drip","borehole","flood","drainage","moisture","dam"],
        "keywords_tw": ["nsuo","quench","drip","borehole","flood","drainage","dam","nsuo gye"],
    },
    "Harvesting & Storage": {
        "icon": "🏪",
        "tw_name": "Yi ne Guina",
        "keywords_en": ["harvest","storage","store","post-harvest","hermetic","silo","aflatoxin","mould","weevil"],
        "keywords_tw": ["yi","guina","harvest","storage","hermetic","silo","aflatoxin","mold","weevil"],
    },
    "Fish Farming": {
        "icon": "🐟",
        "tw_name": "Apataa Adwuma",
        "keywords_en": ["fish","tilapia","catfish","pond","cage","fingerling","aquaculture"],
        "keywords_tw": ["apataa","tilapia","catfish","pond","cage","fingerling","aquaculture"],
    },
    "Poultry Farming": {
        "icon": "🐔",
        "tw_name": "Akoko Adwuma",
        "keywords_en": ["poultry","chicken","broiler","layer","newcastle","litter","brooder","guinea fowl","egg"],
        "keywords_tw": ["akoko","akokɔ","broiler","layer","newcastle","litter","brooder","kurontihene","tamma"],
    },
    "Goat Farming": {
        "icon": "🐐",
        "tw_name": "Birekyie / Abirekyi Adwuma",
        "keywords_en": ["goat","kid","doe","buck","dairy goat"],
        "keywords_tw": ["birekyie","abirekyi","PPR","mma","mmofraase","bɔhyɛ"],
    },
    "Sheep Farming": {
        "icon": "🐑",
        "tw_name": "Oguan Adwuma",
        "keywords_en": ["sheep","lamb","ewe","foot rot"],
        "keywords_tw": ["oguan","lamb","ewe","foot rot"],
    },
    "Cattle Farming": {
        "icon": "🐄",
        "tw_name": "Nnwan Adwuma",
        "keywords_en": ["cattle","cow","bull","calf","trypanosomiasis","fodder"],
        "keywords_tw": ["nnwan","boo","bull","calf","trypanosomiasis","fodder"],
    },
    "Business & Marketing": {
        "icon": "💰",
        "tw_name": "Adwuma ne Dwa",
        "keywords_en": ["market","sell","profit","income","loan","credit","cooperative",
                        "contract","export","insurance","budget","middlemen","business"],
        "keywords_tw": ["dwa","tɔn","mfaso","sika","mfɛdomhyɛw","kuo","contract",
                        "export","insurance","budget","middlemen","adwuma plan"],
    },
    "Climate & Weather": {
        "icon": "🌦️",
        "tw_name": "Osuoha ne Berɛ",
        "keywords_en": ["climate","weather","drought","flood","rainfall","season","agroforestry"],
        "keywords_tw": ["osuoha","berɛ","climate","drought","flood","rainfall","agroforestry"],
    },
    "Farm Management": {
        "icon": "📋",
        "tw_name": "Afuom Hwɛ",
        "keywords_en": ["manage","plan","map","labour","equipment","extension","mofa","record","mechaniz"],
        "keywords_tw": ["hwɛ","plan","map","adwuma","equipment","extension","MOFA","nsɛm","kora"],
    },
}

CATEGORY_TO_TOPIC = {
    "Soil & Land Preparation": "Soil & Land Preparation",
    "Fertilizer & Nutrients": "Fertilizer & Nutrients",
    "Maize": "Maize",
    "Cassava": "Cassava",
    "Plantain & Banana": "Plantain & Banana",
    "Yam": "Yam",
    "Tomato": "Tomatoes",
    "Pepper": "Pepper",
    "Onion": "Onion",
    "Carrot": "Carrot",
    "Garden Eggs": "Garden Eggs",
    "Oil Palm & Coconut": "Palm Oil & Coconut",
    "Palm & Coconut": "Palm Oil & Coconut",
    "Groundnut & Legumes": "Groundnut & Legumes",
    "Rice Farming": "Rice",
    "Cocoa Farming": "Cocoa",
    "Cucumber Farming": "Other Vegetables",
    "Okra Farming": "Other Vegetables",
    "Watermelon Farming": "Other Vegetables",
    "Pest & Disease Control": "Pest & Disease Control",
    "Irrigation & Water": "Irrigation & Water",
    "Harvesting & Storage": "Harvesting & Storage",
    "Post-Harvest & Food Safety": "Harvesting & Storage",
    "Fish Farming": "Fish Farming",
    "Poultry Farming": "Poultry Farming",
    "Goat Rearing": "Goat Farming",
    "Sheep Rearing": "Sheep Farming",
    "Cattle Rearing": "Cattle Farming",
    "Business & Marketing": "Business & Marketing",
    "Farm Business Planning": "Business & Marketing",
    "Climate-Smart Farming": "Climate & Weather",
    "Farm Management & General": "Farm Management",
    "Farm Mechanization & Tools": "Farm Management",
    "Farm Records & Extension": "Farm Management",
    "Beekeeping": "Farm Management",
    "Grasscutter Farming": "Farm Management",
    "Mushroom Farming": "Farm Management",
    "Pig Farming": "Farm Management",
    "Rabbit Farming": "Farm Management",
    "Snail Farming": "Farm Management",
}

# ── CONVERSATION HELPERS ──────────────────────────────────────────
def load_suggestion_links():
    if not SUGGESTION_LINKS_FILE.exists():
        raise RuntimeError(
            f"Missing suggestion linkage artifact: {SUGGESTION_LINKS_FILE}"
        )
    with open(SUGGESTION_LINKS_FILE, 'r', encoding='utf-8') as handle:
        report = json.load(handle)
    links = report.get('links', {})
    if set(links) != set(TOPICS):
        raise RuntimeError('Suggestion-link topics do not match application topics')
    for topic in TOPICS:
        topic_links = links.get(topic)
        if not isinstance(topic_links, list) or not 1 <= len(topic_links) <= 5:
            raise RuntimeError(f"Invalid suggestion links for topic: {topic}")
        for position, link in enumerate(topic_links):
            record_id = link.get('record_id')
            if record_id not in KNOWN_RECORDS:
                raise RuntimeError(
                    f"Suggestion link references unknown record: {topic}[{position}]"
                )
            record = KNOWN_RECORDS[record_id]
            if link.get('dataset_id') != record['dataset_id']:
                raise RuntimeError(f"Stale dataset ID in link: {topic}[{position}]")
            if link.get('category') != record['category']:
                raise RuntimeError(f"Stale category in link: {topic}[{position}]")
            for language in ('en', 'tw'):
                linked_text = link.get(f'suggestion_{language}', '')
                canonical_text = record[f'question_{language}']
                if linked_text != canonical_text:
                    raise RuntimeError(
                        f"Stale suggestion text in link: {topic}[{position}]/{language}"
                    )
    return links


SUGGESTION_LINKS = load_suggestion_links()

EN_GREET  = ['hi','hello','hey','good morning','good afternoon','good evening']
TW_GREET  = ['akwaaba','maakye','maaha','maadwo']
CASUAL    = ['how are you','i am fine','thank you','thanks','okay','ok','good','nice','great']
NAME_PH   = ['my name is','i am ','i\'m ','call me ']
VAGUE     = ['help','help me','i need help','i have a problem','i have a question',
             'i want to know','tell me','what can you do','what do you know']

def detect_topic(text, lang='en'):
    """Return the best matching topic for a given input text."""
    t = text.lower()
    key = 'keywords_tw' if lang == 'tw' else 'keywords_en'
    best_topic, best_score = None, 0
    for topic, info in TOPICS.items():
        score = sum(1 for kw in info[key] if kw in t)
        if score > best_score:
            best_score = score
            best_topic = topic
    return best_topic if best_score > 0 else None

def get_suggestions(topic, lang='en'):
    """Return suggestion questions for a topic in the right language."""
    language = 'tw' if lang == 'tw' else 'en'
    return [
        {
            "id": link["record_id"],
            "text": link[f"suggestion_{language}"],
        }
        for link in SUGGESTION_LINKS.get(topic, [])[:5]
    ]


def validate_known_suggestion(suggestion_id, question, lang):
    """Reject forged/stale suggestion IDs without bypassing retrieval."""
    record = KNOWN_RECORDS.get(str(suggestion_id or ""))
    if record is None:
        return "Unknown suggestion ID"
    language = 'tw' if lang == 'tw' else 'en'
    if normalize_known_question(question) != normalize_known_question(
        record[f"question_{language}"]
    ):
        return "Suggestion text does not match its record ID"
    return None


def get_candidate_suggestions(candidates, lang):
    """Turn retrieved canonical candidates into safe direct-answer buttons."""
    language = 'tw' if lang == 'tw' else 'en'
    suggestions = []
    seen = set()
    for candidate in candidates:
        record_id = f"qa-{candidate['id']:04d}"
        if record_id in seen or record_id not in KNOWN_RECORDS:
            continue
        seen.add(record_id)
        suggestions.append({
            "id": record_id,
            "text": KNOWN_RECORDS[record_id][f"question_{language}"],
        })
    return suggestions

def get_topic_display_name(topic, lang='en'):
    """Return topic name in the right language."""
    info = TOPICS.get(topic, {})
    if lang == 'tw':
        return info.get('tw_name', topic)
    return topic


def get_available_category_presentation():
    """Return UI metadata for categories derived from the in-memory dataset."""
    icons = {}
    twi_names = {}
    for category in AVAILABLE_CATEGORIES:
        topic = CATEGORY_TO_TOPIC.get(category)
        topic_info = TOPICS.get(topic, {})
        icons[category] = topic_info.get('icon', '🌱')
        twi_name = topic_info.get('tw_name')
        twi_names[category] = (
            f"{twi_name} — {category}" if twi_name else category
        )
    return icons, twi_names


# High-precision non-agricultural intent markers supplement the statistical
# domain router. They deliberately use phrases, not isolated words such as
# "field", "seed", "feed", "plant", "crop", or "storage", because those
# words have legitimate agricultural meanings. Canonical and paraphrased
# questions still pass through the same statistical retrieval runtime.
EXPLICIT_OFF_TOPIC_PATTERNS = {
    'en': (
        r'\bcapital (?:city )?of\b',
        r'\blaptop screen\b',
        r'\bpython\b.*\bdecorator\b|\bdecorator\b.*\bpython\b',
        r'\blinux (?:server|root|account)\b|\broot account\b',
        r'\brandom seed\b.*\bsimulation\b|\bsimulation\b.*\brandom seed\b',
        r'\bnews feed\b.*\bsocial media\b|\bsocial media\b.*\bnews feed\b',
        r'\bchemistry (?:textbook|book|class)\b',
        r'\bcomputer virus\b|\bspreadsheet\b',
        r'\bgit\b.*\b(?:branch|merge|commit|repository)\b|\b(?:branch|merge|commit|repository)\b.*\bgit\b',
        r'\b(?:bitcoin|crypto(?:currency)?)\b.*\b(?:farm|farming|mining)\b',
        r'\bserver farm\b',
        r'\bcrop\b.*\b(?:photo|portrait|image)\b',
        r'\bharvest\b.*\b(?:public records|website|web data)\b',
        r'\bmanufacturing plant\b|\bplant\b.*\bphone chargers?\b',
    ),
    'tw': (
        r'\bcapital city\b',
        r'\blaptop screen\b',
        r'\bpython\b.*\bdecorator\b|\bdecorator\b.*\bpython\b',
        r'\blinux (?:server|root|account)\b|\broot account\b',
        r'\brandom seed\b.*\bsimulation\b|\bsimulation\b.*\brandom seed\b',
        r'\bnews feed\b.*\bsocial media\b|\bsocial media\b.*\bnews feed\b',
        r'\bchemistry (?:textbook|book|class)\b',
        r'\bcomputer virus\b|\bspreadsheet\b',
        r'\b(?:bitcoin|crypto(?:currency)?)\b.*\b(?:farm|farming|mining)\b',
        r'\bserver farm\b',
        r'\bgit\b.*\b(?:branch|merge|commit|repository)\b|\b(?:branch|merge|commit|repository)\b.*\bgit\b',
    ),
}

# High-precision crop and livestock names can safely rescue a strict router
# miss into State B. Broader, overloaded terms such as field, plant, crop,
# seed, feed, bug, harvest, and storage are intentionally excluded.
AGRICULTURAL_ENTITY_PATTERNS = {
    'en': (
        r'\b(?:maize|cassava|plantain|cocoyam|groundnut|cowpea|soybean|compost)\b',
        r'\b(?:tomato(?:es)?|garden eggs?|oil palm|cocoa|rice paddy)\b',
        r'\b(?:poultry|chickens?|broilers?|layers?|tilapia|catfish)\b',
        r'\b(?:goats?|sheep|cattle|piglets?|rabbits?|grasscutters?)\b',
    ),
    'tw': (
        r'\b(?:aburo|aburow|bankye|borɔdɔ|bayerɛ|kɔkɔnte|kookoo|compost)\b',
        r'\b(?:ntomato|tomato|ntorɔ|ntoro|mako|gyene|nkatie)\b',
        r'\b(?:akokɔ|akoko|apataa|birekyie|abirekyi|oguan|nnwan)\b',
    ),
}

HIGH_RISK_AGRICULTURE_PATTERN = re.compile(
    r"\b(?:pesticides?|insecticides?|fungicides?|herbicides?|miticides?|"
    r"antibiotics?|vaccin(?:e|es|ation|ate|ated|ating)?|deworm(?:er|ers|ing)?|"
    r"ivermectin|albendazole|levamisole|carbofuran|imidacloprid|spinosad|"
    r"emamectin|mancozeb|chlorothalonil|lambda-cyhalothrin|abamectin|"
    r"chemical(?:s)?|fertili[sz]er|ferefere|nnuru|aduro|dose|dosage|treatment)\b",
    flags=re.IGNORECASE | re.UNICODE,
)

SAFETY_NOTICES = {
    'en': (
        "Safety note: Product strengths and local recommendations vary. Follow "
        "the current product label and consult a MOFA extension officer or "
        "veterinary professional before using pesticides, medicines, vaccines, "
        "fertilizer rates, or treatment doses."
    ),
    'tw': (
        "Ahobammɔ ho nkae: Aduru biara ahoɔden ne ne nhyehyɛe sesa. Di nea "
        "wɔakyerɛw wɔ aduru no so no akyi, na bisa MOFA kuayɛ ɔfotufoɔ anaa "
        "mmoa ayaresafoɔ ansa na wode pesticide, mmoa aduru, vaccine, ferefere "
        "dodow anaa dose bi adi dwuma."
    ),
}


def is_explicitly_off_topic(text, lang='en'):
    """Recognize narrow, unambiguous non-farming intents in either UI language."""
    language = 'tw' if lang == 'tw' else 'en'
    normalized = str(text or '').casefold()
    return any(
        re.search(pattern, normalized, flags=re.UNICODE)
        for pattern in EXPLICIT_OFF_TOPIC_PATTERNS[language]
    )


def has_agricultural_entity_signal(text, lang='en'):
    """Recognize unambiguous crop or livestock names in either UI language."""
    language = 'tw' if lang == 'tw' else 'en'
    normalized = str(text or '').casefold()
    entity_match = any(
        re.search(pattern, normalized, flags=re.UNICODE)
        for pattern in AGRICULTURAL_ENTITY_PATTERNS[language]
    )
    semantic_language = 'Twi' if language == 'tw' else 'English'
    return entity_match or has_agricultural_intent(normalized, semantic_language)


WEATHER_CONDITION_PATTERN = re.compile(
    r"\b(?:weather|forecast|temperature|hot|rain(?:fall|ing)?|sunny|wind(?:y)?|"
    r"humidity|storm|heatwave|dry\s+weather|ewiem|osuo|nsuo|ɔhyew)\b",
    flags=re.IGNORECASE,
)
LIVE_WEATHER_CUE_PATTERN = re.compile(
    r"\b(?:today|tomorrow|tonight|now|current(?:ly)?|this\s+week|next\s+week|"
    r"nnɛ|ɔkyena|seesei)\b|\bwill\s+it\s+(?:rain|be\s+hot)",
    flags=re.IGNORECASE,
)
AGRICULTURAL_WEATHER_KNOWLEDGE_PATTERN = re.compile(
    r"\b(?:farm|farming|rearing|crop|crops|maize|poultry|snails?|irrigation|"
    r"production|chicks?|plants?|soil)\b.*\b(?:affect|important|best|need|needs|"
    r"increase|reduce|matter|suitable|required)\b|"
    r"\b(?:why|how\s+does|what)\b.*\b(?:important|affect|best|matter|increase)\b.*"
    r"\b(?:farm|farming|rearing|production|irrigation|crop|maize|poultry|snails?)\b",
    flags=re.IGNORECASE,
)


def is_weather_information_request(text):
    """Route only live/current conditions, not agricultural weather concepts."""
    normalized = str(text or '').strip()
    if not normalized:
        return False
    if not WEATHER_CONDITION_PATTERN.search(normalized):
        return False
    live_cue = bool(LIVE_WEATHER_CUE_PATTERN.search(normalized))
    agricultural_explanation = bool(
        AGRICULTURAL_WEATHER_KNOWLEDGE_PATTERN.search(normalized)
    )
    if agricultural_explanation and not live_cue:
        return False
    explicit_service_request = bool(
        re.search(r"\b(?:weather|forecast)\b", normalized, flags=re.IGNORECASE)
    )
    return live_cue or explicit_service_request


def add_safety_notice(result, question, lang='en'):
    """Attach transparent high-risk guidance without rewriting canonical answers."""
    if result.get("type") != "answer":
        return result
    combined = f"{question} {result.get('text', '')}"
    if HIGH_RISK_AGRICULTURE_PATTERN.search(combined):
        language = 'tw' if lang == 'tw' else 'en'
        result["safety_notice"] = SAFETY_NOTICES[language]
        result["safety_classification"] = "high_risk_agricultural_guidance"
    return result


def get_answer(question, lang, username=None):
    q  = question.strip()
    ql = q.lower()
    nb = f", {username}" if username else ""
    is_tw = (lang == 'tw')

    # ── Name introduction ──────────────────────────────────────────
    all_name_phrases = [
        ('my name is','en'), ("i am ",'en'), ("i'm ",'en'), ('call me ','en'),
        ('me din de ','tw'), ('wɔfrɛ me ','tw'), ('me din yɛ ','tw')
    ]
    for ph, _ in all_name_phrases:
        if ql.startswith(ph.lower()):
            name = q[len(ph):].strip().split()[0].capitalize()
            if is_tw:
                return {"type":"answer","text":f"Ɛyɛ me anigye sɛ mahuu wo, {name}! 🌱 Yɛfrɛ me AgriBotGH. Bisa me nsɛmfua biara fa okuafo adwuma ho!"}
            return {"type":"answer","text":f"Nice to meet you, {name}! 🌱 I am AgriBotGH. Ask me anything about farming!"}

    # ── Twi Greetings ──────────────────────────────────────────────
    TW_GREET_LIST = ['akwaaba','maakye','maaha','maadwo','ɛte sɛn','wo ho te sɛn']
    if any(re.search(rf'\b{re.escape(g)}\b', ql) for g in TW_GREET_LIST) and len(ql) < 40:
        return {"type":"answer","text":f"Akwaaba{nb}! 🌿 Yɛfrɛ me AgriBotGH, wo okuafo mmoa chatbot. Asɛmmisa bɛn fa okuafo adwuma ho na wopɛ sɛ mebo wo aseɛ?"}

    # ── English Greetings ──────────────────────────────────────────
    EN_GREET_LIST = ['hi','hello','hey','good morning','good afternoon','good evening']
    if any(re.search(rf'\b{re.escape(g)}\b', ql) for g in EN_GREET_LIST) and len(ql) < 40:
        return {"type":"answer","text":f"Hello{nb}! 🌿 I am AgriBotGH, your bilingual farming assistant. What farming question can I help you with today?"}

    # ── Twi Casual ─────────────────────────────────────────────────
    TW_CASUAL_LIST = ['medaase','meda wo ase']
    if is_tw and any(c in ql for c in TW_CASUAL_LIST):
        return {"type":"answer","text":f"Medaase{nb}! 😊 Mewɔ ha bere biara sɛ mboa wo wɔ okuafo asɛmmisa ho. Dɛn na wopɛ sɛ wonim?"}

    # ── English Casual ─────────────────────────────────────────────
    EN_CASUAL_LIST = ['how are you','i am fine',"i'm fine",'thank you','thanks','okay','ok']
    if not is_tw and any(ql.strip() == c for c in EN_CASUAL_LIST):
        return {"type":"answer","text":f"You're welcome{nb}! 😊 I am always here to help with your farming questions. What would you like to know?"}

    # ── Vague / too short ──────────────────────────────────────────
    TW_VAGUE_LIST = ['boa me','mhia mmoa','bisa','kyerɛ me','yɛ dɛn']
    EN_VAGUE_LIST = ['help','help me','i need help','i have a problem','i have a question',
                     'i want to know','tell me','what can you do','what do you know']
    vague_list = TW_VAGUE_LIST if is_tw else EN_VAGUE_LIST
    is_vague = any(ql.strip() == v for v in vague_list) or len(ql.strip()) < 6

    if is_vague:
        topic_icons = {t: TOPICS[t]['icon'] for t in TOPICS}
        topic_names_tw = {t: TOPICS[t].get('tw_name', t) for t in TOPICS}
        if is_tw:
            return {
                "type": "topics",
                "text": f"Akwaaba{nb}! 😊 Yɛfrɛ me AgriBotGH — okuafo mmoa chatbot ma Ghana okuafo.\n\nMetumi aboa wo wɔ nsɛm pii ho. Paw topic baako a ɛdwene wo:",
                "topics": list(TOPICS.keys()),
                "topic_icons": topic_icons,
                "topic_names_tw": topic_names_tw
            }
        return {
            "type": "topics",
            "text": f"Hello{nb}! 😊 I am AgriBotGH — a farming assistant for Ghanaian farmers.\n\nI can help you with many topics. Please select one that interests you:",
            "topics": list(TOPICS.keys()),
            "topic_icons": topic_icons,
            "topic_names_tw": topic_names_tw
        }

    detected_topic = detect_topic(ql, lang)
    entity_profile = ENTITY_GUARD.profile(q, lang)
    agricultural_question = bool(
        has_agricultural_entity_signal(q, lang) or entity_profile["salient"]
    )
    weather_question = is_weather_information_request(q)
    retrieval = RETRIEVAL_RUNTIME.retrieve(q, lang)
    top_candidate = retrieval["candidates"][0]
    entity_decision = ENTITY_GUARD.evaluate(
        q, top_candidate["question"], top_candidate["category"], lang
    )
    if retrieval["state"] == "A" and not entity_decision.compatible:
        retrieval = dict(retrieval)
        retrieval["state"] = "B"
        retrieval["entity_support_rejected"] = True
        retrieval["entity_support_reason"] = entity_decision.reason
    if is_explicitly_off_topic(q, lang):
        retrieval["state"] = "C"
        retrieval["explicit_off_topic"] = True
    elif retrieval["state"] == "C" and agricultural_question:
        # The statistical domain detector is intentionally strict. A known
        # farming-topic term is enough to ask for clarification, but never to
        # return an answer. Explicit non-farming phrases above keep priority.
        retrieval["state"] = "B"
        retrieval["lexical_agriculture_signal"] = True

    assistance = None
    if retrieval["state"] == "B" and not weather_question:
        assistance = attempt_retrieval_assistance(
            q, lang, retrieval, RETRIEVAL_RUNTIME, GEMINI_SERVICE, ENTITY_GUARD
        )
        retrieval = assistance["selected_retrieval"]
        top_candidate = retrieval["candidates"][0]
        entity_decision = ENTITY_GUARD.evaluate(
            q, top_candidate["question"], top_candidate["category"], lang
        )
        if retrieval["state"] == "A" and not entity_decision.compatible:
            retrieval = dict(retrieval)
            retrieval["state"] = "B"
            retrieval["entity_support_rejected"] = True
            retrieval["entity_support_reason"] = entity_decision.reason
            assistance["accepted"] = False
            assistance["reason"] = "entity_incompatible_second_pass"
    top_candidate = retrieval["candidates"][0]

    if retrieval["state"] == "A":
        result = {
            "type": "answer",
            "text": top_candidate["answer"],
            "source": "retrieval_v1",
            "routing_state": "A",
            "record_id": f"qa-{top_candidate['id']:04d}",
            "retrieval_score": top_candidate["final_score"],
            "score_margin": retrieval["answer_margin"],
        }
        if assistance and assistance["accepted"]:
            result["gemini_assisted"] = True
            result["retrieval_assistance"] = {
                "accepted": True,
                "original_score": assistance["original_score"],
                "interpreted_score": assistance["interpreted_score"],
            }
        return result

    if retrieval["state"] == "B":
        if agricultural_question and not weather_question:
            available_topic_icons, available_topic_names_tw = (
                get_available_category_presentation()
            )
            if is_tw:
                text = (
                    "Mete ase sɛ eyi yɛ kuayɛ ho asɛmmisa, nanso mantumi "
                    "annya mmuae a metumi de me ho ato so yiye wɔ me kuayɛ "
                    "nimdeɛ a ɛwɔ hɔ mprempren no mu. Wubetumi apaw kuayɛ "
                    "nsɛm a metumi aboa wo wɔ ho no mu biako wɔ ase ha."
                )
            else:
                text = (
                    "I understand that this is a farming question, but I "
                    "couldn't find a sufficiently reliable answer in my "
                    "current agricultural knowledge base. You can try one of "
                    "the farming topics I currently support below."
                )
            assistance_status = {
                "eligible": bool(assistance and assistance["eligible"]),
                "called": bool(assistance and assistance["called"]),
                "accepted": False,
                "reason": (
                    assistance["reason"] if assistance
                    else "assistance_not_attempted"
                ),
            }
            return {
                "type": "knowledge_gap",
                "text": text,
                "knowledge_gap": True,
                "available_topics": list(AVAILABLE_CATEGORIES),
                "available_topic_icons": available_topic_icons,
                "available_topic_names_tw": available_topic_names_tw,
                "source": "retrieval_v1",
                "routing_state": "D",
                "domain_score": retrieval["domain_score"],
                "score_margin": retrieval["answer_margin"],
                "domain_signal": (
                    "recognized_agricultural_topic"
                    if retrieval.get("lexical_agriculture_signal")
                    else "agricultural_intent_detector"
                ),
                "retrieval_assistance": assistance_status,
            }

        topic = detected_topic or CATEGORY_TO_TOPIC.get(top_candidate["category"])
        if topic in TOPICS:
            suggestions = get_suggestions(topic, lang)
            icon = TOPICS[topic]["icon"]
            display_name = get_topic_display_name(topic, lang)
        else:
            suggestions = get_candidate_suggestions(retrieval["candidates"], lang)
            icon = "🌱"
            display_name = top_candidate["category"]

        if is_tw:
            text = (
                "Me nni ahotoso koraa sɛ mete wo asɛmmisa no ase yiye. "
                "Yɛsrɛ wo, kyerɛkyerɛ mu bio anaa paw asɛmmisa a ɛfa "
                f"{display_name} {icon} ho:"
            )
        else:
            text = (
                "I'm not fully confident that I understood your agricultural "
                "question. Please rephrase it or add more detail, or choose a "
                f"related question about {display_name} {icon}:"
            )
        return {
            "type": "low_confidence",
            "text": text,
            "suggestions": suggestions,
            "topic": topic,
            "source": "retrieval_v1",
            "routing_state": "B",
            "domain_score": retrieval["domain_score"],
            "score_margin": retrieval["answer_margin"],
            "domain_signal": (
                "recognized_agricultural_topic"
                if retrieval.get("lexical_agriculture_signal")
                else "statistical_domain_router"
            ),
        }

    topic_icons = {topic: TOPICS[topic]['icon'] for topic in TOPICS}
    topic_names_tw = {
        topic: TOPICS[topic].get('tw_name', topic) for topic in TOPICS
    }
    if is_tw:
        text = (
            f"Kafra{nb}, me yɛ AgriBotGH — chatbot a wɔayɛ no pɛ ma okuafo "
            "adwuma. Metumi aboa wo pɛ wɔ okuafo nsɛm ho. 🌾\\n\\n"
            "Paw topic baako fi aseɛ yi na mɛkyerɛ wo asɛm a metumi aboa wo wɔ so:"
        )
    else:
        text = (
            f"Sorry{nb}, I am AgriBotGH — a specialised agricultural assistant. "
            "I can only help with farming-related topics. 🌾\\n\\n"
            "Please select a topic below and I will show you what I can help you with:"
        )
    return {
        "type": "off_topic",
        "text": text,
        "topics": list(TOPICS.keys()),
        "topic_icons": topic_icons,
        "topic_names_tw": topic_names_tw,
        "source": "retrieval_v1",
        "routing_state": "C",
        "domain_score": retrieval["domain_score"],
        "off_topic_signal": (
            "explicit_non_agricultural_intent"
            if retrieval.get("explicit_off_topic")
            else "statistical_domain_router"
        ),
    }
# ── ROUTES ────────────────────────────────────────────────────────
@app.route('/api/chat', methods=['POST'])
def chat():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400

    message = d.get('message')
    if not isinstance(message, str):
        return jsonify({"error": "Message must be text"}), 400
    question = message.strip()
    language = d.get('language','en')
    username = d.get('username', None)
    suggestion_id = d.get('suggestion_id')
    if not question:
        return jsonify({"error": "No message provided"}), 400
    if len(question) > 2000:
        return jsonify({"error": "Message must not exceed 2000 characters"}), 400
    if not isinstance(language, str) or language not in {'en', 'tw'}:
        return jsonify({"error": "Language must be 'en' or 'tw'"}), 400
    if username is not None:
        if not isinstance(username, str):
            return jsonify({"error": "Username must be text"}), 400
        username = username.strip()[:30] or None

    if suggestion_id is not None:
        error = validate_known_suggestion(
            suggestion_id, question, language
        )
        if error:
            return jsonify({"error": error}), 400

    result = get_answer(question, language, username)
    add_safety_notice(result, question, language)
    result["language"] = language
    return jsonify(result)

@app.route('/api/topics', methods=['GET'])
def get_topics():
    """Return the canonical topic catalogue used by the browser UI."""
    return jsonify({
        topic: {
            "icon": info['icon'],
            "tw_name": info.get('tw_name', topic),
            "suggestion_count": len(SUGGESTION_LINKS[topic]),
            "suggestions": get_suggestions(topic, 'en'),
        }
        for topic, info in TOPICS.items()
    })


@app.route('/api/quick-suggestions', methods=['GET'])
def quick_suggestions_route():
    """Return reviewed right-panel questions linked to canonical records."""
    lang = request.args.get('lang', 'en')
    if lang not in {'en', 'tw'}:
        return jsonify({"error": "Language must be 'en' or 'tw'"}), 400
    return jsonify({"language": lang, "suggestions": QUICK_QUESTIONS[lang]})

@app.route('/api/topic-suggestions', methods=['POST'])
def topic_suggestions_route():
    """Return suggestions for a selected topic in the right language."""
    d     = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400
    topic = d.get('topic','')
    lang = d.get('lang', 'en')
    if not isinstance(topic, str):
        return jsonify({"error": "Topic must be text"}), 400
    if not isinstance(lang, str) or lang not in {'en', 'tw'}:
        return jsonify({"error": "Language must be 'en' or 'tw'"}), 400
    if topic not in TOPICS:
        return jsonify({"error": "Topic not found"}), 404
    info  = TOPICS[topic]
    suggs = get_suggestions(topic, lang)
    name  = info.get('tw_name', topic) if lang == 'tw' else topic
    return jsonify({
        "topic": topic,
        "display_name": name,
        "icon": info['icon'],
        "suggestions": suggs
    })


@app.route('/api/weather', methods=['GET'])
def weather_route():
    """Return live Open-Meteo conditions and a short location forecast."""
    raw_location = request.args.get('location')
    location = raw_location.strip() if isinstance(raw_location, str) else raw_location
    app.logger.debug("Weather endpoint received location=%r", location)
    result = WEATHER_SERVICE.get_weather(location)
    if result.get('success'):
        return jsonify(result)
    status_by_code = {
        'empty_location': 400,
        'invalid_location': 400,
        'location_not_found': 404,
        'timeout': 504,
        'api_http_error': 502,
        'service_unavailable': 503,
        'invalid_response': 502,
        'unexpected_error': 500,
    }
    return jsonify(result), status_by_code.get(result.get('code'), 502)


@app.route('/api/tts', methods=['POST'])
def twi_tts_route():
    """Return server-generated Twi audio; the browser owns playback fallback."""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400

    text = payload.get('text')
    language = payload.get('language')
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Text must be a non-empty string"}), 400
    if language != 'twi':
        return jsonify({"error": "Language must be 'twi'"}), 400
    text = text.strip()
    if len(text) > MAX_TTS_TEXT_LENGTH:
        return jsonify({
            "error": f"Text must not exceed {MAX_TTS_TEXT_LENGTH} characters"
        }), 413

    result = ABENA_TTS_SERVICE.synthesize(text)
    return jsonify(result), 200 if result.get('success') else 503

@app.route('/api/health')
def health():
    return jsonify({
        "status": "ok",
        "en_pairs": len(en_qs),
        "tw_pairs": len(tw_qs),
        "topics": len(TOPICS),
        "model_version": RETRIEVAL_RUNTIME.metadata["model_version"],
        "semantic_version": RETRIEVAL_RUNTIME.metadata["semantic_version"],
        "retrieval_architecture": RETRIEVAL_RUNTIME.metadata[
            "retrieval_architecture"
        ],
        "training_records": RETRIEVAL_RUNTIME.metadata["training_records"],
        "model_frozen": FINAL_MODEL_FREEZE["status"] == "frozen",
        "freeze_id": FINAL_MODEL_FREEZE["freeze_id"],
        "gemini_retrieval_assistance": GEMINI_SERVICE.availability(),
        "twi_text_to_speech": ABENA_TTS_SERVICE.availability(),
    })


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"error": "Request payload is too large"}), 413

ALLOWED_STATIC_FILES = {
    'app.js',
    'style.css',
    'index.html',
}

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/<path:f>')
def static_files(f):
    if f in ALLOWED_STATIC_FILES or f.startswith('css/') or f.startswith('js/'):
        return send_from_directory(BASE_DIR, f)
    return jsonify({"error": "Not found"}), 404

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'false').strip().lower() == 'true'
    port       = int(os.getenv('PORT', 5000))
    app.run(debug=debug_mode, port=port)
