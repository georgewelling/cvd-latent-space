import time
from pathlib import Path 

import duckdb

raw = Path(r"C:/mimic/data/hosp") # where the data is 
db = Path(r"C:/mimic/my_db/db.duckdb") # where i want the output database
tmp = Path(r"C:/mimic/my_db/temp") # a dump folder, needed cos files too big for pc 

# loading every test from lab events will take too long so we only take the labels that are 
# necessary - to load all set this to NONE
lab_labels = ["NTproBNP", "Troponin T", "Potassium", "Magnesium", "Creatinine",
              "% Hemoglobin A1c", "Cholesterol, Total", "Cholesterol, LDL, Calculated",
              "Triglycerides", "C-Reactive Protein", "Thyroid Stimulating Hormone", "Sodium"]

def f(name):
    """outputs a string that is valid in SQL form so data can be used 
    in SQL load statements"""
    return "'" + str(raw / f"{name}.csv.gz").replace("\\", "/") + "'"

create = """
CREATE TABLE patients (
    subject_id INTEGER PRIMARY KEY,
    gender CHAR(1) NOT NULL,
    anchor_age INTEGER NOT NULL,
    anchor_year INTEGER NOT NULL, 
    dod DATE
);

CREATE TABLE admission_types (
    admission_type_id INTEGER PRIMARY KEY, 
    name VARCHAR NOT NULL UNIQUE
);

CREATE TABLE admissions (
    hadm_id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES patients(subject_id),
    admittime TIMESTAMP NOT NULL,
    dischtime TIMESTAMP NOT NULL,
    admission_type_id INTEGER NOT NULL REFERENCES admission_types(admission_type_id),
    hospital_expire_flag BOOLEAN NOT NULL
);

CREATE TABLE d_icd_diagnoses (
    icd_code VARCHAR, 
    icd_version INTEGER,
    long_title VARCHAR NOT NULL,
    PRIMARY KEY (icd_code, icd_version)
);

CREATE TABLE diagnoses_icd (
    hadm_id INTEGER NOT NULL REFERENCES admissions(hadm_id),
    seq_num INTEGER NOT NULL, 
    icd_code VARCHAR NOT NULL,
    icd_version INTEGER NOT NULL,
    PRIMARY KEY (hadm_id, seq_num, icd_code, icd_version),
    FOREIGN KEY (icd_code, icd_version) REFERENCES d_icd_diagnoses(icd_code, icd_version)
);

CREATE TABLE d_icd_procedures (
    icd_code VARCHAR,
    icd_version INTEGER,
    long_title VARCHAR NOT NULL,
    PRIMARY KEY (icd_code, icd_version)
);

CREATE TABLE procedures_icd (
    hadm_id INTEGER NOT NULL REFERENCES admissions(hadm_id),
    seq_num INTEGER NOT NULL,
    chartdate DATE NOT NULL,
    icd_code VARCHAR NOT NULL,
    icd_version INTEGER NOT NULL,
    PRIMARY KEY (hadm_id, seq_num, icd_code, icd_version),
    FOREIGN KEY (icd_code, icd_version) REFERENCES d_icd_procedures(icd_code, icd_version)
);

CREATE TABLE drugs (
    drug_id INTEGER PRIMARY KEY,
    drug VARCHAR NOT NULL UNIQUE,
    drug_class VARCHAR NOT NULL
); 

CREATE TABLE routes (
    route_id INTEGER PRIMARY KEY,
    route VARCHAR NOT NULL UNIQUE
); 

CREATE TABLE prescriptions (
    rx_id INTEGER PRIMARY KEY,
    hadm_id INTEGER NOT NULL REFERENCES admissions(hadm_id),
    drug_id INTEGER NOT NULL REFERENCES drugs(drug_id),
    route_id INTEGER NOT NULL REFERENCES routes(route_id),
    starttime TIMESTAMP NOT NULL,
    stoptime TIMESTAMP
); 

CREATE TABLE lab_items (
    itemid INTEGER PRIMARY KEY,
    label VARCHAR NOT NULL,
    fluid VARCHAR NOT NULL,
    valueuom VARCHAR
); 

CREATE TABLE lab_results (
    labevent_id INTEGER PRIMARY KEY,
    subject_id INTEGER NOT NULL REFERENCES patients(subject_id),
    itemid INTEGER NOT NULL REFERENCES lab_items(itemid),
    charttime TIMESTAMP NOT NULL,
    valuenum DOUBLE NOT NULL,
    flag BOOLEAN
); 

CREATE TABLE omr_measures (
    measure_id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL UNIQUE,
    unit VARCHAR NOT NULL
); 

CREATE TABLE omr (
    subject_id INTEGER NOT NULL REFERENCES patients(subject_id),
    chartdate DATE NOT NULL,
    measure_id INTEGER NOT NULL REFERENCES omr_measures(measure_id),
    seq_num INTEGER NOT NULL,
    value DOUBLE NOT NULL,
    PRIMARY KEY (subject_id, chartdate, measure_id, seq_num)
);

CREATE VIEW admission_age AS
SELECT a.hadm_id, p.anchor_age + (year(a.admittime) - p.anchor_year) AS age
FROM admissions a JOIN patients p USING (subject_id);
"""

drug_classes = {
    "line_flush": ["flush", " lock"],
    "anticoagulant": ["warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban", "heparin", "enoxaparin"],
    "antiarrhythmic": ["amiodarone", "dronedarone", "flecainide", "propafenone", "sotalol", "dofetilide", "digoxin"],
    "beta_blocker": ["metoprolol", "atenolol", "carvedilol", "bisoprolol", "propranolol", "labetalol", "nebivolol"],
    "ccb_rate": ["diltiazem", "verapamil"],
    "statin": ["atorvastatin", "simvastatin", "rosuvastatin", "pravastatin", "lovastatin"],
    "ace_arb": ["lisinopril", "enalapril", "ramipril", "captopril", "losartan", "valsartan", "irbesartan", "sacubitril"],
    "loop_diuretic": ["furosemide", "bumetanide", "torsemide"],
    "antiplatelet": ["aspirin", "clopidogrel", "ticagrelor", "prasugrel"],
    "insulin": ["insulin"],
    "thyroid": ["levothyroxine", "liothyronine", "methimazole", "propylthiouracil"],
    "steroid": ["prednisone", "prednisolone", "methylprednisolone", "hydrocortisone", "dexamethasone"],
    "electrolyte": ["potassium", "magnesium"],
}

drug_case = "CASE " + " ".join(
    f"WHEN regexp_matches(lower(drug), '{'|'.join(words)}') THEN '{cls}'" for cls, words in drug_classes.items()) + " ELSE 'other' END"

lab_filter = ""
if lab_labels:
    labels = ", ".join("'" + x.replace("'", "''") + "'" for x in lab_labels)
    lab_filter = f"WHERE label IN ({labels}) AND fluid = 'Blood'"

ICD = "types={'icd_code': 'VARCHAR'}"

load = [
    ("patients", f"""
INSERT INTO patients 
SELECT subject_id, gender, anchor_age, anchor_year, dod
FROM read_csv({f('patients')})"""),

    ("admission_types", f"""
INSERT INTO admission_types
SELECT row_number() OVER (ORDER BY admission_type), admission_type
FROM (SELECT DISTINCT admission_type FROM read_csv({f('admissions')}))"""),

    ("admissions", f"""
INSERT INTO admissions
SELECT a.hadm_id, a.subject_id, a.admittime, a.dischtime,
        t.admission_type_id, a.hospital_expire_flag::BOOLEAN
FROM read_csv({f('admissions')}) a
JOIN admission_types t on t.name = a.admission_type"""),

    ("d_icd_diagnoses", f"""
INSERT INTO d_icd_diagnoses
SELECT DISTINCT icd_code, icd_version, long_title FROM read_csv({f('d_icd_diagnoses')}, {ICD})"""),

    ("diagnoses_icd", f"""
    INSERT INTO diagnoses_icd
SELECT DISTINCT hadm_id, seq_num, icd_code, icd_version FROM read_csv({f('diagnoses_icd')}, {ICD})"""),

    ("d_icd_procedures", f"""
INSERT INTO d_icd_procedures
SELECT icd_code, icd_version, long_title FROM read_csv({f('d_icd_procedures')}, {ICD})"""),

    ("procedures_icd", f"""
INSERT INTO procedures_icd
SELECT DISTINCT hadm_id, seq_num, chartdate, icd_code, icd_version FROM read_csv({f('procedures_icd')}, {ICD})"""),
    
    ("_rx_raw", f"""
CREATE TEMP TABLE _rx_raw AS 
SELECT hadm_id, drug, route, starttime, stoptime
FROM read_csv({f('prescriptions')})
WHERE starttime IS NOT NULL AND route IS NOT NULL AND drug IS NOT NULL
    AND hadm_id IN (SELECT hadm_id FROM admissions)"""),

    ("drugs", f"""
INSERT INTO drugs
SELECT row_number() OVER (ORDER BY drug), drug, {drug_case}
FROM (SELECT DISTINCT drug FROM _rx_raw)"""),

    ("routes", """
INSERT INTO routes
SELECT row_number() OVER (ORDER BY route), route
FROM (SELECT DISTINCT route FROM _rx_raw)"""),

    ("prescriptions", """
INSERT INTO prescriptions
SELECT row_number() OVER (ORDER BY r.hadm_id, r.starttime, d.drug_id),
       r.hadm_id, d.drug_id, o.route_id, r.starttime, r.stoptime
FROM _rx_raw r
JOIN drugs d USING (drug)
JOIN routes o USING (route)"""),

    ("_lab_raw", f"""
CREATE TEMP TABLE _lab_raw AS
SELECT labevent_id, subject_id, itemid, charttime, valuenum, valueuom, flag
FROM read_csv({f('labevents')})
WHERE valuenum IS NOT NULL
  AND itemid IN (SELECT itemid FROM read_csv({f('d_labitems')}) {lab_filter})"""),

    ("lab_items", f"""
INSERT INTO lab_items
SELECT i.itemid, i.label, i.fluid, u.unit
FROM read_csv({f('d_labitems')}) i
JOIN (SELECT itemid, mode(valueuom) AS unit FROM _lab_raw GROUP BY itemid) u USING (itemid)"""),

    ("lab_results", """
INSERT INTO lab_results
SELECT labevent_id, subject_id, itemid, charttime, valuenum,
       CASE WHEN flag = 'abnormal' THEN TRUE END
FROM _lab_raw"""),

    ("omr_measures", """
INSERT INTO omr_measures VALUES
  (1, 'Systolic BP', 'mmHg'), (2, 'Diastolic BP', 'mmHg'), (3, 'BMI', 'kg/m2'),
  (4, 'Weight', 'lb'), (5, 'Height', 'in'), (6, 'eGFR', 'mL/min/1.73m2')"""),

    ("omr", f"""
INSERT INTO omr
WITH raw AS (SELECT * FROM read_csv({f('omr')}, types={{'result_value': 'VARCHAR'}})),
long AS (
  SELECT subject_id, chartdate, seq_num, 1 AS measure_id,
         TRY_CAST(split_part(result_value, '/', 1) AS DOUBLE) AS value
  FROM raw WHERE result_name LIKE 'Blood Pressure%'
  UNION ALL
  SELECT subject_id, chartdate, seq_num, 2,
         TRY_CAST(split_part(result_value, '/', 2) AS DOUBLE)
  FROM raw WHERE result_name LIKE 'Blood Pressure%'
  UNION ALL
  SELECT subject_id, chartdate, seq_num,
         CASE WHEN result_name LIKE 'BMI%' THEN 3
              WHEN result_name LIKE 'Weight%' THEN 4
              WHEN result_name LIKE 'Height%' THEN 5
              WHEN result_name LIKE 'eGFR%' THEN 6 END,
         TRY_CAST(result_value AS DOUBLE)
  FROM raw WHERE result_name NOT LIKE 'Blood Pressure%')
SELECT subject_id, chartdate, measure_id,
       row_number() OVER (PARTITION BY subject_id, chartdate, measure_id ORDER BY seq_num),
       value
FROM long
WHERE measure_id IS NOT NULL AND value IS NOT NULL
  AND subject_id IN (SELECT subject_id FROM patients)"""),
]

def main(): 
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    con = duckdb.connect(str(db))
    con.execute(f"SET temp_directory = '{tmp.as_posix()}'")
    con.execute("SET preserve_insertion_order = false")
    con.execute(create)
    for name, sql in load:
        con.execute(sql)
    con.close()
    print("Done")

if __name__ == "__main__":
    main()