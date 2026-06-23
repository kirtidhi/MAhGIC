import streamlit as st
import json
import pandas as pd

st.set_page_config(layout="wide", page_title="AI Stock Brain Dashboard", page_icon="🧠")

st.title("🧠 AI Stock Brain: Hidden Gems Dashboard")

try:
    import os
    results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results.json')
    with open(results_path, 'r') as f:
        data = json.load(f)
except Exception:
    st.error("No results.json found. Run orchestrator.py first.")
    st.stop()

st.sidebar.header("Navigation")
section = st.sidebar.radio("Go to", ["1. Macro Trends", "2. Company Discovery", "3. Hidden Gems"])

if section == "1. Macro Trends":
    st.header("🌍 Phase 1: Macro Trends")
    macro = data.get("macro_result", {})
    
    st.subheader("Identified Trends")
    for t in macro.get("trends", []):
        st.markdown(f"- **{t}**")
        
    st.subheader("Market Commentary")
    st.info(macro.get("commentary", "N/A"))
    
    st.subheader("Sources")
    st.caption(", ".join(macro.get("sources", [])))

elif section == "2. Company Discovery":
    st.header("🔎 Phase 2: Discovered Companies")
    
    st.markdown("### How the Score is Calculated")
    st.info("Each company is evaluated against our **Wisdom Corpus** (Ray Dalio, Charlie Munger, Ashish Chugh). Companies receive a score out of 10 based on their competitive moat, margin of safety, and alignment with these elite frameworks.")
    
    comps = data.get("discovered_companies", [])
    scores = data.get("all_scores", {})
    
    if comps:
        df_data = []
        for c in comps:
            ticker = c.get('ticker')
            score = scores.get(ticker, 0)
            df_data.append({
                "Company": c.get('company_name'),
                "Ticker": ticker,
                "Score": score,
                "Description": c.get('description'),
                "Trends Matched": ", ".join(c.get('trends_matched', []))
            })
        df = pd.DataFrame(df_data)
        df = df.sort_values(by="Score", ascending=False).reset_index(drop=True)
        
        # Color highlighting
        def highlight_score(val):
            if not isinstance(val, (int, float)):
                return ''
            color = 'green' if val >= 7 else ('orange' if val > 3 else 'red')
            return f'color: {color}'
        
        st.dataframe(df.style.map(highlight_score, subset=['Score']), use_container_width=True)

elif section == "3. Hidden Gems":
    st.header("💎 Phase 3: Hidden Gems Deep Dive")
    gems = data.get("hidden_gems", [])
    if not gems:
        st.warning("No Hidden Gems found (Score >= 7) based on strict criteria.")
    else:
        for gem in gems:
            st.markdown("---")
            st.subheader(f"🌟 {gem}")
            
            thesis = data.get("hidden_gems_thesis", {}).get(gem, "")
            
            col1, col2 = st.columns([1, 1])
            with col1:
                st.markdown(thesis)
            
            with col2:
                gem_data = data.get("hidden_gems_data", {}).get(gem, {})
                dates = gem_data.get("dates", [])
                trends = gem_data.get("trends", {})
                if dates and trends:
                    # Align lengths
                    labels = dates[::-1]
                    l = len(labels)
                    chart_df = pd.DataFrame({
                        "Date": labels,
                        "Total Revenue": trends.get("Total Revenue", [])[:l][::-1],
                        "Net Income": trends.get("Net Income", [])[:l][::-1],
                        "Free Cash Flow": trends.get("Free Cash Flow", [])[:l][::-1]
                    }).set_index("Date")
                    
                    st.line_chart(chart_df)
                    
                    st.markdown("**Financial Snapshot (Last Quarter)**")
                    info = gem_data.get("info", {})
                    
                    # Create small metric cards
                    m1, m2, m3, m4 = st.columns(4)
                    currency = info.get("currency", "USD")
                    
                    def fmt(val):
                        if not val: return "N/A"
                        if currency == "INR": return f"₹{val/1e7:.0f}Cr"
                        
                        prefixes = {"USD": "$", "AUD": "A$", "CAD": "C$", "EUR": "€", "GBP": "£", "JPY": "¥"}
                        sym = prefixes.get(currency, "$")
                        return f"{sym}{val/1e9:.2f}B" if val >= 1e9 else f"{sym}{val/1e6:.1f}M"
                        
                    m1.metric("Market Cap", fmt(info.get('marketCap', 0)))
                    m2.metric("Forward P/E", info.get("forwardPE", "N/A"))
                    m3.metric("Total Cash", fmt(info.get('totalCash', 0)))
                    m4.metric("Total Debt", fmt(info.get('totalDebt', 0)))

st.sidebar.markdown("---")
st.sidebar.caption(f"Total Tokens Used: {data.get('token_usage', 0):,}")
