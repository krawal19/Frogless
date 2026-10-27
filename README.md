# Frogless

Paste any crochet pattern. Know if it works before you pick up your hook: where it breaks, how to fix it, and what it will really make.

## Setup

### Requirements
- Python 3.12+
- Node.js 20+ (tested on 24). The pattern engine is JavaScript and runs through Node.
- Git
- A Meta Model API key from https://dev.meta.ai

### 1. Clone Frogless
```sh
git clone <this repo's URL> Frogless
cd Frogless
```

### 2. Clone CrochetPARADE (the pattern engine)
Clone it anywhere you like, and pin it to the commit Frogless is tested against:
```sh
git clone https://github.com/stassev/CrochetPARADE.git
cd CrochetPARADE
git checkout 06e987b
cd ..
```

### 3. Install the Python dependencies
```sh
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Create `.env`
Copy the template and fill in both values:
```sh
cp .env.example .env
```
```ini
META_API_KEY=your-key-here
CROCHETPARADE_PATH=/absolute/path/to/CrochetPARADE
```
On Windows, use forward slashes, for example `C:/code/CrochetPARADE`. `.env` is gitignored, so don't commit it.

### 5. Check it works
```sh
python -m pytest -q        # offline, no API calls
python -m scripts.hello    # one Muse Spark call, under 1 cent
python -m scripts.hello_sam  # one SAM 3.1 call, $0.0025
```
Every model call is logged with its cost to `logs/model_calls.jsonl`.
