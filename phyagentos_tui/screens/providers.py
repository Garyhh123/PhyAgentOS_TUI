"""Providers management screen."""

from typing import Any

from PhyAgentOS.config.loader import save_config
from PhyAgentOS.providers.registry import PROVIDERS, ProviderSpec
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
)

from phyagentos_tui.widgets.app_footer import AppFooter
from phyagentos_tui.widgets.app_header import AppHeader
from phyagentos_tui.widgets.command_palette import CommandPalette
from phyagentos_tui.widgets.nav_bar import NavBar
from phyagentos_tui.widgets.section_title import SectionTitle


class ProvidersScreen(Screen):
    """Providers management screen."""

    BINDINGS = [
        Binding("r", "refresh_providers", "Refresh"),
        Binding("s", "save_provider", "Save"),
        Binding("d", "set_default_provider", "Set Default"),
        Binding("?", "provider_help", "Help"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._selected_provider: str | None = None

    def compose(self) -> ComposeResult:
        yield AppHeader()
        yield NavBar("providers")
        with Vertical(id="providers-main"):
            yield SectionTitle("Providers")
            yield Label(
                "r refresh | s save | d set default | ? help | Ctrl+K command",
                classes="hint",
            )
            with Horizontal(id="providers-body"):
                with Vertical(id="provider-list-container"):
                    yield DataTable(id="provider-table")
                with ScrollableContainer(id="provider-form-container"):
                    yield Label("Select provider", id="form-placeholder")
                    yield Vertical(id="provider-form")
        yield CommandPalette()
        yield AppFooter()

    def on_mount(self) -> None:
        """Populate provider table."""
        self._refresh_table()
        self.query_one("#provider-table", DataTable).focus()

    def action_refresh_providers(self) -> None:
        self._refresh_table()
        self.notify("Providers refreshed")

    async def action_save_provider(self) -> None:
        if not self._selected_provider:
            self.notify("Select a provider first", severity="warning")
            return
        await self._save_and_restart(self._selected_provider)

    async def action_set_default_provider(self) -> None:
        if not self._selected_provider:
            self.notify("Select a provider first", severity="warning")
            return
        await self._set_default_and_restart(self._selected_provider)

    async def action_provider_help(self) -> None:
        form = self.query_one("#provider-form", Vertical)
        await form.remove_children()
        form.mount(Label(
            "Provider help\n\n"
            "DeepSeek official: fill DeepSeek API Key, then use a deepseek model.\n"
            "OpenAI official: fill OpenAI API Key; API Base is optional.\n"
            "OpenAI-compatible relay: prefer Custom, fill API Base and API Key if required.\n"
            "Gateway providers: API Key is required; API Base can use provider defaults.\n"
            "Azure OpenAI: API Key and API Base are both required.\n\n"
            "Keys: s save current provider, d set selected provider as default."
        ))

    def _refresh_table(self) -> None:
        table = self.query_one("#provider-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Provider", "Active", "Type", "Config", "Base")
        table.cursor_type = "row"

        config = self.app.config
        active_name = config.get_provider_name(config.agents.defaults.model)
        forced_name = config.agents.defaults.provider
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue
            active = ""
            if forced_name == spec.name:
                active = "default"
            elif forced_name == "auto" and active_name == spec.name:
                active = "auto"
            table.add_row(
                spec.label,
                active,
                self._provider_type(spec),
                self._config_status(spec, p),
                self._base_display(spec, p),
                key=spec.name,
            )

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle provider selection."""
        provider_name = event.row_key.value
        if provider_name:
            self._selected_provider = str(provider_name)
            await self._show_provider_form(str(provider_name))

    async def _show_provider_form(self, provider_name: str) -> None:
        """Show configuration form for selected provider."""
        form = self.query_one("#provider-form", Vertical)
        await form.remove_children()

        placeholder = self.query_one("#form-placeholder", Label)
        placeholder.display = False

        spec = next((s for s in PROVIDERS if s.name == provider_name), None)
        if not spec:
            return

        config = self.app.config
        p = getattr(config.providers, provider_name, None)

        form.mount(Label(f"Configure: {spec.label}", classes="settings-group-title"))
        form.mount(Label(self._provider_summary(spec, p), classes="hint"))
        note = self._provider_note(spec)
        if note:
            form.mount(Label(note, classes="hint"))

        if self._shows_api_key(spec):
            form.mount(Label("API Key:"))
            form.mount(Input(
                value=p.api_key if p else "",
                password=True,
                id=f"input-{provider_name}-api-key",
            ))

        if self._shows_api_base(spec, p):
            label = "API Base:"
            if spec.name == "openai":
                label = "API Base (optional, required for relays):"
            elif spec.name == "custom":
                label = "API Base (required):"
            form.mount(Label(label))
            form.mount(Input(
                value=p.api_base if p and p.api_base else "",
                id=f"input-{provider_name}-api-base",
            ))

        if spec.is_oauth:
            form.mount(Button(f"Login with {spec.label}", id=f"oauth-{provider_name}"))

        form.mount(Button("Save", variant="primary", id=f"save-{provider_name}"))
        form.mount(Button("Set Default", id=f"default-{provider_name}"))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        button_id = event.button.id or ""

        if button_id.startswith("save-"):
            await self._save_and_restart(button_id[5:])
        elif button_id.startswith("default-"):
            await self._set_default_and_restart(button_id[8:])
        elif button_id.startswith("oauth-"):
            self._oauth_login(button_id[6:])

    async def _save_and_restart(self, provider_name: str) -> None:
        errors = self._save_provider(provider_name)
        if errors:
            self._show_form_message("Cannot save:\n" + "\n".join(f"- {error}" for error in errors))
            self.notify("Provider config is incomplete", severity="error")
            return
        await self.app.restart_gateway()

    def _save_provider(self, provider_name: str) -> list[str]:
        """Save provider configuration."""
        config = self.app.config
        p = getattr(config.providers, provider_name, None)
        spec = next((s for s in PROVIDERS if s.name == provider_name), None)
        if p is None:
            return ["Provider config section is missing."]
        if spec is None:
            return ["Provider metadata is missing."]

        try:
            api_key_input = self.query_one(f"#input-{provider_name}-api-key", Input)
            p.api_key = api_key_input.value
        except Exception:
            pass

        try:
            api_base_input = self.query_one(f"#input-{provider_name}-api-base", Input)
            p.api_base = api_base_input.value or None
        except Exception:
            pass

        errors = self._validate_provider(spec, p)
        if errors:
            return errors

        save_config(config)
        self.app.reload_config()
        self._refresh_table()
        self._show_form_message("Saved. Restarting gateway...")
        return []

    async def _set_default_and_restart(self, provider_name: str) -> None:
        errors = self._save_provider(provider_name)
        if errors:
            self._show_form_message("Cannot set default:\n" + "\n".join(f"- {error}" for error in errors))
            self.notify("Provider config is incomplete", severity="error")
            return
        config = self.app.config
        config.agents.defaults.provider = provider_name
        save_config(config)
        self.app.reload_config()
        self._refresh_table()
        self.notify(f"Default provider set to {provider_name}")
        await self.app.restart_gateway()

    def _oauth_login(self, provider_name: str) -> None:
        """Handle OAuth login."""
        form = self.query_one("#provider-form", Vertical)
        form.mount(Label(f"OAuth login for {provider_name} - run `paos provider login {provider_name}` in terminal"))

    def _show_form_message(self, message: str) -> None:
        form = self.query_one("#provider-form", Vertical)
        form.mount(Label(message, classes="hint"))

    @staticmethod
    def _provider_type(spec: ProviderSpec) -> str:
        if spec.is_oauth:
            return "OAuth"
        if spec.is_local:
            return "Local"
        if spec.is_gateway:
            return "Gateway"
        if spec.is_direct:
            return "Direct"
        return "Std"

    def _provider_summary(self, spec: ProviderSpec, p: Any) -> str:
        return (
            f"Type: {self._provider_type(spec)}\n"
            f"Config: {self._config_status(spec, p)}\n"
            f"API Key: {'configured' if p and p.api_key else 'not set'}\n"
            f"API Base: {self._base_summary(spec, p)}"
        )

    @staticmethod
    def _provider_note(spec: ProviderSpec) -> str:
        if spec.name == "custom":
            return "Use Custom for OpenAI-compatible relay endpoints. API Base is required; API Key depends on the relay."
        if spec.name == "openai":
            return "Use OpenAI for the official API. For a relay, set API Base here or prefer Custom."
        if spec.name == "deepseek":
            return "DeepSeek official usually only needs an API Key and a deepseek model."
        if spec.name == "azure_openai":
            return "Azure OpenAI requires both API Key and API Base; model should be your deployment name."
        if spec.is_gateway:
            return "Gateway provider: API Key is required. API Base can use the built-in default unless your gateway URL is different."
        return ""

    @staticmethod
    def _shows_api_key(spec: ProviderSpec) -> bool:
        return not spec.is_oauth and not spec.is_local

    @staticmethod
    def _shows_api_base(spec: ProviderSpec, p: Any) -> bool:
        return (
            spec.is_local
            or spec.is_gateway
            or spec.is_direct
            or spec.name in {"openai", "custom", "azure_openai", "ollama", "vllm"}
            or bool(p and p.api_base)
        )

    def _config_status(self, spec: ProviderSpec, p: Any) -> str:
        if spec.is_oauth:
            return "OAuth"
        errors = self._validate_provider(spec, p)
        if errors:
            return "incomplete"
        return "ready"

    @staticmethod
    def _base_summary(spec: ProviderSpec, p: Any) -> str:
        if p and p.api_base:
            return p.api_base
        if spec.default_api_base:
            return f"default: {spec.default_api_base}"
        if spec.name == "openai":
            return "official default"
        return "not set"

    @staticmethod
    def _base_display(spec: ProviderSpec, p: Any) -> str:
        if p and p.api_base:
            return "custom"
        if spec.default_api_base:
            return "default"
        if spec.name == "openai":
            return "official"
        return "not set"

    @staticmethod
    def _validate_provider(spec: ProviderSpec, p: Any) -> list[str]:
        if spec.is_oauth:
            return []
        if p is None:
            return ["Provider config section is missing."]

        errors: list[str] = []
        if spec.name == "custom":
            if not p.api_base:
                errors.append("API Base is required for Custom relay endpoints.")
            return errors

        if spec.name == "azure_openai":
            if not p.api_key:
                errors.append("API Key is required for Azure OpenAI.")
            if not p.api_base:
                errors.append("API Base is required for Azure OpenAI.")
            return errors

        if spec.is_local:
            if not p.api_base and not spec.default_api_base:
                errors.append("API Base is required for this local provider.")
            return errors

        if not p.api_key:
            errors.append(f"API Key is required for {spec.label}.")
        return errors

