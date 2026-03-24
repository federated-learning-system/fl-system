"""
ml/synthetic_data/generator.py

Synthetic non-IID data generator for FL client simulation.

Each client profile defines a domain-specific corpus of seed sentences and a
distribution bias via topic weights. The generator produces keystroke-event-like
records: {token_id, context_ids, timestamp_ms}.

Usage:
    from ml.synthetic_data.generator import generate_client_dataset, CLIENT_PROFILES
    from ml.tokenizer.tokenizer import FLTokenizer

    tok = FLTokenizer("ml/tokenizer/vocab_8192.model")
    for profile in CLIENT_PROFILES:
        data = generate_client_dataset(profile, tok)
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ml.tokenizer.tokenizer import FLTokenizer


@dataclass
class ClientProfile:
    """Defines a synthetic FL client with domain-biased text distribution."""

    client_id: str
    device_class: str  # "phone", "tablet", "desktop"
    dataset_size: int  # number of keystroke events to generate
    seed_sentences: list[str] = field(default_factory=list)
    topic_weight: float = 1.0  # mixing weight for domain vs general text


# ── Seed corpora per domain ─────────────────────────────────────────────────

_TECH_SENTENCES = [
    "Can you review the pull request for the new API endpoint",
    "The Kubernetes cluster needs more memory for the aggregation server",
    "I deployed the latest Docker image to production",
    "The CI pipeline failed on the linting step again",
    "Let me check the server logs for the error trace",
    "We should refactor the database schema before the migration",
    "The neural network converges after fifty epochs of training",
    "Python virtual environments prevent dependency conflicts",
    "The load balancer distributes traffic across three nodes",
    "I need to update the SSL certificates before they expire",
    "The microservice architecture scales better than monoliths",
    "Git rebase keeps the commit history clean and linear",
    "The REST API returns JSON responses with pagination",
    "We need to optimize the SQL query for better performance",
    "The container image size is too large for deployment",
    "Terraform manages the cloud infrastructure as code",
    "The WebSocket connection handles real time notifications",
    "I configured the firewall rules for the new subnet",
    "The machine learning model needs more training data",
    "Let me debug the race condition in the async handler",
]

_CASUAL_SENTENCES = [
    "Hey are you coming to the party tonight",
    "I just finished watching that new movie it was amazing",
    "Can you pick up some groceries on your way home",
    "The weather is really nice today lets go for a walk",
    "Happy birthday hope you have an awesome day",
    "Just got back from vacation it was so relaxing",
    "Did you see the game last night what a comeback",
    "I am thinking about getting a new phone soon",
    "The restaurant down the street has the best pizza",
    "Thanks for helping me move last weekend I really appreciate it",
    "My dog learned a new trick today he can shake hands now",
    "I cannot believe how fast this year went by",
    "Do you want to grab coffee tomorrow morning",
    "Just finished reading that book you recommended it was great",
    "The concert was incredible the band played for three hours",
    "I need to clean the house before the guests arrive",
    "Have you tried that new app everyone is talking about",
    "The kids are so excited about the school trip next week",
    "I forgot my umbrella and it started raining on the way home",
    "We should plan a road trip for the long weekend",
]

_MEDICAL_SENTENCES = [
    "The patient presents with elevated blood pressure and tachycardia",
    "Prescribe twenty milligrams of lisinopril once daily for hypertension",
    "The MRI results show no evidence of acute intracranial pathology",
    "Schedule a follow up appointment in two weeks for lab review",
    "The complete blood count indicates mild anemia with low hemoglobin",
    "Administer one gram of ceftriaxone intravenously every twelve hours",
    "The echocardiogram reveals normal left ventricular ejection fraction",
    "Patient reports chronic lower back pain radiating to the left leg",
    "The chest X ray shows bilateral pulmonary infiltrates consistent with pneumonia",
    "Recommend physical therapy three times per week for six weeks",
    "Blood glucose levels are elevated suggesting uncontrolled diabetes mellitus",
    "The surgical wound is healing well with no signs of infection",
    "Administer ondansetron four milligrams for postoperative nausea",
    "The electrocardiogram shows normal sinus rhythm without ST changes",
    "Patient has a family history of coronary artery disease and stroke",
    "The biopsy results confirm benign prostatic hyperplasia",
    "Start metformin five hundred milligrams twice daily with meals",
    "The neurological examination reveals intact cranial nerve function",
    "Patient is allergic to penicillin and sulfa medications",
    "Recommend annual colonoscopy screening starting at age forty five",
]

_SPORTS_SENTENCES = [
    "The team scored three goals in the second half to win",
    "He ran the marathon in under three hours a personal best",
    "The quarterback threw four touchdown passes in the championship game",
    "She won the gold medal in the hundred meter freestyle",
    "The coach made a substitution in the eighty fifth minute",
    "The playoffs start next week and our team has home advantage",
    "He hit a grand slam in the bottom of the ninth inning",
    "The referee awarded a penalty kick for the handball in the box",
    "She broke the world record in the high jump competition",
    "The basketball team is on a ten game winning streak",
    "The training camp starts in July to prepare for the season",
    "He scored the winning goal in overtime to clinch the title",
    "The defense held strong in the final minutes of the game",
    "She qualified for the Olympics with her performance today",
    "The boxing match went the full twelve rounds before the decision",
    "The pitcher struck out fifteen batters in a complete game shutout",
    "The cycling race covers two hundred kilometers through the mountains",
    "He made three three pointers in the fourth quarter comeback",
    "The tennis match lasted five sets and over four hours",
    "The football draft picks were announced live on television tonight",
]

_MIXED_SENTENCES = [
    "I need to buy a new laptop for work this weekend",
    "The doctor said I should exercise more and eat healthier",
    "Did you watch the game while working from home yesterday",
    "The meeting was rescheduled to Thursday afternoon at three",
    "I ordered a new book about machine learning from the store",
    "The kids have soccer practice right after school today",
    "Can you send me the report before the end of the day",
    "We are planning a team building event for next month",
    "The pharmacy called and your prescription is ready for pickup",
    "I signed up for an online course about data science",
    "The traffic was terrible this morning took me an hour to commute",
    "My fitness tracker says I walked ten thousand steps today",
    "The project deadline was moved up to next Friday",
    "I need to renew my gym membership before it expires",
    "The weather forecast shows rain for the rest of the week",
    "Can you help me set up the new printer in the office",
    "The grocery store has a sale on organic vegetables today",
    "I am training for a half marathon in the spring",
    "The software update broke the email client again",
    "We should try that new sushi place downtown for lunch",
]


# ── Predefined client profiles ──────────────────────────────────────────────

CLIENT_PROFILES: list[ClientProfile] = [
    ClientProfile(
        client_id="client-tech",
        device_class="desktop",
        dataset_size=5000,
        seed_sentences=_TECH_SENTENCES,
        topic_weight=0.85,
    ),
    ClientProfile(
        client_id="client-casual",
        device_class="phone",
        dataset_size=5000,
        seed_sentences=_CASUAL_SENTENCES,
        topic_weight=0.85,
    ),
    ClientProfile(
        client_id="client-medical",
        device_class="tablet",
        dataset_size=5000,
        seed_sentences=_MEDICAL_SENTENCES,
        topic_weight=0.85,
    ),
    ClientProfile(
        client_id="client-sports",
        device_class="phone",
        dataset_size=5000,
        seed_sentences=_SPORTS_SENTENCES,
        topic_weight=0.85,
    ),
    ClientProfile(
        client_id="client-mixed",
        device_class="phone",
        dataset_size=5000,
        seed_sentences=_MIXED_SENTENCES,
        topic_weight=0.50,  # more uniform distribution
    ),
]

# General filler sentences (shared across all profiles as minority class)
_GENERAL_SENTENCES = [
    "The sun rises in the east and sets in the west",
    "Water freezes at zero degrees Celsius under normal pressure",
    "The capital of France is Paris and it is beautiful",
    "There are seven continents and five oceans on Earth",
    "Music is a universal language that everyone can enjoy",
    "Reading books helps improve vocabulary and critical thinking",
    "The internet has changed how people communicate worldwide",
    "Mountains are formed by tectonic plate movements over time",
    "Cooking at home is healthier and cheaper than eating out",
    "Education is the key to a better future for everyone",
]


def generate_client_dataset(
    profile: ClientProfile,
    tokenizer: FLTokenizer,
    seq_len: int = 10,
    seed: int | None = None,
) -> list[dict]:
    """
    Generate a synthetic keystroke dataset for a single FL client.

    Each event is a dict with:
        - token_id: int — the next-word prediction target
        - context_ids: list[int] — the preceding seq_len token IDs
        - timestamp_ms: int — synthetic timestamp

    The dataset is non-IID: `topic_weight` fraction of events come from the
    profile's domain sentences, the rest from general sentences.
    """
    rng = random.Random(seed if seed is not None else hash(profile.client_id))

    # Build token pool from seed sentences
    domain_tokens: list[int] = []
    for sentence in profile.seed_sentences:
        domain_tokens.extend(tokenizer.encode(sentence))

    general_tokens: list[int] = []
    for sentence in _GENERAL_SENTENCES:
        general_tokens.extend(tokenizer.encode(sentence))

    if not domain_tokens:
        raise ValueError(f"No tokens generated for profile {profile.client_id}")

    events: list[dict] = []
    current_ts = int(time.time() * 1000)

    for i in range(profile.dataset_size):
        # Choose domain vs general tokens based on topic_weight
        if rng.random() < profile.topic_weight:
            pool = domain_tokens
        else:
            pool = general_tokens

        # Pick a random starting position for context window
        if len(pool) <= seq_len:
            # Pool too small — sample with wrapping
            start = rng.randint(0, len(pool) - 1)
            context = [pool[(start + j) % len(pool)] for j in range(seq_len)]
            target = pool[(start + seq_len) % len(pool)]
        else:
            start = rng.randint(0, len(pool) - seq_len - 1)
            context = pool[start : start + seq_len]
            target = pool[start + seq_len]

        current_ts += rng.randint(50, 500)
        events.append({
            "token_id": target,
            "context_ids": context,
            "timestamp_ms": current_ts,
        })

    return events
