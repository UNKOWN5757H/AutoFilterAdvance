import ast
import builtins
import sys
from pathlib import Path

BUILTINS = set(dir(builtins)) | {
    "__name__", "__file__", "__doc__", "__package__", "__spec__",
    "__loader__", "__builtins__", "__annotations__", "__dict__",
    "__class__", "__module__", "__qualname__", "_",
}

def targets_names(node):
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from targets_names(elt)
    elif isinstance(node, ast.Starred):
        yield from targets_names(node.value)

def collect_bound_names(tree):
    bound = set(BUILTINS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.NamedExpr):
            bound.update(targets_names(node.target))
        elif isinstance(node, ast.MatchAs) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.MatchStar) and node.name:
            bound.add(node.name)
        elif hasattr(ast, "TypeAlias") and isinstance(node, ast.TypeAlias):
            if isinstance(node.name, ast.Name):
                bound.add(node.name.id)
    return bound

def find_undefined(tree, bound):
    issues = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in bound:
                issues.append((node.lineno, node.id))
    return sorted(set(issues))

def find_duplicate_defs(tree):
    dups = []
    def scan_body(body, scope_label):
        seen = {}
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in seen:
                    dups.append((node.lineno, node.name, seen[node.name], scope_label))
                seen[node.name] = node.lineno
            if isinstance(node, ast.ClassDef):
                scan_body(node.body, f"class '{node.name}'")
    scan_body(tree.body, "module")
    return dups

def find_bare_except(tree):
    return [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.ExceptHandler) and n.type is None
    ]

def find_mutable_defaults(tree):
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_defaults = node.args.defaults + node.args.kw_defaults
            for d in all_defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    bad.append((node.lineno, node.name))
                elif isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == "set":
                    bad.append((node.lineno, node.name))
    return bad

def main():
    if len(sys.argv) < 2:
        print("Usage: python check_undefined.py <directory_to_scan>")
        sys.exit(1)

    root = Path(sys.argv[1])
    if not root.exists():
        print(f"Error: Path '{root}' does not exist.")
        sys.exit(1)

    files = sorted(root.rglob("*.py"))

    for f in files:
        src = f.read_text(encoding="utf-8", errors="replace")
        try: tree = ast.parse(src, filename=str(f))
        except SyntaxError as e:
            print(f"\n### {f.relative_to(root)}  -- SYNTAX ERROR: {e}")
            continue

        bound = collect_bound_names(tree)
        undefined = find_undefined(tree, bound)
        dups = find_duplicate_defs(tree)
        bare = find_bare_except(tree)
        mut = find_mutable_defaults(tree)

        if undefined or dups or bare or mut:
            print(f"\n### {f.relative_to(root)}")
            for lineno, name in undefined: print(f"  [undefined-name?] line {lineno}: '{name}' not defined/imported anywhere in this file")
            for lineno, name, first_line, scope in dups: print(f"  [duplicate-def] '{name}' redefined at line {lineno} (first defined line {first_line}, in {scope})")
            for lineno in bare: print(f"  [bare-except] line {lineno}: bare 'except:' catches everything incl. SystemExit/KeyboardInterrupt")
            for lineno, name in mut: print(f"  [mutable-default-arg] def {name}(...) at line {lineno} uses a mutable default")

if __name__ == "__main__":
    main()
