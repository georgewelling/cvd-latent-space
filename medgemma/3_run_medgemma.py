"""
just plain medgemma using the splits of the dx patients, no fine tuning
""" 

import json
import csv
import numpy as np
import torch
from transformers import AutoProcessor, AutoModelForImageTextToText
from pathlib import Path

stays_path = Path("C:/mimic/derived/with_splits")
model_path = Path("C:/mimic/models/medgemma-1.5-4b")
out_path = Path("C:/mimic/derived/lora_runs/baseline")

use_cuda = torch.cuda.is_available()
question = "Which cardiovascular disease is this patient developing or most at risk of: atrial fibrillation, heart failure, myocardial infarction or stroke?"
labels_of = {"AF": 0, "HF": 1, "MI": 2, "Stroke": 3}


def get_stays():
    """dx stays of the region patients, by split (one per patient)"""
    with open(stays_path / "splits.csv", newline="") as f:
        split_of = {}
        for row in csv.DictReader(f):
            split_of[int(row["subject_id"])] = row["split"]
    with open(stays_path / "stays.json") as f:
        patients = json.load(f)

    stays = {"train": [], "val": [], "test": []}
    for patient in patients:
        for stay in patient:
            if stay["phase"] != "dx": 
                continue
            split = split_of.get(stay["subject_id"])
            for name in stays:
                if split == "region_" + name:
                    stays[name].append(stay)
    return stays


def embed(text):
    """Run one stay through MedGemma, return the normalised last token vector"""
    messages = [{"role": "user", "content": [{"type": "text", "text": question + "\n\n" + text}]}]
    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt"
    ).to(model.device)

    with torch.inference_mode():
        out = model(**inputs, output_hidden_states=True, logits_to_keep=1, use_cache=False)
    last_layer = out.hidden_states[-1]
    h = last_layer[0, -1].float()   # one stay, so the last token is the last real token
    h = torch.nn.functional.normalize(h, dim=-1)
    return h.cpu().numpy()


if __name__ == "__main__":
    stays = get_stays()

    model = AutoModelForImageTextToText.from_pretrained(
        model_path,
        dtype=torch.bfloat16 if use_cuda else torch.float32,
        device_map="cuda" if use_cuda else "cpu", # run on gpu, if no gpu, cpu
    )
    processor = AutoProcessor.from_pretrained(model_path)

    save = {}
    for name in stays:
        vecs = []
        labels = []
        for i, stay in enumerate(stays[name]):
            vecs.append(embed(stay["text"]))
            labels.append(labels_of[stay["disease"]])
            if i % 500 == 0:
                print(f"{name}: {i}/{len(stays[name])}") # progress
        save[name + "_labels"] = np.array(labels)
        save[name + "_base"] = np.stack(vecs)

    np.savez(out_path / "vectors_base.npz", **save)
    print(f"Saved to {out_path / 'vectors_base.npz'}")
