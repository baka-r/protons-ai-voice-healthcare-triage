"""Structured symptom interview for COMMON, usually mild complaints.

DRAFT CONTENT - NOT CLINICALLY APPROVED. Every question, danger rule and "common cause" sentence below must be reviewed and
signed off by a clinician before real use. This is NOT a diagnosis: it asks a few yes/no questions, escalates to a human on
any danger answer, and otherwise names the most COMMON possible causes plus general self-care guidance from approved
documents. It never names medicines or doses, and children, pregnancy and anything uncertain go to staff (see rules.is_strict_medical).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Q:
    text: str  # a yes/no question
    danger_if: str | None = None  # "yes" | "no": this answer hands the call to staff
    tag_if_yes: str | None = None
    tag_if_no: str | None = None


@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    pattern: re.Pattern[str]
    dept: str
    guidance_query: str  # matches a passage in knowledge/symptom_guidance.md
    questions: tuple[Q, ...]
    causes: tuple[tuple[str, str], ...]  # (tag, common-cause phrase), in priority order
    default_cause: str


def _p(expr: str) -> re.Pattern[str]:
    return re.compile(expr)


TOPICS: tuple[Topic, ...] = (
    Topic(
        "vomiting", "vomiting", _p(r"\b(vomit\w*|throw(ing|n)? up|threw up|puk\w*|nausea|nauseous|feel(ing)? sick|feel(ing)? like (i('m| am) )?going to be sick)\b"),
        "General Medicine", "I feel sick and I am vomiting. What should I do?",
        (
            Q("Is there any blood in the vomit, or severe stomach pain?", danger_if="yes"),
            Q("Are you able to keep small sips of water down?", danger_if="no"),
            Q("Have you also had diarrhoea or a fever?", tag_if_yes="infection"),
            Q("Has this been going on for more than two days?", tag_if_yes="prolonged"),
        ),
        (("infection", "a stomach infection, which is common and usually settles with rest and fluids"),),
        "something you ate, or a mild stomach bug",
    ),
    Topic(
        "diarrhoea", "diarrhoea", _p(r"\b(diarrh\w*|diarr\w*|loose motions?|loose stools?|runny stools?|upset stomach)\b"),
        "General Medicine", "I have diarrhoea. What should I do?",
        (
            Q("Is there blood in your stool, or severe stomach pain?", danger_if="yes"),
            Q("Are you passing very little urine, or feeling very dizzy or weak?", danger_if="yes"),
            Q("Have you also had a fever or vomiting?", tag_if_yes="infection"),
            Q("Has it lasted more than two days?", tag_if_yes="prolonged"),
        ),
        (("infection", "a stomach infection, which is common and usually settles with rest and fluids"),),
        "something you ate, or a mild stomach upset",
    ),
    Topic(
        "fever", "fever", _p(r"\b(fever\w*|temperature|feverish|shivery|chills)\b"),
        "General Medicine", "I have a fever. What should I do?",
        (
            Q("Do you have a stiff neck, a rash that does not fade, confusion, or trouble breathing?", danger_if="yes"),
            Q("Do you also have a cough, sore throat or runny nose?", tag_if_yes="respiratory"),
            Q("Do you also have stomach upset, vomiting or diarrhoea?", tag_if_yes="stomach"),
            Q("Has the fever lasted more than three days?", tag_if_yes="prolonged"),
        ),
        (("respiratory", "a viral infection such as a cold or flu"), ("stomach", "a stomach infection")),
        "a common viral infection",
    ),
    Topic(
        "headache", "headache", _p(r"\b(headache\w*|head ache|head hurts|head is hurting|head has been aching|head aching|migraine\w*)\b"),
        "General Medicine", "I have a headache. What should I do?",
        (
            Q("Did it start suddenly and severely, or after a knock to the head?", danger_if="yes"),
            Q("Do you also have a fever, stiff neck, confusion, weakness or trouble speaking?", danger_if="yes"),
            Q("Do bright light or noise bother you, along with feeling sick?", tag_if_yes="migraine"),
            Q("Does it feel like a tight band or pressure, or are you tired, stressed or have you skipped meals?", tag_if_yes="tension"),
        ),
        (("migraine", "a migraine"), ("tension", "a tension headache, often linked to stress, tiredness or not drinking enough")),
        "a common tension-type headache or dehydration",
    ),
    Topic(
        "cough", "cough or cold", _p(r"\b(cough\w*|cold|flu|runny nose|blocked nose|stuffy nose|sneez\w*)\b"),
        "General Medicine", "I have a cough or a cold. What should I do?",
        (
            Q("Do you have trouble breathing, chest pain, blue lips, or are you coughing up blood?", danger_if="yes"),
            Q("Do you also have a fever and body aches?", tag_if_yes="flu"),
            Q("Has the cough lasted more than two weeks?", tag_if_yes="prolonged"),
        ),
        (("flu", "flu or a viral chest infection"),),
        "a common cold or an irritated throat",
    ),
    Topic(
        "sore throat", "sore throat", _p(r"\b(sore throat|throat (is )?(sore|hurts|painful|itchy)|scratchy throat)\b"),
        "ENT", "I have a sore throat. What should I do?",
        (
            Q("Do you have trouble breathing or swallowing, or are you drooling?", danger_if="yes"),
            Q("Do you also have a fever?", tag_if_yes="throat_infection"),
            Q("Do you also have a runny nose or cough?", tag_if_yes="cold"),
            Q("Has it lasted more than a week?", tag_if_yes="prolonged"),
        ),
        (("cold", "a cold virus"), ("throat_infection", "a throat infection")),
        "throat irritation from a viral cold or dry air",
    ),
    Topic(
        "stomach ache", "stomach ache", _p(r"\b(stomach ?ache|stomach (pain|hurts|is hurting)|tummy|belly (pain|ache|hurts)|pain in (my )?(stomach|belly)|abdominal pain|gas|bloat\w*|acidity|indigestion)\b"),
        "General Medicine", "I have a stomach ache. What should I do?",
        (
            Q("Is the pain severe or sudden, is your belly hard or swollen, or can you not pass stool or gas?", danger_if="yes"),
            Q("Is the pain mainly low on the right side, or much worse when you move or cough?", danger_if="yes"),
            Q("Do you also have vomiting, diarrhoea or a fever?", tag_if_yes="infection"),
            Q("Do you have bloating or a burning feeling, especially after eating?", tag_if_yes="indigestion"),
        ),
        (("infection", "a stomach infection"), ("indigestion", "indigestion or acidity")),
        "gas or mild indigestion",
    ),
    Topic(
        "dizzy", "dizziness", _p(r"\b(dizz\w*|light ?headed|giddy|head (is )?spinning)\b"),
        "General Medicine", "I feel dizzy. What should I do?",
        (
            Q("Do you have chest pain, trouble speaking, weakness on one side, fainting, or a severe headache?", danger_if="yes"),
            Q("Does it mostly happen when you stand up quickly?", tag_if_yes="postural"),
            Q("Have you eaten and had enough water today?", tag_if_no="dehydrated"),
        ),
        (("postural", "a drop in blood pressure when standing up"), ("dehydrated", "dehydration or low blood sugar")),
        "dehydration, tiredness or standing up too quickly",
    ),
    Topic(
        "rash", "skin rash", _p(r"\b(rash\w*|itchy skin|itching|hives|skin (problem|irritation|allergy))\b"),
        "Dermatology", "I have a skin rash. What should I do?",
        (
            Q("Do you have trouble breathing, swelling of the face, lips or mouth, or a high fever?", danger_if="yes"),
            Q("Is the rash spreading quickly, or are there painful blisters?", danger_if="yes"),
            Q("Is it itchy?", tag_if_yes="allergy"),
            Q("Has it lasted more than three days?", tag_if_yes="prolonged"),
        ),
        (("allergy", "an allergic or irritant skin reaction"),),
        "a common skin irritation",
    ),
)

BY_KEY = {t.key: t for t in TOPICS}


def match_topic(norm: str) -> Topic | None:
    for t in TOPICS:
        if t.pattern.search(norm):
            return t
    return None


def pick_cause(topic: Topic, tags: list[str]) -> str:
    for tag, phrase in topic.causes:
        if tag in tags:
            return phrase
    return topic.default_cause
