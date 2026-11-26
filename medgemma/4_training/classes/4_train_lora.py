"""
fine tuning medgemma 
uses cross entropy loss to deal with class inbalance and a centre loss to tighten the spread on the outputs 
"""

import torch
import csv
import json
import random

from pathlib import Path
from peft import LoraConfig, get_peft_model
from transformers import AutoProcessor, AutoModelForImageTextToText, get_cosine_schedule_with_warmup
from sklearn.metrics import balanced_accuracy_score

random.seed(0)
torch.manual_seed(0)

model_path = Path("C:/mimic/models/medgemma-1.5-4b")
stays_path = Path("C:/mimic/derived/with_splits")
out_path = Path("C:/mimic/derived/lora_runs/dx_e2")
use_cuda = torch.cuda.is_available()
question = "Which cardiovascular disease is this patient developing or most at risk of: atrial fibrillation, heart failure, myocardial infarction or stroke?"

# run settings
epochs = 2
batch_size = 4
lora_lr = 3e-5
head_lr = 1e-3
head_scale = 10
centre_weight = 1.0
eval_every = 1000

labels_of = {"AF": 0, "HF": 1, "MI": 2, "Stroke": 3}

# matches pid to the group it is in
with open(stays_path / "splits.csv", newline="") as f:
    split_of = {}
    for row in csv.DictReader(f):
        split_of[int(row["subject_id"])] = row["split"]

with open(stays_path / "stays.json") as f:
    patients = json.load(f)

# building the train and val 
train_stays = []
val_stays = []
for patient in patients:
    for stay in patient:
        if stay["phase"] != "dx":
            continue
        split = split_of.get(stay["subject_id"])
        if split in ["region_train", "jepa_train"]:
            train_stays.append(stay)
        if split in ["region_val", "jepa_val"]:
            val_stays.append(stay)
        

# LoRA on the attention layers of the language model (not the vision part)
config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    target_modules=r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj)",
)

model = AutoModelForImageTextToText.from_pretrained(
    model_path,
    dtype=torch.bfloat16 if use_cuda else torch.float32,
    device_map="cuda" if use_cuda else "cpu", # run on cpu if no gpu
)
model = get_peft_model(model, config)
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False}) # didn't fit on my GPU without

processor = AutoProcessor.from_pretrained(model_path)
processor.tokenizer.padding_side = "right"

# small head and one centre per disease, kept outside MedGemma
# centres are learnable at the moment, we could try with hard coded centres if it doesnt work
head = [torch.nn.Linear(2560, 512).to(model.device), torch.nn.GELU(), torch.nn.Linear(512, 128), torch.nn.GELU(), torch.nn.Linear(128, 4)]
centres = torch.randn(4, 2560)
centres = centres / centres.norm(dim=1, keepdim=True)
centres = torch.nn.Parameter(centres.to(model.device))


def get_vectors(batch):
    prompts = []
    for stay in batch:
        prompts.append([{"role": "user", "content": [{"type": "text", "text": question + "\n\n" + stay["text"]}]}])

    inputs = processor.apply_chat_template(
        prompts, processor_kwargs={"padding": True}, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt",
    ).to(model.device)
    out = model(**inputs, output_hidden_states=True, logits_to_keep=1, use_cache=False)
    last_layer = out.hidden_states[-1]

    vectors = []
    for i in range(len(batch)):
        last = inputs["attention_mask"][i].sum() - 1   # position of the last real token
        vectors.append(last_layer[i, last].float())
    vectors = torch.stack(vectors)
    return torch.nn.functional.normalize(vectors, dim=-1)


def get_labels(batch):
    return torch.tensor([labels_of[stay["disease"]] for stay in batch]).to(model.device)


def val_score():
    """balanced accuracy of the head on the val stays"""
    model.eval()
    preds = []
    labels = []
    with torch.no_grad():
        for i in range(0, len(val_stays), 8):
            batch = val_stays[i:i + 8]
            scores = head(head_scale * get_vectors(batch))
            preds += scores.argmax(dim=1).tolist()
            labels += get_labels(batch).tolist()
    model.train()
    return balanced_accuracy_score(labels, preds)

# rarer diseases count more in the loss: total / (4 * count)
counts = [0, 0, 0, 0]
for stay in train_stays:
    counts[labels_of[stay["disease"]]] += 1
weights = [len(train_stays) / (4 * c) for c in counts]
loss_func = torch.nn.CrossEntropyLoss(weight=torch.tensor(weights, device=model.device))

# gentle steps for LoRA, bigger ones for the new head and centres
lora_params = [p for p in model.parameters() if p.requires_grad]
head_params = list(head.parameters()) + [centres]
optimiser = torch.optim.AdamW([
    {"params": lora_params, "lr": lora_lr},
    {"params": head_params, "lr": head_lr},
], weight_decay=0.01)

if __name__ == "__main__":
    print(f"train {len(train_stays)} stays, val {len(val_stays)} stays")

    # epochs passes over the train stays (reshuffled each epoch), val check every eval_every steps
    # and at the end of each epoch, keep the best adapter over the whole run
    model.train()
    n_steps = (len(train_stays) + batch_size - 1) // batch_size
    best = 0
    for epoch in range(epochs):
        random.shuffle(train_stays)
        for step in range(n_steps):
            batch = train_stays[step * batch_size:(step + 1) * batch_size]
            y = get_labels(batch)
            h = get_vectors(batch)

            ce = loss_func(head(head_scale * h), y)
            centre = 0.5 * ((h - centres[y]) ** 2).sum(dim=1).mean()
            loss = ce + centre_weight * centre

            loss.backward()
            torch.nn.utils.clip_grad_norm_(lora_params + head_params, 1.0)
            optimiser.step()
            optimiser.zero_grad()

            if (step + 1) % 50 == 0:
                print(f"epoch {epoch + 1}/{epochs}  step {step + 1}/{n_steps}  ce {ce.item():.3f}  centre {centre.item():.4f}")

            if (step + 1) % eval_every == 0 or step + 1 == n_steps:
                score = val_score()
                print(f"epoch {epoch + 1}  step {step + 1}  val balanced accuracy {score:.3f}")
                if score > best:
                    best = score
                    model.save_pretrained(str(out_path))
                    print(f"saved to {out_path} (best so far)")

    print(f"best val balanced accuracy {best:.3f}")
