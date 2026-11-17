"""Dialog engine: a deterministic state machine. Safety rules run first, always.

Order of every turn:
  1. red-flag rules (instant)            -> emergency / distress handover
  2. identity steps are parsed locally   -> names / dates of birth never go to the LLM
  3. LLM analysis (second-net red flag)  -> may only ADD caution
  4. fixed intent routing                -> fixed scripts or approved document text
Anything unexpected fails closed to a human handover.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import re
import time
from datetime import timedelta

from app.config import Settings
from app.dialog import rules, symptoms
from app.dialog.session import HandoverRequest, Line, Reply, Session
from app.safety import scripts
from app.safety.guard import check_output
from app.safety.redflags import scan_red_flags
from app.safety.text import normalize
from app.services.emr import EMR
from app.services.llm import LLM, Analysis

log = logging.getLogger("engine")

GUIDANCE_COSINE = 0.60  # minimum semantic match between the caller's words and an approved guidance topic
INFO_FALLBACK_COSINE = 0.70  # strict bar (calibrated: 0% irrelevant answered, 85% of real info questions) when no intent was recognised


def _l(key: str) -> Line:
    return Line(text=scripts.fixed(key), key=key)


def _L(*chunks: str) -> Line:
    """A dynamic line made of small phrases. Each phrase is synthesised/cached on its own, so recurring pieces
    (dates, times, department names) are pre-rendered and the reply starts instantly."""
    return Line(text=" ".join(chunks), chunks=list(chunks))


def time_chunks(times: list[str]) -> list[str]:
    ts = [rules.fmt_time(t) for t in times]
    if len(ts) == 1:
        return [f"{ts[0]}."]
    return [f"{t}," for t in ts[:-1]] + [f"and {ts[-1]}."]


def phrase_vocab(dept_names: list[str], days: int = 10) -> list[str]:
    """Every reusable phrase the booking flow can say (kept in sync with the templates below) - pre-rendered at start-up."""
    from datetime import date as _date

    out = ["Thank you,", "You're verified.", "Which department would you like to see?"]
    if dept_names:
        out.append(f"We have {rules.join_list(dept_names)}.")
    for d in dept_names:
        out += [f"{d} has openings at", f"I'll book {d},", f"Done. Your {d} appointment is confirmed for", f"{d}, got it."]
    today = rules.now_local().date()
    for i in range(days):
        ds = rules.fmt_date(today + timedelta(days=i))
        out += [f"On {ds},", f"on {ds},", f"{ds},"]
    for h in range(9, 17):
        for m in (0, 30):
            t = rules.fmt_time(f"{h:02d}:{m:02d}")
            out += [f"{t},", f"and {t}.", f"{t}.", f"at {t}."]
    return list(dict.fromkeys(out))


class Engine:
    def __init__(self, settings: Settings, llm: LLM, emr: EMR, rag, verify_limiter=None, doctor=None):
        self.doctor = doctor  # doctor-style conversation (None -> fixed interview / staff only)
        self.s = settings
        self.llm = llm
        self.emr = emr
        self.rag = rag
        self.verify_limiter = verify_limiter  # per-IP cap on failed identity checks (anti-enumeration)

    # ------------------------------------------------------------------ helpers
    def _reply(self, s: Session, lines: list[Line], state: str | None = None, **kw) -> Reply:
        if state:
            s.state = state
        if lines:
            s.last_prompt = " ".join(x.text for x in lines)
        return Reply(lines=lines, state=s.state, **kw)

    def _handover(self, s: Session, lines: list[Line], req: HandoverRequest, **kw) -> Reply:
        s.state = "HANDOVER"
        return Reply(lines=lines, state="HANDOVER", handover=req, **kw)

    def _emergency(self, s: Session, kind: str, category: str, source: str, detail: str = "") -> Reply:
        key = "distress" if kind in ("self_harm", "abuse") else "emergency"
        reason = {"self_harm": "distress", "abuse": "abuse"}.get(kind, "emergency")
        r = self._handover(
            s, [_l(key)], HandoverRequest(reason=reason, urgency="emergency", category=category, source=source),
            trace=[{"step": "safety", "status": "alert", "detail": f"red flag ({source}): {category}"}],
            safety={"redflag": "alert", "scope": "ok", "pii": "on", "llm_check": "alert" if source == "llm" else "skip"},
            intent="emergency",
        )
        return r

    def _not_caught(self, s: Session) -> Reply:
        s.unclear += 1
        if s.unclear >= 2:
            return self._handover(
                s, [_l("unclear_handover")], HandoverRequest("unclear", "routine", source="system"),
                trace=[{"step": "route", "status": "alert", "detail": "not understood twice - handing over"}],
            )
        return self._reply(s, [_l("not_caught")], trace=[{"step": "route", "status": "skip", "detail": "nothing understood"}])

    def _degraded(self, s: Session) -> Reply:
        return self._handover(
            s, [_l("degraded")], HandoverRequest("degraded", "routine", source="system"),
            trace=[{"step": "understand", "status": "alert", "detail": "language model unavailable - failing closed"}],
        )

    # ------------------------------------------------------------------ main entry
    async def handle(self, s: Session, raw: str) -> Reply:
        s.turns += 1
        norm = normalize(raw)
        if not norm:
            return self._not_caught(s)
        if s.turns > self.s.max_turns:
            return self._handover(s, [_l("turn_limit")], HandoverRequest("turn_limit", "routine", source="system"))

        # 1. deterministic red-flag screen - always first
        rf = scan_red_flags(raw)
        if rf:
            return self._emergency(s, rf.kind, rf.category, "rules", rf.matched)

        # 2. identity steps: parsed locally, text not sent to the cloud LLM
        if s.state in ("AWAIT_NAME", "AWAIT_DOB"):
            r = await self._identity_step(s, raw, norm)
            if r is not None:
                return r
            # not a name/dob -> fall through to normal analysis (e.g. caller asked for a human)

        # 2b. LATENCY: benign turns are answered at once from the rules; the AI safety net runs in PARALLEL and can still
        # interrupt (see late_action). Only when a real LLM route is available and the rules are confident.
        quick = await self._rules_first(s, raw, norm)
        if quick is not None:
            return quick

        # 3. LLM analysis (skipped for bare yes/no in confirm states)
        t0 = time.perf_counter()
        fast = s.state in ("AWAIT_CONFIRM", "AWAIT_APPT_CONFIRM", "AWAIT_SYMPTOM_Q") and (rules.is_yes(norm) or rules.is_no(norm))
        analysis: Analysis | None = None
        depts = await self._dept_names()
        if not fast:
            now = rules.now_local()
            analysis = await self.llm.analyze(
                utterance=self._mask_for_llm(raw), state=s.state, expecting=self._expecting(s),
                today=now.date().isoformat(), weekday=now.strftime("%A"), departments=depts,
            )
        nlu_ms = int((time.perf_counter() - t0) * 1000)

        safety = {"redflag": "ok", "scope": "ok", "pii": "on",
                  "llm_check": "skip" if fast else ("offline" if analysis is None else "ok")}
        if analysis and (analysis.red_flag or analysis.distress or analysis.intent == "emergency"):
            kind = "self_harm" if analysis.distress and not analysis.red_flag else "emergency"
            r = self._emergency(s, kind, analysis.red_flag_reason or "llm_flag", "llm")
            r.nlu_ms = nlu_ms
            return r

        # The AI safety net is offline: be stricter. Any mention of symptoms goes to a human instead of
        # carrying on with a booking, because only the keyword rules are left to catch a red flag.
        if analysis is None and not fast and rules.mentions_symptoms(norm):
            r = self._handover(
                s, [_l("medical_refusal")], HandoverRequest("medical_advice_request", "urgent", "symptoms_while_ai_offline", "rules"),
                trace=[{"step": "safety", "status": "alert", "detail": "symptoms mentioned while AI safety net is offline - handing over"}],
                safety={"redflag": "ok", "scope": "block", "pii": "on", "llm_check": "offline"}, intent="medical_question",
            )
            r.nlu_ms = nlu_ms
            return r

        # AI safety net offline and the words match nothing we know: do NOT reply with a cheerful "I can help with
        # appointments" to someone who may be describing an emergency in unusual words. Fail closed to a human.
        if analysis is None and not fast and s.state == "IDLE" and rules.rule_intent(norm) is None and len(norm.split()) >= 3:
            r = self._handover(
                s, [_l("degraded")], HandoverRequest("degraded", "urgent", "unrecognised_while_ai_offline", "system"),
                trace=[{"step": "safety", "status": "alert", "detail": "unrecognised request while AI safety net is offline - handing over"}],
                safety={"redflag": "ok", "scope": "block", "pii": "on", "llm_check": "offline"},
            )
            r.nlu_ms = nlu_ms
            return r

        r = await self._route(s, raw, norm, analysis, fast)
        r.nlu_ms = nlu_ms
        r.safety = {**safety, **r.safety}
        if analysis:
            r.trace.insert(0, {"step": "understand", "status": "ok", "detail": f"intent={analysis.intent} lang={analysis.language}"})
        elif not fast:
            r.trace.insert(0, {"step": "understand", "status": "skip", "detail": "rules only (LLM unavailable)"})
        return r

    # ------------------------------------------------------------------ latency: rules first, safety net in parallel
    # intents that carry no risk by themselves (starting a booking only asks for a name) - answered immediately
    BENIGN = {"hospital_info", "identity_question", "are_you_human", "thanks", "smalltalk", "repeat_request", "greeting", "goodbye",
              "book_appointment", "cancel_appointment", "reschedule_appointment"}

    def _start_analysis(self, s: Session, raw: str, depts: list[str]):
        now = rules.now_local()
        return asyncio.get_running_loop().create_task(self.llm.analyze(
            utterance=self._mask_for_llm(raw), state=s.state, expecting=self._expecting(s),
            today=now.date().isoformat(), weekday=now.strftime("%A"), departments=depts,
        ))

    async def _rules_first(self, s: Session, raw: str, norm: str) -> Reply | None:
        """Return a reply immediately when the rules are confident AND the request is benign, else None.

        * benign intent (hospital info, who-are-you, thanks...): reply now, LLM check runs in parallel and may interrupt;
        * short slot answers (department / date / time) that the rules parse cleanly: no LLM needed at all.
        Anything uncertain falls back to the normal "wait for the LLM" path."""
        if not getattr(self.llm, "enabled", False) or rules.mentions_symptoms(norm):
            return None
        rule_i = rules.rule_intent(norm)
        if rule_i in self.BENIGN:
            depts = await self._dept_names()
            task = self._start_analysis(s, raw, depts)
            snap = copy.deepcopy(s)
            r = await self._route(s, raw, norm, None, False)
            confident = r.handover is None and (rule_i != "hospital_info" or bool(r.sources))
            if confident:
                r.pending_analysis = task
                r.safety = {**r.safety, "llm_check": "pending"}
                r.trace.insert(0, {"step": "understand", "status": "ok", "detail": f"rules: {rule_i} (AI safety net checking in parallel)"})
                return r
            s.__dict__.update(snap.__dict__)  # not confident: undo, wait for the model instead
            task.cancel()
            return None
        if s.state in ("AWAIT_DEPT", "AWAIT_DATE", "AWAIT_TIME") and len(norm.split()) <= 6:
            snap = copy.deepcopy(s)
            r = await self._route(s, raw, norm, None, False)
            if r.handover is None and s.state != snap.state:
                r.safety = {**r.safety, "llm_check": "skip"}
                r.trace.insert(0, {"step": "understand", "status": "ok", "detail": "rules parsed the answer"})
                return r
            s.__dict__.update(snap.__dict__)
        return None

    def late_action(self, s: Session, a: Analysis | None, raw: str) -> Reply | None:
        """Called when the parallel AI check finishes AFTER a benign reply was already given. May escalate."""
        norm = normalize(raw)
        if a is None:
            if rules.mentions_symptoms(norm):
                return self._handover(
                    s, [_l("medical_refusal")], HandoverRequest("medical_advice_request", "urgent", "symptoms_while_ai_offline", "rules"),
                    trace=[{"step": "safety", "status": "alert", "detail": "AI safety net unavailable and symptoms mentioned - handing over"}],
                    safety={"llm_check": "offline", "scope": "block"}, intent="medical_question",
                )
            return None
        if a.red_flag or a.distress or a.intent == "emergency":
            kind = "self_harm" if a.distress and not a.red_flag else "emergency"
            return self._emergency(s, kind, a.red_flag_reason or "llm_flag", "llm")
        if a.intent == "medical_question" and not self._doctor_ready(a):
            return self._handover(
                s, [_l("medical_refusal")], HandoverRequest("medical_advice_request", "urgent", "medical_advice", "llm"),
                trace=[{"step": "safety", "status": "alert", "detail": "AI safety net: medical advice request - handing over"}],
                safety={"scope": "block", "llm_check": "ok"}, intent="medical_question",
            )
        if a.intent == "talk_to_human":
            return self._handover(
                s, [_l("human_request")], HandoverRequest("caller_requested", "routine", source="llm"),
                trace=[{"step": "route", "status": "ok", "detail": "AI safety net: caller wants a person"}], intent="talk_to_human",
            )
        return None

    # ------------------------------------------------------------------ routing
    async def _route(self, s: Session, raw: str, norm: str, a: Analysis | None, fast: bool) -> Reply:
        # language: voice replies are English only for now -> hand over politely
        if a and a.language in ("ur", "ur-roman") and a.confidence >= 0.6 and not rules.is_yes(norm) and not rules.is_no(norm):
            s.language = a.language
            return self._handover(
                s, [_l("urdu_notice")], HandoverRequest("language", "routine", source="llm"),
                trace=[{"step": "route", "status": "alert", "detail": "Urdu caller - voice is English only; handing over"}],
            )

        rule_i = rules.rule_intent(norm)
        intent = rule_i or (a.intent if a else None)
        # medical advice / human requests are decided by rules OR the model - either one is enough
        if rule_i == "medical_question" or (a and a.intent == "medical_question"):
            # Doctor-style conversation: needs the AI safety net to have looked at this turn (a is not None).
            if self._doctor_ready(a):
                d = await self._doctor_turn(s, raw, norm)
                if d is not None:
                    return d
            # General first-line guidance from APPROVED documents for ordinary symptoms; never for medicines, doses,
            # diagnosis, children or pregnancy (those, and anything uncertain, still go to a human).
            if self.s.symptom_guidance and self.rag and not rules.is_strict_medical(norm):
                topic = symptoms.match_topic(norm) if s.state == "IDLE" else None
                if topic:
                    return self._start_symptom_interview(s, topic)
                g = await self._guidance(s, raw, a)
                if g is not None:
                    return g
            return self._handover(
                s, [_l("medical_refusal")], HandoverRequest("medical_advice_request", "urgent", "medical_advice", "rules" if rule_i else "llm"),
                trace=[{"step": "route", "status": "alert", "detail": "medical advice request - not answered, handing over"}],
                safety={"scope": "block"}, intent="medical_question",
            )
        if intent == "talk_to_human":
            return self._handover(
                s, [_l("human_request")], HandoverRequest("caller_requested", "routine", source="caller"),
                trace=[{"step": "route", "status": "ok", "detail": "caller asked for a person"}], intent=intent,
            )

        st = s.state
        if st == "AWAIT_DOCTOR":
            if intent in ("book_appointment", "reschedule_appointment", "cancel_appointment", "goodbye"):
                s.state = st = "IDLE"
            elif intent != "hospital_info":
                d = await self._doctor_turn(s, raw, norm) if self._doctor_ready(a) else None
                if d is not None:
                    return d
                s.state = st = "IDLE"
        if st == "AWAIT_SYMPTOM_Q" and intent not in ("talk_to_human", "identity_question", "are_you_human", "repeat_request", "hospital_info", "goodbye", "thanks"):
            return await self._symptom_answer(s, norm)
        # Hania's own persona: who she is, thanks, small talk, "say that again" - never derails a flow
        if intent in ("identity_question", "are_you_human", "thanks", "smalltalk", "repeat_request"):
            return self._persona_reply(s, intent)
        # a hospital question in the middle of a booking is answered, then the flow resumes
        if intent == "hospital_info" and st != "IDLE":
            query = a.info_query if a and a.info_query else raw
            return await self._info(s, query, interject=True)
        if st in ("AWAIT_NAME", "AWAIT_DOB"):
            if intent == "goodbye":
                return self._reply(s, [_l("goodbye")], "ENDED", end=True, intent=intent)
            return self._not_caught_identity(s)
        if st == "IDLE":
            return await self._idle(s, raw, norm, a, intent)
        if st == "AWAIT_DEPT":
            return await self._dept(s, norm, a)
        if st == "AWAIT_DATE":
            return await self._date(s, norm, a)
        if st == "AWAIT_TIME":
            return await self._time(s, norm, a)
        if st == "AWAIT_CONFIRM":
            return await self._confirm(s, norm)
        if st == "AWAIT_APPT_CONFIRM":
            return await self._appt_confirm(s, norm)
        return self._degraded(s)

    def _mask_for_llm(self, raw: str) -> str:
        from app.safety.pii import mask
        return mask(raw)

    def _expecting(self, s: Session) -> str:
        return {
            "IDLE": "what the caller wants (appointment, hospital information, a person)",
            "AWAIT_DEPT": "a hospital department name",
            "AWAIT_DATE": "an appointment date",
            "AWAIT_TIME": "a time of day chosen from offered times",
            "AWAIT_CONFIRM": "yes or no",
            "AWAIT_APPT_CONFIRM": "yes or no",
            "AWAIT_SYMPTOM_Q": "yes or no to a symptom question",
        }.get(s.state, "anything")

    async def _dept_names(self) -> list[str]:
        try:
            return [d["name"] for d in await self.emr.departments()]
        except Exception:
            return []

    # ------------------------------------------------------------------ IDLE
    async def _idle(self, s: Session, raw: str, norm: str, a: Analysis | None, intent: str | None) -> Reply:
        if intent in ("book_appointment", "reschedule_appointment", "cancel_appointment"):
            s.unclear = 0
            s.pending_intent = intent
            if not s.verified:
                return self._reply(
                    s, [_l("ask_name")], "AWAIT_NAME", intent=intent,
                    trace=[{"step": "route", "status": "ok", "detail": f"{intent} - verifying caller first"}],
                )
            return await self._start_flow(s)
        if intent == "hospital_info":
            s.unclear = 0
            query = (a.info_query if a and a.info_query else raw)
            return await self._info(s, query)
        if intent == "goodbye":
            return self._reply(s, [_l("goodbye")], "ENDED", end=True, intent=intent)
        if intent == "greeting":
            return self._reply(s, [_l("capabilities")], intent=intent)
        # A symptom described in words the intent classifier did not label as medical: talk it through like a doctor would.
        if self._doctor_ready(a) and rules.mentions_symptoms(norm):
            d = await self._doctor_turn(s, raw, norm)
            if d is not None:
                return d
        # Fixed interview (offline fallback) for common symptoms
        if self.s.symptom_guidance and not rules.is_strict_medical(norm):
            topic = symptoms.match_topic(norm)
            if topic:
                return self._start_symptom_interview(s, topic)
        # Nothing recognised. It may still be an information question phrased in unexpected words (the model sometimes says
        # "other"): answer only if an approved passage matches very closely. Irrelevant questions never reach this bar.
        if self.rag and len(norm.split()) >= 2:
            hits = await self.rag.search(raw)
            if hits and hits[0].get("cosine", 0.0) >= INFO_FALLBACK_COSINE:
                s.unclear = 0
                return await self._info(s, raw)
        s.unclear += 1
        if s.unclear >= 2:
            return self._handover(
                s, [_l("unclear_handover")], HandoverRequest("unclear", "routine", source="system"),
                trace=[{"step": "route", "status": "alert", "detail": "out of scope twice - handing over"}], safety={"scope": "block"},
            )
        return self._reply(
            s, [_l("out_of_scope")], trace=[{"step": "route", "status": "skip", "detail": "outside allowed scope"}],
            safety={"scope": "block"}, intent=intent or "other",
        )

    # ------------------------------------------------------------------ doctor-style conversation
    def _doctor_ready(self, a: Analysis | None) -> bool:
        return bool(self.doctor is not None and a is not None and getattr(self.doctor, "available", False))

    async def _doctor_turn(self, s: Session, raw: str, norm: str) -> Reply | None:
        """Ask a follow-up or give possible common explanations (not a diagnosis). None -> caller falls back (interview / staff)."""
        topic = symptoms.match_topic(norm)
        try:
            d = await self.doctor.advise(list(s.history), self._mask_for_llm(raw), topic.label if topic else None, s.doctor_turns)
        except Exception:
            log.exception("doctor mode failed")
            d = None
        if d is None:
            return None
        if d.emergency:
            return self._emergency(s, "emergency", d.emergency_reason or "doctor_flag", "llm")
        verdict = check_output(d.reply)
        if not verdict.ok:
            log.warning("doctor reply blocked by the output guard (%s)", verdict.reason)
            return None
        lines: list[Line] = []
        if not s.disclaimer_given:
            lines.append(_l("doctor_disclaimer"))
            s.disclaimer_given = True
        lines.append(Line(text=d.reply, trusted=False))
        sources = [{"title": f"{x['source']}: {x['title']}", "version": 0, "chunk_id": x.get("url") or x["title"], "score": 0.0} for x in d.sources]
        trace = [{"step": "respond", "status": "ok", "detail": f"doctor mode ({d.stage}); reference: {', '.join(x['source'] for x in d.sources) or 'none'}"}]
        if d.stage == "asking":
            s.doctor_turns += 1
            s.state, s.last_prompt = "AWAIT_DOCTOR", d.reply
            return Reply(lines=lines, state="AWAIT_DOCTOR", intent="doctor_chat", trace=trace, safety={"scope": "ok"}, sources=sources)
        s.doctor_turns = 0
        if "appointment" in d.reply.lower():  # the model already offered one: just leave the door open
            outro = Line(text="Is there anything else I can help you with?")
        else:
            outro = _l("doctor_outro")
        lines.append(outro)
        s.state, s.last_prompt = "IDLE", outro.text
        return Reply(lines=lines, state="IDLE", intent="doctor_chat", trace=trace, safety={"scope": "ok"}, sources=sources,
                     event={"type": "symptom_guidance", "chunk": "doctor_mode"})

    # ------------------------------------------------------------------ symptom interview (common, usually mild complaints)
    def _start_symptom_interview(self, s: Session, topic: symptoms.Topic) -> Reply:
        s.flow = {"symptom": topic.key, "idx": 0, "tags": []}
        s.unclear = 0
        q = topic.questions[0].text
        s.state = "AWAIT_SYMPTOM_Q"
        s.last_prompt = q
        return Reply(
            lines=[_l("symptom_intro"), Line(text=q)], state="AWAIT_SYMPTOM_Q", intent="symptom_triage",
            trace=[{"step": "route", "status": "ok", "detail": f"symptom interview started: {topic.label} (not a diagnosis)"}],
            safety={"scope": "ok"},
        )

    async def _symptom_answer(self, s: Session, norm: str) -> Reply:
        topic = symptoms.BY_KEY[s.flow["symptom"]]
        if rules.wants_never_mind(norm):
            s.flow = {}
            return self._reply(s, [_l("never_mind")], "IDLE")
        yes, no = rules.is_yes(norm), rules.is_no(norm)
        q = topic.questions[s.flow["idx"]]
        if not (yes or no):
            s.unclear += 1
            if s.unclear >= 2:
                return self._handover(
                    s, [_l("unclear_handover")], HandoverRequest("symptom_escalation", "urgent", topic.key, "system"),
                    trace=[{"step": "route", "status": "alert", "detail": "symptom answers unclear - handing over"}],
                )
            s.last_prompt = q.text
            return self._reply(s, [_l("symptom_retry"), Line(text=q.text)], trace=[{"step": "route", "status": "skip", "detail": "needed yes or no"}])
        s.unclear = 0
        answer = "yes" if yes else "no"
        if q.danger_if == answer:
            return self._handover(
                s, [_l("symptom_escalate")], HandoverRequest("symptom_escalation", "urgent", topic.key, "rules"),
                trace=[{"step": "safety", "status": "alert", "detail": f"{topic.label}: warning sign reported - handing over to staff"}],
                safety={"redflag": "alert", "scope": "ok"}, intent="symptom_triage",
            )
        tag = q.tag_if_yes if answer == "yes" else q.tag_if_no
        if tag:
            s.flow["tags"].append(tag)
        s.flow["idx"] += 1
        if s.flow["idx"] < len(topic.questions):
            nxt = topic.questions[s.flow["idx"]].text
            s.last_prompt = nxt
            return Reply(lines=[Line(text=nxt)], state="AWAIT_SYMPTOM_Q", intent="symptom_triage",
                         trace=[{"step": "route", "status": "ok", "detail": f"{topic.label}: question {s.flow['idx'] + 1}/{len(topic.questions)}"}])
        return await self._symptom_result(s, topic)

    async def _symptom_result(self, s: Session, topic: symptoms.Topic) -> Reply:
        tags = list(s.flow.get("tags", []))
        cause = symptoms.pick_cause(topic, tags)
        lines = [Line(text=f"Thank you. I can't diagnose you, but from what you've told me, the most common causes are {cause}.")]
        sources, chunk = [], "none"
        hits = await self.rag.search(topic.guidance_query, category="symptom_guidance") if self.rag else []
        if hits and hits[0].get("cosine", 0.0) >= GUIDANCE_COSINE and check_output(hits[0]["text"]).ok:
            top = hits[0]
            lines.append(Line(text=top["text"], trusted=False))
            chunk = top["chunk_id"]
            sources = [{"title": top["title"], "version": top["version"], "chunk_id": top["chunk_id"], "score": top["score"]}]
        if "prolonged" in tags:
            lines.append(Line(text="Because this has gone on for a while, I'd recommend being seen."))
        outro = (f"I can book you an appointment in {topic.dept}, or connect you to our staff. What would you like? "
                 f"If it gets worse, please call {self.s.emergency_number}.")
        lines.append(Line(text=outro))
        s.last_prompt = outro
        s.flow, s.state = {}, "IDLE"
        return Reply(
            lines=lines, state="IDLE", intent="symptom_triage", sources=sources,
            trace=[{"step": "respond", "status": "ok", "detail": f"{topic.label}: common causes + approved guidance (not a diagnosis)"}],
            safety={"scope": "ok"}, event={"type": "symptom_guidance", "chunk": chunk},
        )

    async def _guidance(self, s: Session, raw: str, a: Analysis | None) -> Reply | None:
        """Approved, general, non-diagnostic guidance (rest, fluids, when to get urgent help). None -> hand over instead."""
        query = " ".join(x for x in (raw, a.info_query if a and a.info_query else "") if x)
        hits = await self.rag.search(query, category="symptom_guidance")
        if not hits or hits[0].get("cosine", 0.0) < GUIDANCE_COSINE:
            return None
        top = hits[0]
        if not check_output(top["text"]).ok:
            return None
        in_flow = s.state != "IDLE" and s.last_prompt
        tail = Line(text=s.last_prompt) if in_flow else _l("guidance_outro")
        if not in_flow:
            s.last_prompt = tail.text
        return Reply(
            lines=[_l("guidance_intro"), Line(text=top["text"], trusted=False), tail], state=s.state, intent="symptom_guidance",
            trace=[{"step": "respond", "status": "ok", "detail": f"approved general guidance: {top['title']} ({top['cosine']:.2f}) - not a diagnosis"}],
            sources=[{"title": top["title"], "version": top["version"], "chunk_id": top["chunk_id"], "score": top["score"]}],
            safety={"scope": "ok"}, event={"type": "symptom_guidance", "chunk": top["chunk_id"]},
        )

    def _persona_reply(self, s: Session, intent: str) -> Reply:
        """Answers about Hania herself. In the middle of a flow the pending question is asked again."""
        in_flow = s.state != "IDLE"
        if intent == "repeat_request":
            text = s.last_prompt or scripts.fixed("capabilities")
            return Reply(lines=[Line(text=text)], state=s.state, intent=intent,
                         trace=[{"step": "respond", "status": "ok", "detail": "repeating last message"}])
        key = {"identity_question": "about_me", "are_you_human": "are_you_human", "thanks": "thanks_reply", "smalltalk": "smalltalk"}[intent]
        lines = [_l(key)]
        if in_flow and s.last_prompt:
            lines = [_l({"thanks": "smalltalk"}.get(intent, key)) if intent != "thanks" else Line(text="You're welcome."), Line(text=s.last_prompt)]
        return Reply(lines=lines, state=s.state, intent=intent, trace=[{"step": "respond", "status": "ok", "detail": f"persona: {intent}"}])

    async def _info(self, s: Session, query: str, interject: bool = False) -> Reply:
        hits = await self.rag.search(query) if self.rag else []
        if not hits:
            if interject:
                return Reply(lines=[_l("no_info"), Line(text=s.last_prompt)], state=s.state, intent="hospital_info",
                             trace=[{"step": "respond", "status": "skip", "detail": "no approved document matched"}])
            return self._reply(
                s, [_l("no_info")], trace=[{"step": "respond", "status": "skip", "detail": "no approved document matched"}], intent="hospital_info",
            )
        top = hits[0]
        verdict = check_output(top["text"])
        if not verdict.ok:
            return self._handover(
                s, [_l("degraded")], HandoverRequest("degraded", "routine", source="system"),
                trace=[{"step": "respond", "status": "alert", "detail": f"output guard blocked ({verdict.reason})"}],
                safety={"scope": "block"},
            )
        sources = [{"title": top["title"], "version": top["version"], "chunk_id": top["chunk_id"], "score": top["score"]}]
        detail = f"approved source: {top['title']} v{top['version']} ({top['score']:.2f})"
        if interject:  # keep the booking flow where it was
            return Reply(lines=[Line(text=top["text"], trusted=False), Line(text=s.last_prompt)], state=s.state, intent="hospital_info",
                         trace=[{"step": "respond", "status": "ok", "detail": detail}], sources=sources)
        s.state = "IDLE"
        lines = [Line(text=top["text"], trusted=False), _l("anything_else")]
        s.last_prompt = top["text"]
        return Reply(
            lines=lines, state="IDLE", intent="hospital_info",
            trace=[{"step": "respond", "status": "ok", "detail": f"approved source: {top['title']} v{top['version']} ({top['score']:.2f})"}],
            sources=[{"title": top["title"], "version": top["version"], "chunk_id": top["chunk_id"], "score": top["score"]}],
        )

    # ------------------------------------------------------------------ identity
    async def _identity_step(self, s: Session, raw: str, norm: str) -> Reply | None:
        if rules.rule_intent(norm) in ("talk_to_human", "goodbye", "identity_question", "are_you_human", "repeat_request", "smalltalk", "thanks", "hospital_info"):
            return None
        name_part, dob_part = rules.split_name_dob(norm)
        if s.state == "AWAIT_NAME":
            name = rules.extract_name(name_part)
            if not name:
                return None if rules.rule_intent(norm) else self._not_caught_identity(s)
            s.claimed_name = name
            dob = rules.parse_dob(dob_part) if dob_part else None
            if not dob:
                return self._reply(s, [Line(text=f"Thank you, {name.split()[0]}. And your date of birth, please?", key=None)], "AWAIT_DOB",
                                   trace=[{"step": "route", "status": "ok", "detail": "name captured locally (not sent to cloud LLM)"}])
            return await self._verify(s, dob)
        # AWAIT_DOB
        dob = rules.parse_dob(dob_part or norm)
        if not dob:
            return self._not_caught_identity(s)
        return await self._verify(s, dob)

    def _not_caught_identity(self, s: Session) -> Reply:
        s.unclear += 1
        if s.unclear >= 3:
            return self._handover(s, [_l("verify_fail")], HandoverRequest("verification_failed", "routine", source="system"))
        return self._reply(s, [_l("not_caught")], trace=[{"step": "route", "status": "skip", "detail": "could not read name/date of birth"}])

    async def _verify(self, s: Session, dob) -> Reply:
        if self.verify_limiter and self.verify_limiter.blocked(s.client_ip):
            return self._handover(
                s, [_l("verify_fail")], HandoverRequest("verification_failed", "routine", source="system"),
                trace=[{"step": "route", "status": "alert", "detail": "too many failed identity checks from this caller - handing over"}],
            )
        try:
            patient = await self.emr.find_patient(s.claimed_name or "", dob.isoformat())
        except Exception as e:
            log.warning("emr verify failed: %s", e)
            return self._degraded(s)
        if patient:
            s.verified, s.patient, s.unclear = True, patient, 0
            first = patient["name"].split()[0]
            r = await self._start_flow(s, greeting=f"Thank you, {first}. You're verified.")
            r.trace.insert(0, {"step": "route", "status": "ok", "detail": "caller verified against EMR"})
            return r
        s.verify_attempts += 1
        if self.verify_limiter:
            self.verify_limiter.add(s.client_ip)
        if s.verify_attempts >= 3:
            return self._handover(
                s, [_l("verify_fail")], HandoverRequest("verification_failed", "routine", source="system"),
                trace=[{"step": "route", "status": "alert", "detail": "verification failed 3 times - handing over"}],
            )
        return self._reply(s, [_l("verify_retry")], "AWAIT_NAME",
                           trace=[{"step": "route", "status": "skip", "detail": f"no EMR match (attempt {s.verify_attempts}/3)"}])

    # ------------------------------------------------------------------ flows
    async def _start_flow(self, s: Session, greeting: str = "") -> Reply:
        intent = s.pending_intent
        s.flow = {}
        pre = (greeting + " ") if greeting else ""
        if intent == "book_appointment":
            names = await self._dept_names()
            # "Thank you, Ayesha. You're verified." -> ["Thank you,", "Ayesha.", "You're verified."]: only the tiny name chunk is new
            lead = [c for c in re.split(r"(?<=[.!?,])\s+", greeting) if c] if greeting else []
            return self._reply(s, [_L(*lead, "Which department would you like to see?", f"We have {rules.join_list(names)}.")], "AWAIT_DEPT", intent=intent)
        # reschedule / cancel -> need the patient's upcoming appointment
        try:
            appts = await self.emr.appointments(s.patient["id"])
        except Exception:
            return self._degraded(s)
        appts = [x for x in appts if x["status"] == "booked"]
        if not appts:
            s.state, s.pending_intent = "IDLE", None
            return self._reply(s, [_l("no_appointments")], "IDLE", intent=intent)
        appt = appts[0]
        s.flow = {"appointment": appt, "dept_id": appt["department_id"]}
        verb = "cancel" if intent == "cancel_appointment" else "change"
        text = (f"{pre}I found your {appt['department']} appointment on {rules.fmt_date(_d(appt['date']))} at "
                f"{rules.fmt_time(appt['time'])}. Would you like to {verb} that one?")
        return self._reply(s, [Line(text=text)], "AWAIT_APPT_CONFIRM", intent=intent)

    async def _dept(self, s: Session, norm: str, a: Analysis | None) -> Reply:
        if rules.wants_never_mind(norm):
            return self._reply(s, [_l("never_mind")], "IDLE")
        depts = await self.emr.departments()
        dept = rules.match_department(norm, depts)
        if not dept and a and a.department:
            dept = next((d for d in depts if d["name"].lower() == a.department.lower()), None)
        if not dept:
            s.unclear += 1
            if s.unclear >= 3:
                return self._handover(s, [_l("unclear_handover")], HandoverRequest("unclear", "routine", source="system"))
            names = rules.join_list([d["name"] for d in depts])
            return self._reply(s, [Line(text=f"Sorry, I didn't find that department. We have {names}. Which one would you like?")])
        s.unclear = 0
        s.flow.update(dept_id=dept["id"], dept_name=dept["name"])
        return self._reply(s, [_L(f"{dept['name']}, got it.", "What date would you like to come in?")], "AWAIT_DATE",
                           trace=[{"step": "route", "status": "ok", "detail": f"department={dept['name']}"}])

    async def _date(self, s: Session, norm: str, a: Analysis | None) -> Reply:
        if rules.wants_never_mind(norm):
            return self._reply(s, [_l("never_mind")], "IDLE")
        d = None
        if s.flow.get("suggested_date") and rules.is_yes(norm):
            d = _d(s.flow.pop("suggested_date"))
        if d is None and a and a.date:
            try:
                d = _d(a.date)
            except ValueError:
                d = None
        if d is None:
            d = rules.parse_date(norm)
        if d is None or not rules.valid_booking_date(d):
            s.unclear += 1
            if s.unclear >= 3:
                return self._handover(s, [_l("unclear_handover")], HandoverRequest("unclear", "routine", source="system"))
            return self._reply(s, [Line(text="Sorry, which date would you like? For example, tomorrow, or the 25th of this month.")])
        s.unclear = 0
        try:
            slots = await self.emr.slots(s.flow["dept_id"], d.isoformat())
            if slots:
                times = [x["time"] for x in slots][:3]
                s.flow.update(date=d.isoformat(), offered=times, slot_by_time={x["time"]: x["id"] for x in slots})
                line = _L(f"On {rules.fmt_date(d)},", f"{s.flow['dept_name']} has openings at", *time_chunks(times), "Which time suits you?")
                return self._reply(s, [line], "AWAIT_TIME", trace=[{"step": "route", "status": "ok", "detail": f"{len(slots)} slots on {d}"}])
            nxt = await self.emr.next_available(s.flow["dept_id"], d.isoformat())
        except Exception:
            return self._degraded(s)
        if nxt:
            s.flow["suggested_date"] = nxt
            return self._reply(
                s,
                [Line(text=f"There are no openings on {rules.fmt_date(d)}. The next available day is {rules.fmt_date(_d(nxt))}. Would you like that day?")],
                trace=[{"step": "route", "status": "skip", "detail": "no slots; suggested next day"}],
            )
        return self._reply(s, [Line(text="I'm sorry, there are no openings in that department soon. Please say another department, or ask for staff.")], "AWAIT_DEPT")

    async def _time(self, s: Session, norm: str, a: Analysis | None) -> Reply:
        if rules.wants_never_mind(norm):
            return self._reply(s, [_l("never_mind")], "IDLE")
        pick = rules.pick_slot(norm, s.flow.get("offered", []), a.time if a else None)
        if not pick:
            s.unclear += 1
            if s.unclear >= 3:
                return self._handover(s, [_l("unclear_handover")], HandoverRequest("unclear", "routine", source="system"))
            offered = rules.join_list([rules.fmt_time(t) for t in s.flow.get("offered", [])])
            return self._reply(s, [Line(text=f"Sorry, I have {offered}. Which one would you like?")])
        s.unclear = 0
        s.flow["time"] = pick
        d = _d(s.flow["date"])
        line = _L(f"I'll book {s.flow['dept_name']},", f"on {rules.fmt_date(d)},", f"at {rules.fmt_time(pick)}.", "Shall I confirm that?")
        return self._reply(s, [line], "AWAIT_CONFIRM")

    async def _confirm(self, s: Session, norm: str) -> Reply:
        if rules.is_yes(norm):
            slot_id = s.flow["slot_by_time"][s.flow["time"]]
            try:
                appt = await self.emr.book(s.patient["id"], slot_id)
            except Exception:
                return self._degraded(s)
            if not appt:
                s.state = "AWAIT_DATE"
                return self._reply(s, [Line(text="Sorry, that slot was just taken. What other date would you like?")], "AWAIT_DATE")
            s.flow["booked"] = appt
            old = s.flow.get("reschedule_from")
            if old:
                try:
                    await self.emr.cancel(old)
                except Exception:
                    log.warning("could not cancel old appointment %s after reschedule", old)
            line = _L(f"Done. Your {appt['department']} appointment is confirmed for", f"{rules.fmt_date(_d(appt['date']))},",
                      f"at {rules.fmt_time(appt['time'])}.", "Please arrive fifteen minutes early.")
            r = self._reply(s, [line, _l("anything_else")], "IDLE", intent="book_appointment",
                            trace=[{"step": "respond", "status": "ok", "detail": f"booked {appt['id']}"}])
            s.pending_intent = None
            r.event = {"type": "appointment_booked", "appointment": appt}
            return r
        if rules.is_no(norm):
            return self._reply(s, [Line(text="No problem. What date would you like instead?")], "AWAIT_DATE")
        s.unclear += 1
        if s.unclear >= 3:
            return self._handover(s, [_l("unclear_handover")], HandoverRequest("unclear", "routine", source="system"))
        return self._reply(s, [Line(text="Sorry, should I confirm that booking? Please say yes or no.")])

    async def _appt_confirm(self, s: Session, norm: str) -> Reply:
        appt = s.flow["appointment"]
        if rules.is_yes(norm):
            if s.pending_intent == "cancel_appointment":
                try:
                    ok = await self.emr.cancel(appt["id"])
                except Exception:
                    return self._degraded(s)
                s.pending_intent = None
                text = "Your appointment has been cancelled." if ok else "I couldn't cancel that appointment, so I'll connect you to staff."
                r = self._reply(s, [Line(text=text), _l("anything_else")], "IDLE", intent="cancel_appointment")
                r.event = {"type": "appointment_cancelled", "appointment": appt}
                return r
            # reschedule: keep the department, pick a new date; old appointment is cancelled once the new one is booked
            s.flow.update(dept_id=appt["department_id"], dept_name=appt["department"], reschedule_from=appt["id"])
            s.pending_intent = "book_appointment"
            return self._reply(s, [Line(text="Sure. What new date would you like?")], "AWAIT_DATE")
        if rules.is_no(norm):
            s.pending_intent = None
            return self._reply(s, [_l("never_mind")], "IDLE")
        s.unclear += 1
        if s.unclear >= 3:
            return self._handover(s, [_l("unclear_handover")], HandoverRequest("unclear", "routine", source="system"))
        return self._reply(s, [Line(text="Sorry, is that the appointment you mean? Please say yes or no.")])


def _d(iso: str):
    from datetime import date
    return date.fromisoformat(iso[:10])
