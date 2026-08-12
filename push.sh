#!/usr/bin/env bash
# Tekshiruvlar yiqilsa push BO'LMAYDI. Bu shart — taxmin bilan deploy qilish
# eng yomon yo'l.
set -euo pipefail

MSG="${1:-}"
if [ -z "$MSG" ]; then
  echo "Ishlatilishi: ./push.sh \"commit matni\""
  exit 1
fi

fail() { echo "❌ $1"; exit 1; }

echo "1/5 Python sintaksisi (ast.parse)"
python3 - <<'PY' || exit 1
import ast, pathlib, sys
bad = 0
for f in pathlib.Path(".").rglob("*.py"):
    if any(p in f.parts for p in (".venv", "venv", "__pycache__")):
        continue
    try:
        ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
    except SyntaxError as e:
        print(f"  {f}:{e.lineno} {e.msg}")
        bad += 1
sys.exit(1 if bad else 0)
PY

echo "2/5 Yashirin escape muammolari (SyntaxWarning)"
python3 - <<'PY' || exit 1
import pathlib, py_compile, sys, warnings
warnings.simplefilter("error", SyntaxWarning)
bad = 0
for f in pathlib.Path(".").rglob("*.py"):
    if any(p in f.parts for p in (".venv", "venv", "__pycache__")):
        continue
    try:
        py_compile.compile(str(f), doraise=True, quiet=1)
    except Exception as e:
        print(f"  {f}: {e}")
        bad += 1
sys.exit(1 if bad else 0)
PY

echo "3/5 Webapp JS bloklari (node --check)"
if command -v node >/dev/null 2>&1; then
  shopt -s nullglob
  for f in bot/webapp/static/*.js; do
    node --check "$f" || fail "JS sintaksisi: $f"
  done
  python3 - <<'PY' || exit 1
# Shablon ichidagi <script> bloklarini ajratib node --check ga beradi
import pathlib, re, subprocess, sys, tempfile
bad = 0
pat = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)
for f in pathlib.Path("bot/webapp/templates").rglob("*.html"):
    text = f.read_text(encoding="utf-8")
    for i, block in enumerate(pat.findall(text)):
        if "{{" in block or "{%" in block:
            continue  # Jinja aralashgan blok — node tushunmaydi
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as tmp:
            tmp.write(block)
            path = tmp.name
        r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        if r.returncode:
            print(f"  {f} #{i}: {r.stderr.strip().splitlines()[:2]}")
            bad += 1
sys.exit(1 if bad else 0)
PY
else
  echo "  node topilmadi — o'tkazib yuborildi"
fi

echo "4/5 Duplikat funksiya nomlari"
python3 - <<'PY' || exit 1
import ast, pathlib, sys
bad = 0
for f in pathlib.Path("bot").rglob("*.py"):
    tree = ast.parse(f.read_text(encoding="utf-8"))
    seen = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in seen:
                print(f"  {f}:{node.lineno} takroriy def {node.name} "
                      f"(birinchisi {seen[node.name]}-qatorda)")
                bad += 1
            seen[node.name] = node.lineno
sys.exit(1 if bad else 0)
PY

echo "5/5 Testlar"
python3 -m pytest -q || fail "testlar yiqildi"

echo "✅ Hammasi o'tdi — push qilinmoqda"
git add -A
git commit -m "$MSG"
git push origin HEAD
echo "commit sha: $(git rev-parse --short HEAD)"
