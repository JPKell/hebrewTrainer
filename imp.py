import requests
import json
import re
import difflib

# ----------------------------
# CONFIG
# ----------------------------
SEFARIA_URL = "https://www.sefaria.org/api/texts/Psalms?lang=he&context=0"
OUTPUT_FILE = "psalms_clean.json"
SIMILARITY_THRESHOLD = 0.95  # adjust between 0.90–0.98


# ----------------------------
# Remove cantillation marks
# ----------------------------
def remove_cantillation(text):
    # Removes trope marks but keeps niqqud
    return re.sub(r'[\u0591-\u05AF\u05BD\u05BF\u05C0\u05C4\u05C5]', '', text)


# ----------------------------
# Normalize spacing
# ----------------------------
def normalize_text(text):
    text = text.strip()
    text = re.sub(r'\s+', ' ', text)
    return text


# ----------------------------
# Fetch Psalms from Sefaria
# ----------------------------
def fetch_psalms():
    print("Downloading Psalms from Sefaria...")
    response = requests.get(SEFARIA_URL)
    response.raise_for_status()
    data = response.json()
    return data["he"]


# ----------------------------
# Flatten chapters into single list
# ----------------------------
def flatten_psalms(psalms_data):
    verses = []
    for chapter in psalms_data:
        for verse in chapter:
            clean = remove_cantillation(verse)
            clean = normalize_text(clean)
            verses.append(clean)
    return verses


# ----------------------------
# Remove duplicates & near duplicates
# ----------------------------
def deduplicate_lines(lines):
    print("Removing duplicates...")
    unique = []

    for line in lines:
        is_duplicate = False
        for existing in unique:
            similarity = difflib.SequenceMatcher(None, line, existing).ratio()
            if similarity >= SIMILARITY_THRESHOLD:
                is_duplicate = True
                break
        if not is_duplicate:
            unique.append(line)

    return unique


# ----------------------------
# Main
# ----------------------------
def main():
    psalms_data = fetch_psalms()
    flat_verses = flatten_psalms(psalms_data)

    print(f"Total verses before dedupe: {len(flat_verses)}")

    unique_verses = deduplicate_lines(flat_verses)

    print(f"Total verses after dedupe: {len(unique_verses)}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(unique_verses, f, ensure_ascii=False, indent=2)

    print(f"Saved cleaned Psalms to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()