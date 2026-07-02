import streamlit as st
import datetime
import pandas as pd

# --- CORE ECONOMIC LOGIC ---
class TitleVIIDamagesCalculator:
    def __init__(self, employer_size: int, is_government_employer: bool):
        self.employer_size = employer_size
        self.is_government_employer = is_government_employer
        self.statutory_cap = self._get_statutory_cap(employer_size)

    def _get_statutory_cap(self, size: int) -> float:
        if size <= 100: return 50000.0
        elif size <= 200: return 100000.0
        elif size <= 500: return 200000.0
        else: return 300000.0

    def _calculate_yearfrac(self, start_date, end_date) -> float:
        if isinstance(start_date, str):
            start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        if isinstance(end_date, str):
            end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
        return abs((end_date - start_date).days) / 365.25

    def calculate_back_pay(self, start_date, end_date, former_salary, former_benefits, mitigation_jobs, actual_earnings_paid):
        duration = self._calculate_yearfrac(start_date, end_date)
        annual_base_pay = former_salary + former_benefits
        total_expected_earnings = duration * annual_base_pay
        
        total_interim_earnings = 0.0
        
        for _, job in mitigation_jobs.iterrows():
            # Skip empty rows from the data editor
            if pd.isnull(job['Start Date']) or pd.isnull(job['End Date']):
                continue
                
            job_annual = job['Annual Salary'] + job['Annual Benefits']
            
            # Logic Gate: Eliminate higher-paying mitigation jobs
            if job_annual < annual_base_pay:
                job_duration = self._calculate_yearfrac(job['Start Date'], job['End Date'])
                total_interim_earnings += (job_duration * job_annual)
                
        total_mitigation = total_interim_earnings + actual_earnings_paid
        total_back_pay = max(0.0, total_expected_earnings - total_mitigation)
        
        return {
            "Duration (Years)": round(duration, 4),
            "Total Expected Earnings": round(total_expected_earnings, 2),
            "Total Mitigation Deducted": round(total_mitigation, 2),
            "Final Back Pay": round(total_back_pay, 2)
        }

    def calculate_front_pay_ev(self, annual_salary, annual_benefits, expected_duration_years, 
                               prob_liability, prob_remedy, discount_rate, future_mitigation_annual):
        ev = 0.0
        but_for_annual = annual_salary + annual_benefits
        
        for t in range(1, int(expected_duration_years) + 1):
            net_loss_t = but_for_annual - future_mitigation_annual
            discounted_t = net_loss_t / ((1 + discount_rate) ** t)
            ev += max(0.0, discounted_t)
            
        total_ev = prob_liability * prob_remedy * ev
        return round(total_ev, 2)

    def calculate_compensatory(self, medical_bills, job_search_costs, emotional_distress, 
                               loss_of_enjoyment, injury_reputation, punitive_requested):
        uncapped_pecuniary = medical_bills + job_search_costs
        punitive_awarded = 0.0 if self.is_government_employer else punitive_requested
            
        requested_non_pecuniary = emotional_distress + loss_of_enjoyment + injury_reputation + punitive_awarded
        allowed_non_pecuniary = min(requested_non_pecuniary, self.statutory_cap)
        
        return {
            "Uncapped Out-of-Pocket": round(uncapped_pecuniary, 2),
            "Capped Emotional/Punitive": round(allowed_non_pecuniary, 2),
            "Total Compensatory Award": round(uncapped_pecuniary + allowed_non_pecuniary, 2)
        }

    def estimate_attorney_fees(self, active_phases: list) -> dict:
        phase_matrix = {
            "Complaint Filed/Served": {"low": 5000, "high": 10000},
            "Discovery/Documents": {"low": 10000, "high": 10000},
            "Depositions taken": {"low": 10000, "high": 20000},
            "Summary Judgment briefed": {"low": 10000, "high": 15000},
            "Trial prep": {"low": 10000, "high": 15000},
            "Trial": {"low": 20000, "high": 30000}
        }
        
        low_est, high_est = 0, 0
        for phase in active_phases:
            low_est += phase_matrix[phase]["low"]
            high_est += phase_matrix[phase]["high"]
                
        return {"Low Estimate": low_est, "High Estimate": high_est, "Average": (low_est + high_est)/2}

# --- STREAMLIT UI ---
st.set_page_config(page_title="Employment Litigation Damages Estimator", layout="wide")

st.title("Title VII Damages Estimator")
st.markdown("Automated calculation model for Back Pay, Front Pay, Compensatory Damages, and Attorney Fees.")

# Sidebar Configuration
st.sidebar.header("Defendant Profile")
is_gov = st.sidebar.checkbox("State Agency / Government Employer", value=True)
emp_size = st.sidebar.number_input("Number of Employees", min_value=1, value=600)

# Initialize Model
model = TitleVIIDamagesCalculator(employer_size=emp_size, is_government_employer=is_gov)

st.sidebar.markdown("---")
st.sidebar.write(f"**Statutory Cap Applied:** ${model.statutory_cap:,.2f}")
if is_gov:
    st.sidebar.warning("Government Immunity Active: Punitive Damages = $0")

# Tabs for distinct damage categories
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Back Pay", "Front Pay", "Compensatory", "Attorney Fees", "Summary Report"])

with tab1:
    st.header("Back Pay Calculation")
    col1, col2 = st.columns(2)
    
    with col1:
        start_date = st.date_input("Adverse Action Date (Start)", datetime.date(2025, 1, 1))
        end_date = st.date_input("Calculation Date (End)", datetime.date.today())
    with col2:
        former_salary = st.number_input("Former Annual Salary ($)", value=80000.0, step=1000.0)
        former_benefits = st.number_input("Former Annual Benefits ($)", value=15000.0, step=1000.0)
        actual_paid = st.number_input("Actual Earnings/Severance Paid ($)", value=0.0, step=500.0)

    st.subheader("Interim Earnings (Mitigation)")
    st.markdown("Enter replacement jobs below. The model will automatically eliminate jobs paying more than the baseline[cite: 136, 137].")
    
    # Dynamic table for mitigation jobs
    if "mitigation_df" not in st.session_state:
        st.session_state.mitigation_df = pd.DataFrame(
            columns=["Start Date", "End Date", "Annual Salary", "Annual Benefits"]
        )
        
    edited_mitigation = st.data_editor(
        st.session_state.mitigation_df, 
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "Start Date": st.column_config.DateColumn("Start Date"),
            "End Date": st.column_config.DateColumn("End Date"),
            "Annual Salary": st.column_config.NumberColumn("Annual Salary ($)", min_value=0),
            "Annual Benefits": st.column_config.NumberColumn("Annual Benefits ($)", min_value=0)
        }
    )

    back_pay_results = model.calculate_back_pay(
        start_date, end_date, former_salary, former_benefits, edited_mitigation, actual_paid
    )
    
    st.write("**Back Pay Results:**")
    st.json(back_pay_results)

with tab2:
    st.header("Front Pay Expected Value (EV)")
    col1, col2 = st.columns(2)
    
    with col1:
        duration = st.number_input("Expected Duration (Years)", value=3.0, step=1.0)
        prob_liab = st.slider("Probability of Liability (Winning)", 0.0, 1.0, 0.75)
        prob_rem = st.slider("Probability of Front Pay Granted", 0.0, 1.0, 0.50)
    with col2:
        discount = st.number_input("Discount Rate (e.g., 0.03 for 3%)", value=0.03, step=0.01)
        future_mitigation = st.number_input("Expected Future Mitigation (Annual $)", value=45000.0, step=1000.0)
        
    front_pay_result = model.calculate_front_pay_ev(
        former_salary, former_benefits, duration, prob_liab, prob_rem, discount, future_mitigation
    )
    st.metric("Estimated Front Pay (EV)", f"${front_pay_result:,.2f}")

with tab3:
    st.header("Compensatory & Punitive Damages")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Uncapped Pecuniary")
        med_bills = st.number_input("Medical / Therapy Bills ($)", value=0.0, step=500.0)
        job_search = st.number_input("Job Search Costs ($)", value=0.0, step=100.0)
        
    with col2:
        st.subheader("Capped Non-Pecuniary")
        em_distress = st.number_input("Emotional Distress Claim ($)", value=100000.0, step=5000.0)
        loss_enjoy = st.number_input("Loss of Enjoyment of Life ($)", value=25000.0, step=5000.0)
        rep_harm = st.number_input("Reputational Harm ($)", value=0.0, step=5000.0)
        punitive = st.number_input("Punitive Damages Requested ($)", value=250000.0, step=10000.0)
        
    comp_results = model.calculate_compensatory(
        med_bills, job_search, em_distress, loss_enjoy, rep_harm, punitive
    )
    
    st.write("**Compensatory Results:**")
    st.json(comp_results)

with tab4:
    st.header("Attorney Fees Estimation")
    st.markdown("Select expected or completed litigation phases[cite: 208, 209].")
    
    phases = [
        "Complaint Filed/Served", "Discovery/Documents", "Depositions taken", 
        "Summary Judgment briefed", "Trial prep", "Trial"
    ]
    
    selected_phases = []
    for phase in phases:
        if st.checkbox(phase, value=True if phase == "Complaint Filed/Served" else False):
            selected_phases.append(phase)
            
    fee_results = model.estimate_attorney_fees(selected_phases)
    st.write("**Fee Results:**")
    st.json(fee_results)

with tab5:
    st.header("Total Exposure Summary")
    
    total_exposure = (
        back_pay_results["Final Back Pay"] + 
        front_pay_result + 
        comp_results["Total Compensatory Award"] + 
        fee_results["Average"]
    )
    
    st.metric("Estimated Total Case Value", f"${total_exposure:,.2f}")
    
    summary_df = pd.DataFrame({
        "Damage Category": ["Back Pay", "Front Pay (EV)", "Compensatory (Uncapped)", "Compensatory (Capped)", "Attorney Fees (Avg)"],
        "Estimated Amount ($)": [
            back_pay_results["Final Back Pay"],
            front_pay_result,
            comp_results["Uncapped Out-of-Pocket"],
            comp_results["Capped Emotional/Punitive"],
            fee_results["Average"]
        ]
    })
    
    st.dataframe(summary_df.style.format({"Estimated Amount ($)": "{:,.2f}"}), use_container_width=True)