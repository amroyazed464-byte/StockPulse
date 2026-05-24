"""Plugin system — discover, load, register, and wire components.

Plugins are self-contained modules under ``plugins/<category>/``.
Each plugin exposes a ``create_plugin()`` factory that returns a
``StockPulsePlugin`` instance, or defines a ``StockPulsePlugin``
subclass directly.

Architecture::

    PluginRegistry  ←──  discover_plugins(config)  ←──  plugins/<category>/*.py
         │
         ▼
    Monitor._setup_wiring()  ──→  plugin.wire(bus)

Usage::

    registry = PluginRegistry()
    discover_plugins(registry, config)
    for plugin in registry.enabled():
        plugin.wire(bus)
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stock_monitor.events import EventBus

logger = logging.getLogger("stock_monitor.plugins")

_PLUGIN_ROOT = Path(__file__).parent

# ═══════════════════════════════════════════════════════════════════════
# Plugin metadata
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class PluginMeta:
    """Immutable metadata describing a plugin.

    Attached to every ``StockPulsePlugin`` instance.  Used by the
    registry for discovery, enable/disable toggling, and introspection.
    """

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    category: str = ""  # "source" | "exporter" | "notifier" | "strategy"
    homepage: str = ""
    enabled: bool = True

    def __str__(self) -> str:
        return (
            f"{self.name} v{self.version}"
            + (f" [{self.category}]" if self.category else "")
        )


# ═══════════════════════════════════════════════════════════════════════
# Base plugin classes
# ═══════════════════════════════════════════════════════════════════════


class StockPulsePlugin(ABC):
    """Base class for all StockPulse plugins.

    Subclass and override:
      - ``wire(bus)`` — subscribe to EventBus events
      - ``teardown()`` — cleanup on shutdown

    The ``meta`` attribute is set by the factory or registry.  Plugin
    authors should set ``meta`` as a class-level ``PluginMeta`` or
    provide it via ``create_plugin()``.
    """

    meta: PluginMeta = PluginMeta(name="unnamed")

    @abstractmethod
    def wire(self, bus: EventBus) -> None:
        """Subscribe to events and initialize plugin state."""
        ...

    def teardown(self) -> None:
        """Called during monitor shutdown. Override for cleanup."""

    @property
    def name(self) -> str:
        """Convenience proxy for ``meta.name``."""
        return self.meta.name

    @property
    def enabled(self) -> bool:
        """Convenience proxy for ``meta.enabled``."""
        return self.meta.enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self.meta.enabled = value

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} name={self.meta.name!r}"
            f" v{self.meta.version} [{self.meta.category}]"
            f"{' DISABLED' if not self.meta.enabled else ''}>"
        )


# ═══════════════════════════════════════════════════════════════════════
# Plugin Registry
# ═══════════════════════════════════════════════════════════════════════


class PluginRegistry:
    """Central registry for all discovered plugins.

    Plugins are grouped by category (source, exporter, notifier,
    strategy).  The registry supports enable/disable toggling,
    lookup by name, and batch wiring.

    Usage::

        registry = PluginRegistry()
        registry.register(plugin)
        for p in registry.enabled("exporter"):
            p.wire(bus)
    """

    def __init__(self) -> None:
        # category → name → plugin
        self._store: dict[str, dict[str, StockPulsePlugin]] = {}

    # ── Registration ──────────────────────────────────────────────

    def register(self, plugin: StockPulsePlugin) -> None:
        """Add a plugin to the registry.

        If a plugin with the same name and category already exists,
        it is replaced (last wins).
        """
        cat = plugin.meta.category
        if cat not in self._store:
            self._store[cat] = {}
        existed = plugin.meta.name in self._store[cat]
        self._store[cat][plugin.meta.name] = plugin
        logger.debug(
            "%s plugin %r in category %r",
            "Replaced" if existed else "Registered",
            plugin.meta.name,
            cat,
        )

    def unregister(self, name: str, category: str) -> bool:
        """Remove a plugin by name and category. Returns True if removed."""
        cat_store = self._store.get(category, {})
        if name in cat_store:
            del cat_store[name]
            logger.debug("Unregistered plugin %r from %r", name, category)
            return True
        return False

    def bulk_register(self, plugins: list[StockPulsePlugin]) -> None:
        """Register multiple plugins at once."""
        for p in plugins:
            self.register(p)

    # ── Lookup ────────────────────────────────────────────────────

    def get(self, name: str, category: str) -> StockPulsePlugin | None:
        """Look up a single plugin by name and category."""
        return self._store.get(category, {}).get(name)

    def list_all(self) -> list[StockPulsePlugin]:
        """Return all registered plugins across all categories."""
        result: list[StockPulsePlugin] = []
        for cat_store in self._store.values():
            result.extend(cat_store.values())
        return result

    def list_by_category(self, category: str) -> list[StockPulsePlugin]:
        """Return all plugins in a given category."""
        return list(self._store.get(category, {}).values())

    @property
    def categories(self) -> list[str]:
        """List of categories that have at least one registered plugin."""
        return sorted(self._store.keys())

    # ── Enable / Disable ──────────────────────────────────────────

    def enabled(self, category: str | None = None) -> list[StockPulsePlugin]:
        """Return enabled plugins, optionally filtered by category.

        If *category* is None, returns all enabled plugins across all
        categories.
        """
        if category is not None:
            return [
                p for p in self._store.get(category, {}).values()
                if p.meta.enabled
            ]
        result: list[StockPulsePlugin] = []
        for cat_store in self._store.values():
            for p in cat_store.values():
                if p.meta.enabled:
                    result.append(p)
        return result

    def disabled(self, category: str | None = None) -> list[StockPulsePlugin]:
        """Return disabled plugins, optionally filtered by category."""
        if category is not None:
            return [
                p for p in self._store.get(category, {}).values()
                if not p.meta.enabled
            ]
        result: list[StockPulsePlugin] = []
        for cat_store in self._store.values():
            for p in cat_store.values():
                if not p.meta.enabled:
                    result.append(p)
        return result

    def set_enabled(self, name: str, category: str, value: bool) -> bool:
        """Enable or disable a plugin by name and category.

        Returns True if the plugin was found and updated.
        """
        plugin = self.get(name, category)
        if plugin is None:
            logger.warning("Cannot set enabled — plugin %r/%r not found", name, category)
            return False
        plugin.meta.enabled = value
        logger.info("%s plugin %r/%r", "Enabled" if value else "Disabled", name, category)
        return True

    def apply_disabled_list(self, disabled_names: list[str]) -> int:
        """Disable all plugins whose name appears in *disabled_names*.

        Returns the number of plugins disabled.
        """
        count = 0
        names = set(disabled_names)
        for cat_store in self._store.values():
            for name, plugin in cat_store.items():
                if name in names and plugin.meta.enabled:
                    plugin.meta.enabled = False
                    count += 1
        if count:
            logger.info("Disabled %d plugin(s) from config", count)
        return count

    # ── Introspection ─────────────────────────────────────────────

    @property
    def total_count(self) -> int:
        """Total number of registered plugins."""
        return sum(len(cat) for cat in self._store.values())

    @property
    def enabled_count(self) -> int:
        """Number of enabled plugins."""
        return len(self.enabled())

    def summary(self) -> str:
        """Return a human-readable summary string."""
        lines = [f"PluginRegistry ({self.enabled_count}/{self.total_count} enabled):"]
        for cat in self.categories:
            cat_plugins = self._store[cat]
            for name, p in sorted(cat_plugins.items()):
                flag = " " if p.meta.enabled else "✗"
                lines.append(f"  [{flag}] {cat}/{name}  v{p.meta.version}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Plugin Discovery
# ═══════════════════════════════════════════════════════════════════════


def discover_plugins(
    registry: PluginRegistry | None = None,
    disabled_names: list[str] | None = None,
    extra_paths: list[str] | None = None,
) -> list[StockPulsePlugin]:
    """Scan ``plugins/`` and *extra_paths* for plugins, register and return them.

    Looks for a ``create_plugin() -> StockPulsePlugin`` callable at the
    top level of every Python module found under ``plugins/<category>/``.
    Modules without this callable are silently skipped.

    After discovery, applies *disabled_names* to disable plugins matching
    the configured exclusion list.

    Args:
        registry: Optional ``PluginRegistry`` to register into.  If
            omitted, plugins are only returned in the list.
        disabled_names: Plugin names to mark as disabled after discovery.
        extra_paths: Additional directories to scan for plugin categories.

    Returns:
        List of discovered ``StockPulsePlugin`` instances.
    """
    plugins: list[StockPulsePlugin] = []
    search_roots = [_PLUGIN_ROOT] if _PLUGIN_ROOT.exists() else []

    for ep in extra_paths or []:
        p = Path(ep)
        if p.is_dir() and p not in search_roots:
            search_roots.append(p)

    for root in search_roots:
        _discover_in_root(root, plugins, registry)

    # Apply disabled list
    if disabled_names:
        names = set(disabled_names)
        for p in plugins:
            if p.meta.name in names:
                p.meta.enabled = False

    if registry is not None:
        registry.bulk_register(plugins)

    logger.info(
        "Discovered %d plugin(s) across %d root(s) "
        "(%d enabled, %d disabled)",
        len(plugins),
        len(search_roots),
        sum(1 for p in plugins if p.meta.enabled),
        sum(1 for p in plugins if not p.meta.enabled),
    )
    return plugins


def _discover_in_root(
    root: Path,
    plugins: list[StockPulsePlugin],
    registry: PluginRegistry | None,
) -> None:
    """Scan one plugin root directory for plugins.

    Handles both the built-in ``plugins/`` tree (imported as
    ``stock_monitor.plugins.{category}``) and external roots (imported
    as standalone packages after temporarily adding the parent to
    ``sys.path``).
    """
    import sys

    is_builtin = root == _PLUGIN_ROOT

    for category_dir in sorted(root.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("_"):
            continue
        if not (category_dir / "__init__.py").exists():
            continue

        category = category_dir.name

        if is_builtin:
            pkg_name = f"stock_monitor.plugins.{category}"
            try:
                pkg = importlib.import_module(pkg_name)
            except ImportError as exc:
                logger.debug("Cannot import category %r: %s", pkg_name, exc)
                continue
        else:
            # External root: add parent to sys.path and import category
            # as a top-level package
            parent = str(category_dir.parent)
            pkg_name = category
            added = False
            if parent not in sys.path:
                sys.path.insert(0, parent)
                added = True
            try:
                pkg = importlib.import_module(pkg_name)
            except ImportError as exc:
                logger.debug(
                    "Cannot import external category %r from %s: %s",
                    category, parent, exc,
                )
                if added:
                    sys.path.remove(parent)
                continue
            # Leave parent on sys.path so subsequent imports work;
            # it's harmless for the lifetime of the process.

        if not hasattr(pkg, "__path__"):
            continue

        for _, mod_name, _ in pkgutil.iter_modules(
            pkg.__path__, prefix=f"{pkg_name}."
        ):
            _load_plugin_from_module(mod_name, category, plugins, registry)


def _load_plugin_from_module(
    mod_name: str,
    category: str,
    plugins: list[StockPulsePlugin],
    registry: PluginRegistry | None,
) -> None:
    """Attempt to load a single plugin from a module."""
    if mod_name.endswith(".__init__"):
        return
    try:
        mod = importlib.import_module(mod_name)
    except ImportError as exc:
        logger.warning("Cannot import plugin module %s: %s", mod_name, exc)
        return

    # Prefer create_plugin() factory, then fall back to scanning for
    # StockPulsePlugin subclasses
    factory = getattr(mod, "create_plugin", None)
    if factory is not None:
        try:
            plugin = factory()
            if not isinstance(plugin, StockPulsePlugin):
                logger.warning(
                    "create_plugin() in %s returned %s, expected StockPulsePlugin",
                    mod_name, type(plugin).__name__,
                )
                return
            _finalize_plugin(plugin, category, mod_name)
            plugins.append(plugin)
        except Exception as exc:
            logger.warning("Plugin factory %s.create_plugin() raised: %s", mod_name, exc)
        return

    # Fallback: scan module namespace for StockPulsePlugin subclasses
    for attr_name in dir(mod):
        obj = getattr(mod, attr_name)
        if (
            isinstance(obj, type)
            and issubclass(obj, StockPulsePlugin)
            and obj is not StockPulsePlugin
            and not _is_abstract(obj)
        ):
            try:
                plugin = obj()
                _finalize_plugin(plugin, category, mod_name)
                plugins.append(plugin)
            except Exception as exc:
                logger.warning(
                    "Failed to instantiate plugin class %s.%s: %s",
                    mod_name, attr_name, exc,
                )


def _is_abstract(cls: type) -> bool:
    """Return True if *cls* has unimplemented abstract methods."""
    return bool(getattr(cls, "__abstractmethods__", False))


def _finalize_plugin(
    plugin: StockPulsePlugin,
    category: str,
    mod_name: str,
) -> None:
    """Set metadata defaults if not provided by the plugin author."""
    if plugin.meta.category == "":
        plugin.meta.category = category
    if plugin.meta.name == "unnamed":
        plugin.meta.name = mod_name.rsplit(".", 1)[-1]


# ═══════════════════════════════════════════════════════════════════════
# Wiring & teardown helpers
# ═══════════════════════════════════════════════════════════════════════


def wire_plugins(plugins: list[StockPulsePlugin], bus: EventBus) -> None:
    """Wire a list of enabled plugins into the event bus.

    Disabled plugins are skipped with a debug log.
    """
    for plugin in plugins:
        if not plugin.meta.enabled:
            logger.debug("Skipping disabled plugin: %s", plugin.meta.name)
            continue
        try:
            plugin.wire(bus)
            logger.debug("Wired plugin: %s", plugin.meta.name)
        except Exception as exc:
            logger.error(
                "Failed to wire plugin %s: %s", plugin.meta.name, exc,
            )


def wire_registry(registry: PluginRegistry, bus: EventBus) -> None:
    """Wire all enabled plugins in a registry into the event bus."""
    wire_plugins(registry.enabled(), bus)


def teardown_plugins(plugins: list[StockPulsePlugin]) -> None:
    """Run teardown for all plugins (enabled and disabled)."""
    for plugin in plugins:
        try:
            plugin.teardown()
        except Exception as exc:
            logger.warning("Plugin %s teardown error: %s", plugin.meta.name, exc)


def teardown_registry(registry: PluginRegistry) -> None:
    """Run teardown for all registered plugins."""
    teardown_plugins(registry.list_all())
