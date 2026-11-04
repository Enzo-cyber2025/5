from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "apk-fix/java/com/ggufchat/app"


class AssistantOptionsSourceTest(unittest.TestCase):
    def test_chat_button_and_generation_hooks_are_present(self):
        compact = (JAVA / "CompactUi.java").read_text()
        inference = (JAVA / "AttachmentInference.java").read_text()
        self.assertIn("AssistantOptions.button(activity)", compact)
        self.assertIn("AssistantOptions.applyClarification(c,rows)", inference)
        self.assertIn("AssistantOptions.captureContext(c,chat,rows)", inference)
        self.assertIn("Context archive failed; continuing generation", inference)

    def test_archive_is_opt_in_local_and_bounded(self):
        source = (JAVA / "AssistantOptions.java").read_text()
        self.assertIn('getBoolean(ARCHIVE, false)', source)
        self.assertIn('new File(c.getFilesDir(), "context-archive")', source)
        self.assertIn("MAX_PER_CHAT_BYTES = 8L * 1024L * 1024L", source)
        self.assertIn("Math.min(2048, p.getInt(QUOTA_MB, DEFAULT_QUOTA_MB))", source)
        self.assertIn("Collections.sort(old, Comparator.comparingLong(File::lastModified))", source)
        self.assertIn('setNeutralButton("Apagar arquivo"', source)

    def test_questions_are_opt_in_and_added_to_system_role(self):
        source = (JAVA / "AssistantOptions.java").read_text()
        self.assertIn('getBoolean(ASK, false)', source)
        self.assertIn('!"system".equals(rows.get(0)[0])', source)
        self.assertIn("faça uma pergunta curta de esclarecimento", source)


if __name__ == "__main__":
    unittest.main()
