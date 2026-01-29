import unittest
import sys
import os

# Ensure we can import from parent directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.email_safety import sanitize_email_text, validate_send_safe, detect_ai_content_markers

class TestEmailSafety(unittest.TestCase):
    
    def test_sanitize_markdown_citations(self):
        input_text = "Gravie **ICHRA** grew 52%[6][2]. [proof]"
        expected = "Gravie ICHRA grew 52%."
        cleaned = sanitize_email_text(input_text)
        self.assertEqual(cleaned, expected)
        
        ok, reasons = validate_send_safe(cleaned)
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_preserve_bullets(self):
        input_text = "- * Item 1\n- * Item 2"
        # Current logic might strip * around Item if valid, but should leave leading - 
        # Actually my regex (?<!^)(?<!\n)\*(.*?)\* preserves start-of-line stars usually
        # Let's test standard markdown bullets
        input_text = "- Item 1\n- Item 2"
        cleaned = sanitize_email_text(input_text)
        self.assertEqual(cleaned, input_text)
        
    def test_preserve_legitimate_brackets(self):
        input_text = "We target SMBs (5–500 employees) [US]"
        cleaned = sanitize_email_text(input_text)
        self.assertEqual(cleaned, "We target SMBs (5-500 employees) [US]")
        
        ok, reasons = validate_send_safe(cleaned)
        self.assertTrue(ok)

    def test_validate_failure(self):
        unsafe = "This is **bold** and bad [12]."
        ok, reasons = validate_send_safe(unsafe)
        self.assertFalse(ok)
        self.assertIn("contains_markdown_emphasis", reasons)
        self.assertIn("contains_bracket_citations", reasons)
        
    def test_validate_placeholders(self):
        unsafe = "Check this [TODO]"
        ok, reasons = validate_send_safe(unsafe)
        self.assertFalse(ok)
        self.assertIn("contains_placeholders", reasons)

    def test_contrastive_framing_detection(self):
        text = "This hinges less on pilots and more on durable enterprise adoption."
        markers = detect_ai_content_markers(text)
        self.assertIn("contrastive_framing", markers)

    def test_question_count_detection(self):
        text = "Is this right? Does that resonate?"
        markers = detect_ai_content_markers(text)
        self.assertTrue(any(m.startswith("question_count_") for m in markers))

    def test_strip_placeholder_with_spaces(self):
        input_text = "This is a draft [sender profile] and should be cleaned."
        cleaned = sanitize_email_text(input_text)
        self.assertNotIn("[sender profile]", cleaned)

if __name__ == '__main__':
    unittest.main()
