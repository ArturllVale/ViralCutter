import unittest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock google.genai if not installed so tests can run in any environment
try:
    import google.genai as genai
    from google.genai.errors import APIError
except ImportError:
    import types
    genai = types.ModuleType("google.genai")
    errors = types.ModuleType("google.genai.errors")
    class APIError(Exception):
        def __init__(self, code=None, message=None):
            self.code = code
            self.message = message
            super().__init__(f"[{code}] {message}" if code else str(message))
    errors.APIError = APIError
    genai.errors = errors
    genai.Client = MagicMock
    google = types.ModuleType("google")
    google.genai = genai
    sys.modules["google"] = google
    sys.modules["google.genai"] = genai
    sys.modules["google.genai.errors"] = errors

import scripts.create_viral_segments as cvs
cvs.genai = genai
cvs.APIError = APIError
cvs.HAS_GEMINI = True
from scripts.create_viral_segments import call_gemini

class TestGeminiFallback(unittest.TestCase):
    @patch('scripts.create_viral_segments.genai.Client')
    def test_call_gemini_valid_model(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Valid model does not raise error
        mock_client.models.get.return_value = MagicMock(name='gemini-2.5-flash')

        mock_response = MagicMock()
        mock_response.text = "Valid response"
        mock_client.models.generate_content.return_value = mock_response

        res = call_gemini("Test prompt", "fake_key", "gemini-2.5-flash")

        mock_client.models.get.assert_called_once_with(model="gemini-2.5-flash")
        mock_client.models.generate_content.assert_called_once_with(
            model="gemini-2.5-flash", contents="Test prompt"
        )
        self.assertEqual(res, "Valid response")

    @patch('scripts.create_viral_segments.genai.Client')
    def test_call_gemini_invalid_model_fallback(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Simula erro de modelo não encontrado
        error = APIError(404, "Model not found")
        mock_client.models.get.side_effect = error

        mock_response = MagicMock()
        mock_response.text = "Fallback response"
        mock_client.models.generate_content.return_value = mock_response

        res = call_gemini("Test prompt", "fake_key", "invalid-model")

        # O script deve interceptar o 404 e usar o fallback 'gemini-2.5-flash'
        mock_client.models.get.assert_called_once_with(model="invalid-model")
        mock_client.models.generate_content.assert_called_once_with(
            model="gemini-2.5-flash", contents="Test prompt"
        )
        self.assertEqual(res, "Fallback response")

    @patch('scripts.create_viral_segments.genai.Client')
    def test_call_gemini_invalid_api_key(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Simula erro de chave de API
        error = APIError(400, "API key not valid")
        mock_client.models.get.side_effect = error

        with self.assertRaises(ValueError) as context:
            call_gemini("Test prompt", "invalid_key", "gemini-2.5-flash")

        self.assertIn("Chave de API Gemini inválida", str(context.exception))

if __name__ == '__main__':
    unittest.main()
