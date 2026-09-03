from .api import (
    get_first_organization,
    get_first_superadmin,
    get_registered_setup_steps,
    get_setup_status,
    get_user_by_email,
    has_organization,
    has_superadmin,
    is_setup_initialized,
    resolve_setup_step,
    submit_setup_step,
)
from .dsl._init_steps import init_setup_steps
from .dsl.registry import (
    clear as clear_setup_steps,
    get as get_setup_step,
    get_all as get_all_setup_steps,
)

from .exceptions import SetupConflictError, SetupValidationError

__all__ = [
    "clear_setup_steps",
    "get_setup_step",
    "get_all_setup_steps",
    "get_registered_setup_steps",
    "resolve_setup_step",
    "get_setup_status",
    "is_setup_initialized",
    "submit_setup_step",
    "has_organization",
    "has_superadmin",
    "get_first_organization",
    "get_first_superadmin",
    "get_user_by_email",
    "SetupConflictError",
    "SetupValidationError",
]

init_setup_steps()
