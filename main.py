#!/usr/bin/env python3
"""
FastAPI server to receive commands and execute crush.exe in a separate PowerShell terminal
"""

import subprocess
import logging
import asyncio
import json
import os
import tempfile
import shlex
from typing import Dict, Any, Optional, Union, List
from pathlib import Path
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import sys
import re

# Ensure asyncio subprocess support on Windows (fix NotImplementedError)
if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Crush Command API",
    description="API to execute crush.exe commands in separate PowerShell terminals",
    version="1.0.0"
)

class CommandRequest(BaseModel):
    """Request model for command execution"""
    prompt: str = Field(..., description="The prompt to send to crush")
    model: Optional[Union[str, List[str]]] = Field("openai:gpt-4o", description="Model(s) to use (provider:model). Accepts a string or a list of strings.")
    cwd: Optional[str] = Field(None, description="Current working directory")
    yolo: bool = Field(True, description="Automatically accept all permissions")
    debug: bool = Field(False, description="Enable debug mode")
    quiet: bool = Field(False, description="Hide spinner when using --prompt")

# --- api response model ---
class CommandResponse(BaseModel):
    """Response model for command execution"""
    success: bool
    command: str
    message: str
    process_id: Optional[int] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    exit_code: Optional[int] = None
    duration: Optional[float] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost: Optional[float] = None

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    crush_exe_exists: bool
    crush_path: str

def check_crush_executable() -> tuple[bool, str]:
    """Check if crush.exe exists and return its path"""
    current_dir = Path.cwd()
    crush_path = current_dir / "crush.exe"
    
    if crush_path.exists():
        return True, str(crush_path)
    
    # Check if it's in PATH
    try:
        result = subprocess.run(
            ["where", "crush.exe"], 
            capture_output=True, 
            text=True, 
            shell=True
        )
        if result.returncode == 0:
            return True, result.stdout.strip().split('\n')[0]
    except Exception:
        pass
    
    return False, ""

def run_powershell_sync(command: str, cwd: Optional[str] = None) -> tuple[str, str, int]:
    """Run a PowerShell command synchronously and capture stdout/stderr."""
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-Command", f"& {{ {command} }}",
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        shell=False,
    )
    return completed.stdout or "", completed.stderr or "", completed.returncode

def run_process_sync(exe: str, args: list[str], cwd: Optional[str] = None) -> tuple[str, str, int]:
    """Run a process directly (no PowerShell) and capture stdout/stderr."""
    completed = subprocess.run(
        [exe, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        shell=False,
    )
    return completed.stdout or "", completed.stderr or "", completed.returncode

ansi_escape_re = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

def strip_ansi(text: Optional[str]) -> str:
    if not text:
        return ""
    return ansi_escape_re.sub("", text)

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    crush_exists, crush_path = check_crush_executable()
    
    return HealthResponse(
        status="healthy" if crush_exists else "unhealthy",
        crush_exe_exists=crush_exists,
        crush_path=crush_path
    )

async def execute_in_separate_terminal(command: str, work_dir: str) -> tuple[bool, str, int]:
    """Execute a command in a new PowerShell terminal window that automatically closes when done."""

    try:
        # Always set-location to the directory containing crush.exe so relative paths work.
        ps_command = f"Set-Location \"{work_dir}\"; {command}"

        # Build the full cmd.exe start command. The empty string after start sets the window title.
        # We pass -NoExit so the window stays open for the entire duration of crush.exe. When crush
        # finishes the PowerShell session ends and the terminal closes automatically.
        full_cmd = [
            "cmd", "/c", "start", "", "powershell", "-NoLogo", "-Command", ps_command
        ]

        # Launch without blocking and without using shell=True to avoid the previous error
        process = subprocess.Popen(full_cmd, cwd=work_dir)

        return True, f"Command started in separate terminal (PID: {process.pid})", process.pid

    except Exception as e:
        return False, f"Failed to start command in separate terminal: {str(e)}", -1

@app.post("/execute", response_model=CommandResponse)
async def execute_command(request: CommandRequest, background_tasks: BackgroundTasks):
    """Execute a crush command in a separate PowerShell terminal"""
    
    # Check if crush.exe exists
    crush_exists, crush_path = check_crush_executable()
    if not crush_exists:
        raise HTTPException(
            status_code=500, 
            detail=f"crush.exe not found. Expected at: {crush_path}"
        )
    
    # Helper to escape a string for PowerShell by wrapping in double quotes and doubling internal quotes
    def escape_ps_arg(val: str) -> str:
        val = val.replace('"', '""')  # PowerShell escape
        return f'"{val}"'

    # Build the command without shlex.quote (which adds single quotes that confuse PowerShell)
    cmd_parts = [
        ".\\crush.exe",  # relative path, runs the binary located in work_dir
        "-p", escape_ps_arg(request.prompt),
        "-m", request.model  # model flag does not need quoting
    ]

    if request.cwd:
        cmd_parts.extend(["--cwd", escape_ps_arg(request.cwd)])

    # Append permission and debug flags in fixed order
    if request.yolo:
        cmd_parts.append("-y")

    if request.debug:
        cmd_parts.append("-d")

    if request.quiet:
        cmd_parts.append("-q")

    command = " ".join(cmd_parts)

    logger.info(f"Executing command (capturing output only): {command}")

    try:
        # Directory where crush.exe resides; we will run PowerShell from there
        bin_dir = os.path.dirname(crush_path)

        # Prefer running the binary directly to avoid PowerShell quoting issues with multi-line prompts
        exe_path = os.path.join(bin_dir, "crush.exe")
        argv: list[str] = [
            "-p", request.prompt,
        ]
        # Accept either a single model or a list of models and pass them through as repeated -m flags
        if isinstance(request.model, list):
            for m in request.model:
                if m:
                    argv.extend(["-m", m])
        elif isinstance(request.model, str) and request.model:
            argv.extend(["-m", request.model])
        if request.cwd:
            argv.extend(["--cwd", request.cwd])
        if request.yolo:
            argv.append("-y")
        if request.debug:
            argv.append("-d")
        if request.quiet:
            argv.append("-q")

        # Run and capture output
        import time
        start_ts = time.time()
        stdout_text, stderr_text, return_code = await asyncio.to_thread(
            run_process_sync, exe_path, argv, bin_dir
        )
        duration = time.time() - start_ts

        # Strip ANSI sequences from outputs
        cleaned_stdout = strip_ansi(stdout_text).strip()
        cleaned_stderr = strip_ansi(stderr_text).strip()

        # Consider success when exit code is 0, or when stdout has content and stderr only contains ANSI control codes
        success = (return_code == 0) or (cleaned_stdout != "" and cleaned_stderr == "")

        # Try to read token/cost data from the crush SQLite DB (best-effort)
        prompt_toks = None
        completion_toks = None
        cost_val: Optional[float] = None
        model_used = None
        provider_used = None
        try:
            db_path = os.path.join(bin_dir, ".crush", "crush.db")
            if os.path.exists(db_path):
                import sqlite3, time as _t
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT prompt_tokens, completion_tokens, cost FROM sessions ORDER BY created_at DESC LIMIT 1")
                row = cur.fetchone()
                conn.close()
                if row:
                    prompt_toks = row["prompt_tokens"]
                    completion_toks = row["completion_tokens"]
                    cost_val = row["cost"]
                    model_used = row["model"] if row["model"] else None
                    provider_used = row["provider"] if row["provider"] else None
        except Exception:
            pass  # ignore db errors, keep response lean

        response = CommandResponse(
            success=success,
            command=command,
            message=f"Command completed successfully in {duration:.2f}s" if success else f"Command failed after {duration:.2f}s",
            stdout=cleaned_stdout if cleaned_stdout else None,
            stderr=cleaned_stderr if cleaned_stderr else None,
            exit_code=return_code,
            duration=duration,
            prompt_tokens=prompt_toks,
            completion_tokens=completion_toks,
            cost=cost_val,
            model=model_used,
            provider=provider_used,
        )

        return response
        
    except Exception as e:
        logger.error(f"Exception during command execution: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Command execution failed: {str(e)}")

@app.post("/execute-raw")
async def execute_raw_command(command: str, background_tasks: BackgroundTasks):
    """Execute a raw PowerShell command and return captured output (no extra terminal)."""
    logger.info(f"Executing raw command (capturing output): {command}")
    try:
        import time
        start_ts = time.time()
        stdout_text, stderr_text, return_code = await asyncio.to_thread(
            run_powershell_sync, command, None
        )
        duration = time.time() - start_ts
        cleaned_stdout = strip_ansi(stdout_text).strip()
        cleaned_stderr = strip_ansi(stderr_text).strip()
        success = (return_code == 0) or (cleaned_stdout != "" and cleaned_stderr == "")

        return CommandResponse(
            success=success,
            command=command,
            message=f"Completed in {duration:.2f}s" if success else f"Failed after {duration:.2f}s",
            process_id=None,
            stdout=cleaned_stdout if cleaned_stdout else None,
            stderr=cleaned_stderr if cleaned_stderr else None,
            exit_code=return_code,
            duration=duration,
        )
    except Exception as e:
        logger.error(f"Exception during raw command execution: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Raw command execution failed: {str(e)}")

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Crush Command API - Separate Terminal Mode",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "execute": "/execute",
            "execute_raw": "/execute-raw",
            "docs": "/docs"
        },
        "note": "All commands run in separate PowerShell terminal windows"
    }

if __name__ == "__main__":
    # Check if crush.exe exists before starting server
    crush_exists, crush_path = check_crush_executable()
    if not crush_exists:
        logger.warning(f"crush.exe not found at expected location: {crush_path}")
        logger.warning("Server will start but commands may fail")
    
    # Start the server
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=9000,
        reload=True,
        log_level="warning"  # Reduces startup noise
    )
