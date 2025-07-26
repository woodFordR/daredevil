from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Placeholder, TabbedContent, TabPane


class DaredevilApp(App):
    CSS_PATH = "daredevil.tcss"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, icon="⚔️⚔️⚔️")
        with TabbedContent(f"dashboard-101"):
            with TabPane(f"vm-abc-123"):
                with Horizontal(id=f"metrics"):
                    yield Container(Placeholder("The Shadows", id="dd"))
        yield Footer()


if __name__ == "__main__":
    app: App = DaredevilApp()
    app.run()
