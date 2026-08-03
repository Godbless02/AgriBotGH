from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from huggingface_hub import hf_hub_download
import numpy as np
import pickle
import json
import os
import re

app = Flask(__name__, static_folder=None)
CORS(app)

REPO_ID = "Godbles02/agribot-gh"
HF_TOKEN = os.getenv('HF_TOKEN', '').strip()
PREFER_HF = os.getenv('PREFER_HF', '').strip().lower() in ('1', 'true', 'yes', 'on')
FORCE_HF = os.getenv('FORCE_HF', '').strip().lower() in ('1', 'true', 'yes', 'on')
DATA_FILE = os.path.join(os.path.dirname(__file__), 'agri_dataset.json')
EN_VEC_FILE = os.path.join(os.path.dirname(__file__), 'en_vectorizer.pkl')
TW_VEC_FILE = os.path.join(os.path.dirname(__file__), 'tw_vectorizer.pkl')

# ── MODEL LOADING ─────────────────────────────────────────────────
print("Loading chatbot data...")

def hf(filename):
    kwargs = {'repo_id': REPO_ID, 'filename': filename}
    if HF_TOKEN:
        kwargs['token'] = HF_TOKEN
    return hf_hub_download(**kwargs)


def load_local_dataset(path):
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    en_qs, en_as, tw_qs, tw_as = [], [], [], []
    for item in data:
        en_q = item.get('instruction_en', '').strip()
        en_a = item.get('response_en', '').strip()
        tw_q = item.get('instruction_tw', '').strip()
        tw_a = item.get('response_tw', '').strip()

        if en_q and en_a:
            en_qs.append(en_q)
            en_as.append(en_a)
        if tw_q and tw_a:
            tw_qs.append(tw_q)
            tw_as.append(tw_a)

    if not en_qs or not tw_qs:
        raise ValueError('Local dataset must contain both English and Twi entries.')

    return en_qs, en_as, tw_qs, tw_as


def try_load_pickle(path):
    try:
        with open(path, 'rb') as f:
            return pickle.load(f)
    except Exception:
        return None


def build_vectorizers(en_qs, tw_qs):
    en_vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
    tw_vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
    en_vecs = en_vec.fit_transform(en_qs)
    tw_vecs = tw_vec.fit_transform(tw_qs)
    return en_vec, tw_vec, en_vecs, tw_vecs


def load_hf_assets():
    print("Loading chatbot from Hugging Face...")
    with open(hf('en_vectorizer.pkl'),'rb') as f:
        en_vec = pickle.load(f)
    with open(hf('tw_vectorizer.pkl'),'rb') as f:
        tw_vec = pickle.load(f)
    with open(hf('en_questions.json'),'r',encoding='utf-8') as f:
        en_qs = json.load(f)
    with open(hf('en_answers.json'), 'r',encoding='utf-8') as f:
        en_as = json.load(f)
    with open(hf('tw_questions.json'),'r',encoding='utf-8') as f:
        tw_qs = json.load(f)
    with open(hf('tw_answers.json'), 'r',encoding='utf-8') as f:
        tw_as = json.load(f)
    en_vecs = en_vec.transform(en_qs)
    tw_vecs = tw_vec.transform(tw_qs)
    return en_vec, tw_vec, en_vecs, tw_vecs, en_qs, en_as, tw_qs, tw_as


def load_chatbot_assets():
    if PREFER_HF or FORCE_HF:
        try:
            return load_hf_assets()
        except Exception as exc:
            if FORCE_HF:
                raise RuntimeError(
                    'Forced Hugging Face loading failed: ' + str(exc)
                )
            print('Hugging Face load failed; falling back to local assets:', exc)

    if os.path.exists(DATA_FILE):
        print(f"Loading local dataset from {DATA_FILE}")
        en_qs, en_as, tw_qs, tw_as = load_local_dataset(DATA_FILE)
        en_vec, tw_vec, en_vecs, tw_vecs = build_vectorizers(en_qs, tw_qs)
        return en_vec, tw_vec, en_vecs, tw_vecs, en_qs, en_as, tw_qs, tw_as

    if os.path.exists(EN_VEC_FILE) and os.path.exists(TW_VEC_FILE):
        print("Loading cached vectorizers from local files...")
        en_vec = try_load_pickle(EN_VEC_FILE)
        tw_vec = try_load_pickle(TW_VEC_FILE)
        if en_vec is not None and tw_vec is not None:
            try:
                with open('en_questions.json','r',encoding='utf-8') as f: en_qs = json.load(f)
                with open('en_answers.json','r',encoding='utf-8') as f: en_as = json.load(f)
                with open('tw_questions.json','r',encoding='utf-8') as f: tw_qs = json.load(f)
                with open('tw_answers.json','r',encoding='utf-8') as f: tw_as = json.load(f)
                en_vecs = en_vec.transform(en_qs)
                tw_vecs = tw_vec.transform(tw_qs)
                return en_vec, tw_vec, en_vecs, tw_vecs, en_qs, en_as, tw_qs, tw_as
            except Exception as e:
                print('Failed to load local cached assets:', e)

    try:
        return load_hf_assets()
    except Exception as e:
        raise RuntimeError('Failed to load chatbot assets from local dataset and Hugging Face: ' + str(e))


en_vec, tw_vec, en_vecs, tw_vecs, en_qs, en_as, tw_qs, tw_as = load_chatbot_assets()
print(f"Ready! {len(en_qs)} EN + {len(tw_qs)} TW pairs loaded.")

# ── TOPICS ────────────────────────────────────────────────────────
# All 28 topics extracted from the dataset with their keywords,
# Twi names, suggested questions, and topic icons.

TOPICS = {
    "Soil & Land Preparation": {
        "icon": "🌍",
        "tw_name": "Asase ne Afuo Siesie",
        "keywords_en": ["soil","land","ph","acidic","erosion","compost",
                        "organic","tillage","raised bed","nursery","transplant",
                        "germina","seed","planting","spacing","rotation","mulch","biochar"],
        "keywords_tw": ["asase","afuo","pH","acidic","huru","compost","nhwiren-tew",
                        "nursery","aba","to mu","siesie","mulch","biochar","asintiɛ"],
        "suggestions_en": [
            "How do I know if my soil is good for farming?",
            "How do I prevent soil erosion on my farm?",
            "How do I make compost at home?",
            "What is the best way to transplant seedlings?",
            "What is crop rotation and why is it important?"
        ],
        "suggestions_tw": [
            "Ɛdeɛn na ɛkyerɛ sɛ m'asase yɛ papa ma okuafo adwuma?",
            "Ɛdeɛn na mema asase amma ɛnhuru wɔ m'afuo mu?",
            "Ɛdeɛn na meyɛ compost wɔ fie?",
            "Kwan bɛn na ɛyɛ papa a yɛfa so si nnua nketewa baabi foforo?",
            "Dea ɛyɛ sɛ wosesa nnuaba gu asase mu na adɛn na ɛyɛ papa?"
        ]
    },
    "Fertilizer & Nutrients": {
        "icon": "🧪",
        "tw_name": "Ferefere ne Aduan",
        "keywords_en": ["fertilizer","npk","nutrient","manure","green manure",
                        "nitrogen","phosphorus","potassium","foliar","deficien"],
        "keywords_tw": ["ferefere","NPK","nutrient","mmoa dɔteɛ","nhwiren-tew",
                        "nitrogen","phosphorus","potassium","foliar","hia"],
        "suggestions_en": [
            "What does NPK mean on a fertilizer bag?",
            "Can I use animal manure instead of chemical fertilizer?",
            "How do I know if my fertilizer is working?",
            "Can over-fertilizing damage my crops?",
            "What is green manure and how do I use it?"
        ],
        "suggestions_tw": [
            "Dɛn na NPK kyerɛ wɔ ferefere bag so?",
            "Metumi de mmoa dɔteɛ adi dwuma mmom sen nnuru ferefere?",
            "Ɛdeɛn na menim sɛ m'ferefere yɛ adwuma?",
            "Ferefere dodo tumi sɛe m'nnuaba anaa?",
            "Dɛn na nhwiren-tew ferefere yɛ na ɛdeɛn na mefa di dwuma?"
        ]
    },
    "Maize": {
        "icon": "🌽",
        "tw_name": "Aburoɔ",
        "keywords_en": ["maize","corn","armyworm","streak","aburow"],
        "keywords_tw": ["aburow","aburo","aborɔnoma adwummaker","streak","aburoɔ"],
        "suggestions_en": [
            "When is the best time to plant maize in Ghana?",
            "What fertilizer should I apply to maize and when?",
            "How do I identify a fall armyworm attack on my maize?",
            "How do I control weeds in my maize farm?",
            "How many bags of maize can I expect from one acre?"
        ],
        "suggestions_tw": [
            "Bere bɛn na ɛyɛ ɔkorɔ sɛ wode aburow to mu wɔ Ghana?",
            "Ferefere bɛn na mede to aburoɔ ho na bere bɛn?",
            "Dɛn na ɛkyerɛ sɛ fall armyworm atu mako wɔ me aburoɔ afuom?",
            "Dɛn na menyɛ nhaban foforo a wɔ me aburoɔ afuom mu?",
            "Sacks aburoɔ ahe na mebetumi anya fi eka baako mu?"
        ]
    },
    "Cassava": {
        "icon": "🥔",
        "tw_name": "Bankye",
        "keywords_en": ["cassava","gari","mosaic","starch","fufu"],
        "keywords_tw": ["bankye","gari","mosaic","starch","fufu"],
        "suggestions_en": [
            "How do I select good cassava stems for planting?",
            "How do I process cassava into gari?",
            "What diseases affect cassava and how do I manage them?",
            "What is the best cassava variety for making fufu?",
            "How much profit can I make from one acre of cassava?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ mepick bankye abɔ pa sɛ mede to mu?",
            "Dɛn na menyɛ bankye ho yɛ gari?",
            "Yadeɛ bɛn na ɛtaa ba bankye ho na dɛn na menyɛ wɔn ho?",
            "Bankye variety bɛn na ɛhia pa ara ma fufu yɛ?",
            "Mfa sika ahe bɛfata me wɔ bankye eka baako mu?"
        ]
    },
    "Plantain & Banana": {
        "icon": "🍌",
        "tw_name": "Boɔde ne Kwadu",
        "keywords_en": ["plantain","banana","sigatoka","sucker"],
        "keywords_tw": ["boɔde","kwadu","sigatoka","sucker","borɔdɔ"],
        "suggestions_en": [
            "What type of sucker is best for planting plantain?",
            "How do I control black sigatoka disease in plantain?",
            "How do I know when plantain is ready to harvest?",
            "How do I make plantain chips for sale?",
            "What fertilizer is best for plantain?"
        ],
        "suggestions_tw": [
            "Sucker bɛn na ɛhia pa ara sɛ mede to mu wɔ boɔde afuom?",
            "Dɛn na menyɛ black sigatoka yadeɛ ho wɔ boɔde ho?",
            "Dɛn na ɛkyerɛ sɛ boɔde atwa so sɛ wɔbɛyi?",
            "Dɛn na menyɛ boɔde chips ma tɔ?",
            "Ferefere bɛn na ɛyɛ ɔkorɔ ma borɔdɔ?"
        ]
    },
    "Yam": {
        "icon": "🍠",
        "tw_name": "Bayerɛ",
        "keywords_en": ["yam","sett","mound"],
        "keywords_tw": ["bayerɛ","sett","afe","stake"],
        "suggestions_en": [
            "How do I prepare yam setts for planting?",
            "What is the best time to plant yam in Ghana?",
            "How do I build a yam mound and why is it important?",
            "How do I store yam properly after harvest?",
            "Can I grow yam without mounds?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ bayerɛ setts ansa na mede to mu?",
            "Bere bɛn na ɛyɛ papa pa ara sɛ wede bayerɛ to mu wɔ Ghana?",
            "Dɛn na menyɛ bayerɛ afe anaa stake na ɛyɛ papa adɛn?",
            "Ɛkwan pa bɛn na mede bayerɛ twew na guina yi akyi?",
            "Metumi ato bayerɛ a afe amma?"
        ]
    },
    "Cocoyam": {
        "icon": "🌿",
        "tw_name": "Kɔkɔnte",
        "keywords_en": ["cocoyam","kontomire","taro","eddoe"],
        "keywords_tw": ["kɔkɔnte","kontomire","taro","eddoe"],
        "suggestions_en": [
            "How do I grow cocoyam successfully in Ghana?",
            "How do I store cocoyam after harvest?",
            "How do I add value to cocoyam for better income?",
            "What are the common pests and diseases of cocoyam?",
            "What are the marketing opportunities for cocoyam?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ meto kɔkɔnte yie wɔ Ghana?",
            "Dɛn na menyɛ kɔkɔnte corms guina yi akyi?",
            "Dɛn na menyɛ sɛ kɔkɔnte bo kɔ so ma sika pa?",
            "Adwummaker ne yadeɛ bɛn na ɛtaa ba kɔkɔnte ho?",
            "Dwa nhyiamu bɛn na ɛwɔ ma kɔkɔnte wɔ Ghana?"
        ]
    },
    "Tomatoes": {
        "icon": "🍅",
        "tw_name": "Ntomatoes",
        "keywords_en": ["tomato","blight","blossom","leaf miner"],
        "keywords_tw": ["ntomato","tomato","blight","ntomate"],
        "suggestions_en": [
            "How do I grow tomatoes in Ghana for good yield?",
            "How do I prevent tomato late blight?",
            "What causes tomato blossom end rot and how do I fix it?",
            "What is the best irrigation method for tomatoes?",
            "What fertilizer programme should I follow for tomatoes?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ meto tomatoes yie wɔ Ghana sɛ nnoa pii aba?",
            "Dɛn na menyɛ sɛ tomato late blight annya me nnuaba?",
            "Dɛn ma tomato blossom end rot na dɛn na menyɛ ho?",
            "Quench nhyiamu bɛn na ɛhia pa ara ma tomatoes wɔ Ghana?",
            "Ferefere programme bɛn na mede to tomatoes ho?"
        ]
    },
    "Pepper": {
        "icon": "🌶️",
        "tw_name": "Mako",
        "keywords_en": ["pepper","scotch bonnet","bell pepper"],
        "keywords_tw": ["mako","pepper","bell pepper"],
        "suggestions_en": [
            "How do I raise pepper seedlings?",
            "How do I prevent pepper root rot?",
            "How do I dry and preserve pepper for longer shelf life?",
            "How do I grow bell pepper for high value markets?",
            "What types of pepper are grown in Ghana?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ pepper seedlings?",
            "Dɛn na menyɛ sɛ pepper root rot annya me nnuaba?",
            "Dɛn na menyɛ pepper tew na kata so sɛ ɛtena mu akyi?",
            "Dɛn na menyɛ bell pepper ma dwa a bo wɔ so wɔ Ghana?",
            "Pepper nhyiamu bɛn na wɔtaa to mu wɔ Ghana?"
        ]
    },
    "Onion": {
        "icon": "🧅",
        "tw_name": "Gyene / Abɔnkɔ",
        "keywords_en": ["onion","downy","thrips"],
        "keywords_tw": ["gyene","abɔnkɔ","onion","thrips","downy"],
        "suggestions_en": [
            "How do I grow onions in Ghana?",
            "What causes onion bulbs to be small?",
            "How do I control thrips on my onions?",
            "How do I cure and store onions after harvest?",
            "What are the main onion varieties grown in Ghana?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ meto abɔnkɔ wɔ Ghana?",
            "Dɛn ma abɔnkɔ bulbs yɛ ketewa?",
            "Ɛdeɛn na metumi kora thrips ase wɔ m'gyene so?",
            "Dɛn na menyɛ sɛ me twew na guina abɔnkɔ yi akyi?",
            "Onion varieties bɛn na wɔtaa to mu wɔ Ghana?"
        ]
    },
    "Carrot": {
        "icon": "🥕",
        "tw_name": "Carrot",
        "keywords_en": ["carrot"],
        "keywords_tw": ["carrot"],
        "suggestions_en": [
            "How do I grow carrots in Ghana?",
            "What problems are common in carrot growing?",
            "How do I thin carrot seedlings?",
            "How do I harvest and clean carrots for market?",
            "What fertilizer does carrot need?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ meto carrot wɔ Ghana?",
            "Aho yɛ den bɛn na ɛtaa ba carrot nnoa mu?",
            "Dɛn na menyɛ carrot seedlings yi?",
            "Dɛn na menyɛ sɛ meyiyɛ na hohoro carrot ma dwa?",
            "Ferefere bɛn na carrot hia na bere bɛn na mede to ho?"
        ]
    },
    "Garden Eggs": {
        "icon": "🍆",
        "tw_name": "Ntorɔ / Mako Ntorɔ",
        "keywords_en": ["garden egg","eggplant","epilachna"],
        "keywords_tw": ["ntorɔ","ntoro","garden egg","epilachna"],
        "suggestions_en": [
            "How do I grow garden eggs in Ghana?",
            "What pests attack garden eggs and how do I control them?",
            "How do I manage water for garden eggs?",
            "How long does garden egg take from planting to harvest?",
            "How do I make garden egg farming profitable?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ meto ntorɔ wɔ Ghana?",
            "Adwummaker bɛn na ɛtaa tu mako ntorɔ na dɛn na menyɛ wɔn ho?",
            "Dɛn na menyɛ sɛ mede nsuo hwɛ ntorɔ ho?",
            "Bere ahe na ɛkyɛ fi to aba kɔsi ntorɔ yi ediɛ?",
            "Dɛn na menyɛ ntorɔ adwuma sɛ ɛde mfaso ba?"
        ]
    },
    "Palm Oil & Coconut": {
        "icon": "🌴",
        "tw_name": "Abɛ ne Kuuku",
        "keywords_en": ["palm","coconut","kernel"],
        "keywords_tw": ["abɛ","kuuku","coconut","palm","ɔman"],
        "suggestions_en": [
            "How do I establish a palm oil plantation in Ghana?",
            "How do I harvest palm fruits properly?",
            "How do I process palm fruits into palm oil?",
            "How do I grow and care for coconut trees?",
            "How do I process coconut into various products?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ mefi ase abɛ afuom wɔ Ghana?",
            "Dɛn na menyɛ sɛ meyiyɛ abɛ ntama pa?",
            "Dɛn na menyɛ abɛ ntama yɛ abɛ ɔman wɔ efie?",
            "Dɛn na menyɛ sɛ meto kuuku nnuaba wɔ Ghana?",
            "Dɛn na menyɛ kuuku yɛ nneɛma ahorow ma sika?"
        ]
    },
    "Groundnut & Legumes": {
        "icon": "🥜",
        "tw_name": "Nkatie ne Abɔdweɛ",
        "keywords_en": ["groundnut","cowpea","soybean","legume"],
        "keywords_tw": ["nkatie","abɔdweɛ","soya","legume"],
        "suggestions_en": [
            "How do I grow groundnuts in Ghana?",
            "How do I make peanut butter from groundnuts?",
            "What disease affects groundnuts?",
            "How do I grow soybean commercially?",
            "How long does cowpea take to mature?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ meto nkatie wɔ Ghana?",
            "Dɛn na menyɛ nkatie betere fi nkatie mu?",
            "Yadeɛ bɛn na ɛtaa ba nkatie ho?",
            "Dɛn na menyɛ soya yɛ adwuma sɛ menya sika?",
            "Bere ahe na ɛsɛ ma abɔdweɛ awie ase?"
        ]
    },
    "Rice": {
        "icon": "🌾",
        "tw_name": "Ɔmo / Ɔtɛ",
        "keywords_en": ["rice","striga"],
        "keywords_tw": ["ɔtɛ","ɔmo","rice","striga"],
        "suggestions_en": [
            "When should I harvest rice?",
            "Which rice varieties perform best in Ghana?",
            "How do I control striga weed in rice?",
            "How do I protect my rice from birds?"
        ],
        "suggestions_tw": [
            "Bere bɛn na ɛsɛ sɛ megye ɔtɛ?",
            "Ɔmɔ aba bɛn na ɛda sor pa wɔ Ghana?",
            "Striga nhaban foforo resɛe m'ɔtɛ. Dɛn na metumi yɛ?",
            "Anomaa redidi m'ɔtɛ. Ɛdeɛn na mekora m'nnuaba?"
        ]
    },
    "Cocoa": {
        "icon": "🍫",
        "tw_name": "Kookoo",
        "keywords_en": ["cocoa","black pod","cacao"],
        "keywords_tw": ["kookoo","cocoa","black pod"],
        "suggestions_en": [
            "How do I increase my cocoa yield?",
            "What causes cocoa black pod disease?",
            "How do I manage disease in my cocoa nursery?",
            "How do I grow cashew successfully?"
        ],
        "suggestions_tw": [
            "Ɛdeɛn na metumi ma m'kookoo da sor dodo?",
            "Dɛn na ɛma kookoo black pod yadeɛ na ɛdeɛn na metumi kora ase?",
            "Ɛdeɛn na metumi kora yadeɛ ase wɔ m'kookoo nursery mu?",
            "Ɛdeɛn na mekura cashew yie?"
        ]
    },
    "Other Vegetables": {
        "icon": "🥦",
        "tw_name": "Nnuan Foforo",
        "keywords_en": ["cucumber","watermelon","moringa","vegetable","pineapple","mango","cashew"],
        "keywords_tw": ["nnuan","kakaduro","watermelon","moringa","aborɔfo","pineapple","mango"],
        "suggestions_en": [
            "Can I grow vegetables in the dry season?",
            "Can I plant different vegetables together in one plot?",
            "How do I grow moringa and what are its benefits?",
            "How do I grow pineapple commercially?",
            "How do I grow watermelon successfully?"
        ],
        "suggestions_tw": [
            "Metumi adua nnɔbae wɔ ɔpɛ bere mu?",
            "Metumi adua nnɔbae ahorow pii wɔ afuo koro mu anaa?",
            "Ɛdeɛn na mekura moringa na mfaaso bɛn na ɛwɔ?",
            "Ɛdeɛn na mekura aborɔfo wɔ adwuma mu?",
            "Ɛdeɛn na mekura watermelon yie?"
        ]
    },
    "Pest & Disease Control": {
        "icon": "🐛",
        "tw_name": "Adwummaker ne Yadeɛ Tia",
        "keywords_en": ["pest","disease","aphid","mite","fungus","nematode",
                        "weevil","armyworm","ipm","integrated","pesticide","neem"],
        "keywords_tw": ["adwummaker","yadeɛ","aphid","mite","fungus","nematode",
                        "weevil","armyworm","IPM","dawuro","neem"],
        "suggestions_en": [
            "How do I use pesticides safely on my farm?",
            "What is Integrated Pest Management (IPM)?",
            "How do I make neem pesticide spray at home?",
            "How do I identify spider mites and control them?",
            "What causes powdery mildew and how do I control it?"
        ],
        "suggestions_tw": [
            "Ɛdeɛn na mefa adwummakers dawuro di dwuma a ɛho tumi wɔ m'afuo mu?",
            "Dɛn na adwumakers hwɛ anammɔn kaa bom (IPM) yɛ?",
            "Ɛdeɛn na meyɛ fie nhwiren adwumakers dawuro fi mako?",
            "Ɛdeɛn na mehunu spider mite na metumi kora wɔn ase?",
            "Dɛn na tukutuku fitaa yadeɛ yɛ na ɛdeɛn na metumi kora ase?"
        ]
    },
    "Irrigation & Water": {
        "icon": "💧",
        "tw_name": "Nsuo ne Quench",
        "keywords_en": ["irrigat","water","drip","borehole","flood","drainage","moisture","dam"],
        "keywords_tw": ["nsuo","quench","drip","borehole","flood","drainage","dam","nsuo gye"],
        "suggestions_en": [
            "What is the best irrigation method for a small farm?",
            "How do I conserve water on my farm during the dry season?",
            "How do I build a small dam or water harvesting system?",
            "How do I manage waterlogging on my farm?",
            "How do I manage irrigation efficiently to save water?"
        ],
        "suggestions_tw": [
            "Nsuo to anammɔn bɛn na ɛyɛ ɔkorɔ wɔ afuo ketewa mu?",
            "Ɛdeɛn na mekora nsuo wɔ m'afuo mu wɔ ɔpɛ bere mu?",
            "Ɛdeɛn na mesi dam ketewa anaa nsuo gye sistɛm?",
            "Ɛdeɛn na mehwɛ nsuo a ɛhyɛ m'afuo mu?",
            "Dɛn na menyɛ sɛ mede quench pa yie sɛ me nsa nsuo?"
        ]
    },
    "Harvesting & Storage": {
        "icon": "🏪",
        "tw_name": "Yi ne Guina",
        "keywords_en": ["harvest","storage","store","post-harvest","hermetic","silo","aflatoxin","mould","weevil"],
        "keywords_tw": ["yi","guina","harvest","storage","hermetic","silo","aflatoxin","mold","weevil"],
        "suggestions_en": [
            "How do I store my maize to prevent aflatoxin?",
            "How do I properly dry my produce after harvesting?",
            "What is hermetic storage and can a small farmer use it?",
            "How do I reduce post-harvest losses for vegetables?",
            "How do I store seeds properly for the next season?"
        ],
        "suggestions_tw": [
            "Ɛdeɛn na meguina m'aburow na aflatoxin nka ho?",
            "Ɛdeɛn na meyaw m'nnuaba yie akyi a megye wɔn?",
            "Dɛn na ntwene-nkuma guina yɛ na okuafo ketewa tumi nya ase anaa?",
            "Ɛdeɛn na metumi sua nnuan a megye wɔn akyi mpoano?",
            "Ɛdeɛn na meguina m'aba yie ma bere a ɛto so?"
        ]
    },
    "Fish Farming": {
        "icon": "🐟",
        "tw_name": "Apataa Adwuma",
        "keywords_en": ["fish","tilapia","catfish","pond","cage","fingerling","aquaculture"],
        "keywords_tw": ["apataa","tilapia","catfish","pond","cage","fingerling","aquaculture"],
        "suggestions_en": [
            "How do I start a fish farm in Ghana?",
            "What is the best fish feed for tilapia?",
            "How do I maintain good water quality in my fish pond?",
            "How much does it cost to start a fish farm in Ghana?",
            "What is the difference between tilapia and catfish farming?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ mefi ase apataa adwuma wɔ Ghana?",
            "Apataa aduan bɛn na ɛhia pa ara ma tilapia wɔ Ghana?",
            "Dɛn na menyɛ sɛ nsuo pa wɔ me apataa pond mu?",
            "Sika ahe na ɛyɛ papa sɛ mefi ase apataa adwuma wɔ Ghana?",
            "Nte sɛn bɛn na ɛwɔ tilapia ne catfish adwuma ntam?"
        ]
    },
    "Poultry Farming": {
        "icon": "🐔",
        "tw_name": "Akoko Adwuma",
        "keywords_en": ["poultry","chicken","broiler","layer","newcastle","litter","brooder","guinea fowl","egg"],
        "keywords_tw": ["akoko","broiler","layer","newcastle","litter","brooder","kurontihene","tamma"],
        "suggestions_en": [
            "How do I start a poultry farm in Ghana?",
            "How do I prevent Newcastle disease in my poultry?",
            "What should I feed my broiler chickens?",
            "How do I set up a brooder for day-old chicks?",
            "How do I reduce feed costs in poultry farming?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ mefi ase akoko adwuma wɔ Ghana?",
            "Dɛn na menyɛ sɛ Newcastle yadeɛ annya me akoko?",
            "Aduan bɛn na mede ma me broiler akoko?",
            "Dɛn na menyɛ brooder ketewa ma day-old chicks?",
            "Dɛn na menyɛ sɛ me aduan bo sua wɔ akoko adwuma mu?"
        ]
    },
    "Goat Farming": {
        "icon": "🐐",
        "tw_name": "Birekyie / Abirekyi Adwuma",
        "keywords_en": ["goat","kid","doe","buck","dairy goat"],
        "keywords_tw": ["birekyie","abirekyi","PPR","mma","mmofraase","bɔhyɛ"],
        "suggestions_en": [
            "How do I start goat farming in Ghana?",
            "What diseases should I vaccinate my goats against?",
            "What do goats eat and how do I feed them?",
            "How often do goats give birth?",
            "How do I identify a healthy goat when buying?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ mefi ase birekyie adwuma wɔ Ghana?",
            "Yadeɛ bɛn na mahware me birekyie so?",
            "Dɛn na birekyie di na dɛn na mede ma wɔn yie?",
            "Bere ahe na birekyie wo mma na mma ahe na ɛwo mmere baako?",
            "Dɛn na ɛkyerɛ birekyie pa bere a megye?"
        ]
    },
    "Sheep Farming": {
        "icon": "🐑",
        "tw_name": "Oguan Adwuma",
        "keywords_en": ["sheep","lamb","ewe","foot rot"],
        "keywords_tw": ["oguan","lamb","ewe","foot rot"],
        "suggestions_en": [
            "How do I start sheep farming in Ghana?",
            "How do I treat sheep for internal parasites?",
            "How do I build a simple sheep pen in Ghana?",
            "How do I market sheep for maximum profit?",
            "What shelter do sheep need in Ghana?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ mefi ase oguan adwuma wɔ Ghana?",
            "Dɛn na menyɛ internal parasites wɔ oguan ho?",
            "Dɛn na menyɛ oguan pen ketewa wɔ Ghana?",
            "Dɛn na menyɛ sɛ metɔ me oguan wɔ bo pa wɔ Ghana?",
            "Beae bɛn na oguan hia sɛ wɔntena wɔ Ghana?"
        ]
    },
    "Cattle Farming": {
        "icon": "🐄",
        "tw_name": "Nnwan Adwuma",
        "keywords_en": ["cattle","cow","bull","calf","trypanosomiasis","fodder"],
        "keywords_tw": ["nnwan","boo","bull","calf","trypanosomiasis","fodder"],
        "suggestions_en": [
            "How do I start cattle farming in Ghana?",
            "What vaccines do cattle need in Ghana?",
            "How do I deworm cattle and when should it be done?",
            "What fodder crops can I grow to feed my cattle?",
            "How do I manage grazing land for cattle sustainably?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ mefi ase nnwan adwuma wɔ Ghana?",
            "Vaccines bɛn na nnwan hia wɔ Ghana?",
            "Dɛn na menyɛ nnwan mu adwummaker na bere bɛn?",
            "Fodder nnuaba bɛn na mede ato mu sɛ mede ma me nnwan wɔ Ghana?",
            "Dɛn na menyɛ nhawan asase ma nnwan yie sɛ ɛtena so?"
        ]
    },
    "Business & Marketing": {
        "icon": "💰",
        "tw_name": "Adwuma ne Dwa",
        "keywords_en": ["market","sell","profit","income","loan","credit","cooperative",
                        "contract","export","insurance","budget","middlemen","business"],
        "keywords_tw": ["dwa","tɔn","mfaso","sika","mfɛdomhyɛw","kuo","contract",
                        "export","insurance","budget","middlemen","adwuma plan"],
        "suggestions_en": [
            "How do I sell my farm produce at a better price?",
            "Where can I get agricultural loans in Ghana?",
            "What is contract farming and how does it benefit me?",
            "How do I write a simple farm business plan?",
            "What government support is available for young farmers?"
        ],
        "suggestions_tw": [
            "Dɛn na menyɛ sɛ metɔ me afuom nnuaba wɔ bo pa wɔ Ghana?",
            "Ɛhɔ na metumi anya okuafo mfɛdomhyɛw wɔ Ghana?",
            "Dɛn na contract farming yɛ na ɛbɛtumi aboa me wɔ Ghana?",
            "Dɛn na menyɛ sɛ meyɛ me afuom adwuma plan ketewa?",
            "Ɔman boa adwuma bɛn na ɛwɔ ho ma okuafo wɔ Ghana?"
        ]
    },
    "Climate & Weather": {
        "icon": "🌦️",
        "tw_name": "Osuoha ne Berɛ",
        "keywords_en": ["climate","weather","drought","flood","rainfall","season","agroforestry"],
        "keywords_tw": ["osuoha","berɛ","climate","drought","flood","rainfall","agroforestry"],
        "suggestions_en": [
            "How does climate change affect farming in Ghana?",
            "How do I protect my farm during heavy rainfall?",
            "How do I prepare my farm for unpredictable weather?",
            "What crops are most resilient to climate change in Ghana?",
            "What is agroforestry and how does it benefit my farm?"
        ],
        "suggestions_tw": [
            "Dɛn na climate change yɛ okuafo adwuma den wɔ Ghana na dɛn na menyɛ?",
            "Ɛdeɛn na mehwɛ nhaban a ɛntia asɛm yie a mennya sika koraa?",
            "Ɛdeɛn na mesiesie m'afuo ama ɛwim tebea a ɛntumi nnim?",
            "Nnuaba bɛn na ɛtumi wiase tebea sɛsae ase hyɛ yie wɔ Ghana?",
            "Dɛn na agroforestry yɛ na ɛboa m'afuo sɛn?"
        ]
    },
    "Farm Management": {
        "icon": "📋",
        "tw_name": "Afuom Hwɛ",
        "keywords_en": ["manage","plan","map","labour","equipment","extension","mofa","record","mechaniz"],
        "keywords_tw": ["hwɛ","plan","map","adwuma","equipment","extension","MOFA","nsɛm","kora"],
        "suggestions_en": [
            "How do I keep records for my farm?",
            "How do I prepare a simple farm budget?",
            "What equipment do I need to start a small farm?",
            "How do I access land for farming in Ghana?",
            "What training opportunities exist for farmers in Ghana?"
        ],
        "suggestions_tw": [
            "Ɛdeɛn na mekora m'afuo nsɛm?",
            "Dɛn na menyɛ afuom budget ketewa?",
            "Adeɛ bɛn na mehia sɛ mesi afuo ketewa?",
            "Dɛn na menyɛ sɛ menya asase ma okuafo adwuma wɔ Ghana?",
            "Training nhyiamu bɛn na ɛwɔ ma okuafo wɔ Ghana?"
        ]
    },
}

# ── CONVERSATION HELPERS ──────────────────────────────────────────
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
    info = TOPICS.get(topic, {})
    key  = 'suggestions_tw' if lang == 'tw' else 'suggestions_en'
    return info.get(key, info.get('suggestions_en', []))[:5]

def get_topic_display_name(topic, lang='en'):
    """Return topic name in the right language."""
    info = TOPICS.get(topic, {})
    if lang == 'tw':
        return info.get('tw_name', topic)
    return topic

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
    if any(g in ql for g in TW_GREET_LIST) and len(ql) < 40:
        return {"type":"answer","text":f"Akwaaba{nb}! 🌿 Yɛfrɛ me AgriBotGH, wo okuafo mmoa chatbot. Asɛmmisa bɛn fa okuafo adwuma ho na wopɛ sɛ mebo wo aseɛ?"}

    # ── English Greetings ──────────────────────────────────────────
    EN_GREET_LIST = ['hi','hello','hey','good morning','good afternoon','good evening']
    if any(g in ql for g in EN_GREET_LIST) and len(ql) < 40:
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

    # ── Detect topic ──────────────────────────────────────────────
    detected_topic = detect_topic(ql, lang)

    # ── Run retrieval ─────────────────────────────────────────────
    # CONFIDENCE alone is too low a bar: common words like "what/is/best"
    # are enough to push unrelated questions (e.g. "capital of France")
    # over 0.18. Requiring a topic-keyword match too (or a much higher
    # score that's basically an exact hit) filters those out without
    # rejecting genuine paraphrases, which almost always hit a topic.
    CONFIDENCE      = 0.18
    HIGH_CONFIDENCE = 0.6
    if is_tw:
        vec    = tw_vec.transform([q])
        scores = cosine_similarity(vec, tw_vecs)[0]
        best   = int(np.argmax(scores))
        conf   = float(scores[best])
        if conf >= HIGH_CONFIDENCE or (conf >= CONFIDENCE and detected_topic):
            return {"type":"answer","text": tw_as[best]}
    else:
        vec    = en_vec.transform([q])
        scores = cosine_similarity(vec, en_vecs)[0]
        best   = int(np.argmax(scores))
        conf   = float(scores[best])
        if conf >= HIGH_CONFIDENCE or (conf >= CONFIDENCE and detected_topic):
            return {"type":"answer","text": en_as[best]}

    # ── Topic detected but no exact match ─────────────────────────
    if detected_topic:
        icon      = TOPICS[detected_topic]['icon']
        suggs     = get_suggestions(detected_topic, lang)
        disp_name = get_topic_display_name(detected_topic, lang)
        if is_tw:
            return {
                "type": "low_confidence",
                "text": f"Mahunu sɛ worerebisa fa **{disp_name}** {icon} ho — eyi yɛ topic a mewɔ ho nsɛm! Nanso, menni aseɛ pɛpɛɛpɛ wɔ saa bere yi.\n\nEyi betumi aba fia sɛ:\n• Wo asɛmmisa yɛ pɛ paa ma me training\n• Wuhia sɛ wo kyer me asɛm bio sɛ mete aseɛ yie\n\nAsɛmmisa a metumi aboa wo wɔ {disp_name} ho:",
                "suggestions": suggs,
                "topic": detected_topic
            }
        return {
            "type": "low_confidence",
            "text": f"I can see you are asking about **{detected_topic}** {icon} — that is one of my topics! However, I do not have a specific answer to your exact question yet.\n\nThis could be because:\n• The question is too specific for my current training\n• I may need more details\n\nHere are some related questions I can help you with:",
            "suggestions": suggs,
            "topic": detected_topic
        }

    # ── Completely off-topic ──────────────────────────────────────
    topic_icons    = {t: TOPICS[t]['icon'] for t in TOPICS}
    topic_names_tw = {t: TOPICS[t].get('tw_name', t) for t in TOPICS}
    if is_tw:
        return {
            "type": "off_topic",
            "text": f"Kafra{nb}, me yɛ AgriBotGH — chatbot a wɔayɛ no pɛ ma okuafo adwuma. Metumi aboa wo pɛ wɔ okuafo nsɛm ho. 🌾\n\nPaw topic baako fi aseɛ yi na mɛkyerɛ wo asɛm a metumi aboa wo wɔ so:",
            "topics": list(TOPICS.keys()),
            "topic_icons": topic_icons,
            "topic_names_tw": topic_names_tw
        }
    return {
        "type": "off_topic",
        "text": f"Sorry{nb}, I am AgriBotGH — a specialised agricultural assistant. I can only help with farming-related topics. 🌾\n\nPlease select a topic below and I will show you what I can help you with:",
        "topics": list(TOPICS.keys()),
        "topic_icons": topic_icons,
        "topic_names_tw": topic_names_tw
    }

# ── ROUTES ────────────────────────────────────────────────────────
@app.route('/api/chat', methods=['POST'])
def chat():
    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400

    question = d.get('message','').strip() if d.get('message') else ''
    language = d.get('language','en')
    username = d.get('username', None)
    if not question:
        return jsonify({"error": "No message provided"}), 400

    result = get_answer(question, language, username)
    return jsonify(result)

@app.route('/api/topics', methods=['GET'])
def get_topics():
    """Return all topics with their icons and suggestions."""
    return jsonify({
        topic: {
            "icon": info['icon'],
            "suggestions": info['suggestions_en']
        }
        for topic, info in TOPICS.items()
    })

@app.route('/api/topic-suggestions', methods=['POST'])
def topic_suggestions_route():
    """Return suggestions for a selected topic in the right language."""
    d     = request.get_json()
    topic = d.get('topic','')
    lang  = d.get('lang','en')
    if topic not in TOPICS:
        return jsonify({"error": "Topic not found"}), 404
    info  = TOPICS[topic]
    suggs = info.get('suggestions_tw' if lang == 'tw' else 'suggestions_en',
                     info.get('suggestions_en', []))
    name  = info.get('tw_name', topic) if lang == 'tw' else topic
    return jsonify({
        "topic": topic,
        "display_name": name,
        "icon": info['icon'],
        "suggestions": suggs[:5]
    })

@app.route('/api/health')
def health():
    return jsonify({"status":"ok","en_pairs":len(en_qs),"tw_pairs":len(tw_qs),"topics":len(TOPICS)})

ALLOWED_STATIC_FILES = {
    'app.js',
    'style.css',
    'index.html',
    'agri_dataset.json',
}

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:f>')
def static_files(f):
    if f in ALLOWED_STATIC_FILES or f.startswith('css/') or f.startswith('js/'):
        return send_from_directory('.', f)
    return jsonify({"error": "Not found"}), 404

if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'false').strip().lower() == 'true'
    port       = int(os.getenv('PORT', 5000))
    app.run(debug=debug_mode, port=port)
