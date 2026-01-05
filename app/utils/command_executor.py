"""
Command execution utilities for Video2Notes application.
"""
import os
import subprocess
import threading
from typing import List, Dict, Optional, Any
from flask import current_app

# Default timeout for subprocess execution (1 hour)
DEFAULT_SUBPROCESS_TIMEOUT = int(os.getenv('SUBPROCESS_TIMEOUT', 3600))


def execute_command(command: List[str], description: str, log_callback=None,
                    timeout: int = None) -> bool:
    """Execute a command and capture output in real-time.

    Args:
        command: Command and arguments to execute
        description: Description of the command for logging
        log_callback: Optional callback for log messages
        timeout: Timeout in seconds (default: DEFAULT_SUBPROCESS_TIMEOUT)

    Returns:
        True if command completed successfully, False otherwise
    """
    if log_callback is None:
        log_callback = _default_log_callback

    if timeout is None:
        timeout = DEFAULT_SUBPROCESS_TIMEOUT

    log_callback(f"Starting: {description}")
    log_callback(f"Command: {' '.join(command)}")

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True
        )

        # Use a thread to read output to avoid blocking
        output_lines = []
        read_complete = threading.Event()

        def read_output():
            try:
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        log_callback(line)
                        output_lines.append(line)
            finally:
                read_complete.set()

        reader_thread = threading.Thread(target=read_output, daemon=True)
        reader_thread.start()

        # Wait for process with timeout
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log_callback(f"⏰ Timeout ({timeout}s) exceeded for {description}, terminating process")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log_callback(f"⚠️ Process did not terminate gracefully, killing")
                process.kill()
            return False

        # Wait for reader thread to finish (with small timeout)
        reader_thread.join(timeout=5)

        if return_code == 0:
            log_callback(f"✅ {description} completed successfully")
            return True
        else:
            log_callback(f"❌ {description} failed with return code {return_code}")
            return False

    except Exception as e:
        log_callback(f"❌ Error executing {description}: {str(e)}")
        return False


def execute_command_with_env(command: List[str], description: str, env: Dict[str, str],
                             log_callback=None, timeout: int = None) -> bool:
    """Execute a command with environment variables and capture output in real-time.

    Args:
        command: Command and arguments to execute
        description: Description of the command for logging
        env: Environment variables for the subprocess
        log_callback: Optional callback for log messages
        timeout: Timeout in seconds (default: DEFAULT_SUBPROCESS_TIMEOUT)

    Returns:
        True if command completed successfully, False otherwise
    """
    if log_callback is None:
        log_callback = _default_log_callback

    if timeout is None:
        timeout = DEFAULT_SUBPROCESS_TIMEOUT

    log_callback(f"Starting: {description}")
    log_callback(f"Command: {' '.join(command)}")

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
            env=env
        )

        # Use a thread to read output to avoid blocking
        output_lines = []

        def read_output():
            for line in process.stdout:
                line = line.strip()
                if line:
                    log_callback(line)
                    output_lines.append(line)

        reader_thread = threading.Thread(target=read_output, daemon=True)
        reader_thread.start()

        # Wait for process with timeout
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            log_callback(f"⏰ Timeout ({timeout}s) exceeded for {description}, terminating process")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log_callback(f"⚠️ Process did not terminate gracefully, killing")
                process.kill()
            return False

        # Wait for reader thread to finish
        reader_thread.join(timeout=5)

        if return_code == 0:
            log_callback(f"✅ {description} completed successfully")
            return True
        else:
            log_callback(f"❌ {description} failed with return code {return_code}")
            return False

    except Exception as e:
        log_callback(f"❌ Error executing {description}: {str(e)}")
        return False


def execute_command_with_output(command: List[str], description: str = None,
                                timeout: int = None) -> tuple[bool, str]:
    """Execute a command and return success status and output.

    Args:
        command: Command and arguments to execute
        description: Optional description for logging
        timeout: Timeout in seconds (default: DEFAULT_SUBPROCESS_TIMEOUT)

    Returns:
        Tuple of (success, output)
    """
    if timeout is None:
        timeout = DEFAULT_SUBPROCESS_TIMEOUT

    if description:
        current_app.logger.info(f"Executing: {description}")
        current_app.logger.debug(f"Command: {' '.join(command)}")

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout
        )

        output = result.stdout + result.stderr
        success = result.returncode == 0

        if description:
            if success:
                current_app.logger.info(f"{description} completed successfully")
            else:
                current_app.logger.error(f"{description} failed with return code {result.returncode}")
                current_app.logger.error(f"Output: {output}")

        return success, output

    except subprocess.TimeoutExpired as e:
        error_msg = f"Timeout ({timeout}s) exceeded"
        if description:
            current_app.logger.error(f"{description} timed out: {error_msg}")
        return False, error_msg

    except Exception as e:
        error_msg = f"Error executing command: {str(e)}"
        if description:
            current_app.logger.error(f"{description} failed: {error_msg}")
        return False, error_msg


def build_command_args(base_command: List[str], **kwargs) -> List[str]:
    """Build command arguments from keyword arguments."""
    command = base_command.copy()
    
    for key, value in kwargs.items():
        if value is True:
            # Boolean flag
            command.append(f"--{key}")
        elif value is not False and value is not None:
            # Key-value pair
            command.extend([f"--{key}", str(value)])
    
    return command


def validate_command_exists(command: str) -> bool:
    """Check if a command exists in the system PATH."""
    try:
        subprocess.run(
            ["which", command] if os.name != 'nt' else ["where", command],
            capture_output=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _default_log_callback(message: str) -> None:
    """Default logging callback."""
    current_app.logger.info(message)