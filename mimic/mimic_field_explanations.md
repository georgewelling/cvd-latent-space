# MIMIC-IV hosp fields

MIMIC-IV v2.2, hospital part. Every file, every column, and what it shows.
Two IDs appear almost everywhere: **subject_id** = the patient, **hadm_id** = one hospital admission.

## patients.csv.gz
One row per patient.
- subject_id: patient ID
- gender: sex (F/M)
- anchor_age: age in the reference year (age at an admission = anchor_age + admission year − anchor_year; over-89s are recorded as 91)
- anchor_year: the shifted reference year that anchor_age belongs to
- anchor_year_group: the real 3-year window the anchor year roughly matches (e.g. 2011–2013)
- dod: date of death, if known

## admissions.csv.gz
One row per hospital admission.
- subject_id: patient ID
- hadm_id: admission ID
- admittime: when they were admitted
- dischtime: when they were discharged
- deathtime: time of death, if they died in hospital
- admission_type: kind of admission (emergency, urgent, elective, observation...)
- admit_provider_id: anonymised ID of the admitting clinician
- admission_location: where they came from (A&E, GP referral, transfer...)
- discharge_location: where they went (home, care home, hospice, died...)
- insurance: insurance type
- language: language spoken
- marital_status: marital status
- race: recorded race/ethnicity
- edregtime: when they arrived in A&E, if they came through it
- edouttime: when they left A&E
- hospital_expire_flag: 1 if they died during this admission

## transfers.csv.gz
One row per ward move.
- subject_id: patient ID
- hadm_id: admission ID
- transfer_id: ID of this move
- eventtype: admit, transfer, discharge or ED
- careunit: the ward or unit
- intime: time they arrived on that ward
- outtime: time they left it

## services.csv.gz
Which medical team was in charge.
- subject_id: patient ID
- hadm_id: admission ID
- transfertime: when the team changed
- prev_service: team before (e.g. MED, CMED for cardiology, SURG)
- curr_service: team after

## diagnoses_icd.csv.gz
One row per diagnosis code per admission.
- subject_id: patient ID
- hadm_id: admission ID
- seq_num: order of importance (1 = main diagnosis)
- icd_code: the diagnosis code, without dots (e.g. I480, 42731)
- icd_version: 9 or 10

## cleaned_diagnoses_icd.csv (made by the lab, not standard MIMIC)
One row per admission.
- subject_id: patient ID
- hadm_id: admission ID
- admittime: when they were admitted
- diagnosis_str: all that admission's diagnosis codes in one text string

## d_icd_diagnoses.csv.gz
Dictionary of diagnosis codes.
- icd_code: the code
- icd_version: 9 or 10
- long_title: the disease name

## d_icd_simplified_diagnoses.csv (made by the lab)
A shorter dictionary of diagnosis codes.
- icd_code: the code
- icd_version: 9 or 10
- long_title: the disease name

## procedures_icd.csv.gz
One row per procedure code per admission.
- subject_id: patient ID
- hadm_id: admission ID
- seq_num: order
- chartdate: date of the procedure
- icd_code: the procedure code
- icd_version: 9 or 10

## d_icd_procedures.csv.gz
Dictionary of procedure codes.
- icd_code: the code
- icd_version: 9 or 10
- long_title: the procedure name

## hcpcsevents.csv.gz
Billing codes for services and procedures.
- subject_id: patient ID
- hadm_id: admission ID
- chartdate: date
- hcpcs_cd: the billing code
- seq_num: order
- short_description: what it was

## d_hcpcs.csv.gz
Dictionary of billing codes.
- code: the billing code
- category: its category
- long_description: full description
- short_description: short description

## drgcodes.csv.gz
Billing group for each admission.
- subject_id: patient ID
- hadm_id: admission ID
- drg_type: which grouping system (HCFA or APR)
- drg_code: the group code
- description: what the group is (e.g. heart failure and shock)
- drg_severity: severity of illness score (APR only)
- drg_mortality: risk of death score (APR only)

## labevents.csv.gz (the biggest file, 1.9 GB)
One row per lab result.
- labevent_id: ID of this result
- subject_id: patient ID
- hadm_id: admission ID (empty for outpatient tests)
- specimen_id: ID of the sample the test was run on
- itemid: which test (look up in d_labitems)
- order_provider_id: anonymised ID of who ordered it
- charttime: when the sample was taken
- storetime: when the result was recorded
- value: result as text
- valuenum: result as a number
- valueuom: unit (e.g. mg/dL)
- ref_range_lower: bottom of the normal range
- ref_range_upper: top of the normal range
- flag: "abnormal" if outside the normal range
- priority: routine or STAT (urgent)
- comments: free-text comments on the result

## d_labitems.csv.gz
Dictionary of lab tests.
- itemid: test ID
- label: test name (e.g. NTproBNP, Troponin T, Creatinine)
- fluid: what was tested (blood, urine...)
- category: chemistry, haematology, blood gas...

## microbiologyevents.csv.gz
Cultures and infection tests.
- microevent_id: ID of this result
- subject_id: patient ID
- hadm_id: admission ID
- micro_specimen_id: ID of the sample
- order_provider_id: who ordered it
- chartdate, charttime: when the sample was taken
- spec_itemid, spec_type_desc: type of sample (blood culture, urine...)
- test_seq: order of tests on that sample
- storedate, storetime: when the result was recorded
- test_itemid, test_name: which test was run
- org_itemid, org_name: organism found, if any
- isolate_num: which isolate of that organism
- quantity: how much grew
- ab_itemid, ab_name: antibiotic tested against it
- dilution_text, dilution_comparison, dilution_value: lab result of the antibiotic test
- interpretation: S (sensitive), R (resistant) or I (intermediate)
- comments: free-text comments

## omr.csv.gz (Online Medical Record)
Outpatient measurements over time.
- subject_id: patient ID
- chartdate: date of the measurement
- seq_num: order on that day
- result_name: what was measured (BMI, weight, height, blood pressure, eGFR), with unit
- result_value: the value (blood pressure is one text like 120/80)

## prescriptions.csv.gz
One row per drug prescribed in hospital.
- subject_id: patient ID
- hadm_id: admission ID
- pharmacy_id: links to the pharmacy table
- poe_id, poe_seq: links to the order that created it
- order_provider_id: who prescribed it
- starttime: when it started
- stoptime: when it stopped
- drug_type: MAIN, BASE (IV fluid base) or ADDITIVE
- drug: drug name (e.g. Metoprolol Tartrate)
- formulary_drug_cd: hospital's internal drug code
- gsn: generic drug code (same ingredient, strength and form)
- ndc: US national drug code
- prod_strength: strength and form (e.g. 50 mg tablet)
- form_rx: prescribed form
- dose_val_rx: dose per time
- dose_unit_rx: dose unit (mg...)
- form_val_disp: amount dispensed per dose
- form_unit_disp: unit dispensed (tab, vial...)
- doses_per_24_hrs: times per day
- route: how it's given (PO oral, IV, SC...)

## pharmacy.csv.gz
Pharmacy-side detail for the same drug orders.
- subject_id, hadm_id: patient and admission
- pharmacy_id: ID of this pharmacy order
- poe_id: links to the order
- starttime, stoptime: when it started and stopped
- medication: drug name
- proc_type: kind of order (unit dose, IV...)
- status: active, discontinued...
- entertime: when it was entered
- verifiedtime: when the pharmacist checked it
- route: how it's given
- frequency: how often (e.g. Q8H)
- disp_sched: dosing schedule times
- infusion_type: type of infusion
- sliding_scale: whether the dose varies (e.g. insulin by glucose)
- lockout_interval, basal_rate, one_hr_max: patient-controlled pain pump settings
- doses_per_24_hrs: times per day
- duration, duration_interval: how long it was ordered for
- expiration_value, expiration_unit, expirationdate: when the order expires
- dispensation: how it was dispensed
- fill_quantity: amount supplied

## emar.csv.gz (electronic medicine administration record)
One row each time a nurse gave, or skipped, a drug.
- subject_id, hadm_id: patient and admission
- emar_id, emar_seq: ID of this event
- poe_id, pharmacy_id: links to the order
- enter_provider_id: who recorded it
- charttime: when it was given
- medication: drug name
- event_txt: what happened (administered, not given, held...)
- scheduletime: when it was due
- storetime: when it was recorded

## emar_detail.csv.gz
Detail for each emar event.
- subject_id: patient ID
- emar_id, emar_seq: links to emar
- parent_field_ordinal: which part of a multi-part dose
- administration_type: kind of administration
- pharmacy_id: links to the pharmacy order
- barcode_type, reason_for_no_barcode: barcode scanning check
- complete_dose_not_given: whether the full dose was skipped
- dose_due, dose_due_unit: dose that was due
- dose_given, dose_given_unit: dose actually given
- will_remainder_of_dose_be_given: whether the rest follows
- product_amount_given, product_unit, product_code, product_description, product_description_other: the actual product used
- prior_infusion_rate, infusion_rate, infusion_rate_adjustment, infusion_rate_adjustment_amount, infusion_rate_unit: drip rates
- route: how it was given
- infusion_complete, completion_interval: infusion finished or not
- new_iv_bag_hung, continued_infusion_in_other_location, restart_interval: IV bag events
- side, site: where on the body
- non_formulary_visual_verification: check for non-standard drugs

## poe.csv.gz (provider order entry)
Every order a clinician made.
- poe_id, poe_seq: order ID
- subject_id, hadm_id: patient and admission
- ordertime: when it was ordered
- order_type: medications, lab, radiology, nutrition, consults...
- order_subtype: more detail on the type
- transaction_type: new, change or discontinue
- discontinue_of_poe_id, discontinued_by_poe_id: links between an order and the one that cancelled it
- order_provider_id: who ordered it
- order_status: active or inactive

## poe_detail.csv.gz
Extra fields for some orders.
- poe_id, poe_seq: links to poe
- subject_id: patient ID
- field_name: name of the extra field (e.g. admit to, code status)
- field_value: its value

## provider.csv.gz
- provider_id: list of every anonymised clinician ID used in the other files

## Not data
- Guide to navigate MIMIC-IV.md: the lab's guide (also describes two ECG files that aren't in the folder)
- index.html: PhysioNet's file listing page
