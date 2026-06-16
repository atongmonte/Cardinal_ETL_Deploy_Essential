"""
windows_impersonation.py
------------------------
Context manager for Windows identity impersonation using pywin32.

Uses LogonUser with LOGON32_LOGON_NEW_CREDENTIALS (equivalent to
'runas /netonly') which redirects ALL outbound network credentials
(SQL Server Kerberos, SMB/net use) to the specified account while
keeping the local Windows token unchanged.

Usage
-----
    from windows_impersonation import impersonate_user

    with impersonate_user(domain, username, password):
        cnxn = pyodbc.connect("...Trusted_Connection=yes;")
        # SQL Server now sees the impersonated account
"""

import contextlib
import win32security
import win32con

# LOGON32_LOGON_NEW_CREDENTIALS (9):
#   Creates a new credential set for outbound network connections only.
#   The local token (file system, registry, etc.) stays as the original user.
#   Equivalent to: runas /netonly /user:DOMAIN\user
#   Ideal for: SQL Server Trusted Connection, SMB shares, LDAP across the network.
_LOGON_TYPE     = 9   # LOGON32_LOGON_NEW_CREDENTIALS
_LOGON_PROVIDER = 3   # LOGON32_PROVIDER_WINNT50


@contextlib.contextmanager
def impersonate_user(domain: str, username: str, password: str):
    """
    Context manager that impersonates *domain*\\*username* for the duration
    of the with-block.  All outbound network calls made inside the block
    will authenticate as the specified account.

    Parameters
    ----------
    domain   : str  e.g. 'DM_MONTYNT'
    username : str  e.g. 'svc_procure_data'
    password : str  plaintext password (decrypt from .env before passing)

    Yields
    ------
    win32security token handle (rarely needed directly)

    Example
    -------
    >>> with impersonate_user('DM_MONTYNT', 'svc_procure_data', pwd):
    ...     cnxn = pyodbc.connect('...Trusted_Connection=yes;')
    """
    token = win32security.LogonUser(
        username,
        domain,
        password,
        _LOGON_TYPE,
        _LOGON_PROVIDER,
    )
    win32security.ImpersonateLoggedOnUser(token)
    try:
        yield token
    finally:
        win32security.RevertToSelf()
        token.Close()


def whoami_network() -> str:
    """
    Return the username that outbound network connections currently run as.
    Useful for verifying that impersonation is active.
    """
    import win32api
    return win32api.GetUserName()
