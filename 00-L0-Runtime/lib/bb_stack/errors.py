class StackError(Exception):
    """Expected operator-facing error."""


class ValidationError(StackError):
    """Configuration or state failed a contract."""


class CommandError(StackError):
    """An external command could not complete."""
