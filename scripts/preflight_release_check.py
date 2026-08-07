from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]{20,}")
SECRET_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "data",
}


def main() -> None:
    args = parse_args()
    started_at = time.perf_counter()

    steps: list[tuple[str, list[str] | str | None]] = [
        (
            "python compile",
            [
                sys.executable,
                "-m",
                "py_compile",
                "backend/app/main.py",
                "scripts/p2_smoke_test.py",
                "scripts/p3_sqlite_smoke.py",
                "scripts/audit_knowledge_bank.py",
                "scripts/systemdesign_acceptance_audit.py",
                "scripts/llm_config_smoke.py",
                "scripts/llm_live_smoke.py",
                "scripts/full_stack_http_smoke.py",
            ],
        ),
        ("secret scan", None),
        (
            "powershell script syntax",
            [
                powershell_command(),
                "-NoProfile",
                "-Command",
                (
                    "$ErrorActionPreference='Stop'; "
                    "$files=@('scripts/start_local_demo.ps1','scripts/stop_local_demo.ps1','scripts/configure_llm_env.ps1'); "
                    "foreach($file in $files){ "
                    "$null=[scriptblock]::Create((Get-Content -Raw -LiteralPath $file)); "
                    "Write-Host \"syntax ok: $file\" "
                    "}"
                ),
            ],
        ),
        ("llm env script smoke", "llm_env_script_smoke"),
        ("llm dotenv parser smoke", "llm_dotenv_parser_smoke"),
        ("p2 smoke", [sys.executable, "scripts/p2_smoke_test.py"]),
        ("p3 sqlite smoke", [sys.executable, "scripts/p3_sqlite_smoke.py"]),
        ("knowledge bank audit", [sys.executable, "scripts/audit_knowledge_bank.py"]),
        (
            "systemdesign acceptance audit",
            [sys.executable, "scripts/systemdesign_acceptance_audit.py", "--allow-missing-manual"],
        ),
        ("llm config smoke", [sys.executable, "scripts/llm_config_smoke.py"]),
        (
            "llm live smoke",
            [
                sys.executable,
                "scripts/llm_live_smoke.py",
                *(["--require"] if args.require_live_llm else []),
            ],
        ),
    ]

    if not args.skip_frontend_build:
        steps.append(("frontend build", [pnpm_command(), "--dir", "frontend", "build"]))

    if args.full_stack:
        steps.append(
            (
                "full-stack HTTP smoke",
                [
                    sys.executable,
                    "scripts/full_stack_http_smoke.py",
                    "--p2-url",
                    args.p2_url,
                    "--p3-url",
                    args.p3_url,
                    "--frontend-url",
                    args.frontend_url,
                    "--min-questions",
                    str(args.min_questions),
                ],
            )
        )

    for name, command in steps:
        print(f"\n== {name} ==", flush=True)
        if command is None:
            run_secret_scan()
        elif command == "llm_env_script_smoke":
            run_llm_env_script_smoke(timeout=args.command_timeout)
        elif command == "llm_dotenv_parser_smoke":
            run_llm_dotenv_parser_smoke()
        else:
            run(command, timeout=args.command_timeout)

    elapsed = time.perf_counter() - started_at
    print(f"\npreflight release check passed in {elapsed:.1f}s", flush=True)
    print("api_key_leaked=false", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run release preflight checks for the Campus-System demo.")
    parser.add_argument(
        "--full-stack",
        action="store_true",
        help="Also run HTTP smoke against already-running P2/P3/frontend services.",
    )
    parser.add_argument("--p2-url", default="http://127.0.0.1:8000")
    parser.add_argument("--p3-url", default="http://127.0.0.1:8103")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5176")
    parser.add_argument("--min-questions", type=int, default=1200)
    parser.add_argument(
        "--require-live-llm",
        action="store_true",
        help="Fail if CAMPUS_LLM_* is missing or the OpenAI-compatible live call fails.",
    )
    parser.add_argument(
        "--skip-frontend-build",
        action="store_true",
        help="Skip pnpm frontend build. Useful when Node dependencies are unavailable.",
    )
    parser.add_argument("--command-timeout", type=float, default=180)
    return parser.parse_args()


def run(command: list[str], *, timeout: float) -> None:
    printable = " ".join(command)
    print(printable, flush=True)
    subprocess.run(command, cwd=ROOT, check=True, timeout=timeout, env=command_env())


def command_env() -> dict[str, str]:
    env = dict(os.environ)
    bundled_node = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
    )
    if bundled_node.exists():
        env["PATH"] = f"{bundled_node}{os.pathsep}{env.get('PATH', '')}"
    return env


def run_secret_scan() -> None:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or should_skip(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if SECRET_PATTERN.search(line):
                relative_path = path.relative_to(ROOT).as_posix()
                hits.append(f"{relative_path}:{line_number}")

    if hits:
        for hit in hits[:20]:
            print(hit)
        raise SystemExit("secret-like API key pattern found")

    print("no secret-like API keys found", flush=True)


def run_llm_env_script_smoke(*, timeout: float) -> None:
    with tempfile.TemporaryDirectory(prefix="campus-llm-env-") as temp_dir:
        env_path = Path(temp_dir) / ".env"
        command = [
            powershell_command(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "scripts/configure_llm_env.ps1",
            "-EnvPath",
            str(env_path),
            "-NoPrompt",
        ]
        run(command, timeout=timeout)
        raw = env_path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise SystemExit("llm env script smoke failed; generated .env contains a UTF-8 BOM")
        text = env_path.read_text(encoding="utf-8-sig")
        required_lines = [
            "CAMPUS_LLM_BASE_URL=https://token.zy-cjk.cn/v1",
            "CAMPUS_LLM_API_KEY=",
            "CAMPUS_LLM_MODEL=openai-compatible",
        ]
        missing = [line for line in required_lines if line not in text.splitlines()]
        if missing:
            raise SystemExit(f"llm env script smoke failed; missing lines: {missing}")
        if SECRET_PATTERN.search(text):
            raise SystemExit("llm env script smoke failed; secret-like key was written")
        print("llm env script smoke passed", flush=True)


def run_llm_dotenv_parser_smoke() -> None:
    module_path = ROOT / "scripts" / "llm_live_smoke.py"
    spec = importlib.util.spec_from_file_location("llm_live_smoke_for_preflight", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit("llm dotenv parser smoke failed; cannot load llm_live_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    load_dotenv = module.load_dotenv

    with tempfile.TemporaryDirectory(prefix="campus-llm-dotenv-") as temp_dir:
        env_path = Path(temp_dir) / ".env"
        env_path.write_text(
            "\ufeffCAMPUS_LLM_BASE_URL=https://token.zy-cjk.cn/v1\n"
            "CAMPUS_LLM_API_KEY=campus-parser-smoke-key\n"
            "CAMPUS_LLM_MODEL=openai-compatible\n",
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            load_dotenv(env_path)
            assert os.environ.get("CAMPUS_LLM_BASE_URL") == "https://token.zy-cjk.cn/v1"
            assert os.environ.get("CAMPUS_LLM_API_KEY") == "campus-parser-smoke-key"
            assert os.environ.get("CAMPUS_LLM_MODEL") == "openai-compatible"
    print("llm dotenv parser smoke passed", flush=True)


def should_skip(path: Path) -> bool:
    if path.name.startswith(".env") and path.name != ".env.example":
        return True
    parts = set(path.relative_to(ROOT).parts)
    return bool(parts & SECRET_EXCLUDED_DIRS)


def pnpm_command() -> str:
    discovered = shutil.which("pnpm")
    if discovered:
        return discovered
    bundled = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "bin"
        / "fallback"
        / "pnpm.cmd"
    )
    if bundled.exists():
        return str(bundled)
    raise SystemExit("pnpm is not available; rerun with --skip-frontend-build or install pnpm")


def powershell_command() -> str:
    discovered = shutil.which("powershell") or shutil.which("pwsh")
    if discovered:
        return discovered
    raise SystemExit("PowerShell is not available; required to validate local demo scripts")


if __name__ == "__main__":
    main()
