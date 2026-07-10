"""Test-support package for headless GUI integration tests.

Nothing here is imported by production code. These helpers let the Flet
wizard screens be driven end-to-end without a real Flet desktop window:

* ``fake_page`` — a stand-in for ``ft.Page`` implementing only the surface
  the screens touch, plus control-tree walking helpers.
* ``sync_runtime`` — makes background threads and ``page.run_task`` run
  synchronously so flows are deterministic.
* ``fixtures`` — loads normalized scenario JSON and reconstructs the real
  riplex dataclasses (DiscInfo, MetadataSearchResult, PlannedDisc, ...).
* ``provider_mocks`` — installs fake TMDb / dvdcompare / makemkv providers
  driven by a loaded scenario.
* ``driver`` — ``WizardDriver`` that builds ``RiplexApp`` on a ``FakePage``
  and exposes click/find/navigate helpers.
"""
