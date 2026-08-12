$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$atlasPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $atlasPython)) {
    throw "Atlas Python was not found at $atlasPython. Create the project environment and install requirements.txt first."
}

Push-Location $projectRoot
try {
    Write-Host "Checking Atlas dependencies..."
    & $atlasPython -c "from PIL import Image; import reportlab, streamlit, pytest; print(f'Python environment ready: Pillow {Image.__version__}, ReportLab {reportlab.Version}, Streamlit {streamlit.__version__}')"
    if ($LASTEXITCODE -ne 0) { throw "Dependency check failed." }

    Write-Host "Running automated tests..."
    & $atlasPython -m pytest -q -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "Automated tests failed." }

    Write-Host "Rendering every Atlas page headlessly..."
    & $atlasPython -c "import os; from streamlit.testing.v1 import AppTest; pages=['Start here','Market','Discover','Portfolio','Accuracy','Financial health','Stress test','Valuation lab','Research','Backtest','Compare','Changes','Thesis tracker','Alerts','Provider health','Data readiness','Settings','Report history']; failures=[]; [os.environ.__setitem__('ATLAS_TEST_PAGE', page) or (lambda app: (app.run(), failures.extend((page, item.value) for item in app.exception)))(AppTest.from_file('app.py', default_timeout=45)) for page in pages]; os.environ.pop('ATLAS_TEST_PAGE', None); print(f'Pages rendered: {len(pages)}; exceptions: {len(failures)}'); [print(page, error) for page, error in failures]; raise SystemExit(1 if failures else 0)"
    if ($LASTEXITCODE -ne 0) { throw "Headless Streamlit validation failed." }

    Write-Host "Atlas verification passed."
}
finally {
    Pop-Location
}
