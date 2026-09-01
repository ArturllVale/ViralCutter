import json
import os
from collections import OrderedDict

LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")
standard_file = os.path.join(LOCALE_DIR, "en_US.json")

# Find all JSON files in the directory
languages = [
    os.path.join(LOCALE_DIR, f)
    for f in os.listdir(LOCALE_DIR)
    if f.endswith(".json") and os.path.abspath(os.path.join(LOCALE_DIR, f)) != os.path.abspath(standard_file)
]

if os.path.exists(standard_file):
    # Load the standard file
    with open(standard_file, "r", encoding="utf-8") as f:
        standard_data = json.load(f, object_pairs_hook=OrderedDict)

    # Loop through each language file
    for lang_file in languages:
        with open(lang_file, "r", encoding="utf-8") as f:
            lang_data = json.load(f, object_pairs_hook=OrderedDict)

        # Find the difference between the language file and the standard file
        diff = set(standard_data.keys()) - set(lang_data.keys())
        miss = set(lang_data.keys()) - set(standard_data.keys())

        # Add any missing keys to the language file
        for key in diff:
            lang_data[key] = key

        # Del any extra keys to the language file
        for key in miss:
            del lang_data[key]

        # Sort the keys of the language file to match the order of the standard file
        lang_data = OrderedDict(
            sorted(lang_data.items(), key=lambda x: list(standard_data.keys()).index(x[0]))
        )

        # Save the updated language file
        with open(lang_file, "w", encoding="utf-8") as f:
            json.dump(lang_data, f, ensure_ascii=False, indent=4, sort_keys=True)
            f.write("\n")
        print(f"Synchronized {os.path.basename(lang_file)} with standard {os.path.basename(standard_file)}.")
