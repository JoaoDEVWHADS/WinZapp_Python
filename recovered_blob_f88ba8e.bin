import json
from app_paths import resource_path

class I18n:
    def __init__(self, main_window):
        self.main_window = main_window
        self.language = "pt-BR" #default

    def get_language(self):
        #Gets the current language setting from main window settings
        self.language = self.main_window.settings.get("general", {}).get("language", "pt-BR")
        return self.language

    def t(self, key):
        #Translates a given key based on the current language
        try:
            with open(resource_path("languages", f"{self.language}.json"), "r", encoding="utf-8") as f:
                translations = json.load(f)
            return translations.get(key, key)
        except Exception:
            return key