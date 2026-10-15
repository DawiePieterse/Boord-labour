"""Set or reset the admin PIN, from the server console.

    cd backend
    .venv\\Scripts\\python set_pin.py

Deliberately not possible from the web page - see admin_auth.py. Setting a
new PIN signs every phone out of /admin/.
"""
import getpass
import sys

import admin_auth

pin = getpass.getpass(f"New admin PIN (at least {admin_auth.MIN_PIN_LENGTH} characters): ")
if getpass.getpass("Type it again: ") != pin:
    sys.exit("The two PINs differ - nothing changed.")
try:
    admin_auth.set_pin(pin)
except ValueError as e:
    sys.exit(f"{e} - nothing changed.")
print("Admin PIN set. Every phone will need to sign in to /admin/ again.")
