import configparser
import os
from enum import Enum
from typing import TypeVar

E = TypeVar("E", bound=Enum)


class ConfigManager:
    def __init__(self, config_file: str = "settings.ini", temp_dir_name: str = "WinYandexMusicRPC") -> None:
        base_dir = os.getenv("LOCALAPPDATA") or "."
        self.temp_dir: str = os.path.join(base_dir, temp_dir_name)
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)

        self.config_file: str = os.path.join(self.temp_dir, config_file)
        self.config: configparser.ConfigParser = configparser.ConfigParser()
        self._load_config()

    def _load_config(self) -> None:
        if os.path.exists(self.config_file):
            self.config.read(self.config_file)
        else:
            with open(self.config_file, "w", encoding="utf-8") as file:
                self.config.write(file)

    def get_setting(self, section: str, option: str, fallback: str | None = None) -> str | None:
        if self.config.has_option(section, option):
            return self.config.get(section, option)
        if fallback is not None:
            self.set_setting(section, option, fallback)
        return fallback

    def set_setting(self, section: str, option: str, value: str) -> None:
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, value)
        self._save_config()

    def _save_config(self) -> None:
        with open(self.config_file, "w", encoding="utf-8") as configfile:
            self.config.write(configfile)

    def set_enum_setting(self, section: str, option: str, enum_value: Enum) -> None:
        self.set_setting(section, option, enum_value.name)

    def get_enum_setting(
        self, section: str, option: str, enum_type: type[E], fallback: E
    ) -> E:
        value = self.get_setting(section, option, fallback=fallback.name)
        if value is not None and value in enum_type.__members__:
            return enum_type[value]
        self.set_enum_setting(section, option, fallback)
        return fallback

    def get_selected_session(self) -> str:
        return self.get_setting("UserSettings", "selected_session", fallback="Automatic") or "Automatic"

    def set_selected_session(self, session_id: str) -> None:
        self.set_setting("UserSettings", "selected_session", session_id)

    def get_gemini_model(self) -> str:
        return self.get_setting("GeminiSettings", "model", fallback="gemini-3.5-flash-lite") or "gemini-3.5-flash-lite"

    def set_gemini_model(self, model: str) -> None:
        self.set_setting("GeminiSettings", "model", model)

    def get_recommendations_count(self) -> int:
        try:
            raw = self.get_setting("GeminiSettings", "count", fallback="6")
            return int(raw) if raw is not None else 6
        except (ValueError, TypeError):
            return 6

    def set_recommendations_count(self, count: int) -> None:
        self.set_setting("GeminiSettings", "count", str(count))
