DEFAULT_USER_ID = "local-default-user"
DEFAULT_USER_EMAIL = "local@example.com"
DEFAULT_USER_NAME = "Local User"

DEFAULT_WORKSPACE_ID = "local-default-workspace"
DEFAULT_WORKSPACE_NAME = "Local Workspace"
DEFAULT_WORKSPACE_SLUG = "local"


def get_current_user_id() -> str:
    return DEFAULT_USER_ID


def get_current_workspace_id() -> str:
    return DEFAULT_WORKSPACE_ID
