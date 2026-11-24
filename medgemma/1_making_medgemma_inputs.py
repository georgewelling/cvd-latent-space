import json
import re
import duckdb

from collections import Counter, defaultdict
from transformers import AutoProcessor

db_path = "C:/mimic/my_db/db.duckdb"
out_path = "C:/mimic/derived/with_splits/stays.json"
model_path = "C:/mimic/models/medgemma-1.5-4b"

# following variables are to ensure the prompt length is relatively constant
n_diagnoses, diagnosis_tokens = 8, 70
n_procedures, procedure_tokens = 2, 25
n_classes = 10

# to hide disease related words within the dx stays (pre stays wont have these, stepping forward might never reach them?)
disease_related = re.compile(
    r"atrial fibrillation|atrial flutter|myocardial infarction|subendocardial infarction|\bN?STEMI\b|"
    r"heart failure|cerebral infarction|cerebral artery|cerebral arteries|precerebral|cerebral thrombosis|"
    r"cerebral embolism|\bstroke\b",
    re.IGNORECASE)

admission_types = {
    "AMBULATORY OBSERVATION": "an ambulatory observation",
    "DIRECT EMER.": "a direct emergency",
    "DIRECT OBSERVATION": "a direct observation",
    "ELECTIVE": "an elective",
    "EU OBSERVATION": "an emergency unit observation",
    "EW EMER.": "an emergency ward",
    "OBSERVATION ADMIT": "an observation",
    "SURGICAL SAME DAY ADMISSION": "a same-day surgical",
    "URGENT": "an urgent",
}

lab_tests = [  # (label in lab_items, name in the text, unit)
    ("Creatinine", "creatinine", "mg/dL"),
    ("% Hemoglobin A1c", "HbA1c", "%"),
    ("Cholesterol, Total", "total cholesterol", "mg/dL"),
    ("Cholesterol, LDL, Calculated", "LDL", "mg/dL"),
    ("Triglycerides", "triglycerides", "mg/dL"),
    ("Sodium", "sodium", "mEq/L"),
    ("Potassium", "potassium", "mEq/L"),
    ("C-Reactive Protein", "CRP", "mg/L"),
]

drug_classes = {
    "ace_arb": "ACE inhibitor or ARB",
    "antiarrhythmic": "antiarrhythmic",
    "anticoagulant": "anticoagulant",
    "antiplatelet": "antiplatelet",
    "beta_blocker": "beta blocker",
    "ccb_rate": "rate-limiting calcium channel blocker",
    "insulin": "insulin",
    "loop_diuretic": "loop diuretic",
    "statin": "statin",
    "steroid": "steroid",
    "thyroid": "thyroid medicine",
}

con = duckdb.connect(db_path, read_only=True)
tokenizer = AutoProcessor.from_pretrained(model_path).tokenizer # counts how many tokens


def query(sql):
    return con.execute(sql).fetchall()


def load_tables():
    # patients with exactly one of AF / MI / HF / stroke, and the time of their first stay with it
    con.execute("""
        CREATE TEMP TABLE cohort AS
        WITH dx AS (
            SELECT DISTINCT hadm_id,
                CASE
                WHEN (icd_version = 9 AND icd_code = '42731') OR (icd_version = 10 AND icd_code LIKE 'I48%') THEN 'AF'
                WHEN (icd_version = 9 AND icd_code LIKE '410%') OR (icd_version = 10 AND (icd_code LIKE 'I21%' OR icd_code LIKE 'I22%')) THEN 'MI'
                WHEN (icd_version = 9 AND icd_code LIKE '428%') OR (icd_version = 10 AND icd_code LIKE 'I50%') THEN 'HF'
                WHEN (icd_version = 9 AND (icd_code LIKE '433%' OR icd_code LIKE '434%')) OR (icd_version = 10 AND icd_code LIKE 'I63%') THEN 'Stroke'
                END AS disease
            FROM diagnoses_icd)
        SELECT a.subject_id, MIN(dx.disease) AS disease, MIN(a.admittime) AS first_time
        FROM admissions a JOIN dx USING (hadm_id)
        WHERE dx.disease IS NOT NULL
        GROUP BY a.subject_id
        HAVING COUNT(DISTINCT dx.disease) = 1""")
    con.execute("""
        CREATE TEMP TABLE stays AS
        SELECT a.subject_id, a.hadm_id, a.admittime, a.dischtime, t.name AS admission_type,
               p.gender, p.anchor_age, p.anchor_year, c.disease, c.first_time
        FROM cohort c
        JOIN admissions a USING (subject_id)
        JOIN patients p USING (subject_id)
        JOIN admission_types t USING (admission_type_id)""")

    stays = query("SELECT * FROM stays ORDER BY subject_id, admittime")

    diagnoses = defaultdict(list) # ensures missing keys dont cause errors they just get default values
    for hadm_id, title in query("""
            SELECT d.hadm_id, t.long_title
            FROM diagnoses_icd d JOIN stays USING (hadm_id) JOIN d_icd_diagnoses t USING (icd_code, icd_version)
            ORDER BY d.hadm_id, d.seq_num"""):
        diagnoses[hadm_id].append(title)

    procedures = defaultdict(list)
    for hadm_id, title in query("""
            SELECT p.hadm_id, t.long_title
            FROM procedures_icd p JOIN stays USING (hadm_id) JOIN d_icd_procedures t USING (icd_code, icd_version)
            ORDER BY p.hadm_id, p.seq_num"""):
        procedures[hadm_id].append(title)

    # latest clinic reading on or before the admission day
    readings = defaultdict(dict)
    for hadm_id, name, value in query("""
            SELECT s.hadm_id, m.name, last(o.value ORDER BY o.chartdate, o.seq_num)
            FROM stays s
            JOIN omr o ON o.subject_id = s.subject_id AND o.chartdate <= s.admittime::DATE
            JOIN omr_measures m USING (measure_id)
            WHERE m.name IN ('BMI', 'Systolic BP', 'Diastolic BP', 'Weight')
            GROUP BY s.hadm_id, m.name"""):
        readings[hadm_id][name] = value

    # last lab result during the stay, and its abnormal flag
    labs = defaultdict(dict)
    for hadm_id, label, value, flag in query("""
            SELECT s.hadm_id, i.label, last(r.valuenum ORDER BY r.charttime), last(r.flag ORDER BY r.charttime)
            FROM stays s
            JOIN lab_results r ON r.subject_id = s.subject_id AND r.charttime BETWEEN s.admittime AND s.dischtime
            JOIN lab_items i USING (itemid)
            WHERE r.valuenum IS NOT NULL
            GROUP BY s.hadm_id, i.label"""):
        labs[hadm_id][label] = (value, flag)

    classes = defaultdict(set)
    n_other = Counter()
    for hadm_id, drug_class, n in query("""
            SELECT r.hadm_id, d.drug_class, COUNT(DISTINCT d.drug)
            FROM prescriptions r JOIN stays USING (hadm_id) JOIN drugs d USING (drug_id)
            GROUP BY r.hadm_id, d.drug_class"""):
        if drug_class == "other":
            n_other[hadm_id] = n
        elif drug_class in drug_classes:
            classes[hadm_id].add(drug_classes[drug_class])

    return stays, diagnoses, procedures, readings, labs, classes, n_other

# normalises the number formatting in the prompt
def number(x):
    return f"{x:.1f}".rstrip("0").rstrip(".")


def listed(items, max_items, max_tokens):
    """joins diagnoses and procedures together with ; until the token budget runs out, then adds + K more on the end"""
    n, used = 0, 0
    for item in items[:max_items]:
        used += len(tokenizer(item, add_special_tokens=False)["input_ids"]) + 1
        if n > 0 and used > max_tokens:
            break
        n += 1
    text = "; ".join(items[:n])
    if len(items) > n:
        text += f"; and {len(items) - n} more"
    return text

# creates the prompt
def make_text(age, sex, admission_type, los_days, diagnoses, procedures, readings, labs, classes, n_other):
    days = number(los_days)
    bmi = f"BMI {number(readings['BMI'])}" if "BMI" in readings else "BMI not recorded"
    if "Systolic BP" in readings and "Diastolic BP" in readings:
        bp = f"blood pressure {readings['Systolic BP']:.0f}/{readings['Diastolic BP']:.0f} mmHg"
    else:
        bp = "blood pressure not recorded"
    weight = f"weight {readings['Weight']:.0f} lb" if "Weight" in readings else "weight not recorded"

    tests = []
    for label, name, unit in lab_tests:
        if label in labs:
            value, abnormal = labs[label]
            tests.append(f"{name} {number(value)} {unit}" + (" (abnormal)" if abnormal else ""))
        else:
            tests.append(f"{name} not measured")

    medicines = sorted(classes)[:n_classes]
    if n_other:
        medicines.append(f"{n_other} other medicine{'s' if n_other > 1 else ''}")

    return "\n".join([
        f"A {age}-year-old {'man' if sex == 'M' else 'woman'}.",
        f"Admitted as {admission_types[admission_type]} admission for {days} day{'' if days == '1' else 's'}.",
        "Diagnoses: " + listed(diagnoses, n_diagnoses, diagnosis_tokens) + "." if diagnoses else "No diagnoses recorded.",
        "Procedures: " + listed(procedures, n_procedures, procedure_tokens) + "." if procedures else "No procedures.",
        f"Last clinic readings: {bmi}, {bp}, {weight}.",
        "Blood tests: " + ", ".join(tests) + ".",
        "Medicines: " + ", ".join(medicines) + "." if medicines else "No medicines recorded.",
    ])

# main pipeline for the input creation
def get_stays():
    stays, diagnoses, procedures, readings, labs, classes, n_other = load_tables()

    by_subject = defaultdict(list)
    for row in stays:
        by_subject[row[0]].append(row)

    patients = []
    for subject_id, rows in by_subject.items():
        # leave out patients with a disease word in a stay before their first CVD stay - some patients have mention of AF pre diagnosis
        if any(row[2] < row[9] and any(disease_related.search(d) for d in diagnoses[row[1]]) for row in rows):
            continue

        patient = []
        for _, hadm_id, admittime, dischtime, admission_type, sex, anchor_age, anchor_year, disease, first_time in rows:
            text = make_text(
                age=anchor_age + admittime.year - anchor_year,
                sex=sex,
                admission_type=admission_type,
                los_days=(dischtime - admittime).total_seconds() / 86400,
                diagnoses=[d for d in diagnoses[hadm_id] if not disease_related.search(d)],
                procedures=[p for p in procedures[hadm_id] if not disease_related.search(p)],
                readings=readings[hadm_id], labs=labs[hadm_id], classes=classes[hadm_id], n_other=n_other[hadm_id])
            phase = "pre" if admittime < first_time else "dx" if admittime == first_time else "post"
            patient.append({"subject_id": subject_id, "hadm_id": hadm_id, "disease": disease, "phase": phase, "text": text})
        patients.append(patient)
    return patients


if __name__ == "__main__":
    patients = get_stays()
    with open(out_path, "w") as f:
        json.dump(patients, f, indent=2)
    print(f"Saved {len(patients)} patients, {sum(len(p) for p in patients)} stays to {out_path}")
