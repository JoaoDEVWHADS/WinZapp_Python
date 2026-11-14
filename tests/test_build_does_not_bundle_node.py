"""A build with the Neonize bridge does not carry Node.js: WPPConnect downloads
it when chosen. build.py is read by AST (importing it downloads assets)."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _stages_node():
    tree = ast.parse((ROOT / "build.py").read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "stages_node")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "build.py", "exec"), namespace)
    return namespace["stages_node"]


def test_node_is_left_out_when_the_bridge_is_staged():
    assert _stages_node()(True) is False


def test_node_stays_in_a_build_without_the_bridge():
    assert _stages_node()(False) is True


def test_the_staging_copies_node_only_through_the_decision():
    source = (ROOT / "build.py").read_text(encoding="utf-8")
    assert "if stages_node(" in source
    assert len(re.findall(r"copytree\(NODE_DIR", source)) == 1


def test_the_release_check_wants_no_node_in_the_zip():
    workflow = (ROOT / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
    assert "$noNodeExe" in workflow and "$hasNodeExe" not in workflow
