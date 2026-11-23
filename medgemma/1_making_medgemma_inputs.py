"""
This file I need to grab the data per hadm_id for each subject

Output: 
    [ [pid1hadm1, pid1hadm2, pid1hadm3], [pid2hadm1, pid2hadm2] ]

    Then these outputs we can pass into mcspace which will show the outputs
"""

import os
import sys

import duckdb

DB = os.environ["MIMIC_DB_PATH"]  # local MIMIC DuckDB file, kept out of the repo
con = duckdb.connect(DB, read_only=True)


def latest_omr(subject_id, name, admittime):
    """OMR reading on or before admission, None is never measured"""
    row = con.execute(f"""
        SELECT o.value FROM omr o JOIN omr_measures m USING (measure_id)
        WHERE o.subject_id = {subject_id} AND m.name = '{name}' AND o.chartdate <= '{admittime}'::DATE
        ORDER BY o.chartdate DESC, o.seq_num DESC LIMIT 1""").fetchone()
    return row[0] if row else None


def last_lab(subject_id, label, admittime, dischtime):
    """Lab reading on or before admission, None if never recorded"""
    row = con.execute(f"""
        SELECT r.valuenum FROM lab_results r JOIN lab_items i USING (itemid)
        WHERE r.subject_id = {subject_id} AND i.label = '{label}' AND r.charttime BETWEEN '{admittime}' 
        AND '{dischtime}' ORDER BY r.charttime DESC LIMIT 1""").fetchone()
    return row[0] if row else None


def get_stays(subject_ids):
    all_patients = []
    for subject_id in subject_ids:
        sex, anchor_age, anchor_year = con.execute(
            f"SELECT gender, anchor_age, anchor_year FROM patients WHERE subject_id = {subject_id}").fetchone()

        admissions = con.execute(f"""
            SELECT a.hadm_id, a.admittime, a.dischtime, t.name
            FROM admissions a JOIN admission_types t USING (admission_type_id)
            WHERE a.subject_id = {subject_id} ORDER BY a.admittime""").fetchall()

        patient = []
        prev_dischtime = None
        for hadm_id, admittime, dischtime, admission_type in admissions:
            age = anchor_age + (admittime.year - anchor_year) # age from anchor data
            los_days = (dischtime - admittime).total_seconds() / 86400
            days_since_prev = (admittime - prev_dischtime).days if prev_dischtime else None

            diagnoses = [r[0] for r in con.execute(f"""
                SELECT t.long_title FROM diagnoses_icd d JOIN d_icd_diagnoses t USING (icd_code, icd_version)
                WHERE d.hadm_id = {hadm_id} ORDER BY d.seq_num""").fetchall()]
            procedures = [r[0] for r in con.execute(f"""
                SELECT t.long_title FROM procedures_icd p JOIN d_icd_procedures t USING (icd_code, icd_version)
                WHERE p.hadm_id = {hadm_id} ORDER BY p.seq_num""").fetchall()]

            bmi = latest_omr(subject_id, "BMI", admittime)
            sbp = latest_omr(subject_id, "Systolic BP", admittime)
            dbp = latest_omr(subject_id, "Diastolic BP", admittime)
            weight = latest_omr(subject_id, "Weight", admittime)

            creatinine = last_lab(subject_id, "Creatinine", admittime, dischtime)
            hba1c = last_lab(subject_id, "% Hemoglobin A1c", admittime, dischtime)
            total_chol = last_lab(subject_id, "Cholesterol, Total", admittime, dischtime)
            ldl = last_lab(subject_id, "Cholesterol, LDL, Calculated", admittime, dischtime)
            triglycerides = last_lab(subject_id, "Triglycerides", admittime, dischtime)
            sodium = last_lab(subject_id, "Sodium", admittime, dischtime)
            potassium = last_lab(subject_id, "Potassium", admittime, dischtime)
            crp = last_lab(subject_id, "C-Reactive Protein", admittime, dischtime)

            drugs = [r[0] for r in con.execute(f"""
                SELECT d.drug FROM prescriptions r JOIN drugs d USING (drug_id)
                WHERE r.hadm_id = {hadm_id} GROUP BY d.drug ORDER BY min(r.starttime)""").fetchall()]

            text = f"""{age}{sex}, {admission_type} admission, stayed {los_days:.1f} days, {days_since_prev} days since previous stay
Diagnoses: {"; ".join(diagnoses)}
Procedures: {"; ".join(procedures)}
BMI: {bmi} 
BP: {sbp}/{dbp} 
Weight: {weight} lbs
"""
# Labs: creatinine {creatinine}, HbA1c {hba1c}, total cholesterol {total_chol}, LDL {ldl}, triglycerides {triglycerides}, sodium {sodium}, potassium {potassium}, CRP {crp}
# Drugs: {", ".join(drugs)}
# """ # commented out for now to see if the labs and drugs supply useful information for number of tokens they take up

            patient.append(text)
            prev_dischtime = dischtime
        all_patients.append(patient)
    return all_patients

if __name__ == "__main__":
    stays = get_stays(sys.argv[1:])  # subject_ids passed on the command line
    print(stays[0][1])
