"""Notifications through Home Assistant — the hub, an earlier release.

The rest of the Ministry is a screen someone chooses to open. This package is
the part that interrupts them, so it is held to a different standard: every
message here has to be worth a phone lighting up at seven in the morning, and
has to be honest about how much the app actually knows.

| Module | What it does |
| --- | --- |
| ``model.py`` | A notification, a recipient, and how certain the thing is |
| ``copy.py`` | The words. The original-theme rule pairing, and the hedging the design requires |
| ``policy.py`` | When to send, when to stay quiet, and what not to send twice |
| ``channels.py`` | The transport: Home Assistant's ``notify`` services |
| ``state.py`` | Reading today's rounds, the frost report and integration health |
| ``jobs.py`` | The three Arq jobs, and what they record |
"""
