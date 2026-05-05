from pathlib import Path
from unittest.mock import MagicMock, patch
import cli
import json
import traceback

def _mock_client() -> MagicMock:
    client = MagicMock()
    first = MagicMock()
    first.choices = [MagicMock(message=MagicMock(content="- point 1\n- point 2\n- point 3"))]
    first.usage = MagicMock(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    second = MagicMock()
    second.choices = [MagicMock(message=MagicMock(content="1. Plaintiff won\n2. Yes\n3. 30\n4. High Court\n5. 5000\n6. File appeal\n7. 30 days"))]
    second.usage = MagicMock(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    client.chat.completions.create.side_effect = [first, second]
    return client

mock_core = MagicMock()
mock_core.extract_text_with_diagnostics.return_value = {
    "text": "Sample judgment text",
    "method": "ocr_tesseract",
    "ocr_used": True,
    "confidence": 88.2,
}

try:
    with patch.object(cli, "core", mock_core):
        result = cli.process_one_pdf(
            pdf_path=Path("sample.pdf"),
            client=_mock_client(),
            language_arg="English",
            model="test-model",
            max_chars=5000,
            prompt_cost_per_1k=0.0,
            completion_cost_per_1k=0.0,
            enable_ocr=True,
            ocr_languages="eng+hin",
            ocr_dpi=300,
        )

    print("Status:", result["status"])
    print("Error:", result.get("error", "NO ERROR"))
    print("Extraction method:", result.get("extraction_method"))
    print("OCR used:", result.get("ocr_used"))
except Exception as e:
    print("Exception occurred:", e)
    traceback.print_exc()
