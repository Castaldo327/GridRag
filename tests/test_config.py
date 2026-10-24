"""Settings load once from .env and the environment, with the exported values winning."""

import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from gridrag.config import Settings, load_settings


class SettingsTests(unittest.TestCase):
    def test_exported_values_win_over_the_local_file_and_key_spellings_are_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("# local\nexport OPENAI_API_KEY='from-file'\nGRIDRAG_ANSWER_MODEL=file-model\n")
            local = load_settings(env_file, {})
            self.assertEqual((local.openai_api_key, local.answer_model), ("from-file", "file-model"))
            exported = load_settings(env_file, {"OPEN_AI_KEY": "exported", "GRIDRAG_ANSWER_MODEL": "env-model"})
            self.assertEqual((exported.openai_api_key, exported.answer_model), ("exported", "env-model"))
            missing = load_settings(Path(tmp) / "missing", {"GRIDRAG_DECISIONS_MODEL": ""})
            self.assertEqual((missing.openai_api_key, missing.decisions_model), (None, Settings().decisions_model))

    def test_settings_are_frozen_and_never_print_the_key(self):
        settings = Settings(openai_api_key="secret")
        with self.assertRaises(FrozenInstanceError):
            settings.sql_max_rows = 1
        with self.assertRaises(TypeError):
            settings.prices["decisions"] = settings.prices["responses"]
        self.assertNotIn("secret", repr(settings))


if __name__ == "__main__":
    unittest.main()
