import ast
import glob
import json
import os
from collections import OrderedDict

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")


def extract_i18n_strings(node):
    i18n_strings = []

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "i18n"
    ):
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                i18n_strings.append(arg.value)
            elif type(arg).__name__ == 'Str':
                i18n_strings.append(getattr(arg, 's', ''))

    for child_node in ast.iter_child_nodes(node):
        i18n_strings.extend(extract_i18n_strings(child_node))

    return i18n_strings


# scan the directory for all .py files (recursively)
strings = []
for filename in glob.iglob(os.path.join(BASE_DIR, "**", "*.py"), recursive=True):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            code = f.read()
            if "i18n" in code:
                tree = ast.parse(code)
                i18n_strings = extract_i18n_strings(tree)
                if i18n_strings:
                    rel_name = os.path.relpath(filename, BASE_DIR)
                    print(f"{rel_name}: {len(i18n_strings)} strings")
                    strings.extend(i18n_strings)
    except Exception as e:
        print(f"Error parsing {filename}: {e}")

code_keys = set(strings)
print(f"\nTotal unique keys found in code: {len(code_keys)}")

standard_file = os.path.join(LOCALE_DIR, "en_US.json")
if os.path.exists(standard_file):
    with open(standard_file, "r", encoding="utf-8") as f:
        standard_data = json.load(f, object_pairs_hook=OrderedDict)
    standard_keys = set(standard_data.keys())

    unused_keys = standard_keys - code_keys
    print(f"Unused keys in {os.path.basename(standard_file)}: {len(unused_keys)}")
    for unused_key in sorted(unused_keys):
        print(f"\t- {unused_key}")

    missing_keys = code_keys - standard_keys
    print(f"Missing keys in {os.path.basename(standard_file)}: {len(missing_keys)}")
    for missing_key in sorted(missing_keys):
        print(f"\t+ {missing_key}")
else:
    print(f"Standard file {standard_file} not found.")
