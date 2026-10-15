"""set_pin.py must still set a PIN on a console where hidden typing fails
(AnyDesk on the farm server makes Windows' getpass raise KeyboardInterrupt)."""
import builtins

import admin_auth
import set_pin


def test_falls_back_to_visible_prompt_when_getpass_fails(client, monkeypatch):
    def broken_getpass(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr(set_pin.getpass, "getpass", broken_getpass)
    monkeypatch.setattr(builtins, "input", lambda prompt="": "5791")
    set_pin.main()
    assert admin_auth.check_pin("5791")
