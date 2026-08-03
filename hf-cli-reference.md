# Hugging Face CLI (`hf`) Quick Reference

Updated to **v1.23.0** (was `huggingface-cli`, now `hf`).

---

## Auth (login once)

```bash
hf auth login                    # browser login
hf auth login --token $HF_TOKEN # or paste a token
hf auth whoami                   # check who you are
```

---

## Git push equivalent (upload files)

```bash
# Upload entire folder (creates repo if missing)
hf upload my-username/my-model ./local/dir .

# Upload a single file
hf upload my-username/my-model ./model.safetensors

# Upload to a Space
hf upload my-username/my-space . . --repo-type space
```

---

## Git pull equivalent (download files)

```bash
# Download entire model repo
hf download meta-llama/Llama-3.2-1B-Instruct

# Download single file
hf download gpt2 config.json

# Download from dataset
hf download bigcode/the-stack --repo-type dataset --revision v1.1

# Download to a specific folder
hf download adept/fuyu-8b model-00001-of-00002.safetensors --local-dir ./fuyu
```

---

## Get logs (Spaces)

```bash
# View Space build/runtime logs
hf spaces logs my-username/my-space
```

---

## Manage Spaces

```bash
hf spaces ls                                    # list spaces
hf spaces info my-username/my-space              # details
hf spaces restart my-username/my-space           # restart
hf spaces pause my-username/my-space             # pause (no billing)
hf spaces wait my-username/my-space              # block until running
hf spaces settings my-username/my-space --hardware t4-medium
hf spaces secrets add my-username/my-space -s KEY=value
```

---

## Search & browse

```bash
hf models ls --search "llama" --sort downloads --limit 5
hf datasets ls --search "code"
hf spaces ls --sort likes --limit 10
hf papers search "vision language"
```

---

## Discussions & PRs (Hub git workflow)

```bash
hf discussions list my-username/my-model          # list open issues/PRs
hf discussions info my-username/my-model 5        # view #5
hf discussions create my-username/my-model --title "Bug" --body "desc"
hf discussions create --pull-request --title "Fix"  # create PR
hf discussions comment my-username/my-model 5 --body "LGTM"
```

---

## Output formats

```bash
hf models ls --json          # JSON (pipe to jq)
hf models ls -q              # quiet (IDs only)
hf models ls --format agent  # tab-separated (AI-friendly)
```

---

## Environment variables

```bash
export HF_TOKEN=hf_...       # token (avoids login prompt)
export HF_HOME=/path/to/cache # custom cache dir
```

---

## What replaced `huggingface-cli` commands

| Old `huggingface-cli` | New `hf` |
|---|---|
| `huggingface-cli login` | `hf auth login` |
| `huggingface-cli whoami` | `hf auth whoami` |
| `huggingface-cli upload` | `hf upload` |
| `huggingface-cli download` | `hf download` |
| `huggingface-cli repo create` | `hf repo create` |
| — (no logs command) | `hf spaces logs` |
