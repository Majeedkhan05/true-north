"""Streamlit frontend.

  CLIENT PORTAL  — language selector (mandatory first screen), document list,
                   viewer, extracted JSON, draft email, APPROVE, billing.
  ADMIN PANEL    — onboarding, MRR, active subscriptions, system health.

Talks to the FastAPI backend over HTTP (API_BASE_URL).

Run:  streamlit run dashboard.py
"""
from __future__ import annotations

import os

import requests
import streamlit as st

API = os.environ.get("API_BASE_URL", "http://localhost:8000")

# i18n shares the backend's string table.
from i18n import t  # noqa: E402

st.set_page_config(page_title="Brokerage-AI", page_icon="🍁", layout="wide")


# ---------------------------------------------------------------------------
#  HTTP helpers
# ---------------------------------------------------------------------------
def api_get(path: str, **params):
    r = requests.get(f"{API}{path}", params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def api_post(path: str, data=None, json=None, files=None):
    r = requests.post(f"{API}{path}", data=data, json=json, files=files, timeout=120)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
#  Mandatory FIRST SCREEN: language selector
# ---------------------------------------------------------------------------
def language_gate() -> None:
    st.markdown("<h1 style='text-align:center'>🍁 Brokerage-AI</h1>", unsafe_allow_html=True)
    st.markdown(
        "<h3 style='text-align:center'>Choose your language · Choisissez votre langue</h3>",
        unsafe_allow_html=True,
    )
    st.write("")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🇨🇦 English", use_container_width=True):
            st.session_state.lang = "en"
            st.rerun()
    with c2:
        if st.button("🇨🇦 Français", use_container_width=True):
            st.session_state.lang = "fr"
            st.rerun()


# ---------------------------------------------------------------------------
#  Client portal
# ---------------------------------------------------------------------------
def client_portal(lang: str) -> None:
    st.header(t(lang, "client_portal"))

    # pick a brokerage (in production this comes from auth; here a selector)
    try:
        brokerages = api_get("/admin/brokerages")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Backend unreachable at {API}: {exc}")
        return
    if not brokerages:
        st.info("No brokerages yet — create one in the Admin Panel.")
        return

    labels = {f"{b['name']} ({b['email']})": b for b in brokerages}
    choice = st.selectbox(t(lang, "select_brokerage"), list(labels.keys()))
    brokerage = labels[choice]
    bid = brokerage["id"]

    # If the brokerage has a stored language, honour it for AI/email context.
    st.caption(f"Brokerage language: {brokerage['language'].upper()} · {t(lang, 'plan')}: {brokerage['plan']}")

    # subscription banner
    if brokerage["status"] in ("active", "trialing"):
        st.success(f"✅ {t(lang, 'subscription_active')}")
    else:
        st.error(f"🚫 {t(lang, 'subscription_inactive')}")

    tab_docs, tab_billing = st.tabs([t(lang, "documents"), t(lang, "billing")])

    # ---- Documents ----
    with tab_docs:
        # upload path so the full pipeline is demoable from the UI
        with st.expander("➕ " + t(lang, "documents") + " — upload PDF"):
            up = st.file_uploader("PDF", type=["pdf"], key="up")
            if up and st.button("Process", key="process"):
                try:
                    api_post(
                        "/webhook/document",
                        data={"brokerage_id": bid},
                        files={"file": (up.name, up.getvalue(), "application/pdf")},
                    )
                    st.success("Processed.")
                except requests.HTTPError as e:
                    code = e.response.status_code
                    if code == 409:
                        st.warning("Duplicate document (SHA256) — already processed.")
                    elif code == 429:
                        st.error("Quota exceeded — upgrade your plan.")
                    elif code == 403:
                        st.error(t(lang, "subscription_inactive"))
                    elif code == 400:
                        st.error("Invalid file — please upload a PDF.")
                    else:
                        st.error(f"Error {code}: {e.response.text}")

        docs = api_get("/brokerage/documents", brokerage_id=bid)
        if not docs:
            st.info(t(lang, "no_documents"))
            return

        for d in docs:
            ej = d.get("extracted_json") or {}
            title = ej.get("policy_number") or d["id"][:8]
            badge = "✅ " + t(lang, "approved") if d["status"] == "approved" else "🟡 " + d["status"]
            with st.expander(f"{badge}  ·  {title}  ·  {t(lang,'confidence')}: {d.get('confidence_score','?')}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader(t(lang, "extracted_data"))
                    st.json(ej)
                with col2:
                    st.subheader(t(lang, "draft_email"))
                    st.text_area("", d.get("draft_email") or "", height=320, key=f"em_{d['id']}")

                if d["status"] != "approved":
                    if st.button("✔ " + t(lang, "approve"), key=f"ap_{d['id']}"):
                        api_post(f"/brokerage/approve/{d['id']}", data={"brokerage_id": bid})
                        st.success(t(lang, "approved"))
                        st.rerun()

    # ---- Billing ----
    with tab_billing:
        st.subheader(t(lang, "subscribe"))
        plan = st.selectbox(t(lang, "plan"), ["starter", "pro", "enterprise"])
        prices = {"starter": "$499/mo · 100 docs", "pro": "$1999/mo · 500 docs",
                  "enterprise": "$4999/mo · unlimited"}
        st.caption(prices[plan])
        if st.button(t(lang, "subscribe"), key="checkout"):
            res = api_post("/billing/checkout", data={"brokerage_id": bid, "plan": plan})
            url = res["checkout_url"]
            st.markdown(f"[➡ Stripe Checkout]({url})")
            st.info("Demo mode marks the subscription active immediately.")


# ---------------------------------------------------------------------------
#  Admin panel
# ---------------------------------------------------------------------------
def admin_panel(lang: str) -> None:
    st.header(t(lang, "admin_panel"))

    # metrics
    try:
        m = api_get("/admin/metrics")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Backend unreachable: {exc}")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric(t(lang, "mrr"), f"${m['mrr_cad']:,} CAD")
    c2.metric(t(lang, "active_subscriptions"), m["active_subscriptions"])
    health = m["system_health"]
    dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[health]
    c3.metric(t(lang, "system_health"), f"{dot} {health}")

    st.bar_chart(m.get("active_by_plan") or {})

    st.divider()
    st.subheader(t(lang, "onboard_brokerage"))
    with st.form("onboard"):
        name = st.text_input(t(lang, "name"))
        email = st.text_input(t(lang, "email"))
        postal = st.text_input(t(lang, "postal_code"))
        plan = st.selectbox(t(lang, "plan"), ["starter", "pro", "enterprise"])
        submitted = st.form_submit_button(t(lang, "create"))
        if submitted:
            try:
                b = api_post(
                    "/admin/brokerage",
                    json={"name": name, "email": email, "postal_code": postal, "plan": plan},
                )
                st.success(f"Created {b['name']} · default language: {b['language'].upper()}")
            except requests.HTTPError as e:
                st.error(f"{e.response.status_code}: {e.response.text}")

    st.divider()
    st.subheader(t(lang, "active_subscriptions"))
    st.dataframe(api_get("/admin/brokerages"), use_container_width=True)


# ---------------------------------------------------------------------------
#  Router
# ---------------------------------------------------------------------------
def main() -> None:
    if "lang" not in st.session_state:
        language_gate()
        return

    lang = st.session_state.lang
    with st.sidebar:
        st.markdown("### 🍁 Brokerage-AI")
        section = st.radio(
            "",
            [t(lang, "client_portal"), t(lang, "admin_panel")],
        )
        if st.button("🌐 " + t(lang, "choose_language")):
            del st.session_state.lang
            st.rerun()

    if section == t(lang, "client_portal"):
        client_portal(lang)
    else:
        admin_panel(lang)


if __name__ == "__main__":
    main()
