import json
import locale
import os

LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locale")


def load_language_list(language):
    file_path = os.path.join(LOCALE_DIR, f"{language}.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class I18nAuto:
    def __init__(self, language=None):
        if language in ["Auto", None]:
            try:
                # Use getlocale with safe fallback
                loc = locale.getlocale()[0]
                if not loc:
                    loc = locale.getdefaultlocale()[0]
                language = loc or "en_US"
            except Exception:
                language = "en_US"

        target_path = os.path.join(LOCALE_DIR, f"{language}.json")
        if not os.path.exists(target_path):
            language = "en_US"
        self.language = language
        self.language_map = load_language_list(language)

    def __call__(self, key):
        return self.language_map.get(key, key)

    def __repr__(self):
        return f"Use Language: {self.language}"
