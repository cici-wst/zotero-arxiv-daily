import subprocess
import sys


def test_importing_utils_does_not_load_optional_onnx_runtime():
    script = (
        "import sys; "
        "import zotero_arxiv_daily.utils; "
        "assert 'pymupdf4llm' not in sys.modules; "
        "assert 'onnxruntime' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
