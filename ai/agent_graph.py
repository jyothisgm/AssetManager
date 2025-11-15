import json, re
from ai.prompts import SYSTEM_INSTRUCTIONS
from ai.utils import get_llm_for_user, safe_parse_json
from common.logging_config import logger
from typing import TypedDict, List, Literal, Any, Dict
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from django.contrib.auth import get_user_model
from user.models import GmailAccount
from user.utils import fetch_all_user_emails
from asgiref.sync import sync_to_async, async_to_sync
from transaction.helpers import create_transaction_from_llm_tx


User = get_user_model()

# ------------------------------
# STATE
# ------------------------------

class AgentState(TypedDict, total=False):
    messages: List[BaseMessage]
    user_id: int
    mode: Literal["voice", "gmail", "verify_only"]
    input_text: str
    emails: List[Dict[str, Any]]
    transactions: List[Dict[str, Any]]
    verified: bool


# ------------------------------
# NODE: classify intent
# ------------------------------

def classify_intent(state: AgentState) -> AgentState:
    logger.info(f"[ClassifyIntent] Starting intent classification for user_id={state['user_id']}")
    if "mode" in state:
        logger.debug(f"[ClassifyIntent] Mode already set to '{state['mode']}' — skipping classification.")
        return state

    llm = get_llm_for_user(state["user_id"])
    user_instruction = (
        "You will be given the user's message. "
        "Respond ONLY with one of: 'voice', 'gmail', or 'verify_only'."
    )
    msg = [SystemMessage(content=user_instruction), HumanMessage(content=state["input_text"])]

    res = llm.invoke(msg)
    intent_raw = res.content.strip().lower()
    if "gmail" in intent_raw:
        mode = "gmail"
    elif "verify" in intent_raw:
        mode = "verify_only"
    else:
        mode = "voice"

    logger.info(f"[ClassifyIntent] Classified mode='{mode}' for user_id={state['user_id']}")
    state["mode"] = mode
    state.setdefault("messages", []).extend(msg + [AIMessage(content=f"[intent: {mode}]")])
    return state


# ------------------------------
# NODE: fetch Gmail emails
# ------------------------------

def fetch_gmail_emails(state: AgentState) -> AgentState:
    user_id = state["user_id"]
    logger.info(f"[FetchGmail] Fetching Gmail emails for user_id={user_id}")
    user = User.objects.get(pk=user_id)

    if not GmailAccount.objects.filter(created_by=user, active=True).exists():
        logger.warning(f"[FetchGmail] No active Gmail accounts for user_id={user_id}")
        state.setdefault("messages", []).append(AIMessage(content="No active Gmail accounts connected."))
        state["emails"] = []
        return state

    try:
        emails = fetch_all_user_emails(user)
        logger.info(f"[FetchGmail] Retrieved {len(emails)} emails for user_id={user_id}")
        state["emails"] = emails
        state.setdefault("messages", []).append(
            AIMessage(content=f"Fetched {len(emails)} Gmail messages for analysis.")
        )
    except Exception as e:
        logger.exception(f"[FetchGmail] Error while fetching Gmail emails for user_id={user_id}: {e}")
        state["emails"] = []
        state.setdefault("messages", []).append(AIMessage(content=f"Error fetching Gmail: {str(e)}"))
    return state


def find_transactions_in_emails(
    user_id: int,
    emails: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Use one Gemini call to extract all possible transactions from a batch of emails.
    Each returned transaction includes a reference to its originating email.
    """
    logger.info(f"[FindTxInEmails] Running single LLM extraction for {len(emails)} emails (user_id={user_id})")
    llm = get_llm_for_user(user_id)
    all_txs: List[Dict[str, Any]] = []

    # --- Build email summaries for prompt ---
    email_summaries = "\n\n".join(
        f"--- EMAIL {idx+1} ---\n"
        f"Email ID: {email.get('id', f'email_{idx}')}\n"
        f"From: {email.get('from', '')}\n"
        f"Subject: {email.get('subject', '')}\n"
        f"Snippet:\n{email.get('snippet', '')}"
        for idx, email in enumerate(emails)
    )

    # --- Build a concise but powerful instruction ---
    prompt = (
        "You are a finance assistant that reads a batch of emails and extracts every "
        "possible financial transaction mentioned in them.\n\n"
        "For each transaction you find, return a JSON object with:\n"
        "date, amount, currency, description, category, needs_review (true/false), "
        "and include two reference fields:\n"
        "email_id (from 'Email ID' above) and email_subject (from 'Subject').\n\n"
        "If no transaction is found in an email, ignore it. Do not include duplicates.\n"
        "Return a single valid JSON array containing all transactions across all emails.\n\n"
        f"{email_summaries}\n\n"
        "Return ONLY the JSON array — no explanations or text outside the array."
    )

    try:
        messages = [SystemMessage(content=SYSTEM_INSTRUCTIONS), HumanMessage(content=prompt)]
        res = llm.invoke(messages)
        txs = safe_parse_json(res.content)
        logger.info(f"[FindTxInEmails] Extracted {len(txs)} transactions for user_id={user_id}")
        all_txs.extend(txs)

    except Exception as e:
        logger.exception(f"[FindTxInEmails] Failed for user_id={user_id}: {e}")

    return all_txs


# ------------------------------
# NODE: extract transactions
# ------------------------------
def extract_transactions(state: AgentState) -> AgentState:
    logger.info(f"[ExtractTransactions] Starting extraction for user_id={state['user_id']}, mode={state.get('mode')}")
    llm = get_llm_for_user(state["user_id"])
    messages = [SystemMessage(content=SYSTEM_INSTRUCTIONS)]

    try:
        if state.get("mode") == "voice":
            logger.debug("[ExtractTransactions] Processing voice input.")
            messages.append(
                HumanMessage(content=f"Voice text:\n{state.get('input_text', '')}")
            )
        elif state.get("mode") == "gmail":
            emails = state.get("emails", [])
            email_summaries = "\n\n".join(
                f"---\nSubject: {e.get('subject')}\nFrom: {e.get('from')}\nSnippet: {e.get('snippet')}"
                for e in emails[:50]
            )
            logger.debug(f"[ExtractTransactions] Providing {len(emails)} emails to LLM.")
            messages.append(HumanMessage(content=f"Emails:\n{email_summaries}"))
        else:
            logger.debug("[ExtractTransactions] Fallback mode (direct text).")
            messages.append(HumanMessage(content=state.get("input_text", "")))

        messages.append(
            HumanMessage(
                content="Return ONLY valid JSON array of transactions with fields: "
                        "date, amount, currency, description, source, category, needs_review."
            )
        )

        res = llm.invoke(messages)
        raw_output = (res.content or "").strip()

        # --- extract JSON even if wrapped in markdown or text ---
        json_match = re.search(r"\[.*\]", raw_output, re.S)
        if not json_match:
            logger.warning(f"[ExtractTransactions] No JSON found in LLM output: {raw_output[:200]}...")
            txs = []
        else:
            json_str = json_match.group(0)
            try:
                txs = json.loads(json_str)
                if not isinstance(txs, list):
                    logger.warning(f"[ExtractTransactions] Parsed JSON not a list. Got: {type(txs)}")
                    txs = []
            except json.JSONDecodeError as e:
                logger.exception(f"[ExtractTransactions] JSON decode error: {e} | Raw: {json_str[:200]}...")
                txs = []


        logger.info(f"[ExtractTransactions] Extracted {len(txs)} transactions for user_id={state['user_id']}")
        state["transactions"] = txs

    except Exception as e:
        logger.exception(f"[ExtractTransactions] Failed for user_id={state['user_id']}: {e}")
        state["transactions"] = []
        messages.append(AIMessage(content=f"Error extracting transactions: {str(e)}"))

    state.setdefault("messages", []).extend(messages + [AIMessage(content=f"Extracted {len(state['transactions'])} transactions.")])
    return state


# ------------------------------
# NODE: verify + save
# ------------------------------
def verify_and_save(state: AgentState) -> AgentState:
    user_id = state["user_id"]
    txs = state.get("transactions", []) or []
    logger.info(f"[VerifyAndSave] Starting verification for user_id={user_id} with {len(txs)} transactions.")

    from django.contrib.auth import get_user_model
    User = get_user_model()

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error(f"[VerifyAndSave] User {user_id} does not exist.")
        state["verified"] = False
        state.setdefault("messages", []).append(
            AIMessage(content=f"Error: user {user_id} not found, cannot save transactions.")
        )
        return state

    # Try to get LLM once (for correction and extra checks)
    llm = None
    try:
        llm = async_to_sync(get_llm_for_user)(user_id)
        logger.debug(f"[VerifyAndSave] Loaded LLM for user_id={user_id}")
    except Exception as e:
        logger.exception(f"[VerifyAndSave] Could not load LLM for user_id={user_id}: {e}")
        # we still continue, but without LLM-based correction

    created_count = 0
    dup_count = 0
    error_count = 0
    stored_ids = []

    for idx, tx_data in enumerate(txs, start=1):
        try:
            logger.debug(f"[VerifyAndSave] Processing tx #{idx}: {tx_data}")
            txn, status = create_transaction_from_llm_tx(user, tx_data, llm=llm)

            if status == "created" and txn:
                created_count += 1
                stored_ids.append(str(txn.id))
            elif status == "duplicate":
                dup_count += 1
            else:
                error_count += 1

        except Exception as e:
            error_count += 1
            logger.exception(f"[VerifyAndSave] Error while saving tx #{idx} for user_id={user_id}: {e}")

    summary = (
        f"[VerifyAndSave] Processed {len(txs)} parsed transactions for user_id={user_id}: "
        f"created={created_count}, duplicates={dup_count}, errors={error_count}."
    )
    logger.info(summary)

    state["verified"] = error_count == 0
    state.setdefault("messages", []).append(
        AIMessage(
            content=f"Stored {created_count} new transactions, "
                    f"skipped {dup_count} duplicates, "
                    f"{error_count} errors."
        )
    )
    # Optionally expose IDs in state if you want to inspect later
    state["saved_transaction_ids"] = stored_ids

    return state


# ------------------------------
# CONDITIONAL ROUTING
# ------------------------------

def route_from_intent(state: AgentState) -> str:
    mode = state.get("mode")
    logger.debug(f"[Router] Routing based on mode='{mode}'")
    if mode == "gmail":
        return "fetch_gmail"
    elif mode == "voice":
        return "extract_transactions"
    else:
        return "extract_transactions"


# ------------------------------
# BUILD GRAPH
# ------------------------------

def build_agent_graph() -> Any:
    logger.info("[Graph] Building AI agent graph.")
    graph = StateGraph(AgentState)

    graph.add_node("classify_intent", classify_intent)
    graph.add_node("fetch_gmail", fetch_gmail_emails)
    graph.add_node("extract_transactions", extract_transactions)
    graph.add_node("verify_and_save", verify_and_save)

    graph.set_entry_point("classify_intent")

    graph.add_conditional_edges(
        "classify_intent",
        route_from_intent,
        {
            "fetch_gmail": "fetch_gmail",
            "extract_transactions": "extract_transactions",
        },
    )
    graph.add_edge("fetch_gmail", "extract_transactions")
    graph.add_edge("extract_transactions", "verify_and_save")
    graph.add_edge("verify_and_save", END)

    logger.info("[Graph] Agent graph successfully compiled.")
    return graph.compile()
