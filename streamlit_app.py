import io
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="AI Energy & Carbon Footprint Calculator", page_icon="🌱", layout="wide")

DEFAULT_WORKBOOK = Path(__file__).with_name("AI_Footprint_Calculator_MI300X.xlsx")

@st.cache_data
def load_workbook_data(file_bytes):
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    assumptions = pd.read_excel(xls, "Assumptions")
    model_factors = pd.read_excel(xls, "Model_Factors")
    hardware_factors = pd.read_excel(xls, "Hardware_Factors")
    usage = pd.read_excel(xls, "Usage_Data")
    return assumptions, model_factors, hardware_factors, usage

def assumption_value(df, parameter, fallback):
    rows = df[df["Parameter"].astype(str).str.strip().str.lower() == parameter.lower()]
    if rows.empty or pd.isna(rows.iloc[0]["Value"]):
        return fallback
    return float(rows.iloc[0]["Value"])

def make_excel_download(results, sheet_name="Streamlit_Results"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        results.to_excel(writer, sheet_name=sheet_name, index=False)
    output.seek(0)
    return output.getvalue()

st.title("AI Energy & Carbon Footprint Calculator")
st.caption("Estimate energy consumption, carbon emissions and water consumption across AI models, use cases and GPU platforms.")

with st.sidebar:
    st.header("Workbook")
    uploaded = st.file_uploader("Upload your calculator workbook (optional)", type=["xlsx"])
    if uploaded:
        workbook_bytes = uploaded.getvalue()
    elif DEFAULT_WORKBOOK.exists():
        workbook_bytes = DEFAULT_WORKBOOK.read_bytes()
    else:
        st.error("Place AI_Footprint_Calculator_MI300X.xlsx in the same folder as app.py.")
        st.stop()

    assumptions, model_factors, hardware_factors, existing_usage = load_workbook_data(workbook_bytes)
    st.divider()
    st.caption("Yellow/input values in the workbook are intended to be calibrated with provider disclosures or measured telemetry.")

default_pue = assumption_value(assumptions, "PUE", 1.2)
default_wue = assumption_value(assumptions, "WUE (on-site)", 0.5)
default_grid_water = assumption_value(assumptions, "Water intensity (grid)", 1.8)
default_ci = assumption_value(assumptions, "Grid carbon intensity", 480)

tab_token, tab_gpu, tab_compare, tab_notes = st.tabs([
    "Token-based estimate", "AMD GPU power estimate", "Compare / export", "Methodology"
])

if "token_results" not in st.session_state:
    st.session_state.token_results = pd.DataFrame()
if "gpu_results" not in st.session_state:
    st.session_state.gpu_results = pd.DataFrame()

with tab_token:
    st.subheader("Model and use-case energy estimate")
    st.info("Uses the per-token energy coefficients in Model_Factors. These are estimates, not direct GPU power measurements.")
    model_names = model_factors["Model"].dropna().astype(str).tolist()
    model = st.selectbox("Model", model_names, key="token_model")
    selected_factor = model_factors[model_factors["Model"].astype(str) == model].iloc[0]
    model_pue_default = float(selected_factor["PUE"]) if pd.notna(selected_factor["PUE"]) else float(default_pue)
    model_ci_default = float(selected_factor["Grid gCO2e/kWh"]) if pd.notna(selected_factor["Grid gCO2e/kWh"]) else float(default_ci)
    model_wue_default = float(selected_factor["WUE L/kWh"]) if pd.notna(selected_factor["WUE L/kWh"]) else float(default_wue)
    with st.form("token_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            month = st.text_input("Month", "2026-11")
            business_unit = st.text_input("Business unit", "AI")
            use_case = st.text_input("Application / use case", "Inference")
        with c2:
            input_tokens = st.number_input("Input tokens", min_value=0, value=1_000_000, step=100_000)
            output_tokens = st.number_input("Output tokens", min_value=0, value=250_000, step=50_000)
        with c3:
            pue = st.number_input("PUE (editable)", min_value=1.0, max_value=3.0, value=model_pue_default, step=0.05)
            grid_ci = st.number_input("Grid carbon intensity (gCO₂e/kWh)", min_value=0.0, value=model_ci_default, step=10.0)
            wue = st.number_input("On-site WUE (L/kWh)", min_value=0.0, value=model_wue_default, step=0.1)
            grid_water = st.number_input("Grid water intensity (L/kWh)", min_value=0.0, value=float(default_grid_water), step=0.1)
        submitted = st.form_submit_button("Calculate token-based footprint", type="primary")
    if submitted:
        row = selected_factor
        kwh_in = float(row["kWh/input token"])
        kwh_out = float(row["kWh/output token"])
        model_ci = float(grid_ci)
        model_pue = float(pue)
        model_wue = float(wue)
        it_energy = (input_tokens * kwh_in) + (output_tokens * kwh_out)
        facility_energy = it_energy * model_pue
        carbon = facility_energy * model_ci / 1000
        water = facility_energy * (model_wue + grid_water)
        total_tokens = input_tokens + output_tokens
        result = {
            "Month": month, "Business Unit": business_unit, "Application / Use Case": use_case,
            "Model": model, "Calculation Method": "Token-based",
            "IT Energy (kWh)": it_energy, "Facility Energy (kWh)": facility_energy,
            "Carbon (kg CO2e)": carbon, "Water (L)": water,
            "Total Tokens": total_tokens,
            "Energy (kWh / 1k tokens)": facility_energy / (total_tokens / 1000) if total_tokens else 0,
            "Grid CI (gCO2e/kWh)": model_ci, "PUE": model_pue
        }
        st.session_state.token_results = pd.concat(
            [st.session_state.token_results, pd.DataFrame([result])], ignore_index=True
        )
    if not st.session_state.token_results.empty:
        latest = st.session_state.token_results.iloc[-1]
        m1, m2, m3 = st.columns(3)
        m1.metric("Facility energy", f'{latest["Facility Energy (kWh)"]:,.3f} kWh')
        m2.metric("Carbon footprint", f'{latest["Carbon (kg CO2e)"]:,.3f} kg CO₂e')
        m3.metric("Water consumption", f'{latest["Water (L)"]:,.2f} L')
        st.dataframe(st.session_state.token_results, use_container_width=True, hide_index=True)

with tab_gpu:
    st.subheader("Hardware-based estimate")
    st.info("Calculates energy from average GPU board power × GPU count × runtime. Use measured average power from telemetry whenever available.")
    gpu_names = hardware_factors["GPU"].dropna().astype(str).tolist()
    if not gpu_names:
        gpu_names = ["AMD Instinct MI300X"]
    selected_gpu = st.selectbox("GPU platform", gpu_names, index=0)
    gpu_row = hardware_factors[hardware_factors["GPU"].astype(str) == selected_gpu].iloc[0]
    peak_tbp = float(gpu_row["Peak TBP (W)"])
    st.caption(f"Published peak TBP reference: {peak_tbp:.0f} W per GPU. This is a maximum board-power specification, not an assumed typical workload draw.")
    with st.form("gpu_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            gpu_month = st.text_input("Month ", "2026-11")
            gpu_bu = st.text_input("Business unit ", "AI")
            gpu_usecase = st.text_input("Application / use case ", "LLM inference")
            gpu_model = st.text_input("Model name", "Llama / custom model")
        with c2:
            gpu_count = st.number_input("Number of GPUs", min_value=1, max_value=4096, value=8, step=1)
            avg_power = st.number_input("Average power per GPU (W)", min_value=0.0, max_value=float(peak_tbp), value=float(peak_tbp), step=10.0,
                                        help="Enter the average power from AMD SMI/telemetry. The default equals the published peak TBP and is a conservative upper-bound input.")
            runtime_hours = st.number_input("Workload runtime (hours)", min_value=0.0, value=1.0, step=0.5)
            utilization = st.slider("Average GPU utilization (%)", 0, 100, 70)
        with c3:
            gpu_pue = st.number_input("PUE ", min_value=1.0, max_value=3.0, value=float(default_pue), step=0.05)
            gpu_ci = st.number_input("Grid carbon intensity (gCO₂e/kWh) ", min_value=0.0, value=float(default_ci), step=10.0)
            gpu_wue = st.number_input("On-site WUE (L/kWh) ", min_value=0.0, value=float(default_wue), step=0.1)
            gpu_grid_water = st.number_input("Grid water intensity (L/kWh) ", min_value=0.0, value=float(default_grid_water), step=0.1)
            gpu_tokens = st.number_input("Total tokens processed (optional)", min_value=0, value=0, step=100_000)
        gpu_submit = st.form_submit_button("Calculate MI300X footprint", type="primary")
    if gpu_submit:
        it_energy = gpu_count * avg_power * runtime_hours / 1000
        facility_energy = it_energy * gpu_pue
        carbon = facility_energy * gpu_ci / 1000
        water = facility_energy * (gpu_wue + gpu_grid_water)
        result = {
            "Month": gpu_month, "Business Unit": gpu_bu, "Application / Use Case": gpu_usecase,
            "Model": gpu_model, "GPU Platform": selected_gpu, "GPU Count": int(gpu_count),
            "Average GPU Power (W)": avg_power, "Runtime (Hours)": runtime_hours,
            "GPU Utilization (%)": utilization, "Calculation Method": "GPU power-based",
            "IT Energy (kWh)": it_energy, "Facility Energy (kWh)": facility_energy,
            "Carbon (kg CO2e)": carbon, "Water (L)": water, "Total Tokens": int(gpu_tokens),
            "Energy (kWh / 1k tokens)": facility_energy / (gpu_tokens / 1000) if gpu_tokens else None,
            "Grid CI (gCO2e/kWh)": gpu_ci, "PUE": gpu_pue
        }
        st.session_state.gpu_results = pd.concat(
            [st.session_state.gpu_results, pd.DataFrame([result])], ignore_index=True
        )
    if not st.session_state.gpu_results.empty:
        latest = st.session_state.gpu_results.iloc[-1]
        m1, m2, m3 = st.columns(3)
        m1.metric("Facility energy", f'{latest["Facility Energy (kWh)"]:,.3f} kWh')
        m2.metric("Carbon footprint", f'{latest["Carbon (kg CO2e)"]:,.3f} kg CO₂e')
        m3.metric("Water consumption", f'{latest["Water (L)"]:,.2f} L')
        st.dataframe(st.session_state.gpu_results, use_container_width=True, hide_index=True)

with tab_compare:
    st.subheader("Results and export")
    combined = pd.concat(
        [st.session_state.token_results, st.session_state.gpu_results],
        ignore_index=True, sort=False
    )
    if combined.empty:
        st.warning("Run at least one calculation in the Token-based or AMD GPU power estimate tab.")
    else:
        numeric_cols = ["IT Energy (kWh)", "Facility Energy (kWh)", "Carbon (kg CO2e)", "Water (L)"]
        totals = combined[numeric_cols].sum(numeric_only=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total facility energy", f'{totals["Facility Energy (kWh)"]:,.3f} kWh')
        c2.metric("Total carbon", f'{totals["Carbon (kg CO2e)"]:,.3f} kg CO₂e')
        c3.metric("Total water", f'{totals["Water (L)"]:,.2f} L')
        st.dataframe(combined, use_container_width=True, hide_index=True)
        st.download_button(
            "Download results as Excel",
            data=make_excel_download(combined),
            file_name="AI_Footprint_Streamlit_Results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.download_button(
            "Download results as CSV",
            data=combined.to_csv(index=False).encode("utf-8"),
            file_name="AI_Footprint_Streamlit_Results.csv",
            mime="text/csv"
        )
        if st.button("Clear session results"):
            st.session_state.token_results = pd.DataFrame()
            st.session_state.gpu_results = pd.DataFrame()
            st.rerun()

with tab_notes:
    st.subheader("Calculation methodology and assumptions")
    st.markdown("""
**Token-based method**
- IT energy = (input tokens × input kWh/token) + (output tokens × output kWh/token)
- Facility energy = IT energy × PUE
- Carbon = facility energy × grid carbon intensity ÷ 1,000
- Water = facility energy × (on-site WUE + grid water intensity)

**GPU power-based method**
- GPU IT energy (kWh) = GPU count × average GPU power (W) × runtime (hours) ÷ 1,000
- Facility energy = GPU IT energy × PUE
- Carbon = facility energy × grid carbon intensity ÷ 1,000
- Water = facility energy × (on-site WUE + grid water intensity)

**Important interpretation**
- The two methods are alternatives. Do not add their results for the same workload; that would double-count energy.
- GPU utilization is recorded as workload context; it is not multiplied into the power formula because average power is entered separately.
- MI300X 750 W is the published peak/maximum TBP. For production reporting, replace the default with measured average board power from telemetry and account separately for host CPU, memory, storage and network power if a full-node or cluster footprint is required.
- Token coefficients in the supplied workbook are retained as supplied and should be calibrated against measured workloads before external reporting.
""")
    st.markdown("**MI300X specification reference:** [AMD Instinct MI300X product specifications](https://www.amd.com/en/products/accelerators/instinct/mi300/mi300x.html)")
