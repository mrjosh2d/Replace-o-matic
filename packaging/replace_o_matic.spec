# PyInstaller recipe for the desktop app. Build from the repository root:
#
#     pyinstaller --noconfirm packaging/replace_o_matic.spec
#     dist/Replace-o-matic/Replace-o-matic --self-test     # must print "self-test: ok"
#
# The model is bundled, so the installed app downloads nothing. Run
# scripts/fetch_model.py first. PyTorch, transformers and gliner are excluded
# on purpose: the app runs the model with onnxruntime alone (onnx_gliner.py).
# QtNetwork and the web modules are excluded so the app cannot open a
# connection through Qt. Build on each target system: PyInstaller does not
# cross-compile.
import os

root = os.path.abspath(os.path.join(SPECPATH, ".."))
model = os.path.join(root, "models", "gliner")
model_files = [
    (os.path.join(model, name), "models/gliner")
    for name in os.listdir(model)
    if os.path.isfile(os.path.join(model, name))
] + [(os.path.join(model, "onnx", "model.onnx"), "models/gliner/onnx")]

analysis = Analysis(
    [os.path.join(root, "gui", "app.py")],
    pathex=[root],
    datas=model_files,
    hiddenimports=["onnx_gliner", "pdf_io", "docx_io", "sanitizer_service", "sanitizer_cli"],
    excludes=[
        "torch", "transformers", "gliner", "huggingface_hub", "tensorflow", "scipy", "pandas",
        "matplotlib", "pytest", "IPython", "tkinter",
        "PySide6.QtNetwork", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebSockets", "PySide6.QtWebChannel", "PySide6.QtQml", "PySide6.QtQuick",
        "PySide6.QtPdf", "PySide6.QtMultimedia", "PySide6.QtSql", "PySide6.QtBluetooth",
    ],
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    exclude_binaries=True,
    name="Replace-o-matic",
    console=False,  # no terminal window; --self-test still prints when run from one
    upx=False,
)
COLLECT(exe, analysis.binaries, analysis.datas, name="Replace-o-matic", upx=False)
