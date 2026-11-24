"""
splits patients depending on how many pre visits they have
2 main groups: 
    region patients (patients with not enough data to form paths) 
    path patients (patients with enough data to form paths)
    determined by n_pre (number of pre visits)

train, val, test within each group
outputs splits.csv
"""
import csv
import json

from pathlib import Path
from sklearn.model_selection import train_test_split

path = Path("C:/mimic/derived/with_splits")
max_pre_region = 0 # patients with this number of pre visits (0 means just dx+post patients are the region patients)

def split(rows, names, val_test):
    """train, val, test numbers, val and test are equal"""
    train, rest = train_test_split(rows, test_size=val_test, random_state=0, stratify=[r[1] for r in rows]) # stratify ensures class weights are the same through all groups
    val, test = train_test_split(rest, test_size=0.5, random_state=0, stratify=[r[1] for r in rest])
    return [r + (name,) for part, name in zip([train, val, test], names) for r in part]

if __name__ == "__main__":
    with open(path / "stays.json") as f:
        patients = json.load(f)

    # one row per patient: (subject_id, disease, n_pre)
    rows = []
    for patient in patients:
        n_pre = sum(i["phase"] == "pre" for i in patient)
        rows.append((patient[0]["subject_id"], patient[0]["disease"], n_pre))

    region_rows = [r for r in rows if r[2] <= max_pre_region]
    path_rows   = [r for r in rows if r[2] > max_pre_region]
    region = split(region_rows, ["region_train", "region_val", "region_test"], 0.2)
    jepa = split(path_rows, ["jepa_train", "jepa_val", "jepa_test"], 0.3)

    with open(path / "splits.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subject_id", "disease", "n_pre", "split"])
        w.writerows(region + jepa)
    print(f"{len(region)} region patients, {len(jepa)} path patients")
