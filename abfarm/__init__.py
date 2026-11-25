"""abfarm - automated Abliteration account provisioning.

Clean-room rewrite: the page's own Turnstile widget mints and spends its token
in one session; no captcha services, no referral codes.
"""
from .config import Config
from .signup import Account, SignupError, run_one, signup

__all__ = ["Config", "Account", "SignupError", "run_one", "signup"]
__version__ = "0.1.0"
