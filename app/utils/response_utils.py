"""
Standardized API response utilities for Video2Notes application.

Provides consistent response formatting across all API endpoints.
"""
from flask import jsonify
from typing import Optional, Any, Dict, Tuple


def success_response(
    data: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
    status_code: int = 200
) -> Tuple[Any, int]:
    """Create a standardized success response.

    Args:
        data: Optional dict of additional data to include
        message: Optional success message
        status_code: HTTP status code (default 200)

    Returns:
        Tuple of (jsonify response, status_code)
    """
    response = {'success': True}
    if message:
        response['message'] = message
    if data:
        response.update(data)
    return jsonify(response), status_code


def error_response(
    error: str,
    status_code: int = 400,
    details: Optional[Dict[str, Any]] = None
) -> Tuple[Any, int]:
    """Create a standardized error response.

    Args:
        error: Error message
        status_code: HTTP status code (default 400)
        details: Optional dict of additional error details

    Returns:
        Tuple of (jsonify response, status_code)
    """
    response = {
        'success': False,
        'error': error
    }
    if details:
        response['details'] = details
    return jsonify(response), status_code


def not_found_response(resource: str = "Resource") -> Tuple[Any, int]:
    """Create a standardized 404 not found response.

    Args:
        resource: Name of the resource that was not found

    Returns:
        Tuple of (jsonify response, 404)
    """
    return error_response(f"{resource} not found", 404)


def forbidden_response(reason: str = "Access denied") -> Tuple[Any, int]:
    """Create a standardized 403 forbidden response.

    Args:
        reason: Reason for the access denial

    Returns:
        Tuple of (jsonify response, 403)
    """
    return error_response(reason, 403)


def server_error_response(error: str = "Internal server error") -> Tuple[Any, int]:
    """Create a standardized 500 server error response.

    Args:
        error: Error message

    Returns:
        Tuple of (jsonify response, 500)
    """
    return error_response(error, 500)
