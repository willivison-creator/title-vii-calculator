import streamlit as st
import datetime
import pandas as pd
import numpy as np

# --- CORE ECONOMIC & LEGAL LOGIC ENGINE ---
class TitleVIIDamagesCalculator:
    def __init__(self, employer_size: int, is_government_employer: bool, is_section_1981: bool):
        self.employer_size = employer_size
        self.is_government_employer = is_government_employer
        self.is_section_1981 = is_section_1981
        self.statutory_cap = self._get_statutory_cap(employer_size, is_section_1981)

    def _get_statutory_cap(self, size: int, is_1981: bool) -> float:
        if is_1981:
            return float('inf')  # No cap under Section 1981 individual claims
        if size <= 100: return 50000.0
        elif size <= 200: return 100000.0
        elif size <= 500: return 200000.0
        else: return 300000.0

    def _calculate_yearfrac(self, start_date, end_date) -> float:
        # Convert any input type (str, date, Timestamp) robustly using pandas
        d1 = pd.to_datetime(start_date).date()
        d2 = pd.to_datetime(end_date).date()
        return max(0.0, (d2 - d1).days / 365.25)

    def calculate_base_annual_compensation(self, is_hourly: bool, hourly_rate: float, weekly_hours: float, 
                                           unpaid_leave_hours: float, annual_salary: float, annual_benefits: float) -> float:
        if is_hourly:
            total_worked_hours = max(0.0, (weekly_hours * 52.0) - unpaid_leave_hours)
            return (total_worked_hours * hourly_rate) + annual_benefits
        else:
            return annual_salary + annual_benefits

    def calculate_back_pay(self, start_date, end_date, base_annual_comp, adverse_action, 
                           actual_ongoing_rate, sought_promoted_rate, mitigation_jobs, actual_paid):
        duration = self._calculate_yearfrac(start_date, end_date)
        is_separation = adverse_action in ["Termination / Discharge", "Constructive Discharge"]
        
        # 1. Base Expected Loss
        if is_separation:
            total_expected_loss = duration * base_annual_comp
            baseline_ongoing_earnings = 0.0
        else:
            total_expected_loss = duration * sought_promoted_rate
            baseline_ongoing_earnings = duration * actual_ongoing_rate
            
        # 2. Dynamic Mitigation & Rate Change Tracker
        total_interim_earnings = 0.0
        
        for _, job in mitigation_jobs.iterrows():
            if pd.isnull(job['Start Date']) or pd.isnull(job['End Date']):
                continue
            
            job_duration = self._calculate_yearfrac(job['Start Date'], job['End Date'])
            job_annual = job['Annual Earnings ($)']
            
            if is_separation:
                # Standard Mitigation: Exclude jobs paying more than the "but for" baseline
                if job_annual < base_annual_comp:
                    total_interim_earnings += (job_duration * job_annual)
            else:
                # Pay Change / Demotion Mitigation: Credit the difference between the new rate and the old ongoing rate
                # (since the old ongoing rate is already factored into baseline_ongoing_earnings)
                rate_increase = max(0.0, job_annual - actual_ongoing_rate)
                total_interim_earnings += (job_duration * rate_increase)
                    
        total_mitigation = baseline_ongoing_earnings + total_interim_earnings + actual_paid
        total_back_pay = max(0.0, total_expected_loss - total_mitigation)
        
        return {
            "Duration (Years)": round(duration, 4),
            "Expected Gross Loss": round(total_expected_loss, 2),
            "Total Mitigation/Offsets": round(total_mitigation, 2),
            "Final Back Pay": round(total_back_pay, 2)
        }

    def calculate_front_pay(self, annual_loss_stream, expected_duration_years, 
                               prob_liability, prob_remedy, discount_rate, future_mitigation_annual):
        
        # Mid-Range: 1 Year Discounted EV
        mid_ev = 0.0
        net_loss_1 = annual_loss_stream - future_mitigation_annual
        mid_ev += max(0.0, net_loss_1 / ((1 + discount_rate) ** 1))
        mid_ev = prob_liability * prob_remedy * mid_ev
        
        # Best Day: 3 Years Raw (No discounting/prob multipliers applied to max exposure)
        best_day = max(0.0, (annual_loss_stream - future_mitigation_annual) * 3.0)
        
        # Conservative: 0 Years
        cons_day = 0.0
            
        return {"Conservative": cons_day, "Mid-Range": round(mid_ev, 2), "Best Day": round(best_day, 2)}

    def calculate_compensatory(self, uncapped_pecuniary, consolidated_non_pecuniary, 
                               severity_multiplier, punitive_requested, is_adea_epa_willful, back_pay_amount):
        
        punitive_awarded = 0.0 if self.is_government_employer else punitive_requested
        adjusted_non_pecuniary = consolidated_non_pecuniary * (1.0 + severity_multiplier)
        liquidated_damages = back_pay_amount if is_adea_epa_willful else 0.0
        
        # Calculate Tiers
        # Best Day = Max Allowed under Cap + Punitive
        best_capped = min(adjusted_non_pecuniary + punitive_awarded, self.statutory_cap)
        # Mid-Range = Adjusted Base (No Punitive assumed in mid-range unless requested) + 50% Punitive
        mid_capped = min(adjusted_non_pecuniary + (punitive_awarded * 0.5), self.statutory_cap)
        # Conservative = 15% of Adjusted Base, 0 Punitive
        cons_capped = min(adjusted_non_pecuniary * 0.15, self.statutory_cap)
        
        # Anti-Double Recovery logic across all tiers
        if is_adea_epa_willful:
            best_final = max(liquidated_damages, best_capped)
            mid_final = max(liquidated_damages, mid_capped)
            cons_final = max(liquidated_damages * 0.15, cons_capped)
            remedy_type = "ADEA Liquidated Damages vs Title VII Capped (Higher applied)"
        else:
            best_final = best_capped
            mid_final = mid_capped
            cons_final = cons_capped
            remedy_type = "Title VII / ADA Capped Award"
            
        return {
            "Uncapped Out-of-Pocket": round(uncapped_pecuniary, 2),
            "Conservative": round(cons_final, 2),
            "Mid-Range": round(mid_final, 2),
            "Best Day": round(best_final, 2),
            "Remedy Applied": remedy_type
        }

    def estimate_attorney_fees(self, active_phases: list) -> dict:
        phase_matrix = {
            "Complaint Filed/Served": {"low": 5000, "high": 10000},
            "Discovery & Document Production": {"low": 10000, "high": 15000},
            "Depositions (Parties & Witnesses)": {"low": 10000, "high": 20000},
            "Summary Judgment Briefing": {"low": 10000, "high": 15000},
            "Pretrial Conference & Motions": {"low": 10000, "high": 15000},
            "Trial Preparation & Execution": {"low": 20000, "high": 30000}
        }
        low_est, high_est = 0, 0
        for phase in active_phases:
            if phase in phase_matrix:
                low_est += phase_matrix[phase]["low"]
                high_est += phase_matrix[phase]["high"]
        return {"Low": low_est, "High": high_est, "Average": (low_est + high_est) / 2}

# --- STREAMLIT USER INTERFACE ---
st.set_page_config(page_title="Title VII Damages Model v1.2.1", layout="wide")

# Navigation Tabs
tab_intro, tab_setup, tab_backpay, tab_frontpay, tab_comp, tab_fees, tab_report = st.tabs([
    "🏠 Homepage & Guide", "⚙️ Case Setup", "💵 Back Pay", "📈 Front Pay", 
    "⚖️ Compensatory & Punitive", "🏛️ Attorney Fees", "📊 Summary Report"
])

# --- TAB 1: HOMEPAGE ---
with tab_intro:
    st.title("Employment Litigation Damages Model & Calculator")
    st.markdown("""
    Welcome to the **Mississippi Attorney General Civil Litigation Damages Model**. This analytical framework is designed to evaluate economic exposure and defense settlement value across federal employment litigation statutes, including **Title VII, the ADA, the ADEA, the Equal Pay Act, and Section 1981**.

    ### Key Methodology & Features
    * **Strict Anti-Double Recovery:** Automatically gates stacked statutory remedies (e.g., ADEA liquidated damages vs. Title VII capped emotional distress) to prevent impermissible double recovery.
    * **Precision Wage Modeling:** Evaluates salaried compensation alongside fractional hourly baselines, PTO adjustments, and dual-rate wage deficits.
    * **Universal Mitigation Tracking:** Unrestricted data tables to log job replacements, interim earnings, or subsequent pay raises.
    * **Three-Tier Scenario Evaluation:** Dynamically brackets exposure into **Best Day** (Maximum Plaintiff Recovery), **Mid-Range** (Average Expected Outcome), and **Conservative** (Minimal Exposure) benchmarks.
    * **Risk-Adjusted Defense Settlement Authority:** Scales total predicted exposure by the plaintiff's direct probability of prevailing at trial.
    """)

# --- TAB 2: CASE SETUP ---
with tab_setup:
    st.header("Case Configuration & Statutory Profile")
    col1, col2, col3 = st.columns(3)
    with col1:
        plaintiff_name = st.text_input("Plaintiff Name", value="Jane Doe")
        defendant_name = st.text_input("Defendant / Employer Name", value="Mississippi State Agency")
    with col2:
        emp_size = st.number_input("Number of Employees", min_value=1, value=600)
        is_gov = st.checkbox("State Agency / Government Employer (Immune to Punitive Damages)", value=True)
    with col3:
        win_prob = st.slider("Plaintiff Chance of Success at Trial (%)", min_value=5, max_value=95, value=50, step=5) / 100.0

    st.subheader("Governing Statutes & Adverse Action")
    col_stat1, col_stat2 = st.columns(2)
    with col_stat1:
        statute = st.selectbox("Primary Employment Statute", ["Title VII", "ADA", "ADEA", "Equal Pay Act", "Section 1981"])
        is_1981 = st.checkbox("Individual Capacity Defendants under Section 1981 (Uncapped Compensatory)", value=(statute == "Section 1981"))
        is_willful = st.checkbox("Willful Violation Claimed (ADEA / Equal Pay Act Liquidated Damages)", value=(statute in ["ADEA", "Equal Pay Act"]))
    with col_stat2:
        adverse_action = st.selectbox("Adverse Employment Action at Issue", [
            "Termination / Discharge", "Constructive Discharge", "Failure to Promote/Hire", 
            "Demotion with Pay Cut", "Compensation/Hours Reduction"
        ])

# Initialize Core Model
model = TitleVIIDamagesCalculator(employer_size=emp_size, is_government_employer=is_gov, is_section_1981=is_1981)

# --- TAB 3: BACK PAY ---
with tab_backpay:
    st.header("Back Pay Calculation")
    st.caption("Back pay compensates for wages lost from the effective date of the adverse action through the date of evaluation, settlement, or trial.")
    
    col_date1, col_date2, col_date3 = st.columns(3)
    with col_date1:
        start_date = st.date_input("Adverse Action Start Date", datetime.date(2025, 1, 1))
    with col_date2:
        end_date_type = st.selectbox("Select Ending Date Profile", ["Calculation Date (Present)", "Mediation / Settlement Date", "Scheduled Trial Date", "Other Custom Date"])
    with col_date3:
        if end_date_type == "Other Custom Date":
            custom_desc = st.text_input("Describe Custom Ending Date", value="Reinstatement Offer Date")
        end_date = st.date_input("Target Ending Date", datetime.date.today() if end_date_type == "Calculation Date (Present)" else datetime.date(2026, 12, 1))

    st.divider()
    st.subheader("Baseline Compensation")
    is_hourly = st.checkbox("Hourly Employee Baseline", value=False)
    
    col_comp1, col_comp2, col_comp3 = st.columns(3)
    if is_hourly:
        with col_comp1:
            hr_rate = st.number_input("Hourly Wage ($/hr)", value=30.0, step=1.0)
        with col_comp2:
            wk_hours = st.number_input("Average Weekly Hours", value=40.0, step=1.0)
        with col_comp3:
            unpaid_leave = st.number_input("Annual Unpaid Leave / PTO Hours", value=0.0, step=8.0)
        base_salary = 0.0
        benefits = st.number_input("Annual Value of Benefits ($)", value=12000.0, step=500.0)
    else:
        with col_comp1:
            base_salary = st.number_input("Former / Baseline Annual Salary ($)", value=80000.0, step=1000.0)
        with col_comp2:
            benefits = st.number_input("Annual Value of Benefits ($)", value=15000.0, step=1000.0)
        hr_rate, wk_hours, unpaid_leave = 0.0, 0.0, 0.0

    base_annual = model.calculate_base_annual_compensation(is_hourly, hr_rate, wk_hours, unpaid_leave, base_salary, benefits)
    st.info(f"**Calculated Annual Baseline Compensation:** ${base_annual:,.2f}")

    st.divider()
    if adverse_action in ["Failure to Promote/Hire", "Demotion with Pay Cut", "Compensation/Hours Reduction"]:
        st.subheader("Dual-Rate Pay Deficit Tracking")
        st.caption("For non-separation actions, input the rate the plaintiff *should* have earned versus what they *actually* earned.")
        col_dif1, col_dif2 = st.columns(2)
        with col_dif1:
            sought_rate = st.number_input("Sought / Promoted Annual Rate ($)", value=base_annual + 15000.0, step=1000.0)
        with col_dif2:
            actual_ongoing = st.number_input("Actual Ongoing Annual Rate ($)", value=base_annual, step=1000.0)
    else:
        sought_rate, actual_ongoing = base_annual, 0.0

    st.subheader("Mitigation & Pay Change Tracker")
    st.caption("For terminations: Enter replacement jobs (higher-paying jobs are automatically excluded). For demotions/promotions: Enter the dates and amounts of any subsequent pay raises with this employer.")
    if "mit_df" not in st.session_state:
        st.session_state.mit_df = pd.DataFrame(columns=["Description", "Start Date", "End Date", "Annual Earnings ($)"])
    
    # Updated st.data_editor with column_config to enforce calendar widgets for dates
    mitigation_df = st.data_editor(
        st.session_state.mit_df, 
        num_rows="dynamic", 
        use_container_width=True,
        column_config={
            "Start Date": st.column_config.DateColumn("Start Date"),
            "End Date": st.column_config.DateColumn("End Date"),
            "Annual Earnings ($)": st.column_config.NumberColumn("Annual Earnings ($)", min_value=0.0, format="$%.2f")
        }
    )
    
    actual_paid = st.number_input("Additional Severance or Lump Sum Offsets Paid by Defendant ($)", value=0.0, step=500.0)

    bp_results = model.calculate_back_pay(start_date, end_date, base_annual, adverse_action, actual_ongoing, sought_rate, mitigation_df, actual_paid)
    st.write(f"**Net Back Pay Deficit:** ${bp_results['Final Back Pay']:,.2f}")

# --- TAB 4: FRONT PAY ---
with tab_frontpay:
    st.header("Front Pay Expected Value")
    st.caption("Front pay is an equitable remedy awarded from the date of judgment forward when workplace reinstatement is unfeasible.")
    col_fp1, col_fp2 = st.columns(2)
    with col_fp1:
        fp_prob_rem = st.slider("Judicial Probability of Granting Front Pay (%)", 0, 100, 50) / 100.0
    with col_fp2:
        fp_discount = st.number_input("Discount Rate (Safe Treasury Yield)", value=0.03, step=0.005)
        fp_mitigation = st.number_input("Expected Future Annual Mitigation ($)", value=45000.0 if adverse_action in ["Termination / Discharge", "Constructive Discharge"] else actual_ongoing, step=1000.0)

    annual_loss_stream = (sought_rate - actual_ongoing) if adverse_action in ["Failure to Promote/Hire", "Demotion with Pay Cut"] else base_annual
    fp_results = model.calculate_front_pay(annual_loss_stream, 1.0, 1.0, fp_prob_rem, fp_discount, fp_mitigation)

# --- TAB 5: COMPENSATORY & PUNITIVE ---
with tab_comp:
    st.header("Compensatory & Punitive Damages")
    st.caption("Compensatory damages cover non-economic harms and out-of-pocket pecuniary losses. Punitive damages punish malicious or recklessly indifferent conduct.")
    
    col_c1, col_c2 = st.columns(2)
    with col_c1:
        st.subheader("Uncapped Pecuniary Losses")
        med_bills = st.number_input("Medical & Psychiatric Therapy Bills ($)", value=0.0, step=500.0)
        job_search = st.number_input("Job Search & Out-of-Pocket Costs ($)", value=0.0, step=100.0)
        other_pec = st.number_input("Other Out-of-Pocket Pecuniary Expenses ($)", value=0.0, step=100.0)
        total_uncapped_pec = med_bills + job_search + other_pec
        
    with col_c2:
        st.subheader("Consolidated Non-Pecuniary Harm")
        non_pec_base = st.number_input("Consolidated Emotional Distress / Humiliation / Reputational Harm ($)", value=100000.0, step=5000.0)
        
        st.markdown("**Select Severity Multipliers:**")
        sev_diag = st.checkbox("Clinical Medical/Psychiatric Diagnosis Present (+25%)")
        sev_treat = st.checkbox("Professional Counseling / Therapy Sought (+15%)")
        sev_expert = st.checkbox("Expert Psychiatric Witness Retained for Trial (+20%)")
        sev_no_counsel = st.checkbox("No Medical or Counseling Records Available (-30%)")
        
        sev_mult = (0.25 if sev_diag else 0.0) + (0.15 if sev_treat else 0.0) + (0.20 if sev_expert else 0.0) - (0.30 if sev_no_counsel else 0.0)
        
    st.divider()
    st.subheader("Punitive Damages Evaluation")
    req_punitive = st.radio("Are Punitive Damages Explicitly Requested in Complaint?", ["Yes", "No"], index=0)
    pun_amt = st.number_input("Requested Punitive Amount ($)", value=250000.0 if req_punitive == "Yes" else 0.0, step=10000.0) if req_punitive == "Yes" else 0.0
    
    comp_results = model.calculate_compensatory(total_uncapped_pec, non_pec_base, sev_mult, pun_amt, is_willful, bp_results["Final Back Pay"])

# --- TAB 6: ATTORNEY FEES ---
with tab_fees:
    st.header("Statutory Attorney Fee Shifting")
    st.caption("Prevailing plaintiffs recover reasonable attorney fees calculated under the lodestar method (hours multiplied by reasonable hourly rate).")
    
    phases = [
        "Complaint Filed/Served", "Discovery & Document Production", 
        "Depositions (Parties & Witnesses)", "Summary Judgment Briefing", 
        "Pretrial Conference & Motions", "Trial Preparation & Execution"
    ]
    selected_phases = []
    st.markdown("**Select Completed or Projected Litigation Phases:**")
    col_f1, col_f2 = st.columns(2)
    for i, p in enumerate(phases):
        with (col_f1 if i % 2 == 0 else col_f2):
            if st.checkbox(p, value=(i < 3)):
                selected_phases.append(p)
                
    fee_results = model.estimate_attorney_fees(selected_phases)

# --- TAB 7: SUMMARY REPORT ---
with tab_report:
    st.header("Executive Exposure Dashboard & Summary Report")
    
    # Compile 3-Tier Summary Matrix
    summary_data = {
        "Damage Category": [
            "Back Pay", 
            "Front Pay", 
            "Compensatory (Uncapped)", 
            "Compensatory/Liquidated (Capped)", 
            "Attorney Fees", 
            "TOTAL EXPOSURE"
        ],
        "Conservative": [
            bp_results["Final Back Pay"],
            fp_results["Conservative"],
            comp_results["Uncapped Out-of-Pocket"],
            comp_results["Conservative"],
            fee_results["Low"],
            bp_results["Final Back Pay"] + fp_results["Conservative"] + comp_results["Uncapped Out-of-Pocket"] + comp_results["Conservative"] + fee_results["Low"]
        ],
        "Mid-Range": [
            bp_results["Final Back Pay"],
            fp_results["Mid-Range"],
            comp_results["Uncapped Out-of-Pocket"],
            comp_results["Mid-Range"],
            fee_results["Average"],
            bp_results["Final Back Pay"] + fp_results["Mid-Range"] + comp_results["Uncapped Out-of-Pocket"] + comp_results["Mid-Range"] + fee_results["Average"]
        ],
        "Best Day": [
            bp_results["Final Back Pay"],
            fp_results["Best Day"],
            comp_results["Uncapped Out-of-Pocket"],
            comp_results["Best Day"],
            fee_results["High"],
            bp_results["Final Back Pay"] + fp_results["Best Day"] + comp_results["Uncapped Out-of-Pocket"] + comp_results["Best Day"] + fee_results["High"]
        ]
    }
    
    summary_df = pd.DataFrame(summary_data)
    
    # Calculate Settlement Value based on Mid-Range * Win Prob
    mid_total = summary_df.loc[summary_df["Damage Category"] == "TOTAL EXPOSURE", "Mid-Range"].values[0]
    defense_settlement_value = mid_total * win_prob
    
    st.metric("Risk-Adjusted Defense Settlement Value", f"${defense_settlement_value:,.2f}", help=f"Mid-Range Exposure adjusted by {win_prob*100:.0f}% Plaintiff Win Probability")
    
    st.subheader("Comprehensive 3-Tier Damage Estimation Table")
    st.dataframe(summary_df.style.format({
        "Conservative": "${:,.2f}", 
        "Mid-Range": "${:,.2f}", 
        "Best Day": "${:,.2f}"
    }), use_container_width=True, hide_index=True)
    
    st.divider()
    st.subheader("Confidential Settlement Memo Narrative Script")
    st.caption("Copy and paste this formally formatted assessment directly into mediation statements or confidential client evaluation memos.")
    
    # Construct Narrative Paragraph
    action_desc = adverse_action.lower()
    script_text = (
        f"In this employment litigation matter, Plaintiff {plaintiff_name} alleges claims under {statute} against Defendant {defendant_name} arising from a disputed {action_desc} effective {start_date.strftime('%B %d, %Y')}. "
        f"To calculate economic exposure, the defense evaluates lost wages over a fractional period of {bp_results['Duration (Years)']:.2f} years extending through the projected {end_date_type.lower()}, establishing an annualized baseline compensation rate of ${base_annual:,.2f}. "
        f"Accounting for applicable interim earnings and wage mitigation offsets totaling ${bp_results['Total Mitigation/Offsets']:,.2f}, net back pay exposure is objectively calculated at ${bp_results['Final Back Pay']:,.2f}. "
    )
    
    if is_willful:
        script_text += f"Because Plaintiff asserts a willful violation under the {statute}, exposure includes potential statutory liquidated damages effectively doubling the net back pay award to an aggregate wage loss claim of ${(bp_results['Final Back Pay']*2):,.2f}, which legally supersedes and locks out standard Title VII non-economic compensatory caps. "
    else:
        script_text += f"In addition to wage loss, Plaintiff seeks non-pecuniary compensatory damages for emotional distress and reputational harm, which are strictly constrained by federal statutory caps of ${model.statutory_cap:,.2f} based on organizational headcount, alongside out-of-pocket pecuniary expenses of ${total_uncapped_pec:,.2f}. "
        
    if is_gov:
        script_text += f"Furthermore, because Defendant {defendant_name} operates as a governmental state agency, sovereign immunity strictly bars the recovery of punitive damages as a matter of law. "
        
    script_text += (
        f"When factoring projected statutory attorney fee shifting under the lodestar method averaging ${fee_results['Average']:,.2f} alongside equitable front pay probabilities, total mid-range trial exposure is estimated at ${mid_total:,.2f}. "
        f"Applying a rigorous defense risk-adjustment reflecting a {win_prob*100:.0f}% direct liability probability of adverse judicial finding, realistic defense settlement authority is objectively established at ${defense_settlement_value:,.2f}."
    )
    
    st.text_area("Generated Mediation & Evaluation Script", value=script_text, height=220)
    
    st.download_button(
        label="📄 Download 1-Page Summary Report (TXT)",
        data=f"EXECUTIVE DAMAGES SUMMARY\nCase: {plaintiff_name} v. {defendant_name}\nDate: {datetime.date.today()}\n\n"
             f"--- THREE-TIER EXPOSURE ---\n"
             f"Best Day Exposure: ${summary_data['Best Day'][-1]:,.2f}\n"
             f"Mid-Range Exposure: ${mid_total:,.2f}\n"
             f"Conservative Exposure: ${summary_data['Conservative'][-1]:,.2f}\n\n"
             f"Defense Settlement Value: ${defense_settlement_value:,.2f}\n\n"
             f"--- NARRATIVE SCRIPT ---\n{script_text}",
        file_name=f"Damages_Report_{plaintiff_name.replace(' ', '_')}.txt",
        mime="text/plain"
    )
