"""
fine tuning medgemma with LoRA
weighted cross entropy (rarer diseases count more) on a small head, plus a centre loss to tighten the spread of each disease
"""

import torch
import csv
import json
import random
import numpy as np

from pathlib import Path
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import AutoProcessor, AutoModelForImageTextToText, get_constant_schedule_with_warmup
from sklearn.metrics import balanced_accuracy_score

random.seed(0)
np.random.seed(0)
torch.manual_seed(0)

model_path = Path("C:/mimic/models/medgemma-1.5-4b")
stays_path = Path("C:/mimic/derived/with_splits")
out_path = Path("C:/mimic/derived/lora_runs/mlp2_e10") 
resume = None # None for a fresh run, or a checkpoint folder to carry on from
use_cuda = torch.cuda.is_available()
question = "Which cardiovascular disease is this patient developing or most at risk of: atrial fibrillation, heart failure, myocardial infarction or stroke?"

# run settings
epochs = 10 
warmup_steps = 250
batch_size = 4
lora_lr = 2e-5
head_lr = 1e-4
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

# building the train and val, dx stays only 
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


# LoRA on the attention layers of the language model 
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
if resume is None:
    model = get_peft_model(model, config)
else:
    model = PeftModel.from_pretrained(model, str(resume), is_trainable=True) # load the saved LoRA weights
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False}) # didn't fit on my GPU without

processor = AutoProcessor.from_pretrained(model_path)
processor.tokenizer.padding_side = "right"

# small head and one centre per disease, kept outside MedGemma
# centres are learnable at the moment, we could try with hard coded centres if it doesnt work
head = torch.nn.Sequential(
    torch.nn.Linear(2560, 512),
    torch.nn.GELU(),
    torch.nn.Dropout(0.1),
    torch.nn.Linear(512, 128),
    torch.nn.GELU(),
    torch.nn.Dropout(0.1),
    torch.nn.Linear(128, 4),
).to(model.device)
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
    head.eval()
    preds = []
    labels = []
    with torch.no_grad():
        for i in range(0, len(val_stays), 8):
            batch = val_stays[i:i + 8]
            scores = head(head_scale * get_vectors(batch))
            preds += scores.argmax(dim=1).tolist()
            labels += get_labels(batch).tolist()
    model.train()
    head.train()
    return balanced_accuracy_score(labels, preds)


def add_row(file, header, row):
    """appends one row to a csv, writing the header first if the file is new"""
    new_file = not file.exists()
    with open(file, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(header)
        writer.writerow(row)


def save_checkpoint(folder, epochs_done, step, best):
    """LoRA adapter plus everything else needed to carry on training from here"""
    model.save_pretrained(str(folder))
    torch.save({
        "head": head.state_dict(),
        "centres": centres.data,
        "optimiser": optimiser.state_dict(),
        "scheduler": scheduler.state_dict(),
        "epochs_done": epochs_done,
        "step": step,
        "best": best,
        "torch_rng": torch.get_rng_state(),
        "cuda_rng": torch.cuda.get_rng_state_all() if use_cuda else None,
        "numpy_rng": np.random.get_state(),
        "random_rng": random.getstate(),
    }, folder / "state.pt")


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

# lr warms up for warmup_steps then stays constant at lora_lr / head_lr
n_steps = (len(train_stays) + batch_size - 1) // batch_size
scheduler = get_constant_schedule_with_warmup(
    optimiser,
    num_warmup_steps=warmup_steps,
)

# carry on from a checkpoint: head, centres, optimiser, scheduler, counters and random states
start_epoch = 0
global_step = 0
best = 0
if resume is not None:
    state = torch.load(Path(resume) / "state.pt", weights_only=False)
    head.load_state_dict(state["head"])
    centres.data.copy_(state["centres"])
    optimiser.load_state_dict(state["optimiser"])
    scheduler.load_state_dict(state["scheduler"])
    start_epoch = state["epochs_done"]
    global_step = state["step"]
    best = state["best"]
    torch.set_rng_state(state["torch_rng"])
    if use_cuda:
        torch.cuda.set_rng_state_all(state["cuda_rng"])
    np.random.set_state(state["numpy_rng"])
    random.setstate(state["random_rng"])

if __name__ == "__main__":
    print(f"train {len(train_stays)} stays, val {len(val_stays)} stays, {n_steps} steps per epoch")
    out_path.mkdir(parents=True, exist_ok=True)
    train_log = out_path / "train_log.csv"
    val_log = out_path / "val_log.csv"

    # passes over the train stays (reshuffled each epoch), val check every eval_every steps
    # and at the end of each epoch, "best" keeps the best checkpoint, "last" is saved at the end of each epoch
    model.train()
    head.train()
    last_epoch = start_epoch + epochs
    for epoch in range(start_epoch, last_epoch):
        order = train_stays[:]
        random.shuffle(order)
        for step in range(n_steps):
            batch = order[step * batch_size:(step + 1) * batch_size]
            y = get_labels(batch)
            h = get_vectors(batch)

            ce = loss_func(head(head_scale * h), y)
            centre = 0.5 * ((h - centres[y]) ** 2).sum(dim=1).mean()
            loss = ce + centre_weight * centre

            lr = optimiser.param_groups[0]["lr"] # LoRA lr used for this step
            loss.backward()
            torch.nn.utils.clip_grad_norm_(lora_params + head_params, 1.0)
            optimiser.step()
            scheduler.step()
            optimiser.zero_grad()
            global_step += 1

            add_row(train_log, ["step", "epoch", "lr", "ce_loss", "centre_loss", "total_loss"],
                    [global_step, epoch + 1, lr, ce.item(), centre.item(), loss.item()])

            if (step + 1) % 50 == 0:
                print(f"epoch {epoch + 1}/{last_epoch}  step {step + 1}/{n_steps}  lr {lr:.2e}  ce {ce.item():.3f}  centre {centre.item():.4f}")

            if (step + 1) % eval_every == 0 or step + 1 == n_steps:
                score = val_score()
                add_row(val_log, ["step", "epoch", "val_balanced_accuracy"], [global_step, epoch + 1, score])
                print(f"epoch {epoch + 1}  step {step + 1}  val balanced accuracy {score:.3f}")
                if score > best:
                    best = score
                    save_checkpoint(out_path / "best", epoch, global_step, best)
                    print(f"saved to {out_path / 'best'} (best so far)")

        save_checkpoint(out_path / "last", epoch + 1, global_step, best)
        print(f"saved to {out_path / 'last'} (end of epoch {epoch + 1})")

    print(f"best val balanced accuracy {best:.3f}")
