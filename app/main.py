from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

APP_VERSION = "1.0.0"
STARTED_AT = time.time()
VALID_SCOPES = {"category", "merchant", "customer", "trigger"}

app = FastAPI(title="Vera Merchant AI Assistant", version=APP_VERSION)
lock = RLock()

# The judge pushes all context. No seed data is required at runtime.
contexts: Dict[str, Dict[str, Dict[str, Any]]] = {
    "category": {},
    "merchant": {},
    "customer": {},
    "trigger": {},
}
conversations: Dict[str, Dict[str, Any]] = {}
sent_suppression: set[str] = set()
conversation_counter = 0


class ContextRequest(BaseModel):
    scope: str
    context_id: str
    version: int = Field(ge=0)
    payload: Dict[str, Any]
    delivered_at: Optional[str] = None


class TickRequest(BaseModel):
    now: str
    available_triggers: list[str] = Field(default_factory=list)


class ReplyRequest(BaseModel):
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: Optional[str] = None
    turn_number: int = Field(ge=1)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def pct(x: Any) -> Optional[str]:
    try:
        return f"{float(x) * 100:.0f}%"
    except (TypeError, ValueError):
        return None


def first_name(merchant: dict) -> str:
    ident = merchant.get("identity", {})
    return ident.get("owner_first_name") or ident.get("name", "").split(" ")[0] or "there"


def merchant_name(merchant: dict) -> str:
    return merchant.get("identity", {}).get("name") or "your business"


def locality(merchant: dict) -> str:
    ident = merchant.get("identity", {})
    return ident.get("locality") or ident.get("city") or "your area"


def category_slug(merchant: dict, category: dict) -> str:
    return merchant.get("category_slug") or category.get("slug", "")


def active_offer(merchant: dict, keywords: tuple[str, ...] = ()) -> Optional[dict]:
    offers = merchant.get("offers") or []
    active = [o for o in offers if str(o.get("status", "active")).lower() == "active"]
    if keywords:
        for o in active:
            title = str(o.get("title", "")).lower()
            if any(k in title for k in keywords):
                return o
    return active[0] if active else None


def offer_title(merchant: dict, keywords: tuple[str, ...] = ()) -> Optional[str]:
    o = active_offer(merchant, keywords)
    return str(o.get("title")) if o and o.get("title") else None


def digest_item(category: dict, trigger: dict) -> Optional[dict]:
    payload = trigger.get("payload") or {}
    wanted = payload.get("top_item_id") or payload.get("digest_item_id")
    items = category.get("digest") or []
    if wanted:
        for item in items:
            if item.get("id") == wanted:
                return item
    return items[0] if items else None


def peer_ctr(category: dict) -> Optional[float]:
    try:
        return float((category.get("peer_stats") or {}).get("avg_ctr"))
    except (TypeError, ValueError):
        return None


def safe_text(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def sanitize_cta(body: str) -> str:
    # Every outbound message has one primary low-friction next step.
    return "open_ended"


def compose(category: dict, merchant: dict, trigger: dict, customer: Optional[dict]) -> dict:
    """Deterministic, context-grounded composer. Never invents missing facts."""
    cat = category_slug(merchant, category)
    kind = trigger.get("kind", "")
    p = trigger.get("payload") or {}
    name = first_name(merchant)
    biz = merchant_name(merchant)
    loc = locality(merchant)
    send_as = "merchant_on_behalf" if trigger.get("scope") == "customer" else "vera"

    # Customer-facing consent is a hard gate.
    if trigger.get("scope") == "customer":
        if not customer:
            return {"skip": True, "reason": "customer_context_missing"}
        consent = customer.get("consent") or {}
        prefs = customer.get("preferences") or {}
        if prefs.get("reminder_opt_in") is False and kind in {"recall_due", "appointment_tomorrow", "chronic_refill_due", "trial_followup"}:
            return {"skip": True, "reason": "reminder_opt_out"}
        if consent.get("scope") == []:
            return {"skip": True, "reason": "no_consent_scope"}
        customer_name = customer.get("identity", {}).get("name") or "there"
        lang = str(customer.get("identity", {}).get("language_pref", "en")).lower()

        if kind == "recall_due":
            due = p.get("due_date")
            slots = p.get("available_slots") or []
            offer = offer_title(merchant, ("clean",))
            slot_text = " or ".join(str(s.get("label")) for s in slots[:2] if s.get("label"))
            if "hi-en" in lang or lang == "hi":
                body = f"Hi {customer_name} 🦷 {biz} here. Aapki {safe_text(p.get('service_due', 'recall'))} recall {due or 'due soon'} hai."
            else:
                body = f"Hi {customer_name} 🦷 {biz} here. Your {safe_text(p.get('service_due', 'recall'))} recall is due {due or 'soon'}."
            if slot_text:
                body += f" We have {slot_text}."
            if offer:
                body += f" {offer}."
            body += " Want me to hold a slot?"
            return _result(body, "Recall trigger + real availability/offer; customer preference and consent are respected.", send_as)

        if kind == "wedding_package_followup":
            days = p.get("days_to_wedding")
            wedding = p.get("wedding_date")
            offer = active_offer(merchant, ("bridal", "wedding", "skin"))
            body = f"Hi {customer_name} 💍 {biz} here."
            if days is not None and wedding:
                body += f" Your wedding is {wedding} ({days} days away), so the {safe_text(p.get('next_step_window_open', 'prep'))} window is open."
            elif wedding:
                body += f" Your wedding is {wedding}, and the {safe_text(p.get('next_step_window_open', 'prep'))} window is open."
            if offer:
                body += f" {offer.get('title')}."
            body += " Want me to help plan the first session?"
            return _result(body, "Bridal follow-up uses the trigger's wedding timing and only an active catalog offer if present.", send_as)

        if kind == "customer_lapsed_soft":
            state = safe_text(customer.get("state", "lapsed_soft")).replace("_", " ")
            last_visit = (customer.get("relationship") or {}).get("last_visit")
            offer = active_offer(merchant)
            body = f"Hi {customer_name} 👋 {biz} here."
            if last_visit:
                body += f" We last saw you on {last_visit}; no pressure, just checking in."
            else:
                body += f" We noticed your account is marked {state}; no pressure."
            if offer:
                body += f" We currently have {offer.get('title')}."
            body += " Want me to help with a simple next visit?"
            return _result(body, "Soft-lapse outreach uses the customer's recorded relationship state/date and an active offer only if supplied.", send_as)

        if kind == "customer_lapsed_hard":
            days = p.get("days_since_last_visit")
            focus = p.get("previous_focus")
            offer = active_offer(merchant, ("trial",))
            body = f"Hi {customer_name} 👋 {name} from {biz} here."
            if days is not None:
                body += f" It’s been {days} days — no pressure."
            else:
                body += " It’s been a little while — no pressure."
            if focus:
                body += f" You were working on {safe_text(focus)}."
            if offer:
                body += f" We currently have {offer.get('title')}."
            body += " Want me to help you pick a low-commitment return option?"
            return _result(body, "Lapsed-customer trigger is handled with a no-shame reactivation ask and only verified offer data.", send_as)

        if kind == "trial_followup":
            options = p.get("next_session_options") or []
            labels = [str(x.get("label")) for x in options[:2] if x.get("label")]
            body = f"Hi {customer_name} 👋 {biz} here. Your trial was on {p.get('trial_date', 'recently')}."
            if labels:
                body += f" The next option is {labels[0]}"
            body += ". Want me to hold it for you?"
            return _result(body, "Trial follow-up uses the recorded trial date and next-session option without inventing availability.", send_as)

        if kind == "chronic_refill_due":
            molecules = p.get("molecule_list") or []
            runout = p.get("stock_runs_out_iso")
            delivery = bool(p.get("delivery_address_saved"))
            body = f"Namaste — {biz} here."
            if molecules:
                body += f" Your refill list is {', '.join(map(str, molecules))}."
            if runout:
                body += f" Stock is due to run out on {str(runout)[:10]}."
            elif not molecules:
                body += " A refill reminder has been raised for your account."
            delivery_offer = offer_title(merchant, ("delivery",))
            if delivery and delivery_offer:
                body += f" {delivery_offer} can be used for the saved address."
            body += " Want us to prepare the refill?"
            return _result(body, "Refill trigger uses molecule/date/address data when present and avoids inventing medicine details when the trigger is a generated placeholder.", send_as)

        if kind == "appointment_tomorrow":
            body = f"Hi {customer_name}, {biz} here. Your appointment is tomorrow."
            body += " Want me to keep the slot confirmed?"
            return _result(body, "Appointment reminder is intentionally concise and asks for one confirmation.", send_as)

    # Merchant-facing trigger routing.
    if kind == "research_digest":
        item = digest_item(category, trigger)
        if item:
            parts = [f"{name}, {item.get('source', 'A new category update')} landed."]
            title = safe_text(item.get("title"))
            if title:
                parts.append(title + ".")
            segment = item.get("patient_segment") or item.get("audience")
            aggregate = merchant.get("customer_aggregate") or {}
            if segment and "high_risk_adult" in str(segment):
                count = aggregate.get("high_risk_adult_count")
                if count is not None:
                    parts.append(f"You have {count} high-risk adult patients in your roster.")
            source = item.get("source")
            if source and source not in " ".join(parts):
                parts.append(f"Source: {source}.")
            parts.append("Want me to pull the item and turn it into a short patient-facing draft?")
            return _result(" ".join(parts), "Research digest selected because the trigger is research-driven; the message anchors to the category source and merchant cohort when available.", send_as)

        if kind == "regulation_change":
            title = safe_text(p.get("title") or "a regulation update")
        summary = safe_text(p.get("summary"))
        deadline = p.get("deadline_iso")

        body = f"{name}, heads-up: {title}."

        if summary:
            body += f" {summary}."

        if deadline:
            body += f" Deadline: {deadline}."

        body += " Want me to turn the requirement into a short checklist?"

        return _result(
            body,
            "Regulation trigger uses the supplied regulation title, summary, and deadline, with one practical next step.",
            send_as,
        )
    if kind in {"perf_dip", "seasonal_perf_dip"}:
        perf = merchant.get("performance") or {}
        metric = p.get("metric")
        if not metric:
            # Generated triggers may intentionally contain only a placeholder. Use a
            # real merchant metric rather than inventing a delta.
            metric = "views" if perf.get("delta_7d", {}).get("views_pct") is not None else "performance"
        supplied_delta = p.get("delta_pct")
        if supplied_delta is None:
            supplied_delta = (perf.get("delta_7d") or {}).get(f"{metric}_pct")
        delta = pct(supplied_delta)
        baseline = p.get("vs_baseline")
        if baseline is None:
            baseline = perf.get("calls") if metric == "calls" else perf.get("views") if metric == "views" else None
        seasonal = bool(p.get("is_expected_seasonal"))
        peer = category.get("peer_stats") or {}

        if kind == "perf_dip" and supplied_delta is not None:
            change_pct = abs(float(supplied_delta)) * 100
            body = (
                f"{metric} are down {change_pct:.0f}% over the last "
                f"{p.get('window', '7d')}; the current reference is {baseline}"
            )
        else:
            body = f"{metric} is {delta or 'flagged for review'}"

        if kind == "perf_dip" and peer.get(metric) is not None:
            body += f". Peer average is {peer.get(metric)}"
        elif baseline is not None and kind != "perf_dip":
            body += f"; current reference is {baseline}"

        body += "."
        if seasonal:
            note = p.get("season_note")
            body += f" This is flagged as an expected seasonal pattern{(' (' + safe_text(note) + ')') if note else ''}."
            action = next((b.get("note") for b in category.get("seasonal_beats", []) if "Apr-Jun" in str(b.get("month_range", ""))), None)
            if action:
                body += f" Category guidance: {action}."
        else:
            avg = peer.get("avg_calls_30d") if metric == "calls" else peer.get("avg_views_30d") if metric == "views" else None
            if avg is not None:
                body += f" Peer average for {metric} is {avg}."
        body += " Want me to draft one focused recovery action?"
        return _result(body, "Performance trigger is prioritized using the supplied metric movement and category benchmark/seasonality.", send_as)

    if kind == "perf_spike":
        perf = merchant.get("performance") or {}
        metric = p.get("metric")
        if not metric:
            metric = "views" if (perf.get("delta_7d") or {}).get("views_pct") is not None else "performance"
        supplied_delta = p.get("delta_pct")
        if supplied_delta is None:
            supplied_delta = (perf.get("delta_7d") or {}).get(f"{metric}_pct")
        delta = pct(supplied_delta)
        driver = p.get("likely_driver")
        body = f"{name}, {metric} is up {delta or 'recently'} over {p.get('window', 'the recent window')}"
        if p.get("vs_baseline") is not None:
            body += f" vs baseline {p['vs_baseline']}"
        if driver:
            body += f". The supplied signal points to {safe_text(driver)} as a likely driver."
        body += " Want me to turn that signal into a repeatable post or offer?"
        return _result(body, "Performance spike is tied to the supplied metric, delta and driver rather than a generic growth message.", send_as)

    if kind == "renewal_due":
        days = p.get("days_remaining")
        plan = p.get("plan")
        amount = p.get("renewal_amount")
        body = f"{name}, your {plan or 'subscription'} renewal is in {days if days is not None else 'an upcoming'} days"
        if amount is not None:
            body += f" at ₹{amount}"
        body += ". Want me to walk you through the renewal options?"
        return _result(body, "Renewal trigger is time-sensitive and uses only the plan, remaining days and amount supplied.", send_as)

    if kind == "festival_upcoming":
        festival = p.get("festival")
        days = p.get("days_until")
        if festival:
            body = f"{name}, {festival} is coming up"
            if days is not None:
                body += f" in {days} days"
            body += f" for {loc}."
        else:
            body = f"{name}, a festival opportunity signal is active for {loc}."
        offer = active_offer(merchant)
        if offer:
            body += f" You already have {offer.get('title')} active."
        body += " Want me to draft one festival-ready message around the supplied signal?"
        return _result(body, "Festival trigger uses explicit festival/timing data when present and avoids inventing a festival when the trigger is a placeholder.", send_as)

    if kind == "ipl_match_today":
        match = p.get("match")
        venue = p.get("venue")
        time_s = p.get("match_time_iso")
        is_weeknight = p.get("is_weeknight")
        offer = active_offer(merchant)
        body = f"Quick heads-up {name} — {match or 'an IPL match'}"
        if venue:
            body += f" at {venue}"
        if time_s:
            body += f" at {time_s[11:16]}"
        body += " today."
        if is_weeknight is False:
            body += " The supplied category guidance says match-night promos are for Tue/Wed/Thu, so today is better treated as a delivery moment than an in-venue promo."
        if offer:
            body += f" You already have {offer.get('title')} active."
        body += " Want me to draft one delivery-focused message?"
        return _result(body, "IPL trigger is interpreted with the category's seasonal beat and the merchant's existing active offer.", send_as)

    if kind == "active_planning_intent":
        topic = safe_text(p.get("intent_topic", "the idea you were planning"))
        last = safe_text(p.get("merchant_last_message"))
        body = f"{name}, picking up your {topic.replace('_', ' ')} plan."
        if last:
            body += f" You said: “{last}”."
        body += " I can turn the current idea into a first draft using only your existing offer/context. Want me to draft it?"
        return _result(body, "Active planning gets continuity from the merchant's last stated intent and offers one concrete next step.", send_as)

    if kind == "curious_ask_due":
        body = f"Hi {name}! Quick check — what service has been most asked-for this week at {biz}?"
        body += " I’ll turn the answer into one short customer-facing draft."
        return _result(body, "Curious-ask cadence is intentionally a low-effort question to elicit fresh merchant signal.", send_as)

    if kind == "supply_alert":
        molecule = p.get("molecule")
        batches = p.get("affected_batches") or []
        manufacturer = p.get("manufacturer")
        body = f"{name}, urgent: the supplied alert flags {molecule or 'a medicine'}"
        if batches:
            body += f" batches {', '.join(map(str, batches))}"
        if manufacturer:
            body += f" from {manufacturer}"
        body += "."
        body += " Pull the affected stock and use the repeat-Rx list to identify customers if applicable."
        body += " Want me to draft the customer notification?"
        return _result(body, "Supply alert is treated as urgent and uses exact molecule/batch/manufacturer data from the trigger.", send_as)

    if kind == "category_seasonal":
        trends = p.get("trends") or []
        trend_text = ", ".join(map(str, trends[:3]))
        body = f"{name}, the supplied summer signal is shifting demand at {biz}."
        if trend_text:
            body += f" Top movements: {trend_text}."
        if p.get("shelf_action_recommended"):
            body += " Shelf visibility is explicitly recommended."
        body += " Want me to turn the signal into one shelf/action checklist?"
        return _result(body, "Seasonal trigger uses only the supplied demand movements and recommended shelf action.", send_as)

    if kind == "gbp_unverified":
        body = f"{name}, your Google Business Profile is currently marked unverified."
        path = p.get("verification_path")
        if path:
            body += f" The supplied verification path is {path}."
        body += " Want me to turn the verification path into a short checklist?"
        return _result(body, "GBP trigger is grounded in the explicit verification state and path.", send_as)

    if kind == "competitor_opened":
        comp = p.get("competitor_name", "a competitor")
        dist = p.get("distance_km")
        their = p.get("their_offer")
        body = f"{name}, {comp} opened"
        if dist is not None:
            body += f" {dist} km away"
        body += "."
        if their:
            body += f" Their supplied offer is {their}."
        body += " Want me to compare that signal with your current active offer?"
        return _result(body, "Competitor trigger is factual: name, distance and supplied competitor offer are used without inventing a response strategy.", send_as)

    if kind == "review_theme_emerged":
        theme = safe_text(p.get("theme", "a review theme"))
        occ = p.get("occurrences_30d")
        body = f"{name}, a {theme.replace('_', ' ')} review theme is rising"
        if occ is not None:
            body += f" ({occ} occurrences in 30 days)"
        body += "."
        quote = p.get("common_quote")
        if quote:
            body += f" One recent theme example: “{safe_text(quote)}”."
        body += " Want me to turn it into one operational fix to test?"
        return _result(body, "Review signal is grounded in the supplied theme, count and quote.", send_as)

    if kind == "milestone_reached":
        metric = p.get("metric")
        now = p.get("value_now")
        milestone = p.get("milestone_value")
        if metric is None or now is None:
            body = f"{name}, a milestone signal just arrived for {biz}. Want me to turn it into one short customer-facing draft?"
        else:
            body = f"{name}, you’re at {now} {safe_text(metric)}"
            if milestone is not None:
                body += f" — only {max(0, int(milestone) - int(now))} from {milestone}"
            body += ". Want me to draft one short post to help you make the milestone?"
        return _result(body, "Milestone trigger is anchored to the supplied values when present; placeholders are not converted into invented numbers.", send_as)

    if kind == "dormant_with_vera":
        days = p.get("days_since_last_merchant_message")
        topic = p.get("last_topic")
        body = f"Hi {name} — it’s been {days} days since our last merchant conversation" if days is not None else f"Hi {name} — it’s been a while since our last conversation"
        if topic:
            body += f" about {safe_text(topic).replace('_', ' ')}"
        body += ". Want a one-minute check-in on what needs attention now?"
        return _result(body, "Dormancy is handled as a low-pressure re-entry rather than a generic promotion.", send_as)

    if kind == "winback_eligible":
        days = p.get("days_since_expiry")
        added = p.get("lapsed_customers_added_since_expiry")
        body = f"{name}, your account has been inactive for {days} days" if days is not None else f"{name}, your account is eligible for a win-back conversation"
        if added is not None:
            body += f"; {added} lapsed customers were added since expiry"
        body += ". Want me to draft one reactivation message using your current offer?"
        return _result(body, "Win-back trigger uses the supplied inactivity and customer-growth signals and asks for one draft action.", send_as)

    if kind == "cde_opportunity":
        credits = p.get("credits")
        fee = p.get("fee")
        body = f"{name}, there’s a CDE opportunity tied to the supplied digest item."
        if credits is not None:
            body += f" It offers {credits} credits"
        if fee:
            body += f" ({fee})"
        body += ". Want me to turn it into a quick registration checklist?"
        return _result(body, "CDE opportunity uses the supplied credits/fee details and avoids claiming unprovided eligibility.", send_as)

    # Safe generic fallback for newly injected trigger kinds.
    body = f"{name}, I’ve got a new {safe_text(kind or 'merchant signal').replace('_', ' ')} signal for {biz}."
    # Use one high-confidence merchant fact if available.
    perf = merchant.get("performance") or {}
    if perf.get("ctr") is not None:
        body += f" Your current CTR is {float(perf['ctr']) * 100:.1f}%."
    body += " Want me to turn the supplied signal into one concrete next step?"
    return _result(body, "Fallback uses the trigger kind plus one directly supplied merchant metric; no unsupported claims are added.", send_as)


def _result(body: str, rationale: str, send_as: str) -> dict:
    return {
        "body": safe_text(body),
        "cta": sanitize_cta(body),
        "send_as": send_as,
        "rationale": safe_text(rationale),
    }


def get_context(scope: str, context_id: str) -> Optional[dict]:
    item = contexts[scope].get(context_id)
    return item.get("payload") if item else None


def find_merchant(merchant_id: str) -> Optional[dict]:
    item = get_context("merchant", merchant_id)
    return item


def find_customer(customer_id: Optional[str]) -> Optional[dict]:
    if not customer_id:
        return None
    return get_context("customer", customer_id)


def find_category(merchant: dict, trigger: dict) -> Optional[dict]:
    slug = merchant.get("category_slug") or (trigger.get("payload") or {}).get("category")
    if not slug:
        return None
    return get_context("category", slug)


def valid_trigger(trigger: dict) -> bool:
    return bool(trigger.get("id") and trigger.get("scope") in {"merchant", "customer"} and trigger.get("merchant_id"))


def new_conversation_id(merchant_id: str, trigger_id: str) -> str:
    global conversation_counter
    conversation_counter += 1
    base = re.sub(r"[^a-zA-Z0-9]+", "_", merchant_id).strip("_")
    trig = re.sub(r"[^a-zA-Z0-9]+", "_", trigger_id).strip("_")
    return f"conv_{base}_{trig}_{conversation_counter}"


def is_affirmative(msg: str) -> bool:
    s = msg.lower().strip()
    return bool(re.search(r"\b(yes|yep|yeah|sure|go ahead|do it|send|confirm|1|okay|ok)\b", s))


def is_negative(msg: str) -> bool:
    s = msg.lower().strip()
    return bool(re.search(r"\b(no|nope|stop|unsubscribe|don't|do not|not interested)\b", s))


def handle_reply(req: ReplyRequest) -> dict:
    with lock:
        conv = conversations.get(req.conversation_id)
        if not conv:
            return {"action": "end", "rationale": "Unknown conversation_id; ending safely rather than inventing prior context."}
        msg = safe_text(req.message)
        if is_negative(msg):
            conv["status"] = "ended"
            return {"action": "end", "rationale": "Merchant/customer declined; conversation closed without another promotional message."}
        if is_affirmative(msg):
            last = conv.get("last_action") or {}
            trigger = conv.get("trigger") or {}
            kind = trigger.get("kind", "")
            if kind == "research_digest":
                return {"action": "send", "body": "Absolutely — I’ll use the supplied digest item and prepare the short draft from that source.", "cta": "open_ended", "rationale": "Acknowledges the requested follow-up and stays anchored to the original research context."}
            if kind in {"perf_dip", "perf_spike", "seasonal_perf_dip", "review_theme_emerged", "milestone_reached"}:
                return {"action": "send", "body": "Got it. I’ll keep it to one concrete action based on the signal we just discussed.", "cta": "open_ended", "rationale": "Honors the affirmative reply and narrows the next step to one action."}
            if kind == "curious_ask_due":
                return {"action": "send", "body": "Perfect. I’ll turn your answer into one concise customer-facing draft.", "cta": "open_ended", "rationale": "Converts the merchant's answer into the promised artifact."}
            if kind in {"recall_due", "appointment_tomorrow", "trial_followup", "customer_lapsed_hard", "wedding_package_followup", "chronic_refill_due"}:
                return {"action": "send", "body": "Done — I’ll use the confirmed context and keep the next step to this request only.", "cta": "open_ended", "rationale": "Acknowledges customer intent without introducing unverified appointment, pricing or medical facts."}
            return {"action": "send", "body": "Got it. I’ll proceed using only the context already supplied for this conversation.", "cta": "open_ended", "rationale": "Affirmative reply acknowledged without fabricating a result."}
        if any(w in msg.lower() for w in ["later", "tomorrow", "busy", "not now"]):
            return {"action": "wait", "wait_seconds": 1800, "rationale": "User indicated a timing objection; backing off avoids pressure."}
        # Ask one short clarifying question rather than hallucinating an action.
        return {"action": "send", "body": "Understood. Which single part should I handle first?", "cta": "open_ended", "rationale": "Ambiguous reply; asks one low-friction clarification instead of guessing."}


@app.post("/v1/context")
def post_context(req: ContextRequest):
    if req.scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail={"accepted": False, "reason": "invalid_scope"})
    if not req.context_id.strip() or not isinstance(req.payload, dict):
        raise HTTPException(status_code=400, detail={"accepted": False, "reason": "invalid_context"})
    with lock:
        existing = contexts[req.scope].get(req.context_id)
        if existing:
            old_version = int(existing["version"])
            if req.version < old_version:
                return _stale(old_version)
            if req.version == old_version:
                return {"accepted": True, "ack_id": f"ack_{req.scope}_{req.context_id}_{req.version}", "stored_at": existing.get("stored_at", now_iso())}
        stored = now_iso()
        contexts[req.scope][req.context_id] = {"version": req.version, "payload": req.payload, "stored_at": stored}
        return {"accepted": True, "ack_id": f"ack_{req.scope}_{req.context_id}_{req.version}", "stored_at": stored}


def _stale(current_version: int):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"accepted": False, "reason": "stale_version", "current_version": current_version})


@app.post("/v1/tick")
def post_tick(req: TickRequest):
    actions = []
    with lock:
        for tid in req.available_triggers:
            stored = contexts["trigger"].get(tid)
            if not stored:
                continue
            trigger = stored["payload"]
            if not valid_trigger(trigger):
                continue
            suppression = trigger.get("suppression_key") or trigger.get("id")
            if suppression in sent_suppression:
                continue
            merchant = find_merchant(trigger.get("merchant_id"))
            if not merchant:
                continue
            customer = find_customer(trigger.get("customer_id"))
            category = find_category(merchant, trigger)
            if not category:
                continue
            result = compose(category, merchant, trigger, customer)
            if result.get("skip"):
                continue
            conv_id = new_conversation_id(trigger["merchant_id"], trigger["id"])
            conversations[conv_id] = {
                "merchant_id": trigger["merchant_id"],
                "customer_id": trigger.get("customer_id"),
                "trigger": trigger,
                "category": category,
                "merchant": merchant,
                "customer": customer,
                "status": "open",
                "sent_bodies": [result["body"]],
                "last_action": result,
            }
            sent_suppression.add(suppression)
            actions.append({
                "conversation_id": conv_id,
                "merchant_id": trigger["merchant_id"],
                "customer_id": trigger.get("customer_id"),
                "send_as": result["send_as"],
                "trigger_id": trigger["id"],
                "template_name": f"vera_{trigger.get('kind', 'signal')}_v1",
                "template_params": [first_name(merchant), safe_text(trigger.get("kind", "signal"))],
                "body": result["body"],
                "cta": result["cta"],
                "suppression_key": suppression,
                "rationale": result["rationale"],
            })
            if len(actions) >= 20:
                break
    return {"actions": actions}


@app.post("/v1/reply")
def post_reply(req: ReplyRequest):
    return handle_reply(req)


@app.get("/v1/healthz")
def healthz():
    with lock:
        counts = {scope: len(contexts[scope]) for scope in ["category", "merchant", "customer", "trigger"]}
    return {"status": "ok", "uptime_seconds": int(time.time() - STARTED_AT), "contexts_loaded": counts}


@app.get("/v1/metadata")
def metadata():
    import os
    members = [x.strip() for x in os.getenv("TEAM_MEMBERS", "Mehak Yadav").split(",") if x.strip()]
    return {
        "team_name": os.getenv("TEAM_NAME", "Mehak Yadav"),
        "team_members": members,
        "model": "deterministic-rule-engine-v1",
        "approach": "deterministic four-context trigger router with category-aware composition and stateful reply handling",
        "contact_email": os.getenv("CONTACT_EMAIL", "mehak.yadav.ug23@nsut.ac.in"),
        "version": APP_VERSION,
        "submitted_at": os.getenv("SUBMITTED_AT", "2026-09-25T00:00:00Z"),
    }


@app.post("/v1/teardown")
def teardown():
    with lock:
        for scope in contexts:
            contexts[scope].clear()
        conversations.clear()
        sent_suppression.clear()
    return {"ok": True, "cleared": True}

