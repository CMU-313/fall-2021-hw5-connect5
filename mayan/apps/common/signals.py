from __future__ import unicode_literals

from django.dispatch import Signal

database_ready = Signal(use_caching=True)
perform_upgrade = Signal(use_caching=True)
post_initial_setup = Signal(use_caching=True)
post_upgrade = Signal(use_caching=True)
pre_initial_setup = Signal(use_caching=True)
pre_upgrade = Signal(use_caching=True)
